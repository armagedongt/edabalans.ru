FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY service/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY service/app ./app
COPY service/static ./static
COPY service/certs ./certs
COPY service/set_cross_messenger_max_webhook.py ./
COPY service/configure_cross_messenger_pair.py ./

EXPOSE 8001
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
