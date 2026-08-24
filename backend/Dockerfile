FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    # LibreOffice (headless) rendert die Dokument-Phase originalgetreu nach PDF –
    # sowohl fuer die Vorschau als auch den PDF-Export. libreoffice-writer genuegt
    # fuer .docx→PDF; fonts-liberation liefert metrikkompatible Arial/Times/Courier
    # (sonst driftet das Layout durch Ersatzschriften).
    libreoffice-writer \
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . ./backend/

EXPOSE 5000

CMD ["python", "-c", "from backend.main import main; main()"]