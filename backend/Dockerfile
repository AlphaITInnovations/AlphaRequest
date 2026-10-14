FROM python:3.12-slim

WORKDIR /app

# LibreOffice (headless) rendert die Dokument-Phase originalgetreu nach PDF –
# sowohl fuer die Vorschau als auch den PDF-Export. libreoffice-writer genuegt
# fuer .docx→PDF; fonts-liberation liefert metrikkompatible Arial/Times/Courier.
# cabextract entpackt die mitgelieferten MS-Font-Archive (unten).
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libreoffice-writer \
    fonts-liberation \
    fontconfig \
    cabextract \
    && rm -rf /var/lib/apt/lists/*

# Echte Microsoft-Fonts (Verdana, Arial, Times New Roman, …). GRUND: die Vorlagen
# sind ueberwiegend in VERDANA gesetzt – dafuer gibt es keine metrikkompatible
# Freetype-Entsprechung (fonts-liberation deckt nur Arial/Times/Courier ab). Ohne
# die echten Fonts substituiert LibreOffice Verdana und bricht anders um als Word
# (eine Seite Unterschied). Mit den echten Fonts stimmt die Paginierung ueberein.
#
# Die 11 Original-Archive liegen IM REPO (backend/vendor/msfonts/). Dadurch braucht der
# Build KEIN Netz und haengt nie mehr an (im Prod-Netz teils unerreichbaren)
# SourceForge-Mirrors. Wir entpacken nur die .ttf daraus (cabextract, genau wie es der
# ttf-mscorefonts-installer tun wuerde) und bauen den Font-Cache; zur Sicherheit wird
# geprueft, dass Verdana (der paginierungs-kritische Font) wirklich da ist. Die MS-EULA
# erlaubt die Weitergabe der UNVERAENDERTEN Original-Archive.
COPY vendor/msfonts/ /tmp/msfonts/
RUN set -eu; \
    mkdir -p /usr/share/fonts/truetype/msttcorefonts; \
    cabextract -L -q -F '*.[Tt][Tt][Ff]' -d /usr/share/fonts/truetype/msttcorefonts /tmp/msfonts/*.exe; \
    fc-cache -f; \
    fc-list | grep -qi verdana || { echo "FEHLER: Verdana nicht installiert"; exit 1; }; \
    rm -rf /tmp/msfonts

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . ./backend/

EXPOSE 5000

CMD ["python", "-c", "from backend.main import main; main()"]