from alpharequestmanager.database.personalnummer import (
    db_init_personalnummer,
    db_get_personalnummer,
    db_next_personalnummer,
    db_reset_personalnummer,
)
from alpharequestmanager.utils.config import config


def init_personalnummer() -> None:
    db_init_personalnummer(start_value=config.PERSONALNUMMER_START)


def get_personalnummer() -> int:
    return db_get_personalnummer(default=config.PERSONALNUMMER_START)


def next_personalnummer() -> int:
    return db_next_personalnummer(end_value=config.PERSONALNUMMER_END)


def reset_personalnummer() -> None:
    db_reset_personalnummer(start_value=config.PERSONALNUMMER_START)