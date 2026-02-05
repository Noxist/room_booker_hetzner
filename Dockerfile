FROM mcr.microsoft.com/playwright/python:v1.41.2-jammy

WORKDIR /app

# Systemvariablen für Playwright setzen, damit es die vorinstallierten Browser findet
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
ENV PYTHONUNBUFFERED=1

# Dependencies installieren
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Code kopieren
COPY . .

# Container am Leben halten
CMD ["tail", "-f", "/dev/null"]
