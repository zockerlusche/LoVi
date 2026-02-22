# Basis-Image: offizielles Python, abgespeckte Version (~50MB)
FROM python:3.11-slim

# Wer hat dieses Image gebaut (für Docker Hub später)
LABEL maintainer="Marcel Balda"
LABEL description="LoVi - Log Viewer"
LABEL version="0.1"

# Arbeitsverzeichnis im Container
WORKDIR /app

# Erst nur requirements.txt kopieren und installieren
# (Docker cached das – bei Code-Änderungen muss Flask nicht neu installiert werden)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Jetzt den Rest des Codes kopieren
COPY . .

# Log-Ordner anlegen (wird später vom Host gemountet)
RUN mkdir -p /logs && mkdir -p /data

# Port freigeben
EXPOSE 5000

# Container starten
CMD ["python", "app.py"]
