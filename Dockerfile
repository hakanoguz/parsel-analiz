FROM python:3.12-slim

# 1. Rasterio için gerekli olan Linux coğrafi kütüphanelerini en başta yüklüyoruz
RUN apt-get update && apt-get install -y \
    gdal-bin \
    libgdal-dev \
    libexpat1 \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=10000 \
    SAATLIK_LIMIT=20

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py rapor_motoru.py ./
COPY static ./static

RUN mkdir -p data cikti \
    && useradd -m uygulama \
    && chown -R uygulama /app
USER uygulama

EXPOSE 10000

CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
