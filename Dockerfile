FROM python:3.9-slim

# Prevent Python from buffering stdout/stderr (Crucial for Logs!)
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Install system dependencies (cached)
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python libs
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright & Browsers (This is the heavy part)
# We do this in the build stage so it doesn't slow down startup
RUN playwright install --with-deps chromium

COPY app.py .

# Healthcheck to prevent 502s while loading
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
  CMD curl --fail http://localhost:3000/_stcore/health || exit 1

EXPOSE 3000

# Start Streamlit on Port 3000
ENTRYPOINT ["streamlit", "run", "app.py", "--server.port=3000", "--server.address=0.0.0.0", "--server.headless=true"]
