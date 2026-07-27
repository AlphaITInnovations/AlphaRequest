from backend.models.models import TicketType

TICKET_LABELS = {
    TicketType.hardware: "Hardwarebestellung",
    TicketType.niederlassung_anmelden: "Niederlassung anmelden",
    TicketType.niederlassung_schliessen: "Niederlassung schließen",
    TicketType.niederlassung_umzug: "Niederlassung umziehen",
    TicketType.einstellung: "Einstellung Mitarbeiter:in",
    TicketType.zugang_beantragen: "Onboarding nach Vertragsrücklauf",
    TicketType.zugang_sperren: "EDV-Zugang sperren",
    TicketType.marketing_stellenanzeige: "Marketing – Stellenanzeige",

}
