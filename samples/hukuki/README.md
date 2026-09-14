# Hukuki test seti

Sözleşme Feneri'ni denemek için hazırlanmış sekiz sözleşme: üçü **v1/v2 çifti**
(tedarikçi revizyonu senaryosu), ikisi tekil. Hepsi banka tedarik bağlamında ve
Türk sözleşme diliyle yazılmıştır.

Metinler `docs/01-madde-taksonomisi-ve-playbook.md`'deki 32 madde tipine ve
gerçek belgelerin diline göre kurgulandı. Dil ve yapı için incelenen kaynaklar
bu dosyanın sonundadır.

| Dosya | Ne sınar |
|---|---|
| `01-cekirdek-bankacilik-saas-v1/v2` | Ağır revizyon: madde silme, madde ekleme, **numara kayması** |
| `02-veri-merkezi-dis-hizmet-v1/v2` | KİK tip sözleşme dili, alt madde (`9.1.1`) farkları, numarası aynı ama içeriği değişmiş madde |
| `03-yazilim-gelistirme-bakim-v1/v2` | **İnce** revizyon: tek kelimelik anlam çevirmeleri, istisna enjeksiyonu, madde yer değiştirmesi |
| `04-cagri-merkezi-riskli` | Kırmızı bayrak yoğun, zorunlu maddeleri eksik sözleşme — boşluk tespiti |
| `05-donanim-alim-bakim-dengeli` | Ağır Osmanlıca-hukuk dili, banka lehine ve eksiksiz — yanlış pozitif ölçümü |

`.pdf` uzantılı kopyalar (01-v1, 02-v1, 05) PDF çıkarma hattını sınamak içindir;
aynı metnin PDF hâlidir.

---

## Karşılaştırmayı nasıl koşarsınız

Karşılaştırma motoru (`compare.py`, `compare_explain.py`) ve `Comparison` veri
modeli hazır; **arayüz ve API ucu henüz bağlı değil** (`/api/contracts` tek dosya
alıyor, `/api/comparisons` yok). Bu yüzden farkı şimdilik doğrudan hattan alın:

```bash
.venv/bin/python samples/hukuki/karsilastir.py \
  samples/hukuki/03-yazilim-gelistirme-bakim-v1.txt \
  samples/hukuki/03-yazilim-gelistirme-bakim-v2.txt
```

Tekil analiz için dosyaları arayüze bırakmanız yeterli.

---

## 01 — Çekirdek bankacılık SaaS (v1 → v2)

BANKA'nın taslağı v1; tedarikçinin geri gönderdiği hâli v2. Madde silinip
eklendiği için **numaralar kayar** — motorun en zorlandığı senaryo.

| # | Madde | v1 | v2 |
|---|---|---|---|
| 1 | Sorumluluk tavanı | Son 12 ayın 2 katı | Son 3 ayın bedeli + dolaylı zarar muafiyeti |
| 2 | Tavan istisnaları | Gizlilik, müşteri sırrı, KVKK, FMH | Yalnız kasıt/ağır kusur |
| 3 | Veri lokasyonu | Münhasıran yurt içi | Tedarikçinin seçtiği veri merkezleri |
| 4 | İhlal bildirimi | En geç 24 saat | "Gecikmeksizin, makul süre" |
| 5 | Sızma testi | Banka'nın hakkı | Yasak |
| 6 | **Denetim maddesi (M14)** | Var (BDDK dâhil) | **Tamamen silinmiş** |
| 7 | Ücret güncellemesi | Yok (bedel sabit) | **Yeni madde:** tek taraflı Yİ-ÜFE+10 puan |
| 8 | Referans kullanımı | Yok | **Yeni madde:** onaysız logo/vaka kullanımı |
| 9 | Alt yüklenici | Önceden yazılı onay | Bildirim yeterli |
| 10 | Ödeme vadesi | 30 gün | 45 gün + %5 temerrüt faizi + askıya alma |
| 11 | Damga vergisi | Eşit paylaşım | Tamamı Banka'da |
| 12 | SLA | %99,5 | %99,9 (**alıcı lehine** — tek tatlandırıcı) |
| 13 | SLA cezası | %10, tavan %50 | %2, tavan %15, "yegâne başvuru yolu" |
| 14 | Sebepsiz fesih | Banka'da (60 gün) | Tedarikçide (30 gün) |
| 15 | FMH devri | Özelleştirmeler Banka'ya | Tedarikçide kalır |
| 16 | Gizlilik süresi | Süresiz / 5 yıl | 2 yıl |
| 17 | Hukuk ve yetki | Türk hukuku, İstanbul | İsviçre hukuku, ICC tahkim/Cenevre |
| 18 | Çıkış desteği | 6 ay, açık format, hapis hakkı yasak | 30 gün, tedarikçi formatı, yasak kaldırılmış |
| 19 | Destek hizmeti kuruluşu beyanı (4.3) | Var | Silinmiş |
| 20 | Mücbir sebep (M18) | Ortada | Metin aynı, **sona taşınmış (M25)** |
| 21 | Madde başlığı M10 | "GİZLİLİK" | "GİZLİLİK VE SIR SAKLAMA" (biçimsel) |

## 02 — Veri merkezi dış hizmet (v1 → v2)

KİK tip sözleşme kalıbı (`Madde 1- Sözleşmenin tarafları`). Numaralar
kaymaz; fark alt maddelerdedir.

| # | Madde | v1 | v2 |
|---|---|---|---|
| 1 | Sözleşme dili (3.1) | Türkçe | Türkçe + İngilizce, **çelişkide İngilizce** |
| 2 | Destek hizmeti kuruluşu (5.2) | BDDK yetkileri kabul | "Bağımsız hizmet sağlayıcı" |
| 3 | Kesin teminat (8.2.1) | %6 | %3 |
| 4 | SLA cezası (9.1.1) | ‰2 | ‰0,5 |
| 5 | Ceza tavanı (9.2) | %30 | %8 |
| 6 | Muafiyet (9.1.3) | Yok | **Yeni alt madde:** planlı bakım/üçüncü taraf hariç |
| 7 | Gizlilik (10.1) | Süresiz | Sözleşme + 2 yıl |
| 8 | Veri lokasyonu (11.3) | Münhasıran yurt içi | TR + AB + "yeterli koruma" ülkeleri |
| 9 | Erişim kaydı (11.4) | 10 yıl | 1 yıl |
| 10 | İhlal bildirimi (12.2) | 24 saat, kök neden 5 iş günü | 72 saat, kök neden yok |
| 11 | RTO / RPO (13.1) | 2 saat / 5 dakika | 8 saat / 4 saat |
| 12 | Denetim (14.1–14.2) | Yerinde + BDDK, 10 iş günü, ihlalde bildirimsiz | Rapor incelemesi, 30 gün, yılda 1 |
| 13 | Tazmin tavanı (15.2) | Bedelin 2 katı | Bedelin %25'i |
| 14 | **Kaynak kod emaneti (M17)** | Var | **Silinmiş — aynı numaraya "Hizmetin askıya alınması" gelmiş** |
| 15 | Hapis hakkı yasağı (18.3) | Var | Silinmiş |
| 16 | Erken fesih (20.3) | Banka tazminatsız | Kalan bedelin %60'ı tazminat |
| 17 | Yetkili mahkeme | İstanbul | Kocaeli |

> 14 numaralı satır özellikle şunu sınar: **numara aynı, metin bambaşka.**
> Doğru davranış tek "değişti" kartı değil, ayrı "silindi" + "eklendi"dir.

## 03 — Yazılım geliştirme ve bakım (v1 → v2)

En sinsi çift. Numaralar sabit, 41 madde aynı; 21 maddede çoğu **tek kelimelik**
ama sonucu tersine çeviren düzeltmeler var.

| # | Madde | v1 → v2 |
|---|---|---|
| 1 | 2.4 | "anlamına **gelmez**" → "anlamına **gelir**" (zımni kabul doğar) |
| 2 | 11.1 | "yılda **en az iki**" → "yılda **en çok bir**" denetim |
| 3 | 3.4 | Ek ücret yasağına istisna cümlesi eklenmiş |
| 4 | 4.1 | "mali hakların **tamamı**" → "**çoğaltma ve yayma hakları**"; "münhasıran" silinmiş |
| 5 | 4.3 | "başka projelerde kullanamaz" ibaresi silinmiş |
| 6 | 8.3 | Gerçek müşteri verisiyle test: yasak → onaylı serbest |
| 7 | 9.3 | Tavan istisnalarından KVKK ve FMH çıkarılmış |
| 8 | 10.2 | Yurt dışı aktarım yasağı → bildirimle serbest |
| 9 | 10.3 | 24 saat → "makul süre" |
| 10 | 2.2 / 5.2 / 6.1.1 / 6.2 / 9.2 / 12.1 | 20→10 iş günü · 24→12 ay garanti · 1→4 saat müdahale · %99,9→%99,0 · 1 kat→%50 tavan · ‰1→‰0,1 ceza |
| 11 | 7.1 | Anahtar personel: onay → bildirim |
| 12 | 13.3 | Banka'nın sebepsiz fesih hakkı **silinmiş** |
| 13 | 14 ↔ 15 | Mücbir sebep ve uyuşmazlık maddeleri **yer değiştirmiş** (metin birebir aynı) |
| 14 | 1.2 / M8 başlığı | Virgül → noktalı virgül, başlık genişletme — **biçimsel**, gürültü sayılmalı |

## 04 — Çağrı merkezi (tekil, riskli)

Tek dosya; karşılaştırma değil **boşluk ve kırmızı bayrak** tespiti içindir.
Kasıtlı olarak eksik bırakılan zorunlu maddeler: denetim hakkı, veri lokasyonu,
ihlal bildirim süresi, KVKK veri işleme eki, iş sürekliliği/RTO-RPO, çıkış ve
veri iade planı, kaynak kod emaneti, alt yüklenici onayı, mevzuat değişikliği
uyarlaması, sigorta.

Barındırdığı kırmızı bayraklar: sorumluluk tavanı tek aylık bedelle ve
**istisnasız** sınırlı · gizlilik 1 yıl · tek taraflı yılda iki kez fiyat artışı
· alt yüklenici tamamen serbest ve tedarikçi sorumsuz · 5 yıllık kendiliğinden
yenileme · tedarikçi 30 günde sebepsiz fesih, banka ancak 180 günde · verinin
model eğitiminde süresiz kullanımı · tek taraflı sözleşme değişikliği · İrlanda
hukuku ve Dublin münhasır yetki · damga vergisi tamamen bankada.

## 05 — Donanım alım ve bakım (tekil, dengeli)

Ağır hukuk diliyle (`münderecat`, `bilâbedel`, `mahfuzdur`, `tahaddüs`,
`gayrimahdut`) yazılmış, banka lehine ve taksonomideki zorunlu maddeleri
karşılayan bir sözleşme. İki işi görür: motorun eski hukuk dilini okuyup
okuyamadığını, ve **temiz bir sözleşmede kaç yanlış bulgu** ürettiğini gösterir.
Buradan çıkan yüksek riskli bulgular yanlış pozitiftir.

---

## İncelenen gerçek belgeler

Dil, madde sırası ve kalıplar şu kamuya açık belgelerden çalışıldı:

- KİK **EK-7 Hizmet Alımlarına Ait Tip Sözleşme** — 39 maddelik resmî kalıp.
  İki tarihli sürümü mevcut ve aradaki değişiklikler metnin içinde
  `(Değişik: …-R.G./… md.)` şeklinde işaretli: gerçek bir v1/v2 çifti.
  - 2016 baskısı: <https://www.hakedis.org/wp-content/uploads/2016/10/Ek-7-Hizmet-Tip-S%C3%B6zle%C5%9Fme.pdf>
  - 30.09.2020 baskısı: <https://hakedis.org/wp-content/uploads/2017/07/Hizmet-alimlarina-ait-Tip-Sozlesme-20200930.pdf>
- Doldurulmuş örnek (T.C. Güney Ege Kalkınma Ajansı):
  <https://geka.gov.tr/uploads/tenders_v/sozlesme-tasarisi.pdf>
- Garanti BBVA **Bankacılık Hizmetleri Sözleşmesi** — aynı sözleşmenin yıllara
  göre yayımlanmış sürümleri (2020 baskısı 25 sayfa/12 bölüm, 2025 baskısı
  18 sayfa; 2024 ile 2025 arasında yalnız filigran farkı var).
  - <https://www.garantibbva.com.tr/content/dam/public-website/pdf/sozlesmeler/tr/2020/bankacilik-hizmet-sozlesmesi-25-08-2020.pdf>
  - <https://www.garantibbva.com.tr/content/dam/public-website/pdf/sozlesmeler/tr/2025/bankacilik-hizmetleri-sozlesmesi.pdf>
- DenizBank Temel Bankacılık Hizmet Sözleşmesi:
  <https://www.denizbank.com/sozlesme-ve-formlar/_pdf/temel-bankacilik-hizmet-sozlesmesi-vs8.pdf>
- Albaraka Genel Kredi Sözleşmesi:
  <https://www.albaraka.com.tr/documents/hakkimizda/sozlesme-ve-formlar/sozlesmeler/BFS/genel-kredi-sozlesmesi.pdf>
- KVKK Standart Sözleşmeler (veri sorumlusundan veri işleyene):
  <https://www.kvkk.gov.tr/Icerik/7929/Standart-Sozlesmeler>
- BDDK Bankaların Destek Hizmeti Almalarına İlişkin Yönetmelik:
  <https://www.bddk.org.tr/Mevzuat/Liste/50>

Buradaki sözleşmeler bu belgelerden kopyalanmadı; dil ve yapı örnek alınıp
test için sıfırdan yazıldı. Kurum ve kişi adları uydurmadır.
