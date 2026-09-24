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

#: Obergrenze der Länge eines Feld-Constraint-Regex (ReDoS-Schutz): ein sehr langes
#: Muster ist ein Warnzeichen und bläht den Backtracking-Raum auf. Großzügig – echte
#: Formate (Telefon, PLZ, Personalnummer …) sind kurz.
_PATTERN_MAX_LEN = 1000


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
    directus = "directus"                # Auswahl aus einer Directus-Quelle (Live-Dropdown)
    directus_multi = "directus_multi"    # Mehrfachauswahl aus einer Directus-Quelle (Liste von IDs)
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
    #: Eine bestimmte Fachabteilung (Trigger.group) hat ihren Teil einer
    #: department-Review-Phase abgeschlossen (Status „done“).
    on_department_done = "on_department_done"


class ActionType(str, Enum):
    notify = "notify"
    escalate = "escalate"
    set_field = "set_field"
    set_priority = "set_priority"
    set_status = "set_status"
    assign_sequence = "assign_sequence"
    auto_advance = "auto_advance"
    #: Automatische Firmenmail (vorname.nachname@firmendomain) + blockierende
    #: Directus-Eindeutigkeitsprüfung beim Phasen-Verlassen (services/company_email_action).
    company_email = "company_email"
    #: Datensatz in Directus anlegen/ändern/löschen (services/directus_write).
    directus_write = "directus_write"
    #: Beliebiger ausgehender HTTP-/API-Aufruf (services/http_action). URL, Header
    #: und Body dürfen {{feld.key}}-Platzhalter aus den Auftragswerten tragen.
    http_request = "http_request"


class DirectusOperation(str, Enum):
    create = "create"
    update = "update"
    delete = "delete"


class DirectusWriteOnError(str, Enum):
    """Verhalten, wenn der Directus-Schreibvorgang fehlschlägt.

    continue_ : Fehler protokollieren/melden, Ablauf läuft weiter (Default,
                rückwärtskompatibel).
    block     : Fehler durchreichen – die auslösende Aktion (z. B. das Abschließen
                der Fachabteilung) wird abgebrochen. So gilt eine Fachabteilung erst
                als erledigt, wenn der Datensatz WIRKLICH in Directus liegt.
    """
    continue_ = "continue"
    block = "block"


class DirectusWriteResolve(str, Enum):
    """Optionale Auflösung eines Zuordnungs-Quellwerts vor dem Schreiben.

    company_directus_id: Die Quelle ist ein Firmen-Feld (widget=company) und trägt
    den Firmennamen. Statt des Namens wird die an der lokalen Firma hinterlegte
    alphacore-Firmen-ID geschrieben – so trifft der Directus-Fremdschlüssel `firma`,
    während die Personalnummer-Logik weiterhin am Firmennamen hängt.
    """
    company_directus_id = "company_directus_id"


class HttpMethod(str, Enum):
    get = "GET"
    post = "POST"
    put = "PUT"
    patch = "PATCH"
    delete = "DELETE"


class HttpRequestOnError(str, Enum):
    """Verhalten, wenn der API-Aufruf fehlschlägt (Netzfehler, Timeout, Status ≥ 400).

    continue_ : Fehler melden (Verlauf/Audit/Mail), Ablauf läuft weiter (Default).
    block     : Fehler durchreichen – die auslösende Aktion (z. B. das Abschließen
                der Fachabteilung) bricht ab; erst wenn der Aufruf klappt, gilt sie
                als erledigt. Blockierend wirkt das NUR im synchronen
                on_department_done-Pfad (wie bei directus_write); in jedem anderen
                Auslöser wird der Fehler nur auditiert.
    """
    continue_ = "continue"
    block = "block"


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
ALLOWED_RECIPIENTS = {"responsible", "owner", "watchers"}   # + "group:<id>", "user:<id>"

#: Präfixe für ID-behaftete Empfänger-Ziele: eine Fachgruppe (deren Verteiler)
#: bzw. eine einzelne Person (deren Mail).
_RECIPIENT_PREFIXES = ("group:", "user:")


def is_valid_recipient(token: str) -> bool:
    """Ein Empfänger-Token ist gültig, wenn es eine bekannte Rolle ist oder ein
    ID-behaftetes Ziel `group:<id>` / `user:<id>` mit nicht-leerer ID."""
    if not token:
        return False
    if token in ALLOWED_RECIPIENTS:
        return True
    return any(token.startswith(p) and token[len(p):].strip() for p in _RECIPIENT_PREFIXES)

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
            if len(v) > _PATTERN_MAX_LEN:
                raise ValueError(f"Regex-Pattern zu lang (max {_PATTERN_MAX_LEN} Zeichen) – "
                                 f"Schutz vor katastrophalem Backtracking (ReDoS)")
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
    #: Quellfeld für op=copy/days_between. Bei op="template" nicht gesetzt (die
    #: Quellen stehen dort als {{feld}} in `template`).
    from_: Optional[str] = Field(default=None, alias="from")
    #: Zweites Quellfeld – nur für op="days_between" (das Enddatum). Das Ergebnis
    #: ist die Tagesdifferenz `to − from`.
    to: Optional[str] = None
    #: Ableitungs-Operation. None/"copy" = Quellwert 1:1 kopieren bzw. per `map`
    #: übersetzen (bisheriges Verhalten). "days_between" = Ganzzahl-Tagesdifferenz
    #: zweier Datumsfelder (from, to). "template" = Textvorlage mit {{feld}}-
    #: Platzhaltern, die aus anderen Feldwerten zusammengesetzt wird.
    op: Optional[str] = None
    #: Optionaler Lookup: Quellwert → abgeleiteter Wert. Ohne `map` wird der
    #: Quellwert 1:1 kopiert (bisheriges Verhalten). Mit `map` wird er übersetzt
    #: (z. B. Position → Fahrzeuggruppe); ein nicht enthaltener Quellwert ergibt
    #: einen leeren Wert.
    map: Optional[dict[str, Any]] = None
    #: Textvorlage für op="template": Platzhalter {{feld.key}} werden durch die
    #: (formatierten) Werte anderer Felder ersetzt.
    template: Optional[str] = None
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    @model_validator(mode="after")
    def _op_rules(self) -> "ComputedSpec":
        if self.op not in (None, "copy", "days_between", "template"):
            raise ValueError(f"computed.op „{self.op}“ ist unbekannt "
                             f"(erlaubt: copy, days_between, template)")
        if self.op == "template":
            if not (self.template and self.template.strip()):
                raise ValueError("computed.op=template benötigt `template` "
                                 "(Textvorlage mit {{feld}}-Platzhaltern)")
            if self.from_ or self.to is not None or self.map is not None:
                raise ValueError("computed.op=template kombiniert nicht mit from/to/map")
            return self
        # copy / days_between: `from` ist Pflicht, `template` nicht erlaubt.
        if not self.from_:
            raise ValueError("computed erfordert `from` (Quellfeld)")
        if self.template is not None:
            raise ValueError("computed.template ist nur für op=template zulässig")
        if self.op == "days_between":
            if not self.to:
                raise ValueError("computed.op=days_between benötigt ein zweites "
                                 "Datumsfeld „to“")
            if self.map is not None:
                raise ValueError("computed.map ist mit op=days_between nicht kombinierbar")
        elif self.to is not None:
            raise ValueError("computed.to ist nur für op=days_between zulässig")
        return self


class DirectusBinding(_Base):
    """Auto-Fill-Zuordnung eines directus-Felds: der Wert am dot-Pfad `source`
    des gewählten Directus-Datensatzes wird beim Auswählen als Snapshot in das
    Zielfeld `target` (Prozess-Feld-Key) geschrieben."""
    source: str          # Directus-Feldpfad, z. B. "firma.name"
    target: str          # Prozess-Feld-Key, z. B. "konditionen.firma"


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


class PrefillSpec(_Base):
    """Ein Feld beim ANLEGEN aus den Daten der angemeldeten Person vorbelegen.

    `source`: "employee" = Directus-Mitarbeiter-Datensatz (user["employee"]),
    "user" = Session-Felder (email, displayName, phone, mobile, company, position).
    `field`: Attribut in der Quelle; dot-Pfad löst Relationen auf, z. B.
    "location.name". Zusammen mit einem read-only Feld in der Start-Phase ergibt
    das ein fest vorbelegtes, nicht editierbares Antragsteller-Feld (serverseitig
    autoritativ gesetzt – manipulationssicher).
    """
    source: str = "employee"
    field: str
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    @model_validator(mode="after")
    def _rules(self) -> "PrefillSpec":
        if self.source not in ("employee", "user"):
            raise ValueError(f"prefill.source ist unbekannt: {self.source!r} "
                             f"(erlaubt: employee, user)")
        if not self.field:
            raise ValueError("prefill.field fehlt")
        return self


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
    directusSource: Optional[str] = None        # Schlüssel einer Directus-Quelle (bei widget=directus)
    directusFieldMap: list[DirectusBinding] = Field(default_factory=list)  # Auto-Fill der Zielfelder
    prefill: Optional[PrefillSpec] = None       # Vorbelegung aus den Daten des angemeldeten Users

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
        directus_widgets = {Widget.directus, Widget.directus_multi}
        if self.widget in directus_widgets and not self.directusSource:
            raise ValueError(f"Feld „{self.key}“: widget={self.widget.value} braucht `directusSource`")
        if self.widget not in directus_widgets and (self.directusSource or self.directusFieldMap):
            raise ValueError(f"Feld „{self.key}“: `directusSource`/`directusFieldMap` nur bei widget=directus/directus_multi")
        # Mehrfachauswahl kennt keinen Einzel-Snapshot in ein Zielfeld.
        if self.widget == Widget.directus_multi and self.directusFieldMap:
            raise ValueError(f"Feld „{self.key}“: `directusFieldMap` ist bei directus_multi nicht erlaubt")
        return self


# ── Phasen ───────────────────────────────────────────────────────────────────

class FieldRef(_Base):
    ref: str
    mode: FieldMode = FieldMode.editable
    required: bool = False
    requiredWhen: Optional[dict] = None
    visibleWhen: Optional[dict] = None
    #: Schaltet ein sonst read-only Feld BEDINGT editierbar (gleiche DSL). Nutzung
    #: z. B.: Feld ist read-only vorbelegt, wird aber bei einem Konflikt-Flag
    #: bearbeitbar. Wirkt additiv zum `mode`.
    editableWhen: Optional[dict] = None

    @model_validator(mode="after")
    def _check_dsl(self) -> "FieldRef":
        if self.requiredWhen is not None:
            validate_condition(self.requiredWhen, f"{self.ref}.requiredWhen")
        if self.visibleWhen is not None:
            validate_condition(self.visibleWhen, f"{self.ref}.visibleWhen")
        if self.editableWhen is not None:
            validate_condition(self.editableWhen, f"{self.ref}.editableWhen")
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
    group: Optional[str] = None      # bei on_department_done: die Fachabteilung (Gruppen-ID)

    @model_validator(mode="after")
    def _trigger_rules(self) -> "Trigger":
        from backend.services.iso_duration import parse_duration
        if self.type == TriggerType.on_department_done and not self.group:
            raise ValueError("trigger on_department_done erfordert `group` (Fachabteilung)")
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


class DirectusWriteCondition(_Base):
    """Bedingung für eine Feld-Zuordnung: die Zuordnung wird NUR geschrieben, wenn
    das Prozess-Feld `field` (als Text verglichen) gleich `equals` ist. Damit lässt
    sich z. B. `has_car=true` nur setzen, wenn `fuhrpark.car` == „Ja". Trifft die
    Bedingung nicht zu, bleibt das Directus-Zielfeld unangetastet."""
    field: str
    #: Vergleichswert; gegen den (als Text normalisierten) Prozesswert geprüft
    #: (Bool → "true"/"false"). Ein Select speichert seinen Options-Wert, z. B. „Ja".
    equals: Union[bool, int, float, str] = ""

    @model_validator(mode="after")
    def _cond_rules(self) -> "DirectusWriteCondition":
        if not str(self.field).strip():
            raise ValueError("Bedingung einer Directus-Zuordnung braucht ein Prozess-Feld (`field`)")
        return self


class DirectusWriteBinding(_Base):
    """Eine Feld-Zuordnung fürs Schreiben nach Directus. Der Wert kommt entweder
    aus einem Prozess-Feld (`source`) ODER ist ein fester Wert (`value`) und wird
    in das Directus-Feld `target` geschrieben – genau EINES von beiden.

    `resolve` übersetzt den Quellwert optional vor dem Schreiben (siehe
    DirectusWriteResolve) – z. B. Firmenname → alphacore-Firmen-ID; nur mit
    `source` sinnvoll, nicht bei einem festen `value`.

    `when` macht die Zuordnung bedingt: sie wird nur geschrieben, wenn das dort
    genannte Prozess-Feld dem Vergleichswert entspricht (siehe
    DirectusWriteCondition). Ohne `when` wird immer geschrieben (bisheriges
    Verhalten)."""
    source: Optional[str] = None
    target: str
    value: Optional[Union[bool, int, float, str]] = None
    resolve: Optional[DirectusWriteResolve] = None
    when: Optional[DirectusWriteCondition] = None

    @model_validator(mode="after")
    def _binding_rules(self) -> "DirectusWriteBinding":
        has_source = bool(self.source)
        has_value = self.value is not None
        if has_source == has_value:
            raise ValueError("Directus-Zuordnung braucht genau EINES: `source` "
                             "(Prozess-Feld) ODER `value` (fester Wert)")
        if has_value and self.resolve is not None:
            raise ValueError("`resolve` ist bei einem festen `value` nicht erlaubt")
        return self


class DirectusWriteSpec(_Base):
    """Konfiguration der Aktion `directus_write`.

    `idField` ist ein Prozess-Feld: bei `create` wird die vergebene Directus-id
    DORTHIN zurückgeschrieben (und dient als Doppelanlage-Schutz); bei
    `update`/`delete` wird die id VON DORT gelesen, um den Datensatz zu treffen.
    """
    operation: DirectusOperation
    collection: str
    fieldMap: list[DirectusWriteBinding] = Field(default_factory=list)
    idField: str
    #: Fehlerverhalten (siehe DirectusWriteOnError). Default: weiterlaufen.
    onError: DirectusWriteOnError = DirectusWriteOnError.continue_
    #: Optionaler Geschäftsschlüssel für get-or-create (nur bei `create`): der Name
    #: eines Directus-Felds, das AUCH `target` einer fieldMap-Zuordnung ist. Vor dem
    #: Anlegen wird per Gleichheit auf diesem Feld gesucht; existiert der Datensatz
    #: schon, wird dessen id übernommen statt ein Duplikat anzulegen.
    matchField: Optional[str] = None


#: Obergrenze für den Aufruf-Timeout (Sekunden) – schützt Motor/Scheduler vor
#: einer hängenden Gegenstelle. Default bewusst kurz.
_HTTP_MAX_TIMEOUT = 60
_HTTP_DEFAULT_TIMEOUT = 10


class HttpHeader(_Base):
    """Ein HTTP-Header für den API-Aufruf. `value` darf {{feld.key}}-Platzhalter
    tragen (roh eingesetzt – der Header-Autor ist Admin)."""
    name: str
    value: str = ""

    @model_validator(mode="after")
    def _header_rules(self) -> "HttpHeader":
        if not self.name.strip():
            raise ValueError("HTTP-Header: `name` fehlt")
        return self


class HttpRequestSpec(_Base):
    """Konfiguration der Aktion `http_request` (ausgehender API-Aufruf).

    `url`, jeder Header-`value` und `body` dürfen `{{feld.key}}`-Platzhalter aus den
    Auftragswerten tragen (zusätzlich {{title}}, {{id}}); in der URL werden die
    eingesetzten Werte prozentkodiert, in Headern/Body roh übernommen. Reiner Text –
    die Definition pflegt die Admin-Rolle (Prozess-Editor), dieselbe
    Vertrauensstellung wie directus_write.
    """
    method: HttpMethod = HttpMethod.post
    url: str
    headers: list[HttpHeader] = Field(default_factory=list)
    body: Optional[str] = None
    #: Content-Type für den Body. Leer + Body gesetzt und kein eigener Header →
    #: application/json.
    contentType: Optional[str] = None
    timeoutSeconds: int = _HTTP_DEFAULT_TIMEOUT
    onError: HttpRequestOnError = HttpRequestOnError.continue_

    @model_validator(mode="after")
    def _http_rules(self) -> "HttpRequestSpec":
        u = (self.url or "").strip()
        if not u:
            raise ValueError("http_request: `url` fehlt")
        if not (u.startswith("http://") or u.startswith("https://")):
            raise ValueError("http_request: `url` muss mit http:// oder https:// beginnen")
        if self.timeoutSeconds < 1 or self.timeoutSeconds > _HTTP_MAX_TIMEOUT:
            raise ValueError(f"http_request: `timeoutSeconds` muss zwischen 1 und "
                             f"{_HTTP_MAX_TIMEOUT} liegen")
        return self


class EmailSpec(_Base):
    """Automatische Firmenmail + Directus-Eindeutigkeitsprüfung (blockierend beim
    Phasen-Verlassen). Die Mail wird aus Vor-/Nachname und der E-Mail-Domain der
    gewählten Firma gebildet (vorname.nachname@domain, transliteriert, klein) –
    aber nur, wenn `targetField` leer ist (manuelle Eingabe hat Vorrang). Existiert
    sie schon in `collection`.`emailField` (oder ist das Format Exchange-untauglich),
    wird `conflictField` gesetzt und die Phase NICHT abgeschlossen; das Feld lässt
    sich per editableWhen dann ändern."""
    targetField: str      # Zielfeld der Mail, z. B. base.firmenmailadresse
    firstNameField: str   # z. B. base.first_name
    lastNameField: str    # z. B. base.last_name
    companyField: str     # Firmenname → Domain-Lookup (z. B. base.contract_company)
    collection: str       # Directus-Collection, z. B. mitarbeitende
    emailField: str       # Feld in der Collection, z. B. email
    conflictField: str    # bool-Feld, das bei Konflikt gesetzt wird
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class Action(_Base):
    type: ActionType
    to: Optional[str] = None         # Empfänger-Resolver (notify/escalate)
    #: Mehrere Empfänger-Ziele (notify/escalate). Ist die Liste gesetzt, ersetzt
    #: sie `to`; jedes Token ist eine Rolle, `group:<id>` oder `user:<id>`.
    recipients: Optional[list[str]] = None
    template: Optional[str] = None
    field: Optional[str] = None
    value: Optional[Any] = None
    counter: Optional[str] = None    # bei assign_sequence
    directus: Optional[DirectusWriteSpec] = None   # bei directus_write
    http: Optional[HttpRequestSpec] = None         # bei http_request
    email: Optional[EmailSpec] = None              # bei company_email

    @model_validator(mode="after")
    def _action_rules(self) -> "Action":
        t = self.type
        if t != ActionType.directus_write and self.directus is not None:
            raise ValueError("`directus` ist nur bei action directus_write erlaubt")
        if t != ActionType.http_request and self.http is not None:
            raise ValueError("`http` ist nur bei action http_request erlaubt")
        if t != ActionType.company_email and self.email is not None:
            raise ValueError("`email` ist nur bei action company_email erlaubt")
        if t == ActionType.company_email and self.email is None:
            raise ValueError("action company_email erfordert `email` (Ziel-/Namens-/"
                             "Firmen-/Directus-Felder)")
        if t == ActionType.http_request and self.http is None:
            raise ValueError("action http_request erfordert `http` (URL, Methode, …)")
        if t == ActionType.directus_write:
            d = self.directus
            if d is None:
                raise ValueError("action directus_write erfordert `directus` (Operation, Collection, …)")
            if not d.collection.strip():
                raise ValueError("action directus_write: `collection` fehlt")
            if not d.idField.strip():
                raise ValueError("action directus_write: `idField` fehlt "
                                 "(Prozessfeld für die Directus-id)")
            if d.operation in (DirectusOperation.create, DirectusOperation.update) and not d.fieldMap:
                raise ValueError(f"action directus_write ({d.operation.value}) erfordert "
                                 "mindestens eine Feld-Zuordnung")
        if t.value in UNIMPLEMENTED_ACTIONS:
            raise ValueError(f"action „{t.value}“ ist noch nicht implementiert und "
                             f"kann daher nicht veröffentlicht werden")
        if t in (ActionType.notify, ActionType.escalate):
            tokens = list(self.recipients or [])
            if self.to:
                tokens.append(self.to)
            if not tokens:
                raise ValueError(f"action {t.value} erfordert `to` oder `recipients`")
            # Nur auflösbare Ziele zulassen – sonst landet die Mail stumm im Fallback.
            for tok in tokens:
                if not is_valid_recipient(tok):
                    raise ValueError(f"action {t.value}: unbekanntes Ziel „{tok}“ "
                                     f"(erlaubt: {', '.join(sorted(ALLOWED_RECIPIENTS))}, "
                                     f"group:<id>, user:<id>)")
        elif self.recipients is not None:
            raise ValueError("`recipients` ist nur bei action notify/escalate erlaubt")
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

    @model_validator(mode="after")
    def _company_email_on_exit(self) -> "Automation":
        """company_email blockiert den Phasenabschluss – das wirkt nur im synchronen
        on_exit-Pfad (VOR dem Persistieren des Übergangs). Anderswo liefe es über den
        fehlerschluckenden fire()-Pfad und die Blockade wäre wirkungslos."""
        if self.action.type == ActionType.company_email \
                and self.trigger.type != TriggerType.on_exit:
            raise ValueError(f"automation[{self.id}]: action company_email ist nur mit "
                             f"Auslöser on_exit erlaubt (die Blockade wirkt nur dort).")
        return self

    @model_validator(mode="after")
    def _blocking_only_on_department_done(self) -> "Automation":
        """onError=block wirkt NUR im synchronen on_department_done-Pfad (dort läuft
        die Aktion VOR dem Persistieren von „done" und bricht den Abschluss ab). Bei
        jedem anderen Auslöser läuft sie über den fehlerschluckenden fire()-Pfad: die
        Phase schaltet trotzdem weiter, der Fehlschlag wird nur generisch auditiert –
        schlechter als continue. So ein wirkungsloser „block" wäre ein stiller
        Footgun; deshalb hier ablehnen statt still ignorieren."""
        oe = None
        act = self.action
        if act.type == ActionType.directus_write and act.directus is not None:
            oe = act.directus.onError
        elif act.type == ActionType.http_request and act.http is not None:
            oe = act.http.onError
        blocks = oe is not None and str(getattr(oe, "value", oe)) == "block"
        if blocks and self.trigger.type != TriggerType.on_department_done:
            raise ValueError(
                f"automation[{self.id}]: onError=block wirkt nur beim Auslöser "
                f"„Fachabteilung abgeschlossen“ (on_department_done). Bei "
                f"„{self.trigger.type.value}“ schaltet die Phase trotzdem weiter – "
                f"entweder den Auslöser ändern oder onError=continue verwenden.")
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


#: Sonderquelle einer Marker-Zuordnung: der aktuelle Tag (kein Katalog-Feld).
TODAY_BINDING = "@today"


class DocumentBinding(_Base):
    """Was ein `{{marker}}` beim Export füllt.

    `field` ist ein Katalog-Feldschlüssel ODER die Sonderquelle `@today`
    (aktuelles Datum). `offset` ist ein optionaler Rechen-Versatz für NUMERISCHE
    Felder (z. B. -20 für „Urlaubsanspruch minus 20"); bei nicht-numerischen
    Werten und bei `@today` wird er ignoriert.
    """
    field: str
    offset: Optional[int] = None


class DocumentSpec(_Base):
    """Vorlage einer Dokument-Phase (view=document).

    `templateHtml` ist ein begrenztes HTML mit `{{feld.key}}`-Platzhaltern (plus
    {{title}}, {{id}} wie in der Mail-Vorlage). Zur Laufzeit wird es
    vorausgefüllt, im Editor angepasst und als Word/PDF exportiert. `filename`
    darf ebenfalls Platzhalter enthalten (z. B. Arbeitsvertrag_{{base.last_name}}).
    """
    #: Stabiler Schlüssel des Dokuments INNERHALB der Phase (mehrere Dokumente je
    #: Phase möglich, z. B. Word-Vertrag + PDF-Fragebogen). Leer nur bei der
    #: Alt-Form (einzelnes `document`), die beim Laden auf „dokument" gehoben wird.
    key: str = ""
    templateHtml: str = ""
    filename: str = "Dokument"
    title: str = "Dokument"
    #: Marker→Zuordnung für eine hochgeladene .docx-Vorlage: `{{marker}}` wird beim
    #: Export durch den (ggf. versetzten) Wert des zugeordneten Katalog-Felds bzw.
    #: `@today` ersetzt; Marker OHNE Zuordnung bleiben als Lücke (in Word
    #: auszufüllen). Die .docx selbst liegt als Blob je Prozess.
    bindings: dict[str, DocumentBinding] = Field(default_factory=dict)
    #: Bedingte Passagen: `name → Bedingung` (dieselbe Condition-DSL wie
    #: `visibleWhen`). In der .docx umschließt `{{#if:name}} … {{/if}}` den Absatz;
    #: ist die Bedingung falsch, entfällt der ganze Passus. Leer = keine
    #: Bedingungen (die Vorlage füllt wie bisher).
    sections: dict[str, dict] = Field(default_factory=dict)

    @field_validator("bindings", mode="before")
    @classmethod
    def _coerce_bindings(cls, v):
        """Alt-Form `{marker: "feld.key"}` (nackter String) auf `{field: ...}`
        heben – gespeicherte Definitionen bleiben lesbar."""
        if not isinstance(v, dict):
            return v
        return {k: ({"field": b} if isinstance(b, str) else b) for k, b in v.items()}

    @model_validator(mode="after")
    def _check_sections(self) -> "DocumentSpec":
        for name, cond in (self.sections or {}).items():
            validate_condition(cond, f"documents.{self.key or '?'}.sections.{name}")
        return self


# ── Eskalation / Erinnerungen (§6.1) ─────────────────────────────────────────
#
# Ein deklarativer Aufsatz auf die vorhandene Timer-/Mail-Laufzeit: pro Phase
# eine Liste von Stufen (Frist in Tagen → optional Wiederholung → Empfänger).
# Beim Planen wird jede Stufe in genau EINE synthetische Timer-Automation
# expandiert (escalation_automations); Scheduler, Fire-once-Ledger und Mailversand
# feuern sie unverändert. Die Liste ist bewusst geordnet – Fundament für spätere
# Eskalationsketten (Stufe 2 an Vorgesetzte usw.).

#: Reserviertes ID-Präfix synthetischer Eskalations-Automationen. Echte
#: Automationen dürfen es nicht verwenden (sonst kollidiert der Timer-Ledger).
ESCALATION_AUTO_PREFIX = "__escalation__"

#: Frist/Wiederholung dürfen nicht beliebig groß werden – schützt die
#: ISO-Dauer-Expansion (P<n>D) vor Unsinn (z. B. Tippfehler „7000“).
_ESCALATION_MAX_DAYS = 3650


class EscalationStage(_Base):
    """Eine Erinnerungs-/Eskalationsstufe innerhalb einer Phase."""
    #: Erste Erinnerung nach so vielen Tagen in der Phase (Verweildauer,
    #: SLA-Pause abgezogen – wie jeder Timer).
    afterDays: int
    #: Danach alle so viele Tage wiederholen. Leer = einmalig.
    repeatDays: Optional[int] = None
    #: Ziele: Rollen (responsible/owner/watchers), `group:<id>`, `user:<id>`.
    recipients: list[str] = Field(default_factory=list)
    #: Freier Anlass-Text der Mail (reiner Text). Leer = „Erinnerung".
    message: Optional[str] = None
    #: Zusätzlich die Ticket-Priorität auf „hoch" setzen (= Aktion escalate statt
    #: notify). Standard aus: reine Erinnerungsmail.
    raisePriority: bool = False

    @model_validator(mode="after")
    def _stage_rules(self) -> "EscalationStage":
        if self.afterDays <= 0:
            raise ValueError("escalation: `afterDays` muss größer als 0 sein")
        if self.afterDays > _ESCALATION_MAX_DAYS:
            raise ValueError(f"escalation: `afterDays` überschreitet {_ESCALATION_MAX_DAYS} Tage")
        if self.repeatDays is not None:
            if self.repeatDays <= 0:
                raise ValueError("escalation: `repeatDays` muss größer als 0 sein")
            if self.repeatDays > _ESCALATION_MAX_DAYS:
                raise ValueError(f"escalation: `repeatDays` überschreitet {_ESCALATION_MAX_DAYS} Tage")
        if not self.recipients:
            raise ValueError("escalation: eine Stufe braucht mindestens einen Empfänger")
        for tok in self.recipients:
            if not is_valid_recipient(tok):
                raise ValueError(f"escalation: unbekanntes Ziel „{tok}“ "
                                 f"(erlaubt: {', '.join(sorted(ALLOWED_RECIPIENTS))}, "
                                 f"group:<id>, user:<id>)")
        return self


class EscalationSpec(_Base):
    """Eskalations-/Erinnerungs-Konfiguration einer Phase (der An/Aus-Schalter je
    Phase). `enabled=false` behält die Stufen, hält sie aber still."""
    enabled: bool = True
    stages: list[EscalationStage] = Field(default_factory=list)

    @model_validator(mode="after")
    def _escalation_rules(self) -> "EscalationSpec":
        if self.enabled and not self.stages:
            raise ValueError("escalation ist aktiv, aber ohne Stufen – entweder eine "
                             "Stufe hinzufügen oder deaktivieren")
        return self


def escalation_automations(phase: "PhaseDef") -> list["Automation"]:
    """Expandiert `phase.escalation` in synthetische Timer-Automationen, die die
    bestehende Timer-/Mail-Laufzeit unverändert feuert. Eine Stufe → eine
    Automation (timer after/repeat + notify bzw. escalate an die Stufen-Empfänger).
    Leere/deaktivierte Eskalation → keine Automationen."""
    esc = getattr(phase, "escalation", None)
    if esc is None or not esc.enabled:
        return []
    out: list[Automation] = []
    for i, st in enumerate(esc.stages):
        out.append(Automation(
            id=f"{ESCALATION_AUTO_PREFIX}{phase.key}__{i}",
            trigger=Trigger(
                type=TriggerType.timer,
                after=f"P{st.afterDays}D",
                repeat=(f"P{st.repeatDays}D" if st.repeatDays else None),
            ),
            action=Action(
                type=(ActionType.escalate if st.raisePriority else ActionType.notify),
                recipients=list(st.recipients),
                template=st.message,
            ),
        ))
    return out


class PhaseDef(_Base):
    key: str
    label: Optional[str] = None
    kind: PhaseKind
    view: PhaseView = PhaseView.form
    enterStatus: Optional[str] = None
    #: Beschriftung des grünen „Weitergeben"-Buttons für diese Phase (z. B.
    #: „Weitergeben an Vorgesetzten"). Leer → Standard („Weitergeben"/„Abschließen").
    advanceLabel: Optional[str] = None
    grantsFullView: bool = False
    responsibility: Responsibility
    #: Pflicht bei kind=approval, sonst verboten.
    approval: Optional[ApprovalSpec] = None
    #: Alt-Form: EINE Dokument-Vorlage. Wird beim Laden nach `documents` migriert
    #: (Key „dokument"); neue Definitionen nutzen direkt `documents`.
    document: Optional[DocumentSpec] = None
    #: Dokument-Vorlagen dieser Phase: Pflicht bei view=document, sonst leer.
    #: Mehrere möglich (jede .docx ODER PDF, je eigener Key/Titel/Dateiname/Bindings).
    documents: list[DocumentSpec] = Field(default_factory=list)
    #: Optional: Erinnerungen/Eskalation, solange das Ticket in dieser Phase liegt.
    escalation: Optional[EscalationSpec] = None
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

    @model_validator(mode="after")
    def _migrate_and_check_documents(self) -> "PhaseDef":
        """Alt-Form (einzelnes `document`) auf `documents` heben und die
        Dokument-Keys prüfen (Slug, nicht leer, eindeutig innerhalb der Phase)."""
        if self.document is not None and not self.documents:
            legacy = self.document
            self.documents = [legacy.model_copy(update={"key": legacy.key or "dokument"})]
            self.document = None
        seen: set[str] = set()
        for i, d in enumerate(self.documents):
            if not re.fullmatch(r"[a-z0-9_]+", d.key or ""):
                raise ValueError(f"Phase „{self.key}“.documents[{i}]: ungültiger document.key "
                                 f"„{d.key}“ (erlaubt: a-z0-9_)")
            if d.key in seen:
                raise ValueError(f"Phase „{self.key}“: doppelter document.key „{d.key}“")
            seen.add(d.key)
        return self

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
        # In einer Endphase wartet nichts mehr – Erinnerungen dort wären Lärm und
        # würden ohnehin nie feuern (terminale Tickets werden nicht mehr geplant).
        if self.escalation is not None and self.kind == PhaseKind.end:
            raise ValueError(f"Phase „{self.key}“: `escalation` ist in einer Endphase "
                             f"(kind=end) nicht sinnvoll")
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
    #: Alle Vorgesetzten dürfen anlegen (Directus-Mitarbeiterfeld `is_executive`).
    #: Wirkt zusätzlich zu groups/users; die Auswertung liest den an der Session
    #: hängenden Mitarbeiterdatensatz (user["employee"]).
    executives: bool = False


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
    #: Optionale Titel-Vorlage. Ist sie gesetzt, wird der Auftrags-Titel beim
    #: Anlegen daraus erzeugt (statt manueller Eingabe) – mit {{feld.key}} aus den
    #: Startphasen-Werten und {{erstellt}} (Erstellzeitpunkt), z. B.
    #: „Onboarding Mitarbeiter:innen – {{base.first_name}} {{base.last_name}}“.
    titleTemplate: Optional[str] = None
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

        # Das Präfix synthetischer Eskalations-Automationen ist reserviert – eine
        # echte Automation mit diesem Präfix würde im Timer-Ledger kollidieren.
        reserved = sorted({a.id for a in all_autos if a.id.startswith(ESCALATION_AUTO_PREFIX)})
        if reserved:
            raise ValueError(f"Automation-ID mit reserviertem Präfix „{ESCALATION_AUTO_PREFIX}“: "
                             f"{', '.join(reserved)} (für Eskalationsstufen reserviert)")

        # ── Alle Feld-Referenzen müssen im Katalog existieren (sonst stiller No-op /
        #    Datenverlust zur Laufzeit). Betrifft computed.from, DSL-Leaf-Refs in
        #    requiredWhen/visibleWhen/constraints/when/guard und Trigger/Action.field.
        def _need(ref: str, where: str):
            if ref not in catalog:
                raise ValueError(f"{where}: Referenz „{ref}“ ist nicht im Feld-Katalog")

        # Titel-Vorlage: {{feld.key}} müssen Katalog-Felder sein; {{erstellt}} ist
        # der einzige erlaubte Spezial-Platzhalter (Erstellzeitpunkt). {{id}} ist
        # beim Anlegen noch nicht vergeben, {{title}} wäre selbstbezüglich – beide
        # verboten. Nicht-skalare Felder lassen sich nicht als Titel einsetzen.
        if self.titleTemplate:
            from backend.services import mail_template as _mt
            feld_je_key = {f.key: f for f in self.fields}
            for ref in _mt.variables(self.titleTemplate):
                if ref == "erstellt":
                    continue
                if ref in ("id", "title"):
                    raise ValueError(
                        f"titleTemplate: «{ref}» ist als Titel-Variable nicht erlaubt "
                        f"(erlaubt sind Feld-Schlüssel und «erstellt»)")
                _need(ref, f"titleTemplate (Variable «{ref}»)")
                f = feld_je_key.get(ref)
                if f and f.widget in (Widget.collection, Widget.attachment):
                    raise ValueError(
                        f"titleTemplate: Variable «{ref}» verweist auf ein "
                        f"„{f.widget.value}“-Feld und lässt sich nicht als Titel einsetzen")

        # Ein `computed.map`-Lookup arbeitet mit Zeichenketten-Schlüsseln (JSON) –
        # er ergibt nur für Felder Sinn, deren Wert eine Zeichenkette ist. Auf
        # Zahl/Checkbox/Mehrfachauswahl würden Backend (nativer Schlüssel) und
        # Frontend sonst auseinanderlaufen; hier hart ausschließen.
        _map_source_ok = {Widget.select, Widget.text, Widget.textarea, Widget.date,
                          Widget.user, Widget.company, Widget.group, Widget.server_generated}
        for f in self.fields:
            if f.computed:
                if f.computed.op == "template":
                    # {{feld}}-Platzhalter müssen Katalog-Felder sein; nicht-skalare
                    # Felder lassen sich nicht als Text einsetzen.
                    from backend.services import mail_template as _mt
                    _fmap = {x.key: x for x in self.fields}
                    for ref in _mt.field_refs(f.computed.template):
                        _need(ref, f"Feld „{f.key}“.computed.template (Variable «{ref}»)")
                        src = _fmap.get(ref)
                        if src is not None and src.widget in (Widget.collection, Widget.attachment):
                            raise ValueError(
                                f"Feld „{f.key}“.computed.template: «{ref}» verweist auf ein "
                                f"„{src.widget.value}“-Feld und lässt sich nicht als Text einsetzen")
                    continue
                _need(f.computed.from_, f"Feld „{f.key}“.computed.from")
                if f.computed.op == "days_between":
                    _need(f.computed.to, f"Feld „{f.key}“.computed.to")
                    # from/to müssen Datumsfelder sein, das Zielfeld eine Zahl –
                    # sonst laufen Ableitung und Anzeige/Validierung auseinander.
                    for ref_key, lbl in ((f.computed.from_, "from"), (f.computed.to, "to")):
                        src = next((x for x in self.fields if x.key == ref_key), None)
                        if src is not None and src.widget != Widget.date:
                            raise ValueError(
                                f"Feld „{f.key}“.computed.{lbl}: „{ref_key}“ "
                                f"(widget={src.widget.value}) ist kein Datumsfeld – "
                                f"days_between erwartet Datumsfelder.")
                    if f.widget != Widget.number:
                        raise ValueError(
                            f"Feld „{f.key}“: computed.op=days_between ergibt eine Zahl, "
                            f"das Feld ist aber widget={f.widget.value}.")
                if f.computed.map is not None:
                    src = next((x for x in self.fields if x.key == f.computed.from_), None)
                    if src is not None and src.widget not in _map_source_ok:
                        raise ValueError(
                            f"Feld „{f.key}“.computed.map: Das Quellfeld "
                            f"„{f.computed.from_}“ (widget={src.widget.value}) ist nicht "
                            f"unterstützt – ein Lookup arbeitet nur mit Text-/Auswahl-Feldern.")

        # directus-Felder: jedes Auto-Fill-Ziel muss ein Katalog-Feld sein und darf
        # nicht auf das Feld selbst zeigen (Selbstbezug). Der Quell-Pfad (Directus)
        # wird hier NICHT geprüft – das Schema kennt Directus nicht; das erledigt
        # der Editor (bietet nur geladene Pfade an) bzw. der Live-Abgleich.
        for f in self.fields:
            if f.widget != Widget.directus:
                continue
            for i, b in enumerate(f.directusFieldMap):
                if b.target == f.key:
                    raise ValueError(
                        f"Feld „{f.key}“.directusFieldMap[{i}]: das Ziel darf nicht das Feld selbst sein")
                _need(b.target, f"Feld „{f.key}“.directusFieldMap[{i}].target")
        # Hinweis: Auto-Fill-Ziele müssen NICHT bearbeitbar sein – den Snapshot
        # schreibt der Server autoritativ beim Speichern (services/directus_snapshot),
        # unabhängig vom Phasen-mode. Deshalb sind read-only Ziele ausdrücklich erlaubt.

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

        wid_by_key = {f.key: f.widget for f in self.fields}
        fld_by_key = {f.key: f for f in self.fields}
        _id_field_forbidden = {Widget.collection, Widget.attachment, Widget.server_generated}
        for a in all_autos:
            if a.guard:
                for r in dsl_refs(a.guard):
                    _need(r, f"automation[{a.id}].guard")
            if a.trigger.field:
                _need(a.trigger.field, f"automation[{a.id}].trigger.field")
            if a.action.field:
                _need(a.action.field, f"automation[{a.id}].action.field")
            if a.action.type == ActionType.directus_write and a.action.directus:
                d = a.action.directus
                _need(d.idField, f"automation[{a.id}].directus.idField")
                if wid_by_key.get(d.idField) in _id_field_forbidden:
                    raise ValueError(
                        f"automation[{a.id}].directus.idField: „{d.idField}“ "
                        f"(widget={wid_by_key[d.idField].value}) kann keine Directus-id tragen "
                        "– ein einfaches Textfeld verwenden")
                # Ein non-overridable computed-Feld würde apply_computed bei jedem
                # Speichern neu setzen und die zurückgeschriebene id überschreiben
                # (Doppelanlage-Schutz + update/delete-Referenz gingen verloren).
                _idf = fld_by_key.get(d.idField)
                if _idf is not None and _idf.computed and not _idf.overridable:
                    raise ValueError(
                        f"automation[{a.id}].directus.idField: „{d.idField}“ ist ein berechnetes "
                        "Feld – es würde die zurückgeschriebene Directus-id überschreiben. "
                        "Ein einfaches, nicht berechnetes Textfeld verwenden")
                for j, b in enumerate(d.fieldMap):
                    # Feste Werte (value) haben kein Prozess-Feld als Quelle.
                    if b.source:
                        _need(b.source, f"automation[{a.id}].directus.fieldMap[{j}].source")
                    # Bedingung (when): das getestete Feld muss im Katalog existieren.
                    if b.when is not None:
                        _need(b.when.field, f"automation[{a.id}].directus.fieldMap[{j}].when.field")
                    if not b.target.strip():
                        raise ValueError(
                            f"automation[{a.id}].directus.fieldMap[{j}].target: "
                            "das Directus-Zielfeld darf nicht leer sein")
                    if (b.resolve == DirectusWriteResolve.company_directus_id
                            and wid_by_key.get(b.source) != Widget.company):
                        raise ValueError(
                            f"automation[{a.id}].directus.fieldMap[{j}]: „als Firmen-ID auflösen“ "
                            "ist nur für ein Firmen-Feld (widget=company) erlaubt")
                # Geschäftsschlüssel (get-or-create): nur bei create und nur auf ein
                # tatsächlich gemapptes Directus-Feld (sonst gäbe es keinen Suchwert).
                if d.matchField:
                    if d.operation != DirectusOperation.create:
                        raise ValueError(
                            f"automation[{a.id}].directus.matchField: der Geschäftsschlüssel "
                            "(get-or-create) ist nur bei operation=create sinnvoll")
                    _match_bindings = [b for b in d.fieldMap if b.target == d.matchField]
                    if not _match_bindings:
                        raise ValueError(
                            f"automation[{a.id}].directus.matchField: „{d.matchField}“ muss ein "
                            "Directus-Zielfeld einer Feld-Zuordnung sein (liefert den Suchwert)")
                    # Ein aufgelöstes Ziel (resolve) würde den ROHEN Wert suchen, aber den
                    # AUFGELÖSTEN schreiben → nie ein Treffer → stille Doppelanlage.
                    if any(b.resolve is not None for b in _match_bindings):
                        raise ValueError(
                            f"automation[{a.id}].directus.matchField: „{d.matchField}“ darf kein "
                            "aufgelöstes Feld sein (Suchwert würde nicht zum gespeicherten passen)")
                    # Ein fester Wert als Suchschlüssel würde bei JEDEM Datensatz matchen
                    # → get-or-create wäre wirkungslos.
                    if any(b.value is not None for b in _match_bindings):
                        raise ValueError(
                            f"automation[{a.id}].directus.matchField: „{d.matchField}“ darf kein "
                            "fester Wert sein (der Suchschlüssel muss aus einem Prozess-Feld kommen)")

        # on_department_done: nur als PHASEN-Automation einer Fachabteilungs-Phase,
        # und die Gruppe muss eine Fachabteilung genau dieser Phase sein.
        for a in self.automations:
            if a.trigger.type == TriggerType.on_department_done:
                raise ValueError(f"automation[{a.id}]: on_department_done ist nur als "
                                 "Phasen-Automation zulässig, nicht prozessweit")
        for p in self.phases:
            dept_groups = ({dr.group for dr in p.responsibility.rule}
                           if p.responsibility.kind == ResponsibilityKind.departments else set())
            for a in p.automations:
                if a.trigger.type != TriggerType.on_department_done:
                    continue
                if p.responsibility.kind != ResponsibilityKind.departments:
                    raise ValueError(f"automation[{a.id}] (Phase „{p.key}“): on_department_done "
                                     "gibt es nur in einer Fachabteilungs-Phase (responsibility=departments)")
                if a.trigger.group not in dept_groups:
                    raise ValueError(f"automation[{a.id}] (Phase „{p.key}“): trigger.group "
                                     f"„{a.trigger.group}“ ist keine Fachabteilung dieser Phase")

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
            # view=document ⇔ mindestens eine Dokument-Vorlage (documents; die
            # Alt-Form `document` wurde in PhaseDef bereits nach documents migriert).
            if (p.view == PhaseView.document) != bool(p.documents):
                raise ValueError(
                    f"Phase „{p.key}“: „view=document“ und mindestens eine Dokument-Vorlage "
                    f"gehören zusammen – bitte beides setzen oder beides weglassen")
            from backend.services import mail_template as _mt
            feld_je_key = {f.key: f for f in self.fields}
            for doc in p.documents:
                for txt in (doc.templateHtml, doc.filename):
                    for ref in _mt.field_refs(txt):
                        _need(ref, f"Phase „{p.key}“.documents[„{doc.key}“] (Variable «{ref}»)")
                # bindings: jeder zugeordnete Marker muss auf ein einsetzbares
                # (skalares) Katalog-Feld ODER die Sonderquelle @today zeigen.
                for marker, binding in doc.bindings.items():
                    fieldkey = binding.field
                    if fieldkey == TODAY_BINDING:
                        continue                       # aktuelles Datum – kein Katalog-Feld
                    _need(fieldkey, f"Phase „{p.key}“.documents[„{doc.key}“].bindings[„{marker}“]")
                    f = feld_je_key.get(fieldkey)
                    # Nicht einsetzbar: Anhang/Wiederholgruppe (kein Text) sowie
                    # Personen-/Gruppenauswahl (trägt nur eine rohe ID, die der
                    # Export nicht in einen Namen auflöst → Vorschau ≠ Vertrag).
                    if f and (f.widget in (Widget.collection, Widget.attachment,
                                           Widget.user, Widget.group)
                              or f.optionsSource in (OptionsSource.users, OptionsSource.groups)):
                        raise ValueError(
                            f"Phase „{p.key}“.documents[„{doc.key}“].bindings[„{marker}“]: Feld "
                            f"„{fieldkey}“ lässt sich nicht in den Vertrag einsetzen (Anhang, "
                            f"Wiederholgruppe oder Personen-/Gruppenauswahl)")

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
