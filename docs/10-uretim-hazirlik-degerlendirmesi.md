# 10 — Üretim Hazırlık Değerlendirmesi

**Tarih:** 24.08.2026 · **Sürüm:** 1.0.0 · **Değerlendiren:** geliştirme

---

## Karar

> **28.08.2026 güncellemesi:** B1 (kimlik doğrulama) ve B3 (denetim izi) **kapatıldı.**
> Kalan blokerler: **B4 (kalite ölçülmedi)** ve **B5 (playbook hukuk onayı)**.
>
> **Kapalı ağda sınırlı pilot için HAZIR. Bankaya açık üretim için HENÜZ DEĞİL.**

Sistem uçtan uca çalışıyor, dayanıklı ve test edilmiş durumda. Ancak bir bankanın
üretim ortamına çıkması için **kimlik doğrulama ve denetim izi** gibi zorunlu
kontroller henüz yok. Bunlar kod kalitesi eksiği değil, **bilinçli olarak
ertelenmiş kapsam** — ama üretim öncesi pazarlık konusu değildir.

| Kullanım | Karar |
|---|---|
| Yerel/iç değerlendirme, gerçek olmayan sözleşmelerle | ✅ Şimdi |
| Sınırlı pilot — kapalı ağ, 2-3 kullanıcı, gerçek sözleşme | ✅ Şimdi (B1/B3 kapatıldı) |
| Karar dayanağı olarak kullanma, toplantıda sunma | ❌ B4 + B5 kapatılmadan olmaz |
| Banka üretimi, çok kullanıcılı, kuruma açık | ❌ B2 + B6 + B7 de gerekir |

---

## Doğrulanmış olanlar

| Alan | Durum | Kanıt |
|---|---|---|
| Uçtan uca analiz | ✅ | PDF/DOCX/TXT → 4 belge; konteynerde 22/22 kabul testi |
| OCR (taranmış belge) | ✅ | 22 MB taranmış PDF → %95 güvenle okundu, metin katmanlı sürümle aynı bulgular |
| Kesinti dayanıklılığı | ✅ | Konteyner analiz ortasında `docker kill` → açılışta kaldığı yerden devam, sonuç birebir aynı |
| Ölümcül/geçici hata ayrımı | ✅ | 404 → tek token harcamadan durdu; 429/503 → devre kesildi, kural katmanı devraldı |
| Token/maliyet tavanları | ✅ | Tavan aşılınca model kapanıyor, analiz çökmüyor |
| Şeffaflık | ✅ | Başarısız çağrılar kayda geçiyor, rapor "model devre dışı bırakıldı" diyor |
| Halüsinasyon savunması | ✅ | Uydurma alıntı düşürülüyor, uydurma mevzuat dayanağı temizleniyor (test edilmiş) |
| Test kapsamı | ✅ | 88 test: birim, dayanıklılık, model yolu, Türkçe eşleştirme, HTTP entegrasyon |
| Kalıcılık | ✅ | Konteyner yeniden başlatmada veri ve raporlar korunuyor |

---

## Üretim blokerleri

### B1 — Kimlik doğrulama yok  🔴 KRİTİK
`app/main.py` içindeki **10 ucun hiçbirinde** kimlik doğrulama yok. Herkes sözleşme
yükleyebilir, `/api/contracts` ile **tüm sözleşmeleri listeleyebilir** ve herhangi bir
raporu indirebilir. Banka sözleşmeleri için bu tek başına diskalifiye edicidir.

**Gereken:** OIDC/SSO (Keycloak veya kurumsal AD), rol bazlı yetki (doküman 03'te
tanımlı: SATIN_ALMA / HUKUK / UYUM / BILGI_GUVENLIGI / YONETICI / ADMIN).

### B2 — Yetkilendirme ve erişim kapsamı yok  🔴 KRİTİK
Sözleşme bazlı erişim kontrolü yok. Herkes her sözleşmeyi görür. Doküman 05'te
"herkes her sözleşmeyi görmez" yazıyor; uygulanmadı.

### B4 — Kalite ölçülmedi  🟠 YÜKSEK  ← elle denetimde İKİ YANLIŞ BEYAN bulundu
Doküman 05'te recall ≥ %90, precision ≥ %80 gibi eşikler tanımlı. **Hiçbiri ölçülmedi**
— altın set yok, ablasyon koşusu yapılmadı. Karar-destek aracının isabet oranı bilinmeden hukukçunun önüne konmamalı.

**24.08.2026'da yapılan elle denetim bunu somutladı.** Tek bir sözleşmenin 36 bulgusu
tek tek okunduğunda iki **yanlış beyan** çıktı:

| Rapor diyordu ki | Gerçek |
|---|---|
| "Tazminat yükümlülüğü sözleşmede yok" | m.12.4'te **var** — üstelik tek taraflı, banka aleyhine |
| "Fiyat artışı maddesi sözleşmede yok" | m.4'te **var** — tedarikçi tek taraflı artırabiliyor |

İkisi de sözleşmenin en ağır maddelerindendi ve "yok" diye raporlanıyordu. Kök neden:
anahtar kelime sınıflandırması maddeyi kaçırınca, eksik madde motoru bunu
"sözleşmede bulunmuyor" şeklinde **olumlu bir iddiaya** çeviriyordu. Bir toplantıda
tedarikçi avukatının maddeyi açması bankayı zor durumda bırakırdı.

**Düzeltildi:** kırmızı çizgi deseni eşleşen madde, anahtar kelime skoru düşük olsa
bile o tipe atanır (desen çok daha spesifik bir sinyaldir). Dört regresyon testi eklendi.

**Ama asıl ders şu:** bu hatayı bulan şey bir test değil, **bir insanın 36 bulguyu tek tek
okuması** oldu. Ölçülmemiş bir sistemde bu sınıftan başka hatalar olduğunu varsaymak
gerekir. Altın set olmadan "isabet oranı şudur" denemez.

### "Kalite modele bağlı, o yüzden ölçülemez" — neden geçerli değil

Model gücü sonucu etkiler; bu doğru ve arayüzde de yazıyor. Ama bu, ölçümün
gereksiz olduğu anlamına gelmez — tersine, ölçümü **daha da gerekli** kılar:

1. **Bulunan dört kaçağın dördü de modelden bağımsızdı.** Sınıflandırma eşiği, Türkçe
   ek eşleştirmesi, `applies_to` boşluğu ve "yok" beyanına dönüşen kaçak — hepsi
   deterministik katmandaydı. **Daha güçlü bir model bunların hiçbirini düzeltmezdi**,
   çünkü model o maddeleri hiç görmüyordu.
2. **Ölçüm mutlak değil, yapılandırma başınadır.** "Sistemin isabeti" diye tek bir sayı
   yoktur; *şu model + şu playbook* ölçülür. Altın set olmadan Opus'un flash-lite'tan
   daha iyi olduğunu **sizin sözleşmelerinizde** doğrulayamazsınız — yalnızca
   varsayarsınız.
3. **Güçlü model bazı hataları artırır.** İstekli bir model daha çok yanlış pozitif
   üretebilir; bunu model gücü değil, doğrulama ve karşı-görüş katmanı dengeler.

Altın set aynı zamanda **model seçimini rasyonelleştirir**: "hangi model bu iş için
parasını hak ediyor?" sorusu ancak ölçümle cevaplanır.

### B5 — Playbook hukuki onaydan geçmedi  🟠 YÜKSEK
42 madde tipinin ideal metinleri, kırmızı çizgileri ve **mevzuat dayanakları** taslak
niteliğindedir. Hukuk Müşavirliği onayı olmadan üretime alınmamalıdır. Bu bir kod
riski değil, **içerik riskidir** ve en az kod kadar önemlidir.

### B6 — Tek düğüm mimarisi  🟡 ORTA
SQLite + işlem içi kuyruk. Eşzamanlı çok kullanıcı ve yatay ölçek yok; tek hata noktası.
Checkpoint tasarımı Postgres + Celery geçişini destekliyor (`DATABASE_URL` yeterli),
ama geçiş yapılmadı.

### B7 — Operasyonel sertleştirme eksik  🟡 ORTA
- TLS yok (ters vekil arkasına konmalı)
- API anahtarı ortam değişkeninde; vault/secret manager yok
- Yükleme dosyalarında virüs taraması ve magic-byte doğrulaması yok
- Hız sınırlama yok
- Saklama/imha politikası (doküman 05) uygulanmadı
- Sızma testi yapılmadı

---

## Bloker olmayan bilinen sınırlar

- Madde sınıflandırma anahtar kelime + Türkçe gövde eşleştirmesi; embedding katmanı yok.
- OCR yalnızca basılı metin okur; el yazısı ve çok düşük çözünürlük kapsam dışı.
- İnceleme akışı (kabul/ret, yorum, sürüm karşılaştırma) yok — ana akış bilinçli olarak
  tam otomatik (doküman 09 §1).
- Lokal model desteği (Faz 7) eklenmedi; soyutlama katmanı hazır.
- Sprint 0 ablasyon koşusu yapılmadı (B4 ile aynı kök).

---

## Önerilen sıra

1. ~~B1 + B3~~ — **tamamlandı.**
2. **B5** — Hukuk playbook'u onaylasın. Koddan bağımsız; hemen başlatılabilir.
3. **B4** — 50-80 sözleşmelik altın set + isabet ölçümü. Pilotun çıktısı bu seti besler.
   **Bu ikisi kapatılmadan çıktı toplantıda dayanak olarak kullanılmamalı.**
4. **B2** (rol/sözleşme bazlı yetki) + **B6** (Postgres/Celery) + **B7** (TLS, vault,
   virüs taraması, saklama politikası) — kuruma açılırken.

**B4:** hukukçu eforuna bağlı, 2–4 hafta.

---

## Özet

Mühendislik tarafı sağlam: hat çalışıyor, kesintiye dayanıyor, maliyeti kontrollü,
çıktısı denetlenebilir ve 88 testle korunuyor. Eksik olan, bankaya özgü **erişim
kontrolü ve kanıtlanmış kalite**. İkisi de bilinen, tanımlı ve sınırlı işler —
ama tamamlanmadan üretim onayı verilemez.
