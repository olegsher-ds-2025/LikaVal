FROM python:3.11-slim

WORKDIR /app

# Install system dependencies for Pillow and git
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    libgl1 \
    libglib2.0-0 \
  && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

# Copy project
COPY . .

# Volumes for persistent data
VOLUME ["/app/config", "/app/state", "/app/logs", "/app/backend/downloads"]

# Configure git identity for automated commits
RUN git config --global user.email "likaval-bot@likaval.com" \
 && git config --global user.name "LikaVal Bot"

ENV PYTHONUNBUFFERED=1

CMD ["python", "backend/main.py", "--daemon"]
