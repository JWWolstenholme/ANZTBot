FROM python:3.13-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip && pip install --no-cache-dir -r requirements.txt

COPY src src

# Expose port 5000 for Quart webserver
EXPOSE 5000

# Disable Python buffering to show output immediately in Docker logs
ENV PYTHONUNBUFFERED=1

CMD ["python", "src/main.py"]
