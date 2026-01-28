FROM python:3.14-slim

WORKDIR /app

# Install system dependencies for building C extensions
RUN apt-get update && apt-get install -y \
    build-essential \
    gcc \
    git \
    curl \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["supervisord", "-c", "/app/supervisor.conf"]
