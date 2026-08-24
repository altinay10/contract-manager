VENV := .venv/bin
PORT ?= 8099

.PHONY: help setup dev test demo demo-model sample-pdf docker-build docker-up docker-down clean

help:
	@echo "make setup        - sanal ortam + bağımlılıklar"
	@echo "make dev          - sunucuyu başlat (http://127.0.0.1:$(PORT))"
	@echo "make test         - testleri çalıştır"
	@echo "make demo         - örnek sözleşmeyi terminalden analiz et (kural modu)"
	@echo "make demo-model   - modelli deneme, sıkı bütçeyle"
	@echo "make sample-pdf   - örnek PDF'i yeniden üret"
	@echo "make docker-build - konteyner imajını üret"
	@echo "make docker-up    - konteyneri başlat"
	@echo "make docker-down  - konteyneri durdur"
	@echo "make clean        - veritabanı ve üretilen dosyaları sil"

setup:
	python3 -m venv .venv
	$(VENV)/pip install --quiet --upgrade pip
	$(VENV)/pip install --quiet -r backend/requirements-dev.txt
	@echo "hazır. 'make dev' ile başlatın."

dev:
	$(VENV)/python -m uvicorn app.main:app --host 127.0.0.1 --port $(PORT) --app-dir backend --reload

test:
	cd backend && ../$(VENV)/python -m pytest tests -q

demo:
	cd backend && ../$(VENV)/python -m app.cli ../samples/ornek-saas-sozlesmesi.pdf --outsourcing

# Örnek PDF'i yeniden üretir
sample-pdf:
	$(VENV)/python samples/pdf_uret.py

# Modelli deneme — sıkı bütçeyle. GOOGLE_API_KEY veya ANTHROPIC_API_KEY gerekir.
demo-model:
	cd backend && MAX_LLM_CLAUSES=6 ENABLE_LENSES=0 ENABLE_REBUTTAL=0 \
	  MAX_LLM_CALLS=10 MAX_COST_USD=0.05 MAX_TOTAL_TOKENS=120000 \
	  ../$(VENV)/python -m app.cli ../samples/ornek-saas-sozlesmesi.pdf --outsourcing

docker-build:
	docker compose build

docker-up:
	docker compose up -d
	@echo "http://localhost:$(PORT)"

docker-down:
	docker compose down

clean:
	rm -rf backend/storage/app.db* backend/storage/uploads backend/storage/reports
	@echo "temizlendi"
