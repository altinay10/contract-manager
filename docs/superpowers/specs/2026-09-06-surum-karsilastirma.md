# Sürüm Karşılaştırma — tasarım ve uygulama planı

**Tarih:** 2026-09-06 · **Dal:** `surum-karsilastirma` · **Durum:** uygulanıyor

Bu dosya hem tasarım belgesidir hem de ilerleme çizelgesi. Oturum kesilirse
buradan devam edilir: işaretli kutular bitmiş, boş kutular kalan iştir.

---

## 1. Ne yapıyoruz

Sözleşmenin eski ve yeni sürümü yüklenir; sistem madde bazında neyin
değiştiğini çıkarır ve her önemli değişikliği açıklar: ne değişti, ne anlama
geliyor, kimin lehine.

Mevcut risk analizi hattından **bağımsızdır**. `runner.py` açılmaz.

## 2. Kararlar (kullanıcı onaylı)

| Konu | Karar |
|---|---|
| Kapsam | Bağımsız karşılaştırma — analiz edilmiş sözleşmeye bağlanmaz |
| Açıklama derinliği | Anlam + taraf etkisi (banka lehine / tedarikçi lehine / nötr) |
| Arayüz | Tek yükleme paneli, iki sekme |
| Çıktı | Ekran + indirilebilir DOCX değişiklik raporu |

## 3. Mimari yerleşim

Metin çıkarma, normalizasyon ve madde ayrıştırma için mevcut **saf
fonksiyonlar** yeniden kullanılır: `extract_ex()`, `normalize()`, `segment()`.
Bunlar `Contract` nesnesine bağlı değildir; onları saran `stage_*`
sarmalayıcıları bağlıdır. Dolayısıyla hattın pahalı kısmı `runner.py`'a hiç
dokunmadan kullanılır.

**`segment()` DEĞİŞTİRİLMEZ.** Onu değiştirmek analiz hattının davranışını da
değiştirir. Karşılaştırma katmanı `segment()`'i olduğu gibi çağırıp
çıktısındaki boşlukları kendi tarafında doldurur.

## 4. Ölçülmüş sorun: kapsama delikleri

Örnek sözleşme üzerinde ölçüldü (`samples/ornek-saas-sozlesmesi.pdf`):

```
normalize metin : 4.496 karakter · madde sayısı: 25
HİÇBİR MADDEYE AİT OLMAYAN: 224 karakter (%5,0)
```

O 224 karakterde sözleşmenin **adı, tarafları ve tarihi** var. Madde bazlı
karşılaştırma tedarikçi tüzel kişiliği değişse bunu göstermezdi.

İkinci delik: belgede 3'ten az başlık tanınırsa `segment()` yedek paragraf
moduna düşer ve `len(block.strip()) > 80` filtresi yüzünden **80 karakterden
kısa blokları tamamen atar**. Ölçüm: `"Bedel: 250.000 TL."` (18 karakter) yok
oldu. Bedel, tarih, süre gibi kısa satırlar tam da burada.

Buna karşılık **çok paragraflı maddelerde sorun yok**: normal modda bir birim
kendi başlığından sonraki başlığa kadar uzanır, aradaki bütün paragrafları
içine alır ve birimler uç uca eklenir (ölçüldü: 0-221, 221-304, 304-356,
kayıp 0).

Ayrıca ölçülen bir tanecik sorunu: `normalize()` satırları birleştirdiği için
alt madde numaraları satır başında kalmaz ve `_match_heading` onları görmez —
gerçek örnekte 12.1, 12.2, 12.3, 12.4 tek birim oldu. Kayıp değil, iri
tanecik; kelime bazlı fark bunu telafi eder.

## 5. Çözüm: karakter muhasebesi

Karşılaştırmanın birimi "madde" değil, **metnin her karakterini kapsayan
birim**tir.

1. `segment()` çağrılır, çıktısı alınır.
2. Kapsanmayan karakter aralıkları hesaplanır; her biri kendi birimi olur
   (`Başlık ve taraflar`, `İmza bloğu`, `Madde 12 ile 13 arası` gibi).
3. **Değişmez koşul:** birimlerin aralıkları birleştiğinde belgenin tamamını
   vermek zorundadır. Kapsam %100 değilse karşılaştırma başlamaz, hata verir.
4. Bu koşul teste bağlanır — örnek sözleşme, yedek mod ve sentetik kenar
   durumları.

Boşluğun *neden* oluştuğuyla ilgilenmez; preamble, atılan kısa paragraf ve
bloklar arası metin aynı kuralla toplanır.

## 6. Eşleştirme

1. **Numara eşleşmesi** — iki tarafta da tekil olan madde numaraları eşlenir.
2. **Benzerlik eşleşmesi** — kalanlar için `difflib.SequenceMatcher`; eşik
   üstü en iyi eşleşme. Numara değişmiş metin aynıysa `TASINDI`.
3. **Artıklar** — eşleşmeyen eski `SILINDI`, eşleşmeyen yeni `EKLENDI`.
4. **Kelime farkı** — eşleşen çiftlerde `get_opcodes()` ile kelime bazında.

**Bilinçli yanlılık: eşik yüksek, şüphede kalırsan eşleştirme.** İki hata
simetrik değil — eşleştirmemek iki kart üretir (bilgi tam), yanlış eşleştirmek
alakasız iki maddeyi yan yana koyar ve okuyan kişi anlamsız kartı atlar.

`difflib` standart kütüphanede; **yeni bağımlılık yok**.

## 7. Model katmanı ve parola kuralı

Mevcut sınır korunur (`Contract.model_izinli` ile aynı mantık):

- **Parolasız:** deterministik fark listesi tam çalışır; açıklama şablon
  metin, `impact` = BELIRSIZ. Ekranda "yorum için giriş yapın" yazar.
- **Parolalı:** her önemli değişiklik için model açıklama üretir.

Maliyet mevcut `Budget` ile sınırlanır. Yalnız noktalama/boşluk değişiklikleri
modele gitmez. `analyze.py`'daki prompt injection koruması taşınır.

## 8. Veri modeli

Yeni tablolar: `comparisons`, `clause_changes`.
Mevcut tabloda tek dokunuş: `reports` tablosuna nullable `comparison_id`.
`contracts`, `clauses`, `findings`, `analysis_runs`, `stage_checkpoints`,
`work_items` **değişmez**.

Çökme dayanıklılığı bedava gelir: açıklamalar `clause_changes` satırlarına tek
tek yazılır, devam ederken yalnız `explanation` alanı boş satırlar işlenir.

## 9. API

```
POST   /api/comparisons              iki dosya
GET    /api/comparisons/{id}/progress
GET    /api/comparisons/{id}/changes
POST   /api/comparisons/{id}/cancel
```

Mevcut hiçbir uç değişmez. Yetki `optional_user`.

## 10. Arayüz

Yükleme paneline iki sekme: **Risk analizi** | **Sürüm karşılaştırma**.
Sekmenin altında o modun ne yaptığını anlatan bir satır.

- Risk analizi sekmesi: mevcut bırakma alanı + bağlam seçenekleri, aynen.
- Karşılaştırma sekmesi: yan yana iki bırakma alanı, "Karşılaştır" düğmesi.
- Sonuç: sayaç şeridi + değişiklik kartları (eski/yeni metin, renkli kelime
  farkı, açıklama, taraf etkisi rozeti) + DOCX indirme.

DOM kimlikleri ayrı (`cmp*`); mevcut `poll()` ve ilerleme kodu değişmez.
"Ne yapar" bölümüne ikinci özelliği tanıtan blok eklenir.

---

## Uygulama çizelgesi

- [x] **1. Veri modeli** — `Comparison`, `ClauseChange`, `Report.comparison_id`, `ensure_schema`
- [ ] **2. Kapsama katmanı** — `pipeline/coverage.py` + %100 kapsam testleri
- [ ] **3. Eşleştirme ve fark** — `pipeline/compare.py` + testler
- [ ] **4. Açıklama katmanı** — `pipeline/compare_explain.py` (LLM + kural fallback)
- [ ] **5. Koşucu** — `compare_runner.py` (aşamalar, iş parçacığı, ilerleme, iptal)
- [ ] **6. API uçları** — `/api/comparisons*`
- [ ] **7. DOCX raporu** — `pipeline/compare_report.py`
- [ ] **8. Arayüz** — sekmeler, iki bırakma alanı, sonuç kartları, tanıtım metni
- [ ] **9. Testler yeşil** — `make test`, mevcut 164 test dahil
- [ ] **10. Pi dağıtımı** — canlıda doğrulama
