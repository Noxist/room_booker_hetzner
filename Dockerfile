FROM mcr.microsoft.com/playwright/python:v1.40.0-jammy

WORKDIR /app

# Zeitzonen-Datenbank installieren (wichtig für Scheduler)
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && \
    apt-get install -y tzdata && \
    ln -fs /usr/share/zoneinfo/Europe/Zurich /etc/localtime && \
    dpkg-reconfigure --frontend noninteractive tzdata && \
    rm -rf /var/lib/apt/lists/*

# Requirements installieren
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Sicherstellen, dass die Browser binaries da sind
RUN playwright install chromium

# Zeitzone Environment
ENV TZ=Europe/Zurich

# Code kopieren
COPY . .

EXPOSE 5000
CMD ["python3", "app.py"]
