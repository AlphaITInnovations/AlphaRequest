# AlphaRequestManager

Internes IT-Request-Management-System zur Verwaltung von Hardware-, Zugangs- und Niederlassungstickets mit Microsoft 365-Integration.

## Tech Stack

- **Backend**: Python, FastAPI, SQLAlchemy, MySQL
- **Frontend**: Vue 3, TypeScript, Vite, Tailwind CSS, Pinia
- **Auth**: Microsoft MSAL (Azure AD)
- **Monitoring**: Prometheus

## Lokale Entwicklung

### Backend

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

## Deployment

Das Deployment erfolgt via GitHub Actions und Docker. Siehe [`.github/workflows/deploy.yaml`](.github/workflows/deploy.yaml).

## Umgebungsvariablen

Eine `.env`-Datei im `backend/`-Verzeichnis wird benötigt. Vorlage beim Team erfragen.
