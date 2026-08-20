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
from typing import Annotated, Any, Literal, Optional, Union

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
    #: Dokument-Phase: HTML-Vorlage mit {{feld}}-Platzhaltern, vorausgefüllt,
    #: im Editor anpassbar, als Word/PDF exportierbar (z. B. Arbeitsvertrag).
    document = "document"


class ResponsibilityKind(str, Enum):
    owner = "owner"
    group = "group"
    user = "user"
    departments = "departments"
    #: Zuständige FACHABTEILUNG steht in einem Gruppen-Feld des Auftrags – so wählt
    #: die erstellende Person selbst, wer bearbeitet (Basis-Ticket).
    group_from_field = "group_from_field"
    #: Zuständige Person steht in einem Personen-FELD des Auftrags (z. B. „Verantwortlich",
    #: bei der Erstellung ausgewählt). Genau das Muster der Alt-Prozesse, nur
    #: datengetrieben – dadurch gelten Pflicht, Sichtbarkeit und Validierung des
    #: Feldes automatisch mit.
    assignable = "assignable"


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
    auto_advance = "auto_advance"


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
# Aktuell ist ALLES umgesetzt, was das Schema anbietet. Die Mengen bleiben als
# Mechanismus bestehen: wer künftig einen Wert ergänzt, dessen Laufzeit noch fehlt,
# trägt ihn hier ein – dann lehnt der Server ihn ab, statt ihn still zu ignorieren.
UNIMPLEMENTED_ACTIONS: set[str] = set()
UNIMPLEMENTED_WIDGETS: set[str] = set()
UNIMPLEMENTED_PHASE_KINDS: set[str] = set()
UNIMPLEMENTED_PHASE_VIEWS: set[str] = set()

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
    #: Optionaler Lookup: Quellwert → abgeleiteter Wert. Ohne `map` wird der
    #: Quellwert 1:1 kopiert (bisheriges Verhalten). Mit `map` wird er übersetzt
    #: (z. B. Position → Fahrzeuggruppe); ein nicht enthaltener Quellwert ergibt
    #: einen leeren Wert.
    map: Optional[dict[str, Any]] = None
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class AssignSpec(_Base):
    """Wie ein server_generated-Feld gefüllt wird.

    Heute genau ein Fall: eine fortlaufende Nummer aus einem Nummernkreis
    (`assign_sequence`). `companyRef` nennt das Feld, aus dem die Firma kommt –
    die Nummernkreise sind pro Firma gepflegt.
    """
    action: ActionType
    counter: Optional[str] = None
    companyRef: Optional[str] = None

    @model_validator(mode="after")
    def _assign_rules(self) -> "AssignSpec":
        if self.action != ActionType.assign_sequence:
            raise ValueError(f"assign.action „{self.action.value}“ ist keine Vergabe-Aktion "
                             f"(erlaubt: assign_sequence)")
        if not self.counter:
            raise ValueError("assign.counter fehlt (Name des Nummernkreises)")
        # Bekannter Nummernkreis? Ein Tippfehler („personalnr") oder ein noch nicht
        # gebauter Kreis darf nicht klaglos durchgehen und erst beim Phasenabschluss
        # auffallen. Import lokal – sonst Zyklus schemas ↔ services.
        from backend.services.process_sequences import KNOWN_COUNTERS
        if self.counter not in KNOWN_COUNTERS:
            raise ValueError(f"assign.counter „{self.counter}“ ist kein bekannter "
                             f"Nummernkreis (bekannt: {', '.join(sorted(KNOWN_COUNTERS))})")
        return self


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
    #: bei kind=assignable: Schlüssel des Personen-Feldes, das die zuständige
    #: Person enthält (muss widget='user' sein).
    fromField: Optional[str] = None
    rule: list[DepartmentRule] = Field(default_factory=list)  # bei kind=departments
    resetOnDescriptionChange: bool = False
    #: Beim Betreten der Phase automatisch benachrichtigen? Standard ja – sonst
    #: erfährt niemand, dass Arbeit ansteht. Nur abschaltbar, wenn es stört.
    notifyOnEnter: bool = True

    @model_validator(mode="after")
    def _kind_rules(self) -> "Responsibility":
        if self.kind == ResponsibilityKind.group and not self.group:
            raise ValueError("responsibility.kind=group erfordert `group`")
        if self.kind == ResponsibilityKind.user and not self.user:
            raise ValueError("responsibility.kind=user erfordert `user`")
        if self.kind == ResponsibilityKind.departments and not self.rule:
            raise ValueError("responsibility.kind=departments erfordert `rule`")
        if self.kind == ResponsibilityKind.assignable and not self.fromField:
            raise ValueError("responsibility.kind=assignable erfordert `fromField` "
                             "(Schlüssel des Personen-Feldes)")
        if self.kind == ResponsibilityKind.group_from_field and not self.fromField:
            raise ValueError("responsibility.kind=group_from_field erfordert `fromField` "
                             "(Schlüssel des Gruppen-Feldes)")
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
        if t == ActionType.assign_sequence:
            # Nur als FELD-Vergabe (fields[].assign) zulässig, nie als Automation:
            # process_engine.fire() fängt jede Action-Exception ab und auditiert sie
            # nur – ein erschöpfter Nummernkreis würde den Auftrag stillschweigend
            # ohne Nummer weiterschalten. Die Laufzeit hängt die Vergabe deshalb an
            # den Phasenabschluss (services/process_sequences.assign_due_sequences).
            raise ValueError("action assign_sequence ist nur als Feld-Vergabe zulässig "
                             "(widget=server_generated mit `assign`), nicht als Automation")
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


# ── Layout (nur Darstellung) ──────────────────────────────────────────────────
#
# Bewusst GETRENNT vom Verhalten: was ein Feld TUT (bearbeitbar, pflicht,
# bedingt) steht in `PhaseDef.fields`; WO und WIE BREIT es erscheint, steht hier.
# Ohne `layout` rendert die Phase wie bisher (alle Felder zweispaltig).

class LayoutWidth(str, Enum):
    quarter = "quarter"        # 1/4 Breite
    third = "third"            # 1/3
    half = "half"              # 1/2
    twothirds = "twothirds"    # 2/3
    full = "full"              # ganze Breite


class SectionVariant(str, Enum):
    """Akzentfarbe + Symbol des Abschnitts (wie im bestehenden Design)."""
    base = "base"
    hr = "hr"
    it = "it"
    fuhrpark = "fuhrpark"
    marketing = "marketing"
    travel = "travel"
    default = "default"


class NoteTone(str, Enum):
    info = "info"
    warning = "warning"
    success = "success"
    neutral = "neutral"


class LayoutField(_Base):
    type: Literal["field"] = "field"
    ref: str
    width: LayoutWidth = LayoutWidth.full


class LayoutNote(_Base):
    """Hinweisbox – reine Information, kein Datenfeld."""
    type: Literal["note"] = "note"
    text: str
    tone: NoteTone = NoteTone.info
    width: LayoutWidth = LayoutWidth.full
    #: Optionale Bedingung (gleiche DSL wie Feld-visibleWhen): die Notiz erscheint
    #: nur, wenn sie erfüllt ist – z. B. ein roter Hinweis „kein Firmenwagen“ nur
    #: für bestimmte Positionen.
    visibleWhen: Optional[dict] = None

    @model_validator(mode="after")
    def _check_visible_when(self) -> "LayoutNote":
        if self.visibleWhen is not None:
            validate_condition(self.visibleWhen, "layout.note.visibleWhen")
        return self


class LayoutHeading(_Base):
    """Zwischen-Überschrift innerhalb eines Abschnitts."""
    type: Literal["heading"] = "heading"
    text: str


class LayoutDivider(_Base):
    type: Literal["divider"] = "divider"


class LayoutSpacer(_Base):
    type: Literal["spacer"] = "spacer"


LayoutItem = Annotated[
    Union[LayoutField, LayoutNote, LayoutHeading, LayoutDivider, LayoutSpacer],
    Field(discriminator="type"),
]


class LayoutSection(_Base):
    type: Literal["section"] = "section"
    title: str = ""
    variant: SectionVariant = SectionVariant.default
    badge: Optional[str] = None
    description: Optional[str] = None
    #: Startet der Abschnitt eingeklappt? (Nur Darstellung.)
    collapsed: bool = False
    items: list[LayoutItem] = Field(default_factory=list)


#: onReject: entweder den ganzen Auftrag ablehnen oder auf eine frühere Phase
#: zurückgeben (Nachbesserung). Muster: "reject" | "back_to:<phase_key>"
_BACK_TO_RE = re.compile(r"^back_to:([a-z0-9_]+)$")


class ApprovalSpec(_Base):
    """Eine Freigabe-Phase: eine Frage, zwei Antworten.

    Der Mail-Link (`externalLink`) ist der Grund, warum es diesen Phasentyp
    überhaupt gibt: die entscheidende Person arbeitet nicht zwingend im System.
    Der Link führt auf eine BESTÄTIGUNGSSEITE, die Entscheidung selbst läuft über
    ein Formular (POST) – ein Link, der beim Anklicken sofort entscheidet, würde
    von Mail-Clients und Sicherheits-Scannern beim Vorab-Laden ausgelöst.
    """
    question: str
    approveLabel: str = "Freigeben"
    rejectLabel: str = "Ablehnen"
    #: Mail mit Entscheidungs-Link versenden? Ohne das läuft die Freigabe nur in der App.
    externalLink: bool = True
    #: Freitext-Vorlage für den Mail-Text der Freigabe. Platzhalter `{{feld.key}}`
    #: werden durch die Auftragswerte ersetzt (zusätzlich {{title}}, {{id}}). Leer
    #: = nur die Frage steht in der Mail. Reiner Text – HTML wird escaped.
    emailBody: Optional[str] = None
    #: Gültigkeit des Links (ISO-8601-Dauer).
    linkMaxAge: str = "P7D"
    #: Begründung bei Ablehnung verlangen.
    requireReason: bool = True
    #: Optionale Felder, in die Entscheidung bzw. Begründung geschrieben werden –
    #: dann greifen Sichtbarkeit und Verlauf automatisch mit.
    decisionField: Optional[str] = None
    reasonField: Optional[str] = None
    onReject: str = "reject"

    @model_validator(mode="after")
    def _approval_rules(self) -> "ApprovalSpec":
        if not (self.question or "").strip():
            raise ValueError("approval.question fehlt – ohne Frage weiß niemand, worüber er entscheidet")
        if self.onReject != "reject" and not _BACK_TO_RE.match(self.onReject):
            raise ValueError(f"approval.onReject „{self.onReject}“ ist unbekannt "
                             f"(erlaubt: reject oder back_to:<phasen_key>)")
        from backend.services.iso_duration import parse_duration
        try:
            sek = parse_duration(self.linkMaxAge)
        except Exception as exc:
            raise ValueError(f"approval.linkMaxAge „{self.linkMaxAge}“ ist keine ISO-8601-Dauer: {exc}")
        if not sek or sek <= 0:
            raise ValueError("approval.linkMaxAge muss größer als null sein")
        return self


class DocumentSpec(_Base):
    """Vorlage einer Dokument-Phase (view=document).

    `templateHtml` ist ein begrenztes HTML mit `{{feld.key}}`-Platzhaltern (plus
    {{title}}, {{id}} wie in der Mail-Vorlage). Zur Laufzeit wird es
    vorausgefüllt, im Editor angepasst und als Word/PDF exportiert. `filename`
    darf ebenfalls Platzhalter enthalten (z. B. Arbeitsvertrag_{{base.last_name}}).
    """
    templateHtml: str = ""
    filename: str = "Dokument"
    title: str = "Dokument"


class PhaseDef(_Base):
    key: str
    label: Optional[str] = None
    kind: PhaseKind
    view: PhaseView = PhaseView.form
    enterStatus: Optional[str] = None
    grantsFullView: bool = False
    responsibility: Responsibility
    #: Pflicht bei kind=approval, sonst verboten.
    approval: Optional[ApprovalSpec] = None
    #: Pflicht bei view=document, sonst verboten.
    document: Optional[DocumentSpec] = None
    fields: list[FieldRef] = Field(default_factory=list)
    #: Optionale Darstellung. Felder, die hier NICHT vorkommen, werden hinten in
    #: einem Sammel-Abschnitt gerendert – so wird nie ein Feld unsichtbar.
    layout: list[LayoutSection] = Field(default_factory=list)
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
        # Freigabe-Phase und Freigabe-Block gehören zusammen: ohne Block wüsste die
        # Laufzeit nicht, worüber entschieden wird; mit Block ohne Phasenart würde er
        # stillschweigend ignoriert.
        if self.kind == PhaseKind.approval and self.approval is None:
            raise ValueError(f"Phase „{self.key}“: kind=approval erfordert einen "
                             f"`approval`-Block (Frage, Beschriftungen, Verhalten bei Nein)")
        if self.kind != PhaseKind.approval and self.approval is not None:
            raise ValueError(f"Phase „{self.key}“: `approval` ist nur bei kind=approval erlaubt")
        if self.view == PhaseView.approval and self.kind != PhaseKind.approval:
            raise ValueError(f"Phase „{self.key}“: view=approval passt nur zu kind=approval")
        return self

    @model_validator(mode="after")
    def _check_constraints(self) -> "PhaseDef":
        for i, c in enumerate(self.constraints):
            if not isinstance(c, dict) or "when" not in c or "message" not in c:
                raise ValueError(f"Phase „{self.key}“: constraints[{i}] braucht `when` und `message`")
            validate_condition(c["when"], f"{self.key}.constraints[{i}].when")
        return self


# ── Prozess ──────────────────────────────────────────────────────────────────

class CreatePermissions(_Base):
    """Wer darf Aufträge dieses Prozesses ANLEGEN?

    Bewusst Teil der Definition (statt einer separaten Tabelle wie im
    Alt-System): So steht alles zu einem Prozess an einer Stelle und wandert
    beim Export/Import/Kopieren mit.

    Default = niemand außer Admin. Bewusst restriktiv: ein neuer Prozess soll
    nicht versehentlich für alle offen sein.
    """
    everyone: bool = False
    #: Gruppen-IDs – Fachabteilungen ODER AD-Gruppen (das Alt-System mischte beides).
    groups: list[str] = Field(default_factory=list)
    #: Einzelne Personen (User-IDs), für Ausnahmen.
    users: list[str] = Field(default_factory=list)


class ProcessDefinition(_Base):
    schemaVersion: int = CURRENT_SCHEMA_VERSION
    key: str
    name: str
    description: Optional[str] = None
    icon: Optional[str] = None
    #: Darf der Auftrags-Titel NACH dem Anlegen noch geändert werden? False =
    #: der Titel wird beim Anlegen festgelegt und ist danach überall nur lesbar
    #: (durchgesetzt im PATCH-Endpunkt, nicht nur in der Oberfläche). Default
    #: True, damit bestehende Definitionen ihr Verhalten behalten.
    titleEditable: bool = True
    createPermissions: CreatePermissions = Field(default_factory=CreatePermissions)
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

        # Layout: darf nur Felder platzieren, die die Phase auch führt, und jedes
        # höchstens einmal (sonst stünde ein Feld doppelt im Formular).
        for p in self.phases:
            phase_refs = {fr.ref for fr in p.fields}
            placed: set = set()
            for si, sec in enumerate(p.layout):
                for ii, item in enumerate(sec.items):
                    if getattr(item, "type", None) != "field":
                        continue
                    where = f"Phase „{p.key}“.layout[{si}].items[{ii}]"
                    if item.ref not in phase_refs:
                        raise ValueError(
                            f"{where}: „{item.ref}“ ist in dieser Phase nicht eingebunden")
                    if item.ref in placed:
                        raise ValueError(f"{where}: „{item.ref}“ ist mehrfach platziert")
                    placed.add(item.ref)

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

        # Ein `computed.map`-Lookup arbeitet mit Zeichenketten-Schlüsseln (JSON) –
        # er ergibt nur für Felder Sinn, deren Wert eine Zeichenkette ist. Auf
        # Zahl/Checkbox/Mehrfachauswahl würden Backend (nativer Schlüssel) und
        # Frontend sonst auseinanderlaufen; hier hart ausschließen.
        _map_source_ok = {Widget.select, Widget.text, Widget.textarea, Widget.date,
                          Widget.user, Widget.company, Widget.group, Widget.server_generated}
        for f in self.fields:
            if f.computed:
                _need(f.computed.from_, f"Feld „{f.key}“.computed.from")
                if f.computed.map is not None:
                    src = next((x for x in self.fields if x.key == f.computed.from_), None)
                    if src is not None and src.widget not in _map_source_ok:
                        raise ValueError(
                            f"Feld „{f.key}“.computed.map: Das Quellfeld "
                            f"„{f.computed.from_}“ (widget={src.widget.value}) ist nicht "
                            f"unterstützt – ein Lookup arbeitet nur mit Text-/Auswahl-Feldern.")

        for p in self.phases:
            for fr in p.fields:
                for cond, lbl in ((fr.requiredWhen, "requiredWhen"), (fr.visibleWhen, "visibleWhen")):
                    if cond:
                        for r in dsl_refs(cond):
                            _need(r, f"{p.key}.{fr.ref}.{lbl}")
            for si, sec in enumerate(p.layout):
                for ii, item in enumerate(sec.items):
                    vw = getattr(item, "visibleWhen", None)
                    if vw:
                        for r in dsl_refs(vw):
                            _need(r, f"{p.key}.layout[{si}].items[{ii}].visibleWhen")
            for i, c in enumerate(p.constraints):
                for r in dsl_refs(c.get("when", {})):
                    _need(r, f"{p.key}.constraints[{i}].when")
            resp = p.responsibility
            # kind=assignable: das Quellfeld muss existieren UND ein Personen-Feld
            # sein – sonst stünde dort später irgendein Text statt einer User-ID.
            erwartet = {ResponsibilityKind.assignable: (Widget.user, "Personen-Feld"),
                        ResponsibilityKind.group_from_field: (Widget.group, "Gruppen-Feld")}
            if resp.kind in erwartet and resp.fromField:
                widget, bezeichnung = erwartet[resp.kind]
                src = next((f for f in self.fields if f.key == resp.fromField), None)
                if src is None:
                    raise ValueError(
                        f"Phase „{p.key}“.responsibility.fromField: „{resp.fromField}“ "
                        f"ist nicht im Feld-Katalog")
                if src.widget != widget:
                    raise ValueError(
                        f"Phase „{p.key}“.responsibility.fromField: „{resp.fromField}“ muss "
                        f"ein {bezeichnung} sein (widget={widget.value}), ist aber "
                        f"„{src.widget.value}“")
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

        # Freigabe-Phasen: die Ziel-Felder müssen existieren, und ein Rücksprung
        # muss auf eine echte, FRÜHERE Phase zeigen (sonst läuft die Ablehnung ins
        # Leere oder – bei einem Sprung nach vorn – überspringt sie Arbeit).
        for i, p in enumerate(self.phases):
            if p.approval is None:
                continue
            for feld, lbl in ((p.approval.decisionField, "decisionField"),
                              (p.approval.reasonField, "reasonField")):
                if feld:
                    _need(feld, f"Phase „{p.key}“.approval.{lbl}")
            # Mail-Vorlage: jede {{variable}} muss ein Katalog-Feld sein (oder eine
            # Spezial-Variable). Sonst stünde in der Freigabe-Mail eine leere Stelle,
            # ohne dass es jemandem auffällt.
            if p.approval.emailBody:
                from backend.services import mail_template as _mt
                feld_je_key = {f.key: f for f in self.fields}
                for ref in _mt.field_refs(p.approval.emailBody):
                    _need(ref, f"Phase „{p.key}“.approval.emailBody (Variable «{ref}»)")
                    f = feld_je_key.get(ref)
                    # Nicht-skalare Felder lassen sich nicht als Text einsetzen –
                    # sie stünden sonst als roher Datensatz in der Mail.
                    if f and f.widget in (Widget.collection, Widget.attachment):
                        raise ValueError(
                            f"Phase „{p.key}“.approval.emailBody: Variable «{ref}» verweist auf ein "
                            f"Feld vom Typ „{f.widget.value}“ – das lässt sich nicht als Text in die "
                            f"Mail einsetzen. Bitte ein einfaches Feld verwenden.")
                # Kollision Spezial-Variable ↔ Feld-Key: sonst gewänne still die
                # Spezial-Variable und in der Mail stünde der Auftragstitel/-id statt
                # des Feldwerts, ohne Warnung.
                for sv in _mt.variables(p.approval.emailBody):
                    if sv in _mt.SPECIAL_VARS and sv in feld_je_key:
                        gemeint = "den Auftragstitel" if sv == "title" else "die Auftragsnummer"
                        raise ValueError(
                            f"Phase „{p.key}“.approval.emailBody: «{sv}» ist als Mail-Variable für "
                            f"{gemeint} reserviert, es gibt aber ein Feld mit diesem Schlüssel. "
                            f"Bitte das Feld umbenennen.")
            m = _BACK_TO_RE.match(p.approval.onReject)
            if m:
                ziel = m.group(1)
                if ziel not in pkeys:
                    raise ValueError(f"Phase „{p.key}“.approval.onReject: Phase „{ziel}“ "
                                     f"gibt es nicht")
                if pkeys.index(ziel) >= i:
                    raise ValueError(f"Phase „{p.key}“.approval.onReject: „{ziel}“ liegt nicht "
                                     f"VOR dieser Phase – ein Rücksprung nach vorn würde "
                                     f"Arbeit überspringen")

        # Dokument-Phasen: view=document und die Vorlage (document) gehören
        # zusammen, und jede {{variable}} der Vorlage muss ein Katalog-Feld sein
        # (sonst bliebe im Vertrag eine leere Stelle, ohne dass es auffällt).
        for p in self.phases:
            if (p.view == PhaseView.document) != (p.document is not None):
                raise ValueError(
                    f"Phase „{p.key}“: „view=document“ und eine Dokument-Vorlage gehören "
                    f"zusammen – bitte beides setzen oder beides weglassen")
            if p.document is not None:
                from backend.services import mail_template as _mt
                for txt in (p.document.templateHtml, p.document.filename):
                    for ref in _mt.field_refs(txt):
                        _need(ref, f"Phase „{p.key}“.document (Variable «{ref}»)")

        # server_generated-Felder füllt ausschließlich der Server. Wären sie in
        # einer Phase editierbar, könnte der Client eine vergebene Nummer setzen
        # oder überschreiben (apply_writes entscheidet allein über den Phasen-mode).
        vergeben = {f.key for f in self.fields if f.widget == Widget.server_generated}
        for p in self.phases:
            for fr in p.fields:
                if fr.ref in vergeben and fr.mode in (FieldMode.editable, FieldMode.append_only):
                    raise ValueError(
                        f"Phase „{p.key}“: „{fr.ref}“ wird vom Server vergeben "
                        f"(server_generated) und darf nicht editierbar sein")

        # Vergabe-Zeitpunkt und Firma müssen bestimmbar sein, sonst bekommt das Feld
        # NIE eine Nummer bzw. die Vergabe scheitert erst zur Laufzeit.
        gefuehrt = {fr.ref for p in self.phases for fr in p.fields}
        for f in self.fields:
            if f.widget != Widget.server_generated:
                continue
            if f.key not in gefuehrt:
                raise ValueError(
                    f"Feld „{f.key}“ wird vom Server vergeben, ist aber in keiner Phase "
                    f"eingebunden – die Vergabe hängt am Abschluss der ERSTEN Phase, die "
                    f"das Feld führt; so bekäme es nie eine Nummer")
            ref = (f.assign.companyRef or "") if f.assign else ""
            src = next((x for x in self.fields if x.key == ref), None)
            if src is None:
                raise ValueError(
                    f"Feld „{f.key}“.assign.companyRef: „{ref}“ ist nicht im Feld-Katalog "
                    f"(Nummernkreise werden je Firma geführt)")
            if src.widget != Widget.company:
                raise ValueError(
                    f"Feld „{f.key}“.assign.companyRef: „{ref}“ muss ein Firmen-Feld sein "
                    f"(widget=company), ist aber „{src.widget.value}“")

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
