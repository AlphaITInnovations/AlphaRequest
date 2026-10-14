FROM python:3.12-slim

WORKDIR /app

# LibreOffice (headless) rendert die Dokument-Phase originalgetreu nach PDF –
# sowohl fuer die Vorschau als auch den PDF-Export. libreoffice-writer genuegt
# fuer .docx→PDF; fonts-liberation liefert metrikkompatible Arial/Times/Courier.
# wget/ca-certificates/cabextract brauchen wir zum Vorab-Laden der MS-Fonts (unten).
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libreoffice-writer \
    fonts-liberation \
    fontconfig \
    wget \
    ca-certificates \
    cabextract \
    && rm -rf /var/lib/apt/lists/*

# Echte Microsoft-Fonts (Verdana, Arial, Times New Roman, …). GRUND: die Vorlagen
# sind ueberwiegend in VERDANA gesetzt – dafuer gibt es keine metrikkompatible
# Freetype-Entsprechung (fonts-liberation deckt nur Arial/Times/Courier ab). Ohne
# die echten Fonts substituiert LibreOffice Verdana und bricht anders um als Word
# (eine Seite Unterschied). Mit den echten Fonts stimmt die Paginierung ueberein.
#
# Der ttf-mscorefonts-installer wuerde die Archive sonst in seinem postinst von
# SourceForge laden und haengt dabei je TOTEM Mirror 60 s im Timeout (der Build zog
# sich minutenlang). Darum laden WIR die 11 Standard-Archive vorab selbst: kurzer
# Timeout gegen den zuverlaessigen master-Mirror, ein Fallback – schlaegt BEIDES fehl,
# brechen wir SOFORT ab (statt den Installer wieder in die SourceForge-Timeouts laufen
# zu lassen). Die vorgeladenen Dateien bekommt der Installer per dldir untergeschoben
# und laedt dann nichts mehr. (comicbd32 gibt es NICHT – Comic Sans Bold steckt bereits
# in comic32.exe.)
RUN set -eu; mkdir -p /opt/msfonts; cd /opt/msfonts; \
    for f in andale32 arial32 arialb32 comic32 courie32 georgi32 \
             impact32 times32 trebuc32 verdan32 webdin32; do \
      echo "Lade $f.exe …"; \
      wget -q --tries=1 --timeout=20 -O "$f.exe" \
        "https://master.dl.sourceforge.net/project/corefonts/the%20fonts/final/$f.exe" \
      || wget -q --tries=1 --timeout=20 -O "$f.exe" \
        "https://downloads.sourceforge.net/project/corefonts/the%20fonts/final/$f.exe" \
      || { echo "FEHLER: $f.exe nicht ladbar – Build-Abbruch statt langem Mirror-Hang"; exit 1; }; \
      test -s "$f.exe"; \
    done

# EULA vorab akzeptieren, dldir auf die vorgeladenen Archive zeigen, installieren und
# zur Sicherheit pruefen, dass Verdana (der paginierungs-kritische Font) wirklich da ist.
RUN set -eu; . /etc/os-release; \
    echo "deb http://deb.debian.org/debian ${VERSION_CODENAME} contrib" \
      > /etc/apt/sources.list.d/mscorefonts.list; \
    apt-get update; \
    echo "ttf-mscorefonts-installer msttcorefonts/accepted-mscorefonts-eula select true" \
      | debconf-set-selections; \
    echo "ttf-mscorefonts-installer msttcorefonts/dldir string /opt/msfonts" \
      | debconf-set-selections; \
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      ttf-mscorefonts-installer; \
    fc-cache -f; \
    fc-list | grep -qi verdana || { echo "FEHLER: Verdana nicht installiert"; exit 1; }; \
    rm -rf /var/lib/apt/lists/* /opt/msfonts

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . ./backend/

EXPOSE 5000

CMD ["python", "-c", "from backend.main import main; main()"]