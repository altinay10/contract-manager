# --- Sözleşme Feneri — tek konteyner ---
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv

# OCR: taranmış PDF'ler için tesseract ve Türkçe dil verisi.
# Bunlar olmadan taranmış belge net bir hata mesajıyla reddedilir.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      tesseract-ocr tesseract-ocr-tur tesseract-ocr-eng \
 && rm -rf /var/lib/apt/lists/*

# Bağımlılıklar önce: katman önbelleği kod değişiminde bozulmasın.
COPY backend/requirements.txt /srv/requirements.txt
RUN pip install --no-cache-dir -r /srv/requirements.txt

COPY backend/app       /srv/app
COPY backend/playbook  /srv/playbook
COPY backend/web       /srv/web
COPY samples           /samples

# Kalıcı veri: SQLite + yüklenen belgeler + üretilen raporlar.
# Konteyner yeniden başlasa bile yarım kalan analizler buradan devam eder.
ENV STORAGE_DIR=/data \
    DATABASE_URL=sqlite:////data/app.db \
    PLAYBOOK_DIR=/srv/playbook \
    OCR_ENABLED=1 \
    OCR_LANG=tur+eng
RUN mkdir -p /data
VOLUME ["/data"]

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status==200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
