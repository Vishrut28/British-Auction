FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .

# Don't run as root (Celery warns about it, and it's safer).
RUN useradd --create-home --uid 1000 app
USER app

EXPOSE 8000
# Apply migrations, then serve. Compose overrides the command for the worker.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
