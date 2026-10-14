"""DB-gestützter Signierschlüssel: Erzeugung bei Bedarf, Persistenz über Neustart,
Rotation (mit Übergangsschlüssel) und Datei-Override (ohne echte DB – settings-Store
wird gefaked)."""
import base64
import time

import pytest
from cryptography.hazmat.primitives import serialization as s
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import backend.database.settings as dbsettings
from backend.services import approval_jwt as aj


@pytest.fixture
def db(monkeypatch):
    """In-Memory-Ersatz für den settings-KV-Store + frischer Key-Cache, DB-Modus."""
    store: dict = {}
    monkeypatch.setattr(dbsettings, "settings_get",
                        lambda key, default=None: store.get(key, default))
    monkeypatch.setattr(dbsettings, "settings_set",
                        lambda key, value: store.__setitem__(key, value))
    monkeypatch.setattr(aj, "_private_key_cache", None)
    monkeypatch.setattr(aj.config, "APPROVAL_PRIVATE_KEY_PATH", "")
    return store


def test_erzeugt_und_speichert_bei_bedarf(db):
    assert aj._SIGNING_KEY_SETTING not in db
    pub = aj.public_key_b64()
    assert db[aj._SIGNING_KEY_SETTING].startswith("-----BEGIN PRIVATE KEY-----")
    assert len(base64.b64decode(pub)) == 32            # Ed25519 Raw-Public-Key
    assert aj.key_source() == "db"


def test_persistent_ueber_prozess_neustart(db):
    pub1 = aj.public_key_b64()
    aj._private_key_cache = None                        # „Neustart": nur der Cache ist weg
    pub2 = aj.public_key_b64()
    assert pub1 == pub2                                 # derselbe PEM aus der DB


def test_ensure_key_legt_an(db):
    aj.ensure_key()
    assert db.get(aj._SIGNING_KEY_SETTING)


def test_regenerate_tauscht_key(db):
    pub1 = aj.public_key_b64()
    pub2 = aj.regenerate_key()
    assert pub1 != pub2
    assert aj.public_key_b64() == pub2                  # Cache UND DB zeigen den neuen


def test_rotation_bewahrt_vorherigen_key_im_fenster(db):
    old_pub = aj.public_key_b64()
    new_pub = aj.regenerate_key()
    assert new_pub != old_pub
    assert aj._PREV_KEY_SETTING in db                   # Vorgänger abgelegt
    raws = [base64.b64encode(k.public_bytes(s.Encoding.Raw, s.PublicFormat.Raw)).decode()
            for k in aj.public_keys_for_verify()]
    assert len(raws) == 2 and old_pub in raws and new_pub in raws   # beide akzeptiert


def test_vorheriger_key_ausserhalb_fensters_entfaellt(db):
    aj.public_key_b64()
    aj.regenerate_key()
    db[aj._PREV_KEY_SETTING]["since"] = int(time.time()) - (aj.MAX_TTL_SECONDS + 10)
    assert len(aj.public_keys_for_verify()) == 1       # Fenster zu → nur noch der aktuelle


def test_datei_override_hat_vorrang(db, monkeypatch, tmp_path):
    key = Ed25519PrivateKey.generate()
    pem = key.private_bytes(s.Encoding.PEM, s.PrivateFormat.PKCS8, s.NoEncryption())
    f = tmp_path / "k.pem"
    f.write_bytes(pem)
    monkeypatch.setattr(aj, "_private_key_cache", None)
    monkeypatch.setattr(aj.config, "APPROVAL_PRIVATE_KEY_PATH", str(f))

    assert aj.key_source() == "file"
    expect = base64.b64encode(
        key.public_key().public_bytes(s.Encoding.Raw, s.PublicFormat.Raw)).decode()
    assert aj.public_key_b64() == expect
    assert aj._SIGNING_KEY_SETTING not in db           # DB bleibt unberührt
    with pytest.raises(RuntimeError):                  # Rotation im Datei-Modus verboten
        aj.regenerate_key()
