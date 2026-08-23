# 00 — Genel Bakış, Kapsam ve Sınırlar

## 1. Problem
Banka, üçüncü taraf tedarikçilerden ürün/hizmet (yazılım, donanım, danışmanlık, dış hizmet)
satın alırken imzalanan **satın alma / tedarik / çerçeve sözleşmelerini** çoğunlukla tedarikçinin
şablonu üzerinden müzakere eder. Bu şablonlar doğal olarak **tedarikçi lehine** kurgulanmıştır.

Bugünkü süreçte:
- Sözleşme incelemesi kişiye bağlıdır; aynı riskli madde bir sözleşmede yakalanır, diğerinde kaçar.
- "Geçen sefer bu maddeyi nasıl kabul ettirmiştik?" kurumsal hafızası kaybolur.
- Eksik madde (hiç yazılmamış olan) fark edilmesi en zor risktir; gözle yakalanmaz.
- Hukuk / Uyum / Bilgi Güvenliği / Satın Alma birimleri arasında tur atarken zaman kaybedilir.

## 2. Ürünün Tek Cümlelik Tanımı
> Yüklenen bir tedarik sözleşmesini madde madde ayrıştırıp, bankanın **playbook**'una ve
> yürürlükteki mevzuata karşı denetleyen; riskli maddeleri gerekçesi ve metinden alıntısıyla
> işaretleyen, eksik maddeleri listeleyen ve **banka lehine alternatif madde metni** öneren
> karar-destek uygulaması.

## 3. Uygulamanın Cevapladığı 4 Soru
1. **Bu sözleşmede bankayı zora sokacak madde var mı?** → Riskli madde tespiti + skor
2. **Bu maddelerin gereklilikleri neler?** → Mevzuat/iç politika dayanağı, zorunlu-önerilen ayrımı
3. **Neyi unutmuşuz?** → Eksik (olması gereken ama yazılmamış) madde tespiti
4. **Nasıl düzeltilir?** → Banka lehine alternatif metin (redline) + müzakere argümanı

## 4. Kullanıcılar (Persona) ve Ana İhtiyaçları
| Persona | İhtiyaç | Uygulamadaki karşılığı |
|---|---|---|
| Satın Alma uzmanı | Hızlı ön eleme, "imzaya hazır mı?" | Risk skoru, trafik ışığı özeti |
| Hukuk müşaviri | Madde bazlı derin inceleme, alternatif metin | Madde görüntüleyici + redline üretimi |
| Uyum / Mevzuat | BDDK–KVKK gereklerinin sözleşmede karşılanması | Uyum kontrol listesi, eksik madde raporu |
| Bilgi Güvenliği | Veri lokasyonu, denetim hakkı, ihlal bildirimi, alt yüklenici | Güvenlik maddeleri kümesi |
| Yönetici / İmza yetkilisi | 1 sayfalık özet, kalan açık riskler | Yönetici özeti (PDF) |
| Playbook sahibi (Hukuk) | Kurumsal standardı sürdürmek | Playbook yönetim ekranı, geri besleme döngüsü |

## 5. Kapsam (v1'de VAR)
- Türkçe ve İngilizce metin tabanlı sözleşmeler (PDF, DOCX); taranmış PDF için OCR.
- Sözleşme türleri: yazılım lisans/bakım, SaaS/bulut, donanım tedarik, danışmanlık/hizmet,
  dış kaynak (destek hizmeti), çerçeve sözleşme + sipariş formu (SoW).
- Madde ayrıştırma (Madde/fıkra/bent hiyerarşisi), madde tipi sınıflandırma.
- Playbook'a göre sapma tespiti: **zayıf madde**, **riskli madde**, **eksik madde**.
- Risk skorlaması ve önceliklendirme.
- Alternatif madde metni önerisi + gerekçe + müzakere argümanı.
- İnceleme akışı: bulguyu kabul et / reddet / not düş; sürüm karşılaştırma (v1 vs v2 diff).
- Çıktılar: DOCX redline, PDF yönetici özeti, XLSX bulgu listesi.
- Tam denetim izi (kim, ne zaman, neyi gördü/değiştirdi).

## 6. Kapsam Dışı (v1'de YOK — bilinçli sınır)
- **Hukuki mütalaa yerine geçmez.** Çıktı karar-destek verisidir; her ekranda uyarı görünür.
- Otomatik imza, e-imza/KEP entegrasyonu, onay-akışı (mevcut BPM/DYS'ye devredilir).
- Tedarikçiyle otomatik yazışma / e-posta gönderimi.
- Sözleşme yaşam döngüsü yönetimi (yenileme takvimi, fatura eşleştirme) — v2 konusu.
- İhale/RFP değerlendirme, tedarikçi risk skorlaması (finansal).
- Mevzuatın otomatik/canlı takibi; mevzuat korpusu **elle sürümlenerek** güncellenir.
- Sözleşme dışı ekler (fiyat listesi, teknik şartname) derin analizi — sadece referanslanır.

## 7. Başarı Kriterleri (ölçülebilir)
| Metrik | Hedef (v1 sonu) |
|---|---|
| Madde segmentasyon doğruluğu (altın set) | ≥ %95 madde sınırı doğru |
| Madde tipi sınıflandırma F1 | ≥ 0.85 (ilk 30 madde tipinde) |
| Kritik riskli madde yakalama (recall) | ≥ %90 |
| Eksik madde tespiti recall | ≥ %95 (deterministik kontrol listesi olduğu için yüksek) |
| Halüsinasyon (metinde olmayan alıntı) | %0 — doğrulama katmanı zorunlu |
| Yanlış pozitif oranı (hukukçu "alakasız" dedi) | ≤ %20 |
| Tek sözleşme analiz süresi (40 sayfa) | ≤ 4 dakika |
| Hukukçu ön inceleme süresi kazancı | ≥ %40 |

## 8. Temel Tasarım İlkeleri
1. **Her bulgu metne bağlıdır.** Model bir iddia üretiyorsa, sözleşme metninden birebir alıntı
   vermek zorundadır; alıntı deterministik olarak metinde aranır, bulunmazsa bulgu düşürülür.
2. **Kural katmanı analist değil, dikkat yönetmenidir.** *(08 ile revize edildi — AI-first)*
   Kurallar modelin yerine karar vermez; modelin **nereye bakacağını** belirler: hangi playbook
   kuralının hangi maddeye zerk edileceğini, hangi maddeye ne kadar düşünme bütçesi
   harcanacağını ve çıktının kanıtının doğrulanmasını kurallar yönetir. Yargı modelindir.
   Ayrıntı: [08 — Dikkat Yönlendirme Mimarisi](08-dikkat-yonlendirme-mimarisi.md).
3. **Playbook kod değil veridir.** Yeni bir kırmızı çizgi eklemek için deploy gerekmez.
4. **Model değiştirilebilir olmalı.** Tüm LLM çağrıları tek bir arayüzün arkasındadır;
   bugün Claude API, yarın lokal model (vLLM/Ollama) — prompt ve şema değişmez.
5. **İnsan son merci.** Hiçbir bulgu otomatik "kapanmaz"; kullanıcı kabul/ret verir, bu veri
   playbook'u iyileştirmek için geri beslenir.
