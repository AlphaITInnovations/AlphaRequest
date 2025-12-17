from alpharequestmanager.models.models import TicketType

TICKET_LABELS = {
    TicketType.hardware: "Hardwarebestellung",
    TicketType.niederlassung_anmelden: "Niederlassung anmelden",
    TicketType.niederlassung_schliessen: "Niederlassung schließen",
    TicketType.niederlassung_umzug: "Niederlassung umziehen",
    TicketType.zugang_beantragen: "EDV-Zugang beantragen",
    TicketType.zugang_sperren: "EDV-Zugang sperren",
}
