#!/usr/bin/env python3
"""Ed25519-Schlüsselpaar für den externen Freigabe-Weg (AlphaApprove) erzeugen.

Einmalig JE UMGEBUNG (prod, test) im Python-Umfeld von AlphaRequest ausführen:

    python -m backend.scripts.gen_approval_key /etc/alpharequest/approve-private.pem

AlphaRequest lädt den Private Key ausschließlich aus APPROVAL_PRIVATE_KEY_PATH und
signiert damit die Freigabe-Links. Der Private Key bleibt NUR hier:
  * außerhalb des Repos ablegen, Rechte 600, nur der AlphaRequest-Prozess darf lesen,
  * *.pem steht in .gitignore,
  * NIEMALS auf die AlphaApprove-VM kopieren, niemals in Mails/Chats posten.
An AlphaApprove geht NUR die ausgegebene Zeile `APPROVE_PUBLIC_KEY=…`
(→ /etc/alphaapprove/alphaapprove.env).

Rotation/Verlust: neues Paar erzeugen, Public Key auf AlphaApprove tauschen, beide
Dienste neu starten. Bereits verschickte Links werden dann „Link ungültig“, Daten
gehen nicht verloren.
"""
import argparse
import base64
import os
import sys

from cryptography.hazmat.primitives import serialization as s
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def main(argv=None) -> None:
    p = argparse.ArgumentParser(description="Ed25519-Freigabe-Schlüsselpaar erzeugen")
    p.add_argument("out", help="Zieldatei für den Private Key (PEM), z. B. "
                               "/etc/alpharequest/approve-private.pem")
    args = p.parse_args(argv)

    key = Ed25519PrivateKey.generate()
    pem = key.private_bytes(s.Encoding.PEM, s.PrivateFormat.PKCS8, s.NoEncryption())

    # O_EXCL: eine bestehende Schlüsseldatei NIE überschreiben (sonst würden alle
    # bereits verschickten Links ungültig). 0o600: nur der Besitzer darf lesen.
    try:
        fd = os.open(args.out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        sys.exit(f"Abbruch: {args.out} existiert bereits – kein Überschreiben.")
    with os.fdopen(fd, "wb") as f:
        f.write(pem)

    pub = base64.b64encode(
        key.public_key().public_bytes(s.Encoding.Raw, s.PublicFormat.Raw)).decode()

    print(f"Private Key geschrieben: {args.out} (Rechte 600)")
    print(f"→ in die AlphaRequest-.env:  APPROVAL_PRIVATE_KEY_PATH={args.out}")
    print()
    print("Diese EINE Zeile an AlphaApprove geben (/etc/alphaapprove/alphaapprove.env):")
    print(f"APPROVE_PUBLIC_KEY={pub}")


if __name__ == "__main__":
    main()
