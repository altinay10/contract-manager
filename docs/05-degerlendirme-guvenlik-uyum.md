# 05 — Değerlendirme (Eval), Güvenlik, Uyum ve Risk Yönetimi

## 1. Neden Eval Zorunlu
Bu uygulamanın çıktısı bir hukukçunun kararını etkiler. "İyi görünüyor" yeterli değil.
Prompt veya model her değiştiğinde **ölçülebilir** bir regresyon testi gerekir — ve bu,
ileride lokal modele geçerken kalite kaybını görebilmenin tek yoludur.

## 2. Altın Set (Gold Set)
- **50–80 gerçek sözleşme** (anonimleştirilmiş: taraf adları, tutarlar, kişi adları maskeli).
- Dağılım: yazılım lisans 15, SaaS/bulut 15, hizmet/danışmanlık 15, donanım 10, dış kaynak 10,
  çerçeve+SoW 5. Ayrıca 5 adet **taranmış/kötü kaliteli** PDF (OCR testi).
- Her sözleşme için hukukçu tarafından işaretlenmiş **beklenen bulgular** (`expected_findings.json`):
  madde no, kod, tip, şiddet. "Bulunmaması gerekenler" de listelenir (yanlış pozitif testi).
- Ayrıca **sentetik tuzak sözleşmeler**: bilinçli olarak 20 kırmızı çizgi içeren, iç çelişkili,
  eke atıf yapıp eki olmayan bir metin — kenar durum testi.

## 3. Metrikler ve Eşikler
| Metrik | Tanım | Geçme eşiği |
|---|---|---|
| Segment doğruluğu | Doğru madde sınırı / toplam madde | ≥ 0.95 |
| Sınıflandırma F1 (makro) | Madde tipi | ≥ 0.85 |
| Kritik bulgu recall | Beklenen KRITIK/YUKSEK bulguların yakalanması | ≥ 0.90 |
| Precision (tüm bulgular) | Hukukçunun "geçerli" dediği oran | ≥ 0.80 |
| Eksik madde recall | | ≥ 0.95 |
| Grounding ihlali | Alıntısı metinde bulunmayan bulgu oranı | = 0.00 |
| Uydurma dayanak | Playbook dışı `legal_basis` | = 0.00 |
| Şiddet uyumu | Beklenen ile ±1 seviye içinde | ≥ 0.85 |
| Öneri kabul oranı | Hukukçunun düzeltmeden kabul ettiği öneri metni | ≥ 0.50 (v1 için) |
| Maliyet | Sözleşme başına | Hedef takibi (lokal geçiş kıyası) |

Eval koşucusu: `make eval` → tüm altın seti işler, `reports/eval-<tarih>.html` üretir,
önceki koşuyla farkı gösterir. **CI'da her prompt/playbook değişikliğinde çalışır.**

## 3.5 Dikkat Kaldıraçlarının Ablasyonu
AI-first mimaride eval'in ikinci görevi, [08 §7](08-dikkat-yonlendirme-mimarisi.md)'deki
**ablasyon tablosunu** üretmektir: her dikkat kaldıracının (K1-K7) recall/precision'a katkısı
ve puan başına maliyeti. Bu tablo hangi kaldıracın üretimde açık kalacağına karar verir.

## 4. Model Kullanımına İlişkin Güvenceler
1. **Grounding zorunluluğu** (bkz. 02 §6) — halüsinasyonun ana panzehiri.
2. **Enum kısıtlı dayanak** — model kanun maddesi uyduramaz.
3. **Düşük sıcaklık + şema zorlaması** (structured output).
4. **İkinci görüş (Verifier)** kritik bulgularda: farklı prompt, "bu bulgu yerinde mi?"
5. **Belirsizlik itirafı:** model emin değilse `confidence < 0.6` → UI'da "kontrol edilmeli"
   etiketi; asla sessizce atılmaz.
6. **Prompt injection:** sözleşme metni veri bloğunda; sistem promptunda açık kural;
   ayrıca metinde şüpheli talimat kalıpları taranır ve kullanıcıya uyarı gösterilir.

## 5. Güvenlik (uygulama)
- Kimlik: OIDC/SSO, MFA kurumsal politikaya bağlı.
- Yetki: rol bazlı + **sözleşme bazlı erişim** (herkes her sözleşmeyi görmez).
- Depolama: belge deposunda sunucu tarafı şifreleme; DB'de hassas alanlar için şifreleme.
- Aktarım: TLS 1.2+; iç servisler arası mTLS (K8s aşamasında).
- Denetim izi: görüntüleme dâhil tüm işlemler; değiştirilemez (append-only) tablo.
- Belge indirmede filigran (kullanıcı adı + tarih) opsiyonu.
- Virüs taraması ve dosya tipi doğrulama (magic-byte), boyut limiti.
- Saklama süresi politikası: analiz çıktısı X yıl, ham belge Y yıl; otomatik imha görevi.

## 6. Uyum Notları (kurum içi onaylar için gerekli olacak)
- **Bulut/AI kullanımı — KARAR VERİLDİ:** Bu senaryoda **harici model API'si kullanılacaktır**
  ve sözleşme metninin banka dışına çıkması kabul edilmiştir. Dolayısıyla:
  - **Maskeleme katmanı kritik yoldan çıkarılmıştır.** Tam metin modele gönderilir — bu, dikkat
    mimarisinin (08) tam bağlam gerektiren Geçiş A ve çapraz atıf analizini mümkün kılar.
    Maskeleme kodu yine de **kapatılabilir bir özellik olarak** yazılır (`MASKING_ENABLED`),
    çünkü ileride farklı bir müşteri/birim için gerekebilir.
  - Tüm gönderilen ve alınan içerik `llm_calls` üzerinden loglanır (ne gitti, ne geldi,
    hangi prompt sürümü, kaç token, ne kadar maliyet).
  - Model sağlayıcıyla veri saklama/eğitim politikası yine de kayda geçirilir.
- **Lokal model geçişi** (06 §Faz 7) bu kararın *gereği* değil, **maliyet ve bağımsızlık**
  gerekçesiyle opsiyonel bir hedeftir. Faz 7'nin değeri, 08 §7'deki ablasyon tablosunun
  lokal model üzerinde yeniden koşulabilmesidir.
- **KVKK:** Uygulama içinde kişisel veri (kullanıcılar + sözleşmelerdeki imzacı bilgileri)
  işlenir; kayıt envanteri (VERBİS) ve aydınlatma metni güncellenmelidir.
- Uygulamanın kendisi bankanın **bilgi sistemleri envanterine** eklenmeli, kritiklik
  seviyesi belirlenmeli, sızma testinden geçmelidir.

## 7. Proje Riskleri ve Azaltımları
| Risk | Etki | Azaltım |
|---|---|---|
| Madde ayrıştırma bozuk (kötü PDF) | Tüm analiz çöker | OCR kalite skoru; eşik altında kullanıcıya "DOCX yükleyin" uyarısı; manuel madde düzeltme aracı |
| Yanlış pozitif bolluğu → güven kaybı | Kullanıcı uygulamayı bırakır | Şiddet eşiği ile filtre, ret gerekçesi toplama, playbook kalibrasyonu, ilk sürümde dar ama isabetli kapsam |
| Kaçırılan kritik madde | Gerçek zarar | "Uygulama tek başına yeterli değildir" ilkesi, kontrol listesi çıktısı, kritik sözleşmelerde çift kontrol politikası |
| Playbook sahipsiz kalır | Sistem eskir | Hukuk'ta atanmış sahip + çeyreklik gözden geçirme ritüeli |
| Mevzuat değişimi | Yanlış dayanak | Mevzuat korpusu sürümlü; değişiklikte etkilenen kural listesi otomatik çıkar |
| Maliyet kontrolsüz büyür | Bütçe | Sözleşme başına token bütçesi, madde başına tek çağrı, önbellekleme (aynı hash → aynı sonuç) |
| Kapsam kayması (CLM'e dönüşme) | Teslim edilemez | 00 §6 kapsam dışı listesi sözleşme gibi korunur |
