FROM python:3.9-slim

# Environment variables to keep the build clean
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# 1. Install System Dependencies
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 2. Install Python Libraries
COPY requirements.txt .
RUN pip install -r requirements.txt

# 3. Install Playwright Browsers (The heavy step)
# We use a separate layer to cache this effectively
RUN playwright install --with-deps chromium

# 4. Copy Application Code
COPY app.py .

# 5. Setup Port and Healthcheck
EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=30s --start-period=5s --retries=3 \
  CMD curl --fail http://localhost:3000/_stcore/health || exit 1

ENTRYPOINT ["streamlit", "run", "app.py", "--server.port=3000", "--server.address=0.0.0.0"]
