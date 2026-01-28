FROM python:3.9-slim

# Arbeitsverzeichnis setzen
WORKDIR /app

# Updates und Abhängigkeiten für Chrome/Playwright installieren
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    && rm -rf /var/lib/apt/lists/*

# Python Bibliotheken installieren
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Playwright Browser installieren (mit System-Abhängigkeiten)
RUN playwright install --with-deps chromium

# Code kopieren
COPY app.py .

# Port freigeben (Standard für Streamlit)
EXPOSE 8501

# Gesundheitscheck (Optional, gut für Cloud)
HEALTHCHECK CMD curl --fail http://localhost:8501/_stcore/health

# Startbefehl
ENTRYPOINT ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]
