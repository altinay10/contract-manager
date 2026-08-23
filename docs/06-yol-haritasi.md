# 06 — Yol Haritası: Fazlar, Sprintler, Tamamlanma Kriterleri

Tahminler **tek geliştirici + agent desteği** varsayımına göredir. Ekip büyürse Faz 3–5 paralelleşir.

> **AI-first sıralama notu.** Bu projede riskin çoğu altyapıda değil, **modelin dikkatini
> doğru yere düşürebilmekte**. Bu yüzden sıralama klasik "önce uygulama, sonra AI" değildir:
> Faz 0.5'te, hiç UI olmadan, bir betikle 5 sözleşme üzerinde dikkat kaldıraçları kalibre
> edilir. Prompt mimarisi tutmuyorsa güzel bir arayüz bunu kurtarmaz — tersi mümkündür.

---

## Gerçekleşme Durumu (23.08.2026)

Çalışan bir sistem kuruldu. Aşağıdaki tablo planın neresinde olduğumuzu gösterir.

| Faz | Durum | Not |
|---|---|---|
| Faz 0 — Temel iskelet | ✅ | FastAPI + SQLAlchemy + SQLite (Postgres'e `DATABASE_URL` ile geçilir); Celery yerine işlem içi kuyruk |
| Faz 0.5 — Prompt laboratuvarı | ⏳ | Prompt mimarisi kodda hazır (K2/K3/K4/K6/K7), **ablasyon koşusu API anahtarı gerektiriyor** |
| Faz 1 — Belge anlama | ✅ | PDF/DOCX/TXT, normalizasyon, madde ayrıştırma. **OCR yok** |
| Faz 2 — Playbook & sınıflandırma | 🟡 | 27/42 madde tipi yazıldı; sınıflandırma anahtar kelime tabanlı, embedding yok |
| Faz 3 — Risk analizi & doğrulama | ✅ | Dikkat kaldıraçları, grounding, skorlama, veto kuralı |
| Faz 4 — Öneri & rapor | 🟡 | DOCX **rapor** üretiliyor; değişiklik izlemeli redline henüz yok |
| Faz 5 — İnceleme akışı | ❌ | Bilinçli olarak ertelendi: ana akış tam otomatik (bkz. 09 §1) |
| Faz 6 — Eval & sertleştirme | 🟡 | 27 birim + failsafe testi var; altın set ve ablasyon raporu yok |
| Faz 7 — Lokal model | ❌ | Soyutlama katmanı hazır, sağlayıcı eklenmedi |

**Plana eklenen, planda olmayan iş:** dayanıklılık katmanı (checkpoint, resume, orphan
kurtarma, ölümcül hata ayrımı). Bu, "kullanıcı manuel işlem yapmayacak" kararının
doğrudan sonucudur ve [docs/09](09-uygulama-ve-dayaniklilik.md)'da anlatılır.

---

## Faz 0 — Temel İskelet  (≈1 hafta)
**Hedef:** Boş ama çalışan bir sistem; dosya yükleniyor, metin çıkıyor.

| # | Görev | Çıktı |
|---|---|---|
| 0.1 | Repo, `docker-compose` (Postgres+pgvector, Redis, MinIO), Makefile | `make up` çalışıyor |
| 0.2 | FastAPI iskeleti, sağlık ucu, yapılandırılmış log, config (12-factor) | `/health` 200 |
| 0.3 | Alembic + ilk migration: `users, contracts, documents, document_texts` | migration çalışıyor |
| 0.4 | Basit kimlik (geliştirmede token, üretimde OIDC yer tutucu) + RBAC iskeleti | rol kontrolü çalışıyor |
| 0.5 | Yükleme ucu + MinIO'ya yazma + SHA-256 + tip doğrulama | dosya yüklenip geri okunuyor |
| 0.6 | Celery worker + örnek görev + SSE ilerleme kanalı | uzun görev takip edilebiliyor |

**DoD:** DOCX/PDF yükleniyor, kuyruk çalışıyor, testler CI'da geçiyor.

---

## Faz 0.5 — Prompt Laboratuvarı (≈1 hafta, UI YOK)  ★ AI-first çekirdek
**Hedef:** Dikkat mimarisinin (08) işe yaradığını, uygulama yazmadan önce kanıtlamak.

| # | Görev | Çıktı |
|---|---|---|
| 0.5.1 | 5 gerçek sözleşme + hukukçunun elle işaretlediği beklenen bulgular | Mini altın set |
| 0.5.2 | Tek dosyalık betik: sözleşme → Claude API → bulgu JSON'u | `lab/run.py` |
| 0.5.3 | 3 madde tipi için playbook kaydı (sorumluluk, denetim, veri lokasyonu) | Şema doğrulanmış |
| 0.5.4 | K3 (bakış açısı) + K2 (hipotez zerki) prompt'ları | `prompts/risk_analyst/v1..v4` |
| 0.5.5 | **Ablasyon koşusu**: yalın prompt → +K3 → +K2 → +K7, metrik tablosu | `lab/ablation.md` |
| 0.5.6 | Prompt caching kurulumu + `cache_read_input_tokens` doğrulaması | Maliyet ölçümü |
| 0.5.7 | Gerçek maliyet/sözleşme ölçümü (08 §5 tahminini yerine koy) | Bütçe kararı |

**DoD:** 5 sözleşmede kritik bulgu recall'ı yalın prompt'a göre **ölçülebilir biçimde**
yükseldi; sözleşme başı maliyet biliniyor; önbellek okuması çalışıyor.
**Bu faz başarısızsa mimari revize edilir — uygulama kodu yazılmaz.**

---

## Faz 1 — Belge Anlama  (≈1,5 hafta)
**Hedef:** Sözleşme, madde ağacına dönüşüyor ve ekranda gösteriliyor.

| # | Görev | Notlar |
|---|---|---|
| 1.1 | DOCX metin+stil çıkarımı (python-docx) | Başlık stilleri madde tespitini kolaylaştırır |
| 1.2 | PDF metin+koordinat çıkarımı (PyMuPDF), sayfa offset haritası | Vurgulama için şart |
| 1.3 | OCR yolu (Tesseract tur+eng) + kalite skoru | Eşik altı → kullanıcı uyarısı |
| 1.4 | Normalizasyon: tireleme, satır birleştirme, üst/alt bilgi temizliği, Türkçe karakter | Altın metin üretimi |
| 1.5 | **Madde segmentasyonu**: "MADDE 7", "7.", "7.2", "7.2.a", "Article 7", romen rakamı, EK-1 | En kritik bileşen; regex + heuristik + doğrulama |
| 1.6 | Tanımlar bölümü ve ekler listesi tespiti | Bağlam zenginleştirme |
| 1.7 | `clauses` tablosuna yazma + ağaç API'si | |
| 1.8 | Frontend: belge görüntüleyici, madde ağacı, metin arama | E4'ün sol paneli |
| 1.9 | Manuel madde düzeltme aracı (birleştir/böl) | Kötü PDF kurtarma |

**DoD:** Altın setteki 20 sözleşmede madde sınırı doğruluğu ≥ %90.

---

## Faz 2 — Playbook ve Sınıflandırma  (≈2 hafta)
**Hedef:** Her madde "ne maddesi" olduğunu biliyor; eksikler çıkıyor.

| # | Görev | Notlar |
|---|---|---|
| 2.1 | Playbook YAML şeması + doğrulayıcı + seed yükleyici | 01 no'lu dokümandaki 42 madde |
| 2.2 | **İlk 32 madde tipinin playbook içeriğini yazma** (Hukuk ile birlikte) | Projenin en değerli, en emek isteyen işi |
| 2.3 | `clause_types` CRUD + sürümleme + Playbook ekranı (E7) | |
| 2.4 | Embedding üretimi (madde + playbook ideal metin) → pgvector | |
| 2.5 | Hibrit sınıflandırıcı: kural skoru + top-k benzerlik + LLM teyidi | Aday liste ile kısıtlı |
| 2.6 | **Eksik madde motoru** (deterministik küme farkı + hedefli ikinci arama) | E5 ekranını besler |
| 2.7 | Meta çıkarımı: taraflar, bedel, süre, yenileme, damga vergisi yükümlüsü | Regex + LLM doğrulama |

**DoD:** Sınıflandırma F1 ≥ 0.80; eksik madde recall ≥ 0.90.

---

## Faz 3 — Risk Analizi ve Doğrulama  (≈2 hafta)
**Hedef:** Gerçek bulgular üretiliyor ve hiçbiri uydurma değil.

| # | Görev | Notlar |
|---|---|---|
| 3.1 | LLM soyutlama katmanı + prompt kayıt/sürümleme altyapısı | Lokal geçişin temeli |
| 3.2 | `RiskAnalyst`: iki geçişli plan (Geçiş A harita + Geçiş B madde) | 08 §2 |
| 3.2b | **K2 hipotez zerki** — playbook `red_lines` kontrol listesi zorunlu cevap | En yüksek getirili kaldıraç |
| 3.2c | **K4 çoklu mercek** — kritik madde tiplerinde 3-5 bakış açısı, birleştirme | 08 §1 |
| 3.2d | **K5 yokluğa dikkat** — eksik madde için tam metin doğrulayıcı geçiş | Kural + model birlikte |
| 3.2e | **K6 effort yönlendirme** — madde ağırlığına göre model/effort seçimi | Maliyet/kalite |
| 3.2f | **K7 karşı-görüş** — kritik bulguların çürütme geçişi | Yanlış pozitif düşürür |
| 3.2g | Prompt caching prefix düzeni + önbellek kırılma alarmı | 08 §3 |
| 3.3 | Deterministik hedefleyiciler: belirsiz ifade sözlüğü, iç çelişki, çapraz atıf, tek taraflılık — **bulgu üretmekten çok modele hedef göstermek için** | Ucuz ve isabetli |
| 3.4 | **Verifier katmanı** (alıntı doğrulama, enum dayanak, şema, mükerrer birleştirme) | Grounding ihlali = 0 hedefi |
| 3.5 | Skorlama motoru + bağlam çarpanları + veto kuralı | 01 §5 |
| 3.6 | `llm_calls` maliyet/token takibi + bütçe koruması | |
| 3.7 | Risk Özeti ekranı (E3) + Madde İnceleyici bulgu paneli (E4 sağ) | |

**DoD:** Altın sette kritik bulgu recall ≥ 0.85, grounding ihlali 0.

---

## Faz 4 — Öneri ve Redline  (≈1,5 hafta)
**Hedef:** "Nasıl düzeltilir" sorusunun cevabı belgeye dönüşüyor.

| # | Görev |
|---|---|
| 4.1 | `RedlineDrafter` prompt: sözleşmenin diline/numaralamasına uyumlu alternatif metin |
| 4.2 | Fallback (geri çekilme) metni + müzakere argümanı üretimi |
| 4.3 | Öneri düzenleme/kabul akışı, `recommendations` tablosu |
| 4.4 | **DOCX tracked-changes üretimi** (`w:ins`/`w:del` + yorum balonları) |
| 4.5 | Eksik maddelerin doğru yere eklenmesi (numaralandırma kaydırma) |
| 4.6 | PDF yönetici özeti + XLSX bulgu listesi |

**DoD:** Word'de açılan çıktıda değişiklikler kabul/ret edilebiliyor; hukukçu 5 sözleşmede onaylıyor.

---

## Faz 5 — İnceleme Akışı, Sürüm ve Portföy  (≈1,5 hafta)
| # | Görev |
|---|---|
| 5.1 | Bulgu durum makinesi, ret gerekçesi toplama, yorumlar |
| 5.2 | Yeni sürüm yükleme + madde bazlı diff + "bulgu kapandı mı?" eşleştirmesi |
| 5.3 | Portföy panosu, filtreler, arama |
| 5.4 | Bildirimler (e-posta/Teams: analiz bitti, kritik bulgu atandı) |
| 5.5 | Denetim izi ekranı, saklama/imha görevleri |

**DoD:** İki turlu bir müzakere baştan sona uygulama üzerinden yürütülebiliyor.

---

## Faz 6 — Kalite, Eval ve Sertleştirme  (≈2 hafta)
| # | Görev |
|---|---|
| 6.1 | Altın set toplama + anonimleştirme aracı + `expected_findings` işaretleme arayüzü |
| 6.2 | Eval koşucusu, metrik raporu, CI entegrasyonu |
| 6.3 | Kalibrasyon: yanlış pozitif analizi → playbook/prompt iyileştirme turu |
| 6.4 | Güvenlik sertleştirme: yetki testleri, sızma testi bulguları, maskeleme katmanı |
| 6.5 | Performans: paralellik, önbellek, 100+ sayfa sözleşme testi |
| 6.6 | Pilot: 2 birim, 20 gerçek sözleşme, geri bildirim |

**DoD:** 05 §3'teki tüm eşikler geçiliyor; pilot kullanıcı memnuniyeti ölçüldü.

---

## Faz 7 — Lokal Model Geçişi  (≈1,5 hafta, sonraya bırakılabilir)
| # | Görev |
|---|---|
| 7.1 | vLLM/Ollama sağlayıcı uygulaması, aynı arayüz |
| 7.2 | Aday model kıyaslaması **aynı eval seti üzerinde** (kalite/hız/donanım) |
| 7.3 | Lokal embedding modeli (Türkçe destekli) + vektörlerin yeniden üretimi |
| 7.4 | Gerekirse LoRA ince ayar için veri hazırlığı (kabul/ret geri bildirimlerinden) |
| 7.5 | Gizlilik: maskeleme katmanı kaldırılabilir; harici çağrı sıfırlanır |

**DoD:** Lokal modelle metrik kaybı ≤ %10; harici API çağrısı yok.

---

## Toplam
**≈ 12–14 hafta** (Faz 0–6, Faz 0.5 dâhil) + Faz 7 opsiyonel.
Kritik yol: **Faz 0.5 (dikkat kalibrasyonu)**, **Faz 1 (segmentasyon)** ve
**Faz 2.2 (playbook içeriği)**. Playbook yazımı teknik değil hukuki emektir; Faz 0'da
başlatılıp paralel yürütülmelidir — Faz 0.5 zaten 3 kaydına ihtiyaç duyar.

## MVP Tanımı (en erken gösterilebilir değer — ≈4-5 hafta)
Faz 0 + **Faz 0.5** + Faz 1 + Faz 2 (10 madde tipiyle) + Faz 3'ün 3.2/3.2b/3.4/3.7 adımları:
> Sözleşme yükle → 10 kritik madde için riskli/eksik bulgu listesi + alıntı + gerekçe.
Öneri metni ve redline olmadan da bu, elde yapılan işin büyük kısmını kısaltır ve
kuruma göstermek için yeterlidir.
