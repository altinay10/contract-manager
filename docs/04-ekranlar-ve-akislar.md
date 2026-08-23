# 04 — Ekranlar, Kullanıcı Akışları ve Çıktılar

## 1. Ana Akış (mutlu yol)
```
Yükle → (analiz 2-4 dk, canlı ilerleme) → Risk Özeti → Madde İnceleyici
   → Bulguları tek tek kabul/ret → Redline DOCX indir → tedarikçiye gönder
   → Revize sözleşmeyi v2 olarak yükle → Diff: "hangi bulgular kapandı?"
```

## 2. Ekran Listesi

### E1 — Yükleme
- Sürükle-bırak; sözleşme tipi, tahmini bedel, "kişisel veri işlenecek mi?",
  "dış hizmet mi?" gibi **bağlam soruları** (skorlama çarpanlarını besler — 5 alan, 30 saniye).
- Dosya hash'i daha önce yüklenmişse uyarı: "Bu belge X tarihinde analiz edilmiş."

### E2 — Analiz İlerlemesi
- 10 aşamanın canlı durumu (SSE). Her aşamada ne yapıldığı tek satır açıklama.
- Hata olursa hangi aşamada olduğu + "sadece bu aşamayı tekrar dene" butonu.

### E3 — Risk Özeti (Dashboard of one contract)
- Üstte: skor kadranı + renk bandı + veto uyarısı ("2 kırmızı çizgi ihlali").
- Sözleşme künyesi: taraflar, bedel, süre, yenileme, damga vergisi yükümlüsü.
- Kategori bazlı ısı haritası (8 kategori × şiddet).
- **"Eksik Maddeler"** ayrı ve göze çarpan bir kart — en çok gözden kaçan risk budur.
- İlk 5 öncelikli aksiyon listesi.

### E4 — Madde İnceleyici (uygulamanın kalbi)
İki panelli düzen:
- **Sol:** sözleşme metni, madde numaralarıyla, bulgu olan maddeler renkli vurgulu.
  Tıklayınca sağ panel o bulguya kayar. Metin aranabilir. Sayfa/madde navigasyonu.
- **Sağ:** seçili bulgu kartı:
  - Bulgu tipi + şiddet rozeti
  - **Neden riskli** (gerekçe)
  - **Metinden alıntı** (vurgulanmış, sol panele bağlantılı)
  - **Dayanak** (mevzuat/iç politika — tıklanınca ilgili metin açılır)
  - **Önerilen madde metni** (kopyala / düzenle) + **geri çekilme seçeneği (fallback)**
  - **Müzakere argümanı** (tedarikçiye söylenecek cümle)
  - Aksiyon: Kabul / Reddet (gerekçe zorunlu) / Müzakerede / Yorum ekle
- Filtreler: şiddet, kategori, tip, "sadece açık olanlar".

### E5 — Eksik Maddeler
- Zorunlu ama yok olan maddelerin listesi + hazır madde metni + "sözleşmeye ekle" (redline'a dâhil et).

### E6 — Sürüm Karşılaştırma
- v1 ↔ v2 madde bazlı diff (eklendi/silindi/değişti).
- Her bulgunun durumu: **kapandı / hâlâ açık / kısmen karşılandı / yeni risk doğdu**.
- Bu ekran müzakere turlarını yönetmenin ana aracıdır.

### E7 — Playbook Yönetimi (Hukuk/Admin)
- Madde tipleri listesi, düzenleme formu (ideal metin, kırmızı çizgiler, ağırlık).
- Sürüm geçmişi ve "kim değiştirdi".
- **Etki analizi:** "Bu kuralı sıkılaştırırsam geçmiş 120 sözleşmede kaç bulgu üretirdi?"
  (kuru çalıştırma / dry-run).

### E8 — Portföy Panosu
- Sözleşme listesi + risk bandı, açık kritik bulgu sayısı, sorumlusu, yaş.
- Trendler: en sık ihlal edilen 10 madde, en riskli 10 tedarikçi, ortalama müzakere turu.
- Bu tablo zamanla **kurumsal pazarlık gücü** verisine dönüşür.

### E9 — Yönetici Özeti / Rapor
- 1 sayfa: skor, 5 kritik madde, imza tavsiyesi (imzalanabilir / şartlı / imzalanmamalı),
  kalan riskin kabulü için gereken onay seviyesi.

### E10 — Yönetim & Denetim
- Kullanıcılar/roller, LLM maliyet raporu, denetim izi arama, prompt sürümleri.

## 3. Çıktı Formatları
| Format | İçerik | Kime |
|---|---|---|
| **DOCX (redline)** | Orijinal sözleşme + değişiklik izlemeli önerilen madde metinleri + kenar notu olarak gerekçe | Tedarikçiye gönderilecek belge |
| **PDF yönetici özeti** | E9 ekranı | İmza yetkilisi |
| **XLSX bulgu listesi** | Tüm bulgular, durum, sorumlusu | Hukuk/Satın Alma takip |
| **JSON** | Tam analiz çıktısı | Entegrasyon / arşiv |

DOCX redline üretimi teknik olarak en zahmetli parçadır: Word'ün `w:ins`/`w:del`
etiketleriyle gerçek "tracked change" üretilmelidir; hukukçular metnin yanına yazılmış
öneriyi değil, kabul-et/reddet yapabildikleri değişikliği ister.

## 4. Güven ve Şeffaflık Öğeleri (UI'da zorunlu)
- Her bulgunun yanında **güven skoru** ve "bu bulguyu ne üretti?" (kural / model / ikisi).
- Model üretimi her yerde işaretli; "Bu analiz hukuki mütalaa değildir" kalıcı uyarı.
- Kullanıcı bir bulguyu reddettiğinde sorulan **tek soru**: "Neden?" (5 hazır seçenek +
  serbest metin) — bu, sistemin öğrenme döngüsünün girdisidir.
