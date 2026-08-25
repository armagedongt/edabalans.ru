FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app/backend

RUN addgroup --system app && adduser --system --ingroup app app

COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/alembic.ini ./
COPY backend/migrations ./migrations
COPY backend/app ./app
COPY backend/scripts ./scripts
COPY docs /app/docs
COPY PROJECT_CONTEXT.md ARCHITECTURE.md /app/
COPY content/masterclass/imported-draft/extracted-2026-08-23.json /app/content/masterclass/imported-draft/extracted-2026-08-23.json
COPY content/masterclass/course/course.json /app/content/masterclass/course/course.json
COPY content/masterclass/source-current /app/content/masterclass/source-current

RUN chmod -R a+rX /app

USER app

CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*'"]
