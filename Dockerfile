FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PORT=8080

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir gunicorn

COPY . .

RUN SECRET_KEY=dummy-key-for-build \
    DEBUG=False \
    ALLOWED_HOSTS="*" \
    python manage.py collectstatic --noinput

EXPOSE 8080

CMD ["sh", "-c", "gunicorn card_manager.wsgi:application --bind 0.0.0.0:${PORT} --workers 2 --timeout 120"]
