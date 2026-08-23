# 01 — Madde Taksonomisi, Risk Kataloğu ve Playbook Modeli

Bu doküman uygulamanın **bilgi çekirdeğidir**. Kod bunun etrafında yazılır.
Buradaki tablolar doğrudan `seed` verisine (JSON/YAML) dönüştürülecektir.

---

## 1. Playbook Kaydının Şeması
Her madde tipi için tek bir playbook kaydı tutulur:

```yaml
code: LIMITATION_OF_LIABILITY          # makine anahtarı
name_tr: "Sorumluluğun Sınırlandırılması"
category: TICARI_RISK                   # gruplama
obligation: ZORUNLU                     # ZORUNLU | ONERILEN | OPSIYONEL | YASAK
applies_to: [YAZILIM, SAAS, HIZMET, DONANIM]   # sözleşme tipi filtresi
trigger_conditions:                     # ne zaman devreye girer
  - contract_value_min: 0
  - involves_personal_data: any
weight: 5                               # 1-5, toplam skora katkı ağırlığı
ideal_text_tr: |
  Tedarikçinin sözleşmeden doğan toplam sorumluluğu ... Ancak gizlilik ihlali,
  kişisel verilerin korunmasına ilişkin yükümlülüklerin ihlali, fikri mülkiyet
  hakkı ihlali, kasıt ve ağır kusur hâllerinde sorumluluk sınırlaması uygulanmaz.
acceptable_variants:
  - "Sorumluluk tavanı yıllık sözleşme bedelinin en az 1 katı"
red_lines:                              # asla kabul edilmez
  - "Tavan aylık ücretle veya tek seferlik ücretle sınırlı"
  - "İstisnasız (kasıt/ağır kusur dâhil) sınırlama"
  - "Tedarikçi lehine tek taraflı sınırlama"
detection_hints:                        # sınıflandırıcı/regex ipuçları
  keywords_tr: ["sorumluluk", "tazminat tavanı", "sınırlandır", "dolaylı zarar"]
  keywords_en: ["limitation of liability", "aggregate liability", "consequential"]
legal_basis:                            # dayanak
  - "TBK m.115 (sorumsuzluk anlaşması - kasıt/ağır kusurda geçersiz)"
  - "Banka iç politika: SAT-POL-014"
negotiation_argument_tr: |
  Bankanın maruz kalacağı zarar (regülatif ceza, itibar, müşteri tazminatı) sözleşme
  bedeliyle orantılı değildir; veri ihlali kalemi tavandan istisna edilmelidir.
severity_if_missing: YUKSEK             # eksikse risk seviyesi
severity_if_weak: KRITIK
```

---

## 2. Risk Kategorileri (üst gruplar)
| Kod | Kategori | Odak |
|---|---|---|
| `REGULASYON` | Regülatif Uyum | BDDK, KVKK, MASAK, Bankacılık Kanunu |
| `VERI_GUVENLIK` | Veri ve Bilgi Güvenliği | Lokasyon, ihlal bildirimi, erişim |
| `TICARI_RISK` | Ticari / Mali Risk | Sorumluluk, fiyat, ödeme, ceza |
| `OPERASYONEL` | Operasyonel Süreklilik | SLA, iş sürekliliği, çıkış |
| `FIKRI_MULKIYET` | Fikri Mülkiyet & Lisans | Mülkiyet, escrow, kullanım hakkı |
| `SOZLESMESEL` | Sözleşmesel Denge | Fesih, yenileme, devir, hukuk seçimi |
| `VERGI_MALI` | Vergi ve Mali Yükümlülük | Damga vergisi, KDV, stopaj |
| `ETIK_ITIBAR` | Etik / İtibar | Rüşvet, yaptırım, referans kullanımı, ESG |

---

## 3. Kritik Madde Kataloğu — "Bankayı zora sokan" tipik durumlar
Aşağıdaki tablo, uygulamanın v1'de tespit etmesi gereken **çekirdek 32 madde tipidir**.
`Tipik tedarikçi metni` = kırmızı bayrak. `Banka lehine` = önerilecek yön.

### 3.1 Regülasyon ve Denetim
| # | Madde | Tipik tedarikçi metni (RİSK) | Banka lehine olması gereken |
|---|---|---|---|
| 1 | **Denetim hakkı** | Denetim yok ya da "yılda 1 kez, 30 gün önce yazılı bildirimle, mesai saatlerinde" | Bankanın, bağımsız denetçisinin **ve BDDK'nın** yerinde/uzaktan denetim hakkı; ihlal şüphesinde bildirimsiz; masraf tedarikçide |
| 2 | **Regülatöre erişim** | Hiç yok | Düzenleyici otoritenin bilgi/belge talebine tedarikçinin uyma taahhüdü |
| 3 | **Destek hizmeti statüsü** | Belirsiz | Tedarikçi "destek hizmeti kuruluşu" ise ilgili yönetmelik yükümlülükleri sözleşmeye işlenmeli (risk programı, süreklilik, gizlilik) |
| 4 | **Alt yüklenici** | "Tedarikçi dilediği alt yükleniciyi kullanabilir" | Bankanın **önceden yazılı onayı**; alt yüklenici fiillerinden tedarikçinin tam sorumluluğu; alt yüklenici listesi eki |
| 5 | **Mevzuat değişikliği** | Yok | Mevzuat değişirse sözleşmenin uyarlanması, tedarikçinin ek ücretsiz uyum taahhüdü, uyarlanamazsa bankaya cezasız fesih |

### 3.2 Veri ve Bilgi Güvenliği
| # | Madde | Tipik tedarikçi metni (RİSK) | Banka lehine olması gereken |
|---|---|---|---|
| 6 | **Veri lokasyonu** | "Veriler tedarikçinin global altyapısında işlenebilir" | Birincil ve ikincil sistemler ve veri **yurt içinde**; yurt dışı aktarım için bankanın yazılı onayı ve KVKK m.9 şartları |
| 7 | **KVKK veri işleyen** | Yok veya tek paragraf | Ayrı **Veri İşleme Eki**: işleme amacı/süresi, talimatla bağlılık, teknik-idari tedbirler, silme/iade, denetim, aydınlatma desteği |
| 8 | **İhlal bildirimi** | "Makul süre içinde" / "gecikmeksizin" | **En geç 24 saat** içinde bankaya bildirim (banka Kurul'a 72 saatte bildirmek zorunda olduğundan), kök neden raporu 5 iş günü |
| 9 | **Banka sırrı / müşteri sırrı** | Genel gizlilik maddesi | 5411 s.K. m.73 atfı; müşteri sırrının paylaşımı yasağı; ihlalde sınırsız sorumluluk |
| 10 | **Gizlilik süresi** | "Sözleşme süresince + 1 yıl" | Süresiz (banka/müşteri sırrı), diğer bilgiler için ≥ 5 yıl |
| 11 | **Güvenlik testi hakkı** | Yok / yasak | Bankanın sızma testi ve zafiyet taraması hakkı; bulguların SLA'lı kapatılması |
| 12 | **Veri ile model eğitimi** | Sessiz veya "hizmeti geliştirmek için kullanılabilir" | **Açık yasak**: banka verisi model eğitimi/analitik/anonim istatistik dâhil kullanılamaz |
| 13 | **Personel güvenliği** | Yok | Adli sicil/özgeçmiş kontrolü, gizlilik taahhütnamesi, çıkışta erişim iptali |

### 3.3 Ticari / Mali Risk
| # | Madde | Tipik tedarikçi metni (RİSK) | Banka lehine olması gereken |
|---|---|---|---|
| 14 | **Sorumluluk sınırı** | "Toplam sorumluluk son 3 ayda ödenen bedelle sınırlıdır; dolaylı zararlardan sorumlu değildir" | Tavan ≥ yıllık bedel; gizlilik/KVKK/FMH/kasıt/ağır kusur **tavandan istisna**; karşılıklı (mütekabil) sınırlama |
| 15 | **Tazminat (indemnity)** | Sadece banka tedarikçiyi tazmin ediyor | Tedarikçinin FMH ihlali, veri ihlali, üçüncü kişi taleplerinde bankayı tazmin taahhüdü |
| 16 | **Fiyat artışı** | "Tedarikçi ücretleri tek taraflı güncelleyebilir" | Yıllık en fazla 1 kez; TÜFE veya sözleşmede yazılı formülle sınırlı tavan; döviz kuru riski paylaşımı; bankaya artışı reddedip cezasız fesih hakkı |
| 17 | **Ödeme koşulları** | "Sipariş anında %100 peşin" | Kabul/teslim sonrası, kilometre taşına bağlı, vade ≥ 30 gün; hatalı işte ödemeyi askıya alma hakkı |
| 18 | **Cezai şart** | Sadece bankanın geç ödemesine faiz | Gecikme/eksik ifa için tedarikçiye cezai şart; ceza ödenmesi zararı aşan kısmı talep hakkını kaldırmaz |
| 19 | **Teminat / Sigorta** | Yok | Kesin teminat mektubu; mesleki sorumluluk ve siber sorumluluk sigortası poliçe zorunluluğu |
| 20 | **Damga vergisi** | "Damga vergisi Banka'ya aittir" | Yarı yarıya veya tedarikçiye; nüsha sayısını 1'e indirerek (veya nüshasız/e-imza) vergi yükünü azaltma notu |
| 21 | **Vergi ve stopaj** | "Tüm vergiler bankaya" / brüt-net belirsiz | Bedelin vergi hariç mi dâhil mi olduğu; yurt dışı ödemelerde stopaj/KDV2 sorumluluğu net |

### 3.4 Operasyonel Süreklilik
| # | Madde | Tipik tedarikçi metni (RİSK) | Banka lehine olması gereken |
|---|---|---|---|
| 22 | **SLA** | Yok veya "ticari makul çaba" | Ölçülebilir erişilebilirlik (%99,x), yanıt/çözüm süreleri, ölçüm yöntemi, raporlama; **hizmet kredisi tek çare (sole remedy) OLMAMALI** |
| 23 | **İş sürekliliği / OKM** | Yok | RTO/RPO taahhüdü, yedeklilik, yılda 1 test ve sonuç paylaşımı |
| 24 | **Kabul kriterleri** | "Teslimden 5 gün içinde itiraz edilmezse kabul edilmiş sayılır" | Yazılı kabul testi, test senaryoları, düzeltme hakkı, kabul edilmeden ödeme yok |
| 25 | **Garanti / bakım** | 3 ay garanti, sonra ücretli | ≥ 12–24 ay garanti; garanti sonrası bakım bedeli tavanı sözleşmede sabit |
| 26 | **Çıkış / geçiş desteği** | Yok | Fesih/sona ermede ≥ 6 ay geçiş desteği; verinin **makine-okunabilir standart formatta** iadesi; iade sonrası kalıcı silme ve imha sertifikası |
| 27 | **Değişiklik yönetimi** | Tedarikçi hizmeti tek taraflı değiştirebilir | Önemli değişiklikte önceden bildirim + bankanın onayı/fesih hakkı |

### 3.5 Fikri Mülkiyet
| # | Madde | Tipik tedarikçi metni (RİSK) | Banka lehine olması gereken |
|---|---|---|---|
| 28 | **Geliştirme mülkiyeti** | "Banka için yapılan tüm geliştirmeler tedarikçiye aittir" | Bankaya özel geliştirmelerin mülkiyeti/münhasır kullanım hakkı bankada; en azından süresiz-devredilebilir lisans |
| 29 | **Lisans kapsamı** | Kullanıcı/işlemci sayısı dar, grup şirketleri hariç | Banka + iştirakleri + dış hizmet aldığı taraflar; birleşme/devirde lisansın devamı |
| 30 | **Kaynak kodu emaneti (escrow)** | Yok | Escrow anlaşması; tedarikçinin iflası/desteği kesmesi/kritik ihlalinde kodun bankaya açılması |

### 3.6 Sözleşmesel Denge
| # | Madde | Tipik tedarikçi metni (RİSK) | Banka lehine olması gereken |
|---|---|---|---|
| 31 | **Fesih** | Tedarikçi 30 günde sebepsiz feshedebilir; banka feshedemez | Bankaya sebepsiz fesih (convenience) hakkı; tedarikçinin sebepsiz feshi yok/uzun ihbar; regülatif zorunluluk hâlinde anında cezasız fesih |
| 32 | **Otomatik yenileme** | "Sözleşme, 60 gün önce ihbar edilmezse 1 yıl uzar" | Otomatik yenileme yok ya da ihbar süresi ≤ 30 gün; yenileme fiyat artışına bağlanamaz |
| 33 | **Devir / temlik** | Tedarikçi serbestçe devredebilir | Bankanın yazılı onayı; alacağın faktoringe temliki sınırı |
| 34 | **Kontrol değişikliği** | Yok | Tedarikçinin el değiştirmesi (özellikle bankanın rakibi/ambargolu taraf) hâlinde bankaya fesih hakkı |
| 35 | **Uygulanacak hukuk / yetki** | Yabancı hukuk + yabancı tahkim | Türk hukuku, İstanbul mahkemeleri (veya ISTAC tahkimi), sözleşme dili Türkçe (çelişkide Türkçe üstün) |
| 36 | **Mücbir sebep** | Grev, tedarik zinciri, siber saldırı, alt yüklenici hatası dâhil çok geniş | Dar tanım; tedarikçinin kendi ihmali/siber olayı mücbir sebep sayılmaz; 30 günü aşarsa bankaya fesih |
| 37 | **Münhasırlık / asgari taahhüt** | Banka minimum alım taahhüdü veriyor | Taahhüt yok veya düşük; münhasırlık yok |
| 38 | **Personel ayartmama** | Karşılıklı ve bankayı da bağlıyor, cezası ağır | Tek taraflı (tedarikçi bankadan personel alamaz) veya makul ve simetrik |

### 3.7 Etik / İtibar
| # | Madde | Tipik tedarikçi metni (RİSK) | Banka lehine olması gereken |
|---|---|---|---|
| 39 | **Referans / logo kullanımı** | "Tedarikçi bankayı referans gösterebilir" | Bankanın **her seferinde yazılı onayı** olmadan ad/logo kullanılamaz |
| 40 | **Rüşvet ve yolsuzlukla mücadele** | Yok | Anti-bribery taahhüdü, ihlalde derhal fesih |
| 41 | **Yaptırım / ambargo** | Yok | Tedarikçi ve alt yüklenicilerinin yaptırım listelerinde olmadığı beyanı; ihlalde fesih |
| 42 | **ESG / insan hakları** | Yok | Tedarikçi davranış kuralları eki (öncelik: ONERILEN) |

---

## 4. "Eksik Madde" Kontrol Listesi Mantığı
Her sözleşme tipi için **zorunlu madde kümesi** tanımlanır. Analiz sonunda:

```
eksikler = {playbook[obligation=ZORUNLU, applies_to ∋ tip]} − {tespit edilen madde tipleri}
```

Bu **deterministik** bir küme farkıdır; LLM'e sorulmaz. Sadece "bu madde gerçekten yok mu,
yoksa sınıflandırıcı mı kaçırdı?" doğrulaması için hedefli bir ikinci arama yapılır
(anahtar kelime + semantik arama), sonra eksik ilan edilir.

## 5. Risk Skorlama Modeli
```
madde_bulgu_skoru = siddet(1..5) × playbook_agirlik(1..5) × baglam_carpani
baglam_carpani:
  sözleşme bedeli > eşik              → ×1.25
  kişisel veri işleniyor              → ×1.25 (VERI_GUVENLIK kategorisinde)
  dış hizmet / kritik sistem          → ×1.5  (REGULASYON kategorisinde)
  süre > 3 yıl                        → ×1.15 (fiyat/fesih maddelerinde)

sozlesme_skoru = 100 − normalize(Σ madde_bulgu_skoru)   # 0-100, yüksek = iyi
```
Renk eşikleri: **≥80 Yeşil** (imzalanabilir), **60–79 Sarı** (müzakere edilmeli),
**<60 Kırmızı** (mevcut hâliyle imzalanmamalı). Ayrıca **tek bir kırmızı çizgi ihlali
varsa skor ne olursa olsun sözleşme Kırmızı** işaretlenir (veto kuralı).

## 6. Bulgu Tipleri
| Tip | Anlamı | Örnek |
|---|---|---|
| `RED_LINE` | Playbook kırmızı çizgisi ihlal edilmiş | Sorumluluk aylık ücretle sınırlı |
| `WEAK` | Madde var ama banka aleyhine/yetersiz | "Makul sürede bildirim" |
| `MISSING` | Zorunlu madde hiç yok | Escrow maddesi yok |
| `ONE_SIDED` | Yükümlülük tek taraflı | Sadece banka tazmin ediyor |
| `AMBIGUOUS` | Belirsiz/ölçülemez ifade | "ticari makul çaba", "gerektiğinde" |
| `INTERNAL_CONFLICT` | Sözleşme içi çelişki | m.7 fesih 30 gün, m.15 fesih 90 gün |
| `CROSS_REF_ERROR` | Atıf hatası / olmayan eke atıf | "Ek-4'te belirtildiği üzere" ama Ek-4 yok |
| `INFO` | Bilgi amaçlı tespit | Sözleşme bedeli, süre, yenileme tarihi |

## 7. Belirsiz İfade Sözlüğü (deterministik tarama)
`makul çaba, ticari makul, gerektiğinde, mümkün olan en kısa sürede, uygun görüldüğü takdirde,
zaman zaman, önemli ölçüde, esaslı, derhal, ivedilikle, vb., benzeri, dilediği gibi,
tek taraflı olarak değiştirebilir, bildirimde bulunmaksızın`
→ Bu ifadeler geçtiği maddede otomatik `AMBIGUOUS` adayı üretir; LLM sadece
"bu bağlamda gerçekten risk mi?" filtresini uygular.
