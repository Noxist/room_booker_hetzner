FROM mcr.microsoft.com/playwright/python:v1.40.0-jammy

WORKDIR /app

# Zeitzonen-Datenbank ohne Interaktion installieren
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && \
    apt-get install -y tzdata && \
    ln -fs /usr/share/zoneinfo/Europe/Zurich /etc/localtime && \
    dpkg-reconfigure --frontend noninteractive tzdata && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

ENV TZ=Europe/Zurich

COPY . .
EXPOSE 5000
CMD ["python3", "app.py"]
