# ── Stage 1: Vue Build ────────────────────────────────────────────────────────
FROM node:20-slim AS frontend-build

WORKDIR /app/frontend

COPY frontend/package*.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build


# ── Stage 2: Python App ───────────────────────────────────────────────────────
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Vue dist aus Stage 1 kopieren
COPY --from=frontend-build /app/frontend/dist ./frontend/dist

CMD ["python", "-m", "alpharequestmanager.main"]