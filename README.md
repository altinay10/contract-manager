# Sözleşme Feneri

Banka tedarik sözleşmelerini madde madde inceleyip bankayı zora sokabilecek maddeleri,
hiç yazılmamış zorunlu maddeleri ve banka lehine düzeltme önerilerini **tek bir sonuç
belgesinde** veren karar-destek uygulaması.

Kullanıcı dosyayı bırakır, başka hiçbir şey yapmaz. Sistem on aşamayı kendi yürütür,
kesintiye uğrarsa kaldığı yerden devam eder ve Word raporunu hazırlar.

---

## Hızlı Başlangıç

### Docker ile
```bash
cp .env.example .env      # anahtar ve limitleri buraya yazın (hepsi isteğe bağlı)
docker compose up -d --build
```
→ http://localhost:8099

**Anahtar girmek zorunlu değildir.** Öncelik sırası:

```
arayüzden girilen anahtar  →  .env dosyası  →  kural tabanlı mod
```

Anahtar geçersizse veya kota biterse uygulama bunu **söyler** ve iki seçenek sunar:
yeni anahtar girmek, ya da kural tabanlı motorla devam etmek.

**Maliyet:** fiyatı bilinen modellerde birim fiyat kutuları hazır gelir; bilinmeyen
modelde boş gelir. Doldurursanız maliyet hesaplanır, doldurmazsanız rapor “—” yazar —
uydurma rakam üretilmez.

**Sağlayıcı seçimi açık uçludur:**

| Seçenek | Kapsam |
|---|---|
| **Claude** | Anthropic |
| **ChatGPT** | OpenAI |
| **Gemini** | Google |
| **Diğer** | OpenAI sohbet protokolünü konuşan her servis — Qwen, DeepSeek, Groq, OpenRouter, Together, yerel **Ollama / vLLM** (yerel uçlar anahtar istemez) |

"Diğer"de uç nokta adresini ve model adını siz girersiniz; uygulama `GET /v1/models` ile
mevcut modelleri listeleyebilir ve tek küçük çağrıyla bağlantıyı test eder.
Yapılandırılmış çıktı desteği sağlayıcıdan sağlayıcıya değiştiği için
`json_schema → json_object → serbest metin` şeklinde kademeli geri düşüş uygulanır.

**Raspberry Pi'ye kuracaksanız** [doc 11](docs/11-raspberry-pi-kurulum.md)'i okuyun:
imajı Pi'de derlemeniz gerekir (`--build`), 64-bit OS zorunludur ve OCR ayarları
düşürülmelidir.

### Yerel geliştirme
```bash
make setup
make dev
```
→ http://127.0.0.1:8099

Diğer komutlar: `make test`, `make demo`, `make demo-model`, `make sample-pdf`, `make clean`

### Terminalden tek sözleşme
```bash
cd backend && ../.venv/bin/python -m app.cli ../samples/ornek-saas-sozlesmesi.pdf --outsourcing
```

---

## Ne Yapıyor

Yüklenen sözleşme on aşamadan geçer:

| # | Aşama | Ne yapar |
|---|---|---|
| 1 | Alım | Dosya doğrulama, SHA-256 |
| 2 | Metin Çıkarma | PDF / DOCX / TXT metin katmanı; taranmış belgede **OCR** (tesseract, tur+eng) |
| 3 | Normalizasyon | Tireleme, üstbilgi temizliği (offset koruyarak) |
| 4 | Madde Ayrıştırma | Madde / fıkra / ek hiyerarşisi |
| 5 | Meta Çıkarımı | Taraflar, bedel, süre, damga vergisi yükümlüsü |
| 6 | Sınıflandırma | Her madde hangi playbook tipine karşılık geliyor |
| 7 | Ön Kontroller | Belirsiz ifade, çapraz atıf hataları |
| 8 | **Risk Analizi** | Kırmızı çizgi kontrolü, çoklu mercek, madde bazlı inceleme |
| 9 | Doğrulama | Alıntı metinde birebir var mı; kritik bulgularda karşı-görüş |
| 10 | Rapor | Skorlama ve sonuç belgesi (DOCX + JSON) |

**Üç çıktı üretilir:**
| Belge | İçerik |
|---|---|
| **Risk raporu** (DOCX) | Künye, yönetici özeti, skor + bant, öncelikli aksiyonlar, tüm bulgular (alıntı, gerekçe, dayanak, önerilen metin, müzakere argümanı), model kullanımı |
| **Redline** (DOCX) | Word'de **kabul et / reddet** edilebilen gerçek değişiklik izlemeli öneri metinleri |
| **Rapor** (HTML) | Aynı içerik tarayıcıda — indirmeden okunur |
| **Analiz** (JSON) | Tam çıktı, entegrasyon ve arşiv için |

### İki çalışma modu
- **API anahtarı varsa:** seçtiğiniz model + kural katmanı. Çoklu mercek,
  karşı-görüş ve tam metin eksik madde taraması açık.
- **Anahtar yoksa:** kural tabanlı playbook motoru. Sahte cevap üretmez — yalnızca
  playbook'tan deterministik çıkarılabilen bulguları raporlar.

### Token şeffaflığı
Her analiz için harcanan girdi/çıktı/önbellek tokeni, çağrı sayısı, gecikme ve maliyet
**göreve göre ayrıştırılmış** olarak raporda, arayüzde ve `/api/contracts/{id}/usage`
ucunda görünür.

### Token ve maliyet kontrolü
Harcama tek bir yerden sınırlanır; tavan aşılınca model **kapatılır** ve analiz kural
katmanıyla tamamlanır — çökmez, eli boş bırakmaz.

```bash
MAX_LLM_CALLS=10 MAX_COST_USD=0.05 MAX_LLM_CLAUSES=6 \
ENABLE_LENSES=0 ENABLE_REBUTTAL=0 make demo-model
```

Kalıcı hatalar (geçersiz anahtar, emekli model) **hiç tekrar denenmez**; geçici
hatalarda üst üste 3 başarısızlıkta devre kesilir. Ölçülen: 2 sayfalık sözleşme,
6 madde modele → 8 çağrı, ~14 bin token, **$0.012**.

---

## Dayanıklılık

Analiz yarıda kesilirse **baştan başlamaz**:

- Her aşamanın durumu kalıcıdır; tamamlanmış aşama tekrar çalışmaz.
- Risk analizi **madde madde** işaretlenir; 62 maddenin 40'ında çökerse kalan 22 işlenir.
- Geçici hatalar üstel beklemeyle denenir; bozuk dosya gibi ölümcül hatalar tekrarlanmaz.
- Uygulama/konteyner çökerse açılışta öksüz analizler otomatik devam ettirilir
  (açılış kimliği + kalp atışı; periyodik tarayıcı da vardır).
- **İptal** işbirliklidir: tamamlanan aşamalar korunur, sonra devam edilebilir.
- **Sayfa yenilense bile** analiz kaybolmaz; arayüz izlemeye geri bağlanır.
- Tek maddenin hatası tüm analizi durdurmaz.

Ayrıntı: [docs/09](docs/09-uygulama-ve-dayaniklilik.md)

---

## Dokümanlar

| # | Doküman | İçerik |
|---|---|---|
| 00 | [Genel Bakış](docs/00-genel-bakis.md) | Problem, personalar, kapsam ve kapsam dışı |
| 01 | [Madde Taksonomisi & Playbook](docs/01-madde-taksonomisi-ve-playbook.md) | 42 madde tipi, risk kataloğu, skorlama |
| 02 | [Mimari & Analiz Hattı](docs/02-mimari-ve-analiz-hatti.md) | 10 aşamalı pipeline, agent rolleri |
| 03 | [Veri Modeli & API](docs/03-veri-modeli-ve-api.md) | Şema, durum makineleri, uçlar |
| 04 | [Ekranlar & Akışlar](docs/04-ekranlar-ve-akislar.md) | Ekran tasarımları, çıktı formatları |
| 05 | [Eval, Güvenlik, Uyum](docs/05-degerlendirme-guvenlik-uyum.md) | Altın set, metrikler, KVKK/BDDK |
| 06 | [Yol Haritası](docs/06-yol-haritasi.md) | Fazlar, sprintler |
| 07 | [Kodlamaya Başlangıç](docs/07-kodlamaya-baslangic.md) | Sprint planı, regex seti, prompt iskeleti |
| 08 | [**Dikkat Yönlendirme Mimarisi**](docs/08-dikkat-yonlendirme-mimarisi.md) | AI-first çekirdek: 7 dikkat kaldıracı, prompt caching, maliyet |
| 09 | [**Uygulama & Dayanıklılık**](docs/09-uygulama-ve-dayaniklilik.md) | Çalışan kodun mimarisi, failsafe, OCR, token şeffaflığı |
| 10 | [**Üretim Hazırlık Değerlendirmesi**](docs/10-uretim-hazirlik-degerlendirmesi.md) | Go/no-go kararı ve bloker listesi |
| 11 | [**Raspberry Pi Kurulumu**](docs/11-raspberry-pi-kurulum.md) | Mimari, OCR ayarları, depolama, bilinen sorunlar |

---

## Playbook

Bankanın standardı kod değil **veridir**: `backend/playbook/*.yaml` — **42 madde tipi**.
Yeni bir kırmızı çizgi eklemek için yeniden derleme gerekmez; docker-compose
playbook dizinini konteynere bağlar.

Her kayıt: ideal madde metni, kabul edilebilir geri çekilme, kırmızı çizgiler
(tespit kalıplarıyla), mevzuat dayanağı, müzakere argümanı, ağırlık.

---

## Test durumu

```
153 test — 31 birim · 12 dayanıklılık/iptal · 25 model/bütçe · 20 Türkçe eşleştirme · 46 entegrasyon · 19 kimlik/denetim
```

Entegrasyon testleri HTTP seviyesinde gerçek uygulama üzerinden koşar: yükleme →
arka plan analizi → ilerleme → dört belge → indirme → hata yolları.
Konteyner üzerinde ayrıca uçtan uca kabul testi yapılmıştır (22/22).

## Güvenlik

Tüm API uçları **parola ile korunur**; yalnızca giriş ve `/api/health` açıktır.
Parola `scrypt` ile karmalanır, oturum çerezi HMAC ile imzalanır, giriş denemeleri
sınırlanır. Parola tanımlı değilse uygulama açık kalmaz — rastgele parola üretilip
loga yazılır.

```bash
APP_PASSWORD=güçlü-bir-parola
SESSION_SECRET=rastgele-uzun-dize
COOKIE_SECURE=1        # HTTPS arkasındaysanız
```

Her önemli işlem **denetim izine** yazılır (`GET /api/audit`): giriş/çıkış, başarısız
giriş, yükleme, rapor indirme, ayar değişikliği, iptal. API anahtarı denetim izine yazılmaz.

## Üretim durumu

**Kapalı ağda sınırlı pilot için hazır.** Kimlik doğrulama ve denetim izi tamamlandı.
Kalan iki bloker — **kalite ölçülmedi** ve **playbook hukuk onayından geçmedi** —
kapatılmadan çıktı toplantıda dayanak olarak kullanılmamalıdır.
Ayrıntı: [doc 10](docs/10-uretim-hazirlik-degerlendirmesi.md).

## Uyarı

Bu uygulamanın çıktısı **hukuki mütalaa yerine geçmez**. Karar-destek verisidir;
her bulgu imza öncesinde Hukuk Müşavirliği tarafından değerlendirilmelidir.
