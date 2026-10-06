FROM python:3.11-slim

# Set environment flags
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY pyproject.toml .
RUN pip install --upgrade pip && \
    pip install "telethon>=1.36.0" \
                "fastapi>=0.110.0" \
                "uvicorn>=0.29.0" \
                "pillow>=10.0.0" \
                "httpx>=0.27.0" \
                "pydantic>=2.7.0" \
                "pydantic-settings>=2.3.0" \
                "structlog>=24.1.0" \
                "typer>=0.12.0" \
                "python-multipart>=0.0.9"

# Copy source code and config
COPY src/ src/
COPY data/ data/
RUN mkdir -p backups data

# Install local package in editable mode
RUN pip install -e . --no-deps

EXPOSE 8000

# Run FastAPI web dashboard
CMD ["uvicorn", "tg_cleaner.web.app:app", "--host", "0.0.0.0", "--port", "8000"]
