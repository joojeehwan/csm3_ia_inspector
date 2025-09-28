FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# System deps (tesseract optional — comment out if not needed)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libglib2.0-0 libsm6 libxrender1 libxext6 \
    tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY . .

# Azure App Service injects PORT env var
ENV PORT=8000 \
    HOST=0.0.0.0 \
    USE_LANGGRAPH=true

# Expose for local run (Azure uses PORT automatically)
EXPOSE 8000

# Chainlit: use production server, listen on $PORT
CMD ["sh", "-c", "chainlit run app.py --host $HOST --port $PORT"]
