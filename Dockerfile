FROM mcr.microsoft.com/playwright/python:v1.40.0-jammy

# Arbeitsverzeichnis
WORKDIR /app

# Abhängigkeiten installieren
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Zeitzone auf Zürich setzen
ENV TZ=Europe/Zurich
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# App-Code kopieren
COPY . .

# Port freigeben
EXPOSE 5000

# Start-Befehl
CMD ["python3", "app.py"]
