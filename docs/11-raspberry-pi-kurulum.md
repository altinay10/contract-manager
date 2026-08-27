# 11 — Raspberry Pi Kurulumu ve Bilinen Sorunlar

## Kısa cevap

Docker entegrasyonu çalışıyor, **ama Pi'ye kurarken bilmeniz gereken dört şey var.**
En önemlisi: **imajı Pi'nin kendisinde derlemelisiniz.**

---

## 1. Mimari — imajı Pi'de derleyin  ⚠️ EN KRİTİK

Geliştirme makinesinde üretilen imaj **amd64**'tür; Raspberry Pi **arm64**'tür.
Hazır imajı Pi'ye kopyalarsanız çalışmaz (veya QEMU altında dayanılmaz yavaş olur).

```bash
git clone <depo> && cd contract-manager
cp .env.example .env          # anahtarınızı yazın (isteğe bağlı)
docker compose up -d --build  # ← --build şart: Pi native derler
```

İlk derleme **15–35 dakika** sürer (tesseract apt paketleri + Python tekerlekleri).
Sonraki derlemeler katman önbelleğiyle çok daha hızlıdır.

### 64-bit işletim sistemi zorunlu

| Paket | arm64 (64-bit) | armv7 (32-bit) |
|---|---|---|
| PyMuPDF | ✅ hazır tekerlek | ❌ yok — kaynaktan derlenir, saatler sürer/başarısız olur |
| Pillow | ✅ hazır tekerlek | ❌ yok |
| diğerleri | ✅ saf Python | ✅ |

Kontrol: `uname -m` → **`aarch64`** görmelisiniz. `armv7l` görüyorsanız
64-bit Raspberry Pi OS'a geçin.

**Pi 3 ve altı önerilmez** — bellek ve CPU yetersiz kalır. Pi 4 (4 GB+) veya Pi 5 hedefleyin.

---

## 2. OCR ayarlarını düşürün

OCR bir sayfayı 300 dpi'da rasterleştirir: ~2480×3508 RGB ≈ **26 MB bellek/sayfa**,
üstüne tesseract'ın kendi kullanımı. Pi'de bu hem belleği hem CPU'yu zorlar.

`.env` içinde:
```
OCR_DPI=200          # 300 yerine
OCR_MAX_PAGES=30     # 60 yerine
MEM_LIMIT=1200m      # 4 GB Pi için
```

200 dpi basılı sözleşmelerde yeterli doğruluk verir. Ölçüm: masaüstünde 2 sayfalık
taranmış PDF 300 dpi'da %95 güvenle okundu; Pi'de aynı iş **5–10 kat yavaş** olur
(sayfa başına ~10–30 sn beklenmeli).

---

## 3. SD kart yerine SSD kullanın

SQLite ve üretilen belgeler `/data` biriminde tutulur ve WAL modunda sürekli yazar.
SD kart hem yavaştır hem de yazma aşınmasıyla bozulur.

```yaml
# docker-compose.override.yml
services:
  feneri:
    volumes:
      - /mnt/ssd/feneri-data:/data
```

Yalnızca deneme yapacaksanız SD kart yeterlidir; sürekli kullanımda USB SSD şart.

---

## 4. Kaynak sınırları ve log şişmesi

`docker-compose.yml` içinde ikisi de tanımlı:
- `mem_limit` (varsayılan 1500m) — konteynerin Pi'yi kilitlemesini engeller
- `logging` max-size 10m / 3 dosya — logların kartı doldurmasını engeller

Bellek sınırı aşılırsa konteyner öldürülür; **yarım kalan analiz kaybolmaz**,
açılışta kaldığı yerden devam eder (bkz. doc 09 §2).

---

## Doğrulama

```bash
docker compose ps                       # healthy görmelisiniz
curl -s localhost:8099/api/health | jq  # ocr.ready true olmalı
uname -m                                # aarch64
docker image inspect sozlesme-feneri:0.1 --format '{{.Architecture}}'   # arm64
```

---

## API anahtarı — üç seçenek

| Yöntem | Nasıl | Ne zaman |
|---|---|---|
| `.env` dosyası | `GOOGLE_API_KEY=...` | Sunucu sabit anahtarla çalışsın |
| Uygulama arayüzü | "Model ayarları" paneli | Kullanıcı kendi anahtarını girsin |
| Hiçbiri | — | Kural tabanlı mod (model yok, uydurma yok) |

Arayüzden girilen anahtar `/data/settings.json` dosyasına `0600` izniyle yazılır ve
ortam değişkenini **ezer**. Konteyner yeniden başlasa da kalır.

> ⚠️ Uygulamada kimlik doğrulama yoktur (bkz. [doc 10](10-uretim-hazirlik-degerlendirmesi.md) B1).
> Ağınızda uygulamaya erişebilen herkes bu anahtarı okuyamaz (maskeli döner) ama
> **değiştirebilir ve harcatabilir**. Pi'yi internete açmayın; kapalı ağda tutun
> veya önüne kimlik doğrulamalı bir ters vekil koyun.

---

## Bilinen sınırlar (Pi'ye özgü)

- Model çağrıları ağa bağlıdır; Pi'nin CPU'su darboğaz değildir. Kural tabanlı mod
  Pi'de de hızlıdır (küçük sözleşme ~1–3 sn).
- OCR ve büyük PDF ayrıştırma tek çekirdek kullanır; eşzamanlı çok kullanıcı için
  uygun değildir (zaten tek düğüm mimarisi — doc 10 B6).
- `MAX_UPLOAD_MB=40` varsayılanı Pi için yüksek olabilir; 20 MB önerilir.
