FROM python:3.12-slim

WORKDIR /app

# LibreOffice (headless) rendert die Dokument-Phase originalgetreu nach PDF –
# sowohl fuer die Vorschau als auch den PDF-Export. libreoffice-writer genuegt
# fuer .docx→PDF; fonts-liberation liefert metrikkompatible Arial/Times/Courier.
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libreoffice-writer \
    fonts-liberation \
    fontconfig \
    && rm -rf /var/lib/apt/lists/*

# Echte Microsoft-Fonts (Verdana, Arial, Times New Roman, …). GRUND: die Vorlagen
# sind ueberwiegend in VERDANA gesetzt – dafuer gibt es keine metrikkompatible
# Freetype-Entsprechung (fonts-liberation deckt nur Arial/Times/Courier ab). Ohne
# die echten Fonts substituiert LibreOffice Verdana und bricht anders um als Word
# (eine Seite Unterschied). Mit den echten Fonts stimmt die Paginierung ueberein.
# Der Installer laedt die Fonts zur BUILD-ZEIT von Microsoft/SourceForge (Netz
# noetig); die EULA wird vorab automatisch akzeptiert.
RUN . /etc/os-release \
    && echo "deb http://deb.debian.org/debian ${VERSION_CODENAME} contrib" \
      > /etc/apt/sources.list.d/mscorefonts.list \
    && apt-get update \
    && echo "ttf-mscorefonts-installer msttcorefonts/accepted-mscorefonts-eula select true" \
      | debconf-set-selections \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y \
        cabextract \
        ttf-mscorefonts-installer \
    && fc-cache -f \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . ./backend/

EXPOSE 5000

CMD ["python", "-c", "from backend.main import main; main()"]