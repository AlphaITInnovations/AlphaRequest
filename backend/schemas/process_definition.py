"""
Das Prozess-Format (`ProcessDefinition`) als validierendes Pydantic-Meta-Schema.

Dies ist der maschinenlesbare Vertrag hinter dem Design-Doc (docs/design/
dynamic-process-system.md, §3). Beim Anlegen/Bearbeiten/Import wird eine
Definition hiergegen validiert – wohlgeformte Felder, existierende Referenzen,
Widgets/Views/Status aus der Whitelist, wohlgeformte Bedingungs-DSL.

Stufe 1 validiert die STRUKTUR. Die Auswertung der DSL und die Laufzeit
(Ticket-Runtime, Sichtbarkeit, Automations-Ausführung) folgen in späteren Stufen.
"""
from __future__ import annotations

import re
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# Aktuelle Schema-Version des Formats. Der Interpreter muss alle je ausgelieferten
# Versionen gepinnter Definitionen verstehen (§3.3) – daher hier zentral gepflegt.
CURRENT_SCHEMA_VERSION = 1

KEY_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


# ── Enums / Whitelists ─────────────────────────────────────────────────────────

class Widget(str, Enum):
    text = "text"
    textarea = "textarea"
    number = "number"
    date = "date"
    select = "select"
    multiselect = "multiselect"
    checkbox = "checkbox"
    checkbox_group = "checkbox-group"
    attachment = "attachment"
    user = "user"
    company = "company"
    group = "group"
    collection = "collection"            # Wiederholgruppe (Array von Sub-Items)
    server_generated = "server_generated"  # kein Client-Input, per Action befüllt
    server_stamped = "server_stamped"       # nur innerhalb collection-Items


class OptionsSource(str, Enum):
    static = "static"
    groups = "groups"
    companies = "companies"
    users = "users"


class PhaseKind(str, Enum):
    start = "start"
    task = "task"
    approval = "approval"
    review = "review"
    end = "end"


class PhaseView(str, Enum):
    form = "form"
    readonly = "readonly"
    approval = "approval"
    review = "review"
    export = "export"


class ResponsibilityKind(str, Enum):
    owner = "owner"
    group = "group"
    user = "user"
    departments = "departments"
    originator = "originator"   # bei Spawn: Ersteller:in des auslösenden Prozesses


class FieldMode(str, Enum):
    editable = "editable"
    readonly = "readonly"
    hidden = "hidden"
    append_only = "append_only"


class TriggerType(str, Enum):
    on_enter = "on_enter"
    on_exit = "on_exit"
    on_field_change = "on_field_change"
    timer = "timer"


class ActionType(str, Enum):
    notify = "notify"
    escalate = "escalate"
    set_field = "set_field"
    set_priority = "set_priority"
    set_status = "set_status"
    assign_sequence = "assign_sequence"
    require_attachment = "require_attachment"
    auto_advance = "auto_advance"
    spawn_process = "spawn_process"


# Erlaubte enterStatus-Werte (Whitelist gegen Tippfehler). Bewusst als Menge
# gepflegt statt an das alte RequestStatus-Enum gekoppelt.
ALLOWED_ENTER_STATUS = {
    "in_progress", "in_request", "waiting_contract", "archived", "rejected",
}

ALLOWED_PRIORITY = {"low", "normal", "high", "urgent"}

# Terminale Status dürfen NICHT über enterStatus/set_status mitten im Prozess
# gesetzt werden – das Ticket wäre unbearbeitbar und ohne Reopen-Pfad tot.
TERMINAL_STATUS = {"archived", "rejected"}

# Empfänger-Ziele, die process_actions.resolve_recipients wirklich auflösen kann.
ALLOWED_RECIPIENTS = {"responsible", "owner", "watchers"}   # + "group:<id>"

# Ehrlichkeits-Regel (§ Review): Was die Laufzeit NICHT umsetzt, wird beim
# Speichern/Veröffentlichen abgelehnt statt still ignoriert. Beim Nachrüsten der
# Funktion hier wieder austragen.
UNIMPLEMENTED_ACTIONS = {"spawn_process", "assign_sequence", "require_attachment"}
UNIMPLEMENTED_WIDGETS = {"server_generated"}       # braucht assign_sequence
UNIMPLEMENTED_PHASE_KINDS = {"approval"}           # kein Freigabe-Token-Flow
UNIMPLEMENTED_PHASE_VIEWS = {"approval", "export"}  # kein Renderer/Runtime

# Boolean-Operatoren der Condition-DSL (§6.1). Die Auswertung kommt in Stufe 4;
# hier wird nur die STRUKTUR geprüft.
_DSL_BINARY = {"==", "!=", "in"}
_DSL_LIST = {"and", "or"}


def dsl_refs(cond: Any) -> set:
    """Sammelt alle Feld-Refs (Dot-Paths) aus einem (wohlgeformten) DSL-Ausdruck."""
    out: set = set()
    if not isinstance(cond, dict) or len(cond) != 1:
        return out
    op, arg = next(iter(cond.items()))
    if op in ("==", "!=", "in"):
        if isinstance(arg, list) and arg and isinstance(arg[0], str):
            out.add(arg[0])
    elif op == "truthy":
        if isinstance(arg, str):
            out.add(arg)
    elif op in ("and", "or"):
        for sub in (arg or []):
            out |= dsl_refs(sub)
    elif op == "not":
        out |= dsl_refs(arg)
    return out


def validate_condition(cond: Any, path: str = "condition") -> None:
    """Prüft die Wohlgeformtheit eines DSL-Ausdrucks; wirft ValueError."""
    if not isinstance(cond, dict) or len(cond) != 1:
        raise ValueError(f"{path}: erwartet genau einen Operator")
    op, arg = next(iter(cond.items()))
    if op in _DSL_BINARY:
        if op == "in":
            if not (isinstance(arg, list) and len(arg) == 2 and isinstance(arg[0], str)
                    and isinstance(arg[1], list)):
                raise ValueError(f"{path}.in: erwartet [ref, [werte...]]")
        else:
            if not (isinstance(arg, list) and len(arg) == 2 and isinstance(arg[0], str)):
                raise ValueError(f"{path}.{op}: erwartet [ref, wert]")
    elif op == "truthy":
        if not isinstance(arg, str):
            raise ValueError(f"{path}.truthy: erwartet einen Feld-Ref (String)")
    elif op in _DSL_LIST:
        if not (isinstance(arg, list) and arg):
            raise ValueError(f"{path}.{op}: erwartet eine nicht-leere Liste von Bedingungen")
        for i, sub in enumerate(arg):
            validate_condition(sub, f"{path}.{op}[{i}]")
    elif op == "not":
        validate_condition(arg, f"{path}.not")
    else:
        raise ValueError(f"{path}: unbekannter Operator „{op}“")


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ── Feld-Katalog ─────────────────────────────────────────────────────────────

class FieldConstraints(_Base):
    pattern: Optional[str] = None
    minLength: Optional[int] = None
    maxLength: Optional[int] = None
    min: Optional[float] = None
    max: Optional[float] = None
    minDate: Optional[str] = None
    maxDate: Optional[str] = None

    @field_validator("pattern")
    @classmethod
    def _valid_regex(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            try:
                re.compile(v)
            except re.error as e:
                raise ValueError(f"ungültiges Regex-Pattern: {e}")
        return v

    @model_validator(mode="after")
    def _ranges_ordered(self) -> "FieldConstraints":
        if self.minLength is not None and self.maxLength is not None and self.minLength > self.maxLength:
            raise ValueError("minLength > maxLength")
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError("min > max")
        if self.minDate is not None and self.maxDate is not None and self.minDate > self.maxDate:
            raise ValueError("minDate > maxDate")
        return self


class FieldVisibility(_Base):
    confidential: bool = False
    visibleToGroups: list[str] = Field(default_factory=list)  # Gruppen-IDs

    @model_validator(mode="after")
    def _confidential_needs_groups(self) -> "FieldVisibility":
        if self.confidential and not self.visibleToGroups:
            raise ValueError("confidential=true erfordert mindestens eine Gruppe in visibleToGroups")
        return self


class ComputedSpec(_Base):
    from_: str = Field(alias="from")
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class AssignSpec(_Base):
    action: ActionType
    counter: Optional[str] = None
    companyRef: Optional[str] = None


class StaticOption(_Base):
    value: str
    label: Optional[str] = None


class SubField(_Base):
    """Ein Feld innerhalb einer collection."""
    key: str
    label: Optional[str] = None
    widget: Widget
    value: Optional[str] = None   # für server_stamped: "actor" | "now"


class FieldDef(_Base):
    key: str
    label: Optional[str] = None
    widget: Widget
    help: Optional[str] = None
    placeholder: Optional[str] = None
    options: list[StaticOption] = Field(default_factory=list)
    optionsSource: Optional[OptionsSource] = None
    allowOther: bool = False
    valueShape: Optional[str] = None            # "id" | "name" | strukturiert
    constraints: Optional[FieldConstraints] = None
    visibility: Optional[FieldVisibility] = None
    computed: Optional[ComputedSpec] = None
    overridable: bool = False
    assign: Optional[AssignSpec] = None
    mode: Optional[FieldMode] = None            # z.B. append_only bei collection
    item: list[SubField] = Field(default_factory=list)  # Sub-Katalog für collection

    @field_validator("key")
    @classmethod
    def _key_shape(cls, v: str) -> str:
        # Dot-Paths sind erlaubt (base.first_name); Segmente aus [a-z0-9_].
        if not v or not all(re.fullmatch(r"[A-Za-z0-9_]+", seg) for seg in v.split(".")):
            raise ValueError(f"ungültiger Feld-Key „{v}“ (erlaubt: a-z0-9_ und Punkte)")
        return v

    @model_validator(mode="after")
    def _widget_rules(self) -> "FieldDef":
        if self.widget == Widget.collection and not self.item:
            raise ValueError(f"Feld „{self.key}“: collection braucht `item` (Sub-Felder)")
        if self.widget != Widget.collection and self.item:
            raise ValueError(f"Feld „{self.key}“: `item` nur bei widget=collection erlaubt")
        if self.widget.value in UNIMPLEMENTED_WIDGETS:
            raise ValueError(f"Feld „{self.key}“: widget „{self.widget.value}“ hat noch keine "
                             f"Laufzeit-Umsetzung (die zugehörige Action fehlt)")
        if self.widget == Widget.server_generated and not self.assign:
            raise ValueError(f"Feld „{self.key}“: server_generated braucht `assign`")
        if self.widget == Widget.server_stamped:
            raise ValueError(f"Feld „{self.key}“: server_stamped ist nur innerhalb einer collection erlaubt")
        return self


# ── Phasen ───────────────────────────────────────────────────────────────────

class FieldRef(_Base):
    ref: str
    mode: FieldMode = FieldMode.editable
    required: bool = False
    requiredWhen: Optional[dict] = None
    visibleWhen: Optional[dict] = None

    @model_validator(mode="after")
    def _check_dsl(self) -> "FieldRef":
        if self.requiredWhen is not None:
            validate_condition(self.requiredWhen, f"{self.ref}.requiredWhen")
        if self.visibleWhen is not None:
            validate_condition(self.visibleWhen, f"{self.ref}.visibleWhen")
        return self


class DepartmentRule(_Base):
    group: str                      # Gruppen-ID
    required: bool = True
    when: Optional[dict] = None

    @model_validator(mode="after")
    def _check_when(self) -> "DepartmentRule":
        if self.when is not None:
            validate_condition(self.when, f"department[{self.group}].when")
        return self


class Responsibility(_Base):
    kind: ResponsibilityKind
    group: Optional[str] = None     # bei kind=group
    user: Optional[str] = None      # bei kind=user
    rule: list[DepartmentRule] = Field(default_factory=list)  # bei kind=departments
    resetOnDescriptionChange: bool = False

    @model_validator(mode="after")
    def _kind_rules(self) -> "Responsibility":
        if self.kind == ResponsibilityKind.group and not self.group:
            raise ValueError("responsibility.kind=group erfordert `group`")
        if self.kind == ResponsibilityKind.user and not self.user:
            raise ValueError("responsibility.kind=user erfordert `user`")
        if self.kind == ResponsibilityKind.departments and not self.rule:
            raise ValueError("responsibility.kind=departments erfordert `rule`")
        return self


class Trigger(_Base):
    type: TriggerType
    after: Optional[str] = None      # ISO-8601-Dauer (z.B. P7D) bei timer
    repeat: Optional[str] = None
    field: Optional[str] = None      # bei on_field_change

    @model_validator(mode="after")
    def _trigger_rules(self) -> "Trigger":
        from backend.services.iso_duration import parse_duration
        if self.type == TriggerType.timer:
            if not self.after:
                raise ValueError("trigger timer erfordert `after` (ISO-8601-Dauer)")
            # Dauern JETZT parsen – eine unparsebare Dauer würde den Timer sonst
            # zur Laufzeit still lahmlegen.
            for label, val in (("after", self.after), ("repeat", self.repeat)):
                if val is not None:
                    try:
                        secs = parse_duration(val)
                    except ValueError as e:
                        raise ValueError(f"trigger.{label}: {e}")
                    if secs <= 0:
                        raise ValueError(f"trigger.{label} muss größer als 0 sein")
        elif self.after or self.repeat:
            raise ValueError(f"trigger {self.type.value} kennt kein after/repeat")
        if self.type == TriggerType.on_field_change and not self.field:
            raise ValueError("trigger on_field_change erfordert `field`")
        return self


class Action(_Base):
    type: ActionType
    to: Optional[str] = None         # Empfänger-Resolver (notify/escalate)
    template: Optional[str] = None
    field: Optional[str] = None
    value: Optional[Any] = None
    process: Optional[str] = None    # bei spawn_process
    counter: Optional[str] = None    # bei assign_sequence

    @model_validator(mode="after")
    def _action_rules(self) -> "Action":
        t = self.type
        if t.value in UNIMPLEMENTED_ACTIONS:
            raise ValueError(f"action „{t.value}“ ist noch nicht implementiert und "
                             f"kann daher nicht veröffentlicht werden")
        if t in (ActionType.notify, ActionType.escalate):
            if not self.to:
                raise ValueError(f"action {t.value} erfordert `to`")
            # Nur auflösbare Ziele zulassen – sonst landet die Mail stumm im Fallback.
            if not (self.to in ALLOWED_RECIPIENTS or self.to.startswith("group:")):
                raise ValueError(f"action {t.value}: unbekanntes Ziel „{self.to}“ "
                                 f"(erlaubt: {', '.join(sorted(ALLOWED_RECIPIENTS))}, group:<id>)")
        if t == ActionType.set_field and (not self.field or self.value is None):
            raise ValueError("action set_field erfordert `field` und `value`")
        if t == ActionType.set_status:
            if self.value not in ALLOWED_ENTER_STATUS:
                raise ValueError(f"action set_status: unbekannter Status „{self.value}“")
            if self.value in TERMINAL_STATUS:
                raise ValueError(f"action set_status: „{self.value}“ würde das Ticket "
                                 f"unbearbeitbar machen (kein Reopen-Pfad)")
        if t == ActionType.set_priority:
            if self.value not in ALLOWED_PRIORITY:
                raise ValueError(f"action set_priority: unbekannte Priorität „{self.value}“")
        if t == ActionType.spawn_process and not self.process:
            raise ValueError("action spawn_process erfordert `process`")
        if t == ActionType.assign_sequence and not self.counter:
            raise ValueError("action assign_sequence erfordert `counter`")
        if t == ActionType.require_attachment and not self.field:
            raise ValueError("action require_attachment erfordert `field`")
        return self


class Automation(_Base):
    id: str
    trigger: Trigger
    guard: Optional[dict] = None
    action: Action

    @model_validator(mode="after")
    def _check_guard(self) -> "Automation":
        if self.guard is not None:
            validate_condition(self.guard, f"automation[{self.id}].guard")
        return self


class PhaseDef(_Base):
    key: str
    label: Optional[str] = None
    kind: PhaseKind
    view: PhaseView = PhaseView.form
    enterStatus: Optional[str] = None
    grantsFullView: bool = False
    responsibility: Responsibility
    fields: list[FieldRef] = Field(default_factory=list)
    constraints: list[dict] = Field(default_factory=list)  # [{when, message}]
    automations: list[Automation] = Field(default_factory=list)

    @field_validator("key")
    @classmethod
    def _phase_key_shape(cls, v: str) -> str:
        if not re.fullmatch(r"[a-z0-9_]+", v or ""):
            raise ValueError(f"ungültiger Phasen-Key „{v}“ (erlaubt: a-z0-9_)")
        return v

    @field_validator("enterStatus")
    @classmethod
    def _status_whitelist(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in ALLOWED_ENTER_STATUS:
            raise ValueError(f"unbekannter enterStatus „{v}“")
        if v in TERMINAL_STATUS:
            raise ValueError(f"enterStatus „{v}“ ist terminal – ein Ticket wäre beim "
                             f"Betreten der Phase unbearbeitbar (kein Reopen-Pfad)")
        return v

    @model_validator(mode="after")
    def _runtime_supported(self) -> "PhaseDef":
        if self.kind.value in UNIMPLEMENTED_PHASE_KINDS:
            raise ValueError(f"Phase „{self.key}“: kind „{self.kind.value}“ hat noch keine "
                             f"Laufzeit-Umsetzung")
        if self.view.value in UNIMPLEMENTED_PHASE_VIEWS:
            raise ValueError(f"Phase „{self.key}“: view „{self.view.value}“ hat noch keine "
                             f"Laufzeit-Umsetzung")
        if self.responsibility.resetOnDescriptionChange:
            raise ValueError(f"Phase „{self.key}“: resetOnDescriptionChange ist noch nicht "
                             f"umgesetzt")
        return self

    @model_validator(mode="after")
    def _check_constraints(self) -> "PhaseDef":
        for i, c in enumerate(self.constraints):
            if not isinstance(c, dict) or "when" not in c or "message" not in c:
                raise ValueError(f"Phase „{self.key}“: constraints[{i}] braucht `when` und `message`")
            validate_condition(c["when"], f"{self.key}.constraints[{i}].when")
        return self


# ── Prozess ──────────────────────────────────────────────────────────────────

class ProcessDefinition(_Base):
    schemaVersion: int = CURRENT_SCHEMA_VERSION
    key: str
    name: str
    description: Optional[str] = None
    icon: Optional[str] = None
    fields: list[FieldDef] = Field(default_factory=list)
    phases: list[PhaseDef] = Field(default_factory=list)
    automations: list[Automation] = Field(default_factory=list)

    @field_validator("key")
    @classmethod
    def _key_shape(cls, v: str) -> str:
        if not KEY_RE.fullmatch(v or ""):
            raise ValueError("key muss ein Slug sein (a-z, 0-9, '-', 1–64 Zeichen)")
        return v

    @field_validator("schemaVersion")
    @classmethod
    def _schema_version(cls, v: int) -> int:
        if v < 1 or v > CURRENT_SCHEMA_VERSION:
            raise ValueError(f"nicht unterstützte schemaVersion {v} (max {CURRENT_SCHEMA_VERSION})")
        return v

    @model_validator(mode="after")
    def _integrity(self) -> "ProcessDefinition":
        # Feld-Keys eindeutig
        keys = [f.key for f in self.fields]
        dupes = {k for k in keys if keys.count(k) > 1}
        if dupes:
            raise ValueError(f"doppelte Feld-Keys: {', '.join(sorted(dupes))}")
        catalog = set(keys)

        if not self.phases:
            raise ValueError("Prozess braucht mindestens eine Phase")

        # Phasen-Keys eindeutig
        pkeys = [p.key for p in self.phases]
        pdupes = {k for k in pkeys if pkeys.count(k) > 1}
        if pdupes:
            raise ValueError(f"doppelte Phasen-Keys: {', '.join(sorted(pdupes))}")

        # Genau eine start-Phase, und sie steht am Anfang
        starts = [p.key for p in self.phases if p.kind == PhaseKind.start]
        if len(starts) != 1:
            raise ValueError("Prozess braucht genau eine start-Phase")
        if self.phases[0].kind != PhaseKind.start:
            raise ValueError("die start-Phase muss die erste Phase sein")

        # Alle fieldRefs verweisen auf existierende Katalog-Felder
        for p in self.phases:
            for fr in p.fields:
                if fr.ref not in catalog:
                    raise ValueError(f"Phase „{p.key}“: fieldRef „{fr.ref}“ ist nicht im Feld-Katalog")

        # Automation-IDs eindeutig (über den ganzen Prozess)
        all_autos = list(self.automations) + [a for p in self.phases for a in p.automations]
        aids = [a.id for a in all_autos]
        adupes = {a for a in aids if aids.count(a) > 1}
        if adupes:
            raise ValueError(f"doppelte Automation-IDs: {', '.join(sorted(adupes))}")

        # ── Alle Feld-Referenzen müssen im Katalog existieren (sonst stiller No-op /
        #    Datenverlust zur Laufzeit). Betrifft computed.from, DSL-Leaf-Refs in
        #    requiredWhen/visibleWhen/constraints/when/guard und Trigger/Action.field.
        def _need(ref: str, where: str):
            if ref not in catalog:
                raise ValueError(f"{where}: Referenz „{ref}“ ist nicht im Feld-Katalog")

        for f in self.fields:
            if f.computed:
                _need(f.computed.from_, f"Feld „{f.key}“.computed.from")

        for p in self.phases:
            for fr in p.fields:
                for cond, lbl in ((fr.requiredWhen, "requiredWhen"), (fr.visibleWhen, "visibleWhen")):
                    if cond:
                        for r in dsl_refs(cond):
                            _need(r, f"{p.key}.{fr.ref}.{lbl}")
            for i, c in enumerate(p.constraints):
                for r in dsl_refs(c.get("when", {})):
                    _need(r, f"{p.key}.constraints[{i}].when")
            resp = p.responsibility
            for dr in resp.rule:
                if dr.when:
                    for r in dsl_refs(dr.when):
                        _need(r, f"{p.key}.responsibility[{dr.group}].when")

        for a in all_autos:
            if a.guard:
                for r in dsl_refs(a.guard):
                    _need(r, f"automation[{a.id}].guard")
            if a.trigger.field:
                _need(a.trigger.field, f"automation[{a.id}].trigger.field")
            if a.action.field:
                _need(a.action.field, f"automation[{a.id}].action.field")

        # Non-overridable computed-Felder dürfen nicht als editierbar referenziert
        # werden – apply_computed würde die Eingabe bei jedem Speichern überschreiben.
        ro_computed = {f.key for f in self.fields if f.computed and not f.overridable}
        for p in self.phases:
            for fr in p.fields:
                if fr.ref in ro_computed and fr.mode in (FieldMode.editable, FieldMode.append_only):
                    raise ValueError(
                        f"Phase „{p.key}“: computed-Feld „{fr.ref}“ (non-overridable) darf nicht "
                        f"editierbar sein")

        return self
