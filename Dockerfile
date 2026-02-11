FROM mcr.microsoft.com/playwright/python:v1.40.0-jammy

# Arbeitsverzeichnis
WORKDIR /app

# WICHTIG: tzdata ohne Interaktion installieren
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && \
    apt-get install -y tzdata && \
    ln -fs /usr/share/zoneinfo/Europe/Zurich /etc/localtime && \
    dpkg-reconfigure --frontend noninteractive tzdata && \
    rm -rf /var/lib/apt/lists/*

# Abhängigkeiten installieren
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Environment Variable für Python
ENV TZ=Europe/Zurich

# App-Code kopieren
COPY . .

# Port freigeben
EXPOSE 5000

# Start-Befehl
CMD ["python3", "app.py"]
