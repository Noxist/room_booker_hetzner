FROM python:3.9-slim

# Arbeitsverzeichnis
WORKDIR /app

# System-Abhängigkeiten für Playwright installieren
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    && rm -rf /var/lib/apt/lists/*

# Python Bibliotheken installieren
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Playwright Browser UND System-Abhängigkeiten (sehr wichtig für Docker!)
RUN playwright install --with-deps chromium

# Code kopieren
COPY app.py .

# Port auf 3000 setzen (passend zu Shipper)
EXPOSE 3000

# Startbefehl mit expliziter Port-Zuweisung
ENTRYPOINT ["streamlit", "run", "app.py", "--server.port=3000", "--server.address=0.0.0.0"]
