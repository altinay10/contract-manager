# 12 — Sunucu Mimarisi ve Deploy Planı (Raspberry Pi 5)

> **Durum:** Onay bekliyor. Bu belge yazıldığında Pi üzerinde **hiçbir değişiklik yapılmamıştır.**
> Tüm keşif salt-okuma yapılmıştır.
> Tarih: 2026-08-29 · Hedef: `192.168.1.100` (raspberrypi5)

---

## 1. Karar özeti

Contract Manager (Sözleşme Feneri), Pi 5 üzerinde **Docker konteyneri** olarak,
`127.0.0.1:8099`'a bağlı biçimde çalışacak. Erişim iki ayrı yoldan olacak:

- **LAN'dan:** `http://sozlesmeanaliz.raspberrypi5.local` — nginx `:80` üzerinden (mevcut düzen).
- **İnternetten:** `https://<alan-adı>` — nginx `:8443` üzerinden, TLS ile.
  Router yalnızca bu portu yönlendirir, dolayısıyla **dışarıdan yalnızca bu uygulamaya
  ulaşılabilir**; Grafana, Pi-hole ve OpenVAS LAN'da kapalı kalır.

Seçilen yaklaşımlar:

| Konu | Karar | Gerekçe |
|---|---|---|
| Yönlendirme | **Alt alan adı** (vhost) | Mevcut deseni izler; uygulamada base-path ayarı gerekmez |
| İsim çözümü | **avahi (mDNS) alias** | `.local` deseni korunur; macOS/iOS'ta ek ayar gerekmez |
| Kod aktarımı | **Git deposu** | Tekrarlanabilir; güncelleme `git pull` + rebuild |
| Dış erişim | **Ayrı dinleme portu** (`8443`) | Router yönlendirmesi yalnız bu uygulamaya ulaşır; Grafana/Pi-hole/OpenVAS LAN'da kalır |
| TLS | **Zorunlu** (Let's Encrypt) | Uygulama internete açılacak; parola ve API anahtarı düz metin gidemez |
| Yetki | **root SSH anahtarı** | Kullanıcı tercihi (bkz. §9 risk notu) |
| Sunucu adı | **`sozlesmeanaliz`** | Kod içindeki "Feneri" adından bağımsız; yalnız nginx + mDNS |
| Çerez | **`COOKIE_SECURE=0`** | LAN (HTTP) ve dış erişim (HTTPS) birlikte çalışsın (§4.4-B) |

---

## 2. Mevcut durum envanteri

**Donanım / sistem**

| Öğe | Değer |
|---|---|
| Model | Raspberry Pi 5, `aarch64` |
| İşletim sistemi | Debian 13 (trixie), çekirdek 6.18.33 |
| CPU | 4 çekirdek — **load average 5.03** (sürekli aşırı yük) |
| RAM | 7.9 GB toplam, **4.0 GB müsait**, 2 GB zram swap |
| Disk | **238 GB SD kart** (`mmcblk0`), 174 GB boş — **SSD yok** |
| Sıcaklık | 54.9 °C, throttle yok (`0x0`) |
| Güvenlik duvarı | ufw yok, nftables kuralı yok |

**Çalışan servisler** — hepsi systemd altında, Docker'da değil:

| Port | Servis | nginx vhost |
|---|---|---|
| 22 | sshd | — |
| 53 | Pi-hole FTL (DNS) | — |
| 80 | **nginx** | — |
| 3000 | Grafana | `grafana.*` — **`listen 80 default_server`** |
| 3100 / 9096 | Loki | — |
| 5335 | unbound (yalnız localhost) | — |
| 7500 | Basic-auth'lu bilinmeyen servis | — |
| 8080 | Pi-hole v6 admin | `pihole.*` |
| 9080 | promtail | — |
| 9090 | Prometheus | — |
| 9091 | "panel" (yanıt vermiyor) | `panel.*` |
| 9100 | node-exporter | — |
| 9167 | pihole-exporter | — |
| 9392 | OpenVAS / gvmd | `openvas.*` |
| 9617 | unbound-exporter | — |

Ayrıca servis olarak: Suricata (IDS), postgres, redis, containerd, Tailscale (**çıkış yapılmış**), avahi-daemon.

**Kaynak tüketen ilk üç süreç:** Suricata 1.3 GB · gvmd ~840 MB (çoklu süreç) · postgres + redis ~620 MB.

**Docker:** 26.1.5 kurulu ve çalışıyor. İki özel bridge ağı mevcut (`172.18.0.0/16`, `172.30.0.0/24`)
— yani konteyner(ler) var, ancak `pi` kullanıcısı `docker` grubunda olmadığı için listelenemedi.

---

## 3. Kritik bulgular

### 3.1 Alt alan adları şu an çalışmıyor  ⚠️

nginx'te 4 uygulama için 8 vhost dosyası tanımlı, fakat **hiçbir isim çözülmüyor**:

```
dig @192.168.1.100 grafana.raspberrypi5.local   → (boş)
ping raspberrypi5.local                          → 192.168.1.100   ✓
ping grafana.raspberrypi5.local                  → çözülmedi        ✗
```

Ne Pi-hole'da yerel kayıt, ne avahi alias'ı (`avahi-publish` kurulu bile değil),
ne de istemci `/etc/hosts` satırı var. Sistem yalnızca şu nedenle çalışıyor:
Grafana bloğunda **`listen 80 default_server`** olduğu için, `Host` başlığı hiçbir
`server_name` ile eşleşmeyen tüm istekler Grafana'ya düşüyor. Vhost'lar pratikte ölü.

**macOS tuzağı:** macOS `.local` uzantısını **daima** mDNS'e yönlendirir, unicast DNS'e
sormaz. Bu nedenle Pi-hole'a `*.raspberrypi5.local` kaydı eklemek Mac'ten **işe yaramaz**.
`.local` kullanılacaksa çözüm mDNS tarafında olmalıdır — planın §5.2 adımı budur.

### 3.2 Pi zaten yük altında

Load average 4 çekirdekte 5.03 (çekirdek başına 1.26 — doygunluk üstü). Suricata ve
OpenVAS sürekli CPU/RAM tüketiyor. **Üç uygulama daha eklenecekse bellek bütçesi
yazılı olarak sabitlenmelidir** (§6).

### 3.3 SD kart yazma yükü — asıl kaynak OpenVAS

Ölçüldü (root, 60 sn pencere, `/proc/diskstats` + `/proc/PID/io`):

```
blok seviyesi : 496 MB / 60 sn   ->  ~700 GB/gun
en cok yazan  : 451 MB  postgres: gvm gvmd [local] SELECT   (2sa 58dk suredir)
                112 MB  postgres: background writer
                104 MB  postgres: walwriter
```

`gvmd --osp-vt-update` açılışta **NVT (zafiyet tanımı) feed güncellemesi** başlatmış.
Açık dosya tanıtıcıları `/data/database/base/16386/...` — geçici sıralama dosyaları değil,
tablo dosyaları: milyonlarca `UPDATE`, MVCC satır kopyaları ve checkpoint sonrası
full-page write'lar. `/data` ayrı bir disk değildir, `/` üzerindedir — yani SD karttadır.

Bu yük **elektrik kesintisi sonrası yeniden başlatmayla tetiklenmiştir** (`fsck` bugün
18:42'de çalışmış, dosya sistemi `clean`), ancak tek seferlik bir kurtarma artığı değildir:
GVM feed güncellemesini düzenli olarak yapar, dolayısıyla bu yük tekrarlayacaktır.

**Contract Manager'ın katkısı bunun yanında ihmal edilebilir.** Ölçüm yerine kod okunarak
hesaplandı:

- [`backend/app/db.py:30`](../backend/app/db.py) → `journal_mode=WAL`, `synchronous=NORMAL`
  (her commit'te `fsync` **yok** — SD kart için ciddi hafifletme)
- [`backend/app/runner.py`](../backend/app/runner.py) → 22 `commit()`; mimari her aşamada
  *ve her maddede* checkpoint yazar
- `MAX_LLM_CLAUSES=40` ile bir analiz onlarca–birkaç yüz commit; her commit değişen 4 KB
  sayfaları `app.db-wal`'a ekler, ~1000 sayfada bir checkpoint ana dosyaya katlar

Kaba tahmin: **analiz başına birkaç MB**, günde 20 analiz ≈ **100 MB/gün** —
mevcut yükün ~%0.015'i.

**Sonuç:** SD kart bir risk, ama bu planın yarattığı bir risk değil. Öncelik sırası:
1. OpenVAS'ın feed güncelleme davranışını ele almak (bu planın kapsamı dışında, ayrı iş).
2. `/var/log/gravity-sync/gravity-sync-push.log` — **422 MB**, log2ram'ın
   `LOG_DISK_SIZE=200M` ayarını aşıyor (`/var/log` toplam 434 MB). Ayrı iş.
3. USB SSD takıldığında hem postgres hem Docker verisini taşımak.

**log2ram bu sorunu çözmez** — yalnızca `/var/log`'u kapsar:

| Yazan | Yer | log2ram kapsamında |
|---|---|---|
| Contract Manager SQLite | `/var/lib/docker/volumes/` | ❌ |
| Docker konteyner logları | `/var/lib/docker/containers/` | ❌ |
| OpenVAS postgres (asıl yük) | `/data/database` | ❌ |
| Sistem / nginx logları | `/var/log` | ✅ |

---

## 3.4 Depolama kararı: SQLite kalıyor

SD kart ömrü için SQLite'ın değiştirilmesi değerlendirildi. Ölçümler bunu desteklemiyor.

**Yazma yükünün dağılımı** (60 sn pencere, root ölçümü):

| Kaynak | Yazma | Pay |
|---|---|---|
| OpenVAS postgres (`gvmd COPY`, feed import) | ~354 GB/gün | **%99.97** |
| Contract Manager (tahmini, kod analiziyle) | ~0.1 GB/gün | %0.03 |

SQLite'ı tamamen kaldırmak yazma yükünü **binde üç** azaltır. Kart ömrü açısından
ölçülemez bir fark.

**Değerlendirilen alternatifler:**

| Seçenek | Değerlendirme |
|---|---|
| **SQLite kalsın** ✅ | Zaten SD kart için doğru ayarlı: `journal_mode=WAL` + `synchronous=NORMAL` → her commit'te `fsync` yok, yalnız checkpoint'te. Değiştirilecek bir şey yok. |
| Postgres'e taşı | **Daha kötü.** WAL + checkpoint sonrası full-page write + MVCC ölü satır birikimi + autovacuum. Aynı veri için SQLite'tan kat kat fazla yazar. Ayrıca uygulamayı GVM'in postgres örneğine bağlar. |
| Veritabanını tmpfs'e (RAM) al | **Tehlikeli.** Elektrik kesintisinde tüm analiz geçmişi gider. Bu Pi geçen hafta zaten kesinti nedeniyle dosya sistemi hatası yaşadı (`fsck` 29 Ağustos 18:42). Uygulamanın checkpoint mimarisinin varlık sebebi tam olarak bu senaryo. |
| `wal_autocheckpoint` büyüt | Marjinal kazanç, karşılığında WAL dosyası büyür ve kurtarma süresi uzar. Değmez. |

**Sonuç:** Kod tarafında değişiklik yok. Kart ömrü için gerçek kaldıraçlar:

1. **OpenVAS feed güncelleme davranışı** — yükün %99.97'si. Bu planın kapsamı dışında, ayrı iş.
2. **USB SSD** — takıldığında hem `/data/database` (postgres) hem `/var/lib/docker` taşınır;
   tek hamlede her iki sorunu da çözer.

> Kart: Samsung, 238.8 GB, üretim 10/2023. Tüketici SD kartı olduğu için aşınma sayacı
> (`life_time` / `pre_eol_info`) raporlamıyor — kalan ömür okunamıyor. 354 GB/gün ≈ 129 TB/yıl;
> bu sınıf kartların dayanımı tipik olarak onlarca TB mertebesindedir.

---

## 3.5 Yapılan bakım — 29 Ağustos 2026

Deploy öncesi, Pi'yi hazır hale getirmek için aşağıdakiler **uygulandı**.

### Sonuçlar

| Ölçüt | Önce | Sonra |
|---|---|---|
| SD kart yazma | 1021 GB/gün | **1.3 GB/gün** |
| Load average | 5.03 | **0.13** |
| Kullanılan RAM | 3.9 GB | **2.0 GB** |
| Müsait RAM | 4.0 GB | **5.9 GB** |
| `/var/log` | 435 MB | **13 MB** |
| tmpfs (RAM'deki log) | 555 MB | **21 MB** |

### 1. gravity-sync — sonsuz hata döngüsü durduruldu

`gravity-sync-push.service` `Restart=on-failure` + `RestartSec=30` ile **saatte 103 kez**
başlayıp başarısız oluyordu. Üç kırık halka: aradığı `/etc/gravity-sync/gravity-sync.rsa`
anahtarı yok, hedef `192.168.1.110` SSH'ı reddediyor, uzak tarafta parolasız sudo yok.
Haziran'dan beri hiç çalışmamış; 5.105.259 satır / 442 MB log biriktirmiş — üstelik
`/var/log` log2ram olduğu için bu **RAM'de** duruyordu.

- Servis ve timer durduruldu, `disable` edildi
- Birim dosyaları `/root/gravity-sync-devre-disi/` altına taşındı → reboot sonrası da başlamaz
- Loglar silindi

**Geri alma:** birim dosyalarını `/etc/systemd/system/`'e geri koy, `daemon-reload`, `enable`.

### 2. OpenVAS — yazma fırtınasının kaynağı

Docker'da (`immauss/openvas`), `SKIPSYNC=false` + `restart: always` ile **her başlangıçta
tam feed senkronizasyonu** yapıyordu. Elektrik kesintisi sonrası yeniden başlamış ve
3.5 saattir `COPY` ile 37 GB'lık şişmiş `gvmd` veritabanına yazıyordu — hızlanarak,
1021 GB/gün seviyesine kadar.

- Konteyner `docker stop` ile temiz durduruldu → yazma **1021 → 1.3 GB/gün**
- `restart: always` → `unless-stopped` (canlı konteynerde ve compose dosyasında)
- Açıkça durdurulmuş olduğu için **reboot sonrası da başlamaz**
- Compose yedeği: `/opt/openvas/docker-compose.yml.yedek-20260829`

**Elle başlatmak için:** `docker start openvas`

**Çözülmemiş kalanlar** (kullanıcı kararıyla ertelendi):
- `gvmd` veritabanı **37 GB** (normali 2–5 GB) — tekrarlanan senkronizasyonların bıraktığı ölü satırlar
- Feed bütünlüğü bozuk: `Unable to calculate hash: sha256sums not found`
- Healthcheck 5 dakikada bir `gvmd` süreci başlatıyor (`Interval: 300s`)
- Tarama zamanlamasının gerçekten haftalık olup olmadığı **doğrulanmadı** — `schedules`
  tablosunda `period=0` görüldü, ancak GVM 22.x tekrarlamayı `icalendar` sütununda tutar.
  Konteyner çalışmadan sorgulanamıyor.

### 3. Suricata — yanlış pozitif gürültüsü

Çalışıyordu, logrotate düzgün kurulmuştu (50 MB × 3), ama ürettiği alarmların tamamı
Priority 3 protokol gürültüsüydü. Sebep: `suricata.yaml:114` `checksum-validation: yes`
iken `eth0`'da `rx/tx-checksumming: on` — ağ kartı checksum'ı kendisi hesapladığı için
Suricata paketleri bozuk sanıyordu.

- `checksum-validation: no` yapıldı → "invalid checksum" alarmları **sıfırlandı**
- `/var/log/suricata` izinleri `777` → `750` (`root:adm`)
- Yedek: `/etc/suricata/suricata.yaml.yedek-20260829-2241`

> ⚠️ **`suricata.yaml` başında "Managed by Ansible — Do not edit this file manually!" yazıyor.**
> Pi'de Ansible kurulu değil, yani playbook başka bir makineden çalıştırılıyor.
> **Bir sonraki Ansible çalıştırmasında bu düzeltme geri alınır** — değişiklik kaynak
> template'ine de işlenmelidir. Bu yüzden dosyaya başka manuel düzenleme yapılmadı.

**Kalan gürültü:** `SURICATA STREAM Packet with invalid timestamp` ~4/dakika. İstenirse
`threshold.config` ile bastırılabilir, ancak bu da Ansible template'inde yapılmalıdır
(`suricata.yaml` şu an `threshold-file` direktifini içermiyor).

---

## 4. Hedef mimari

Uygulama internete açılacağı için **iki ayrı dinleme portu** kullanılır. Bu, planın
en kritik güvenlik kararıdır (gerekçe §4.2).

```
LAN istemcisi                                 İnternet
     │ http://sozlesmeanaliz.raspberrypi5.local            │ https://<alan-adi>
     ▼                                             ▼
  nginx :80  (router YÖNLENDİRMEZ)          nginx :8443  (router WAN:443 → 8443)
     ├─ grafana.*  → 127.0.0.1:3000  MEVCUT       ├─ <alan-adi> → 127.0.0.1:8099  (TLS)
     ├─ pihole.*   → 127.0.0.1:8080  MEVCUT       └─ default_server → 444 (bağlantıyı kes)
     ├─ openvas.*  → 127.0.0.1:9392  MEVCUT
     ├─ panel.*    → 127.0.0.1:9091  MEVCUT       nginx :8081  (router WAN:80 → 8081)
     ├─ sozlesme*  → 127.0.0.1:8099  YENİ         ├─ /.well-known/acme-challenge/  (sertifika)
     ├─ app2.*     → 127.0.0.1:8100  ileride      └─ diğer her şey → 301 https
     └─ app3.*     → 127.0.0.1:8101  ileride
                                             ┌──────────────────────────────────┐
     grafana.* burada default_server          │ Grafana / Pi-hole / OpenVAS      │
     olarak KALIR (kullanıcı isteği)          │ dışarıdan ERİŞİLEMEZ             │
                                             └──────────────────────────────────┘
```

### 4.1 Değişmez kurallar

1. **Mevcut 8 vhost dosyasının hiçbirine dokunulmaz.** Yalnızca `sites-available/` altına
   yeni dosya eklenir ve `sites-enabled/`'a symlink verilir. Geri alma = symlink sil + reload.
2. **`:80` üzerindeki `default_server` Grafana'da kalır** (kullanıcı isteği). Yeni LAN
   vhost'una `default_server` **yazılmaz** — ikinci bir tanım nginx'i başlatmaz.
3. **`:8443` ve `:8081` kendi `default_server`'larına sahiptir.** `default_server`
   dinleme portu başınadır, dolayısıyla `:80`'deki Grafana tanımıyla çakışmaz.
4. **Her değişiklikten önce `nginx -t`,** sonra `systemctl reload nginx` (restart değil).
5. **Konteyner `127.0.0.1`'e bağlanır.** Uygulamaya yalnızca nginx üzerinden erişilir.
6. **Her uygulama için çift LAN ismi:** `<ad>.raspberrypi5.local` ve `<ad>.rasp.local`.

### 4.2 Neden ayrı port — atlanırsa ne olur

Router doğrudan Pi'nin `:80`'ine yönlendirilirse, `Host` başlığı hiçbir `server_name` ile
eşleşmeyen her istek **Grafana'ya** düşer (çünkü `default_server` orada). Ayrıca saldırgan
`Host: pihole.raspberrypi5.local` başlığı göndererek Pi-hole yönetim arayüzüne,
`Host: openvas.raspberrypi5.local` ile OpenVAS'a **internetten** ulaşabilir.

Ayrı dinleme portu bunu kökten keser: `:8443` yalnızca Contract Manager vhost'unu tanır,
tanımadığı `Host` başlıklarında `return 444` ile bağlantıyı sessizce düşürür.

### 4.3 İsim ve port tahsis tablosu

| Uygulama | Dahili port | LAN ismi | Dış erişim |
|---|---|---|---|
| Contract Manager | **8099** | `sozlesmeanaliz.raspberrypi5.local`, `sozlesmeanaliz.rasp.local` | **var** (`:8443`) |
| (2. uygulama) | **8100** | `app2.*` | ayrılmış |
| (3. uygulama) | **8101** | `app3.*` | ayrılmış |
| Grafana | 3000 | `grafana.*` (+ `:80` default) | **yok** |
| Pi-hole / OpenVAS / panel | 8080 / 9392 / 9091 | mevcut | **yok** |

nginx dinleme portları: `80` (LAN), `8081` (dış HTTP→ACME/yönlendirme), `8443` (dış HTTPS).
8081, 8443, 8099, 8100, 8101 portlarının tamamının boş olduğu doğrulanmıştır.

### 4.4 Çerez kararı: `COOKIE_SECURE=0`  ✅ KARAR VERİLDİ

Çerez, oturumun kendisidir — [`backend/app/auth.py:34`](../backend/app/auth.py) `CEREZ_ADI =
"feneri_oturum"`, [`backend/app/main.py:107`](../backend/app/main.py) girişten sonra imzalı
oturum çerezi bırakır. `AUTH_ENABLED=1` olduğu sürece çerez kaçınılmazdır.

`COOKIE_SECURE` yalnızca "bu çerez sadece HTTPS'te gönderilsin mi" sorusunu yanıtlar:

- `1` → LAN'daki düz HTTP üzerinden **giriş yapılamaz** (çerez hiç kurulmaz)
- `0` → hem LAN (HTTP) hem dış erişim (HTTPS) çalışır ✅ **seçilen**

**Bedeli:** LAN içinde çerez şifresiz gider; ağı dinleyen biri oturumu çalabilir.
Dışarıya giden trafik TLS içinde olduğu için internetten bu risk yoktur.

**Kazancı:** Tek bir ayarla iki erişim yolu da çalışır; split-horizon DNS veya
hairpin NAT kurulumuna gerek kalmaz.

### 4.5 İnternete açılmanın getirdiği sertleştirmeler

| Önlem | Gerekçe |
|---|---|
| **TLS zorunlu** (Let's Encrypt, otomatik yenileme) | Uygulama parolası ve API anahtarı düz metin gidemez |
| `COOKIE_SECURE=1` | TLS varken oturum çerezi yalnız HTTPS üzerinden |
| **`/api/login`'e hız sınırı** (`limit_req`) | Uygulamada tek bir paylaşılan parola var; kaba kuvvete açık |
| Güçlü `APP_PASSWORD` + rastgele `SESSION_SECRET` | Aynı sebep |
| `client_max_body_size 25m` | Yükleme kaynaklı kaynak tüketimini sınırlar |
| `MAX_UPLOAD_MB=20` | Aynı |
| `:8443` üzerinde `default_server` → `444` | Diğer vhost'ların Host başlığıyla sızmasını engeller |

> ⚠️ `docs/11` uyarısı internete açılınca ağırlaşır: **uygulamaya giriş yapabilen herkes
> API anahtarını değiştirebilir ve harcatabilir.** `APP_PASSWORD` bu yüzden uzun ve
> rastgele olmalıdır — bu, sistemin tek savunma hattıdır.

---

## 5. Uygulama adımları

Her adım bağımsızdır ve tek başına geri alınabilir. Adımlar sırayla yürütülür;
her adımın sonunda doğrulama vardır.

### Adım 0 — Erişim  ✅ TAMAMLANDI

root SSH anahtarı kuruldu ve doğrulandı (`ssh root@192.168.1.100 'id'` → `uid=0`).

### Adım 1 — Git deposu

Yerelde depo başlatılır ve uzak sunucuya gönderilir; Pi'de klonlanır.
`.gitignore` zaten `.env`, `*.key`, `backend/storage/` girdilerini içeriyor —
**API anahtarları ve parolalar depoya girmez.** Push öncesi `git status` ile doğrulanır.

```
Yerel:  git init → commit → remote ekle → push
Pi:     git clone → /opt/sozlesmeanaliz   (sahip: pi:pi)
```

### Adım 2 — Pi'ye özgü yapılandırma

`.env.example` kopyalanıp `docs/11`'deki Pi ayarlarıyla doldurulur:

| Değişken | Değer | Gerekçe |
|---|---|---|
| `HOST_PORT` | `8099` | tahsis edilen port |
| `OCR_DPI` | `200` | 300 dpi Pi'de sayfa başına ~26 MB RAM (`docs/11` §2) |
| `OCR_MAX_PAGES` | `30` | aynı |
| `MAX_UPLOAD_MB` | `20` | `docs/11` son madde |
| `MEM_LIMIT` | `1200m` | §6 bellek bütçesi |
| `AUTH_ENABLED` | `1` | ters vekil kimlik doğrulama yapmıyor |
| `APP_PASSWORD` | *(kullanıcı belirler)* | uygulama parolası |
| `SESSION_SECRET` | *(rastgele üretilir)* | oturum imzası |
| `COOKIE_SECURE` | `1` | TLS var; çerez yalnız HTTPS üzerinden gider |

`docker-compose.yml`'de tek satır değişir — konteyner yalnız localhost'a bağlanır:

```yaml
ports:
  - "127.0.0.1:${HOST_PORT:-8099}:8000"
```

### Adım 3 — İmajı Pi'de derle ve başlat

```bash
docker compose up -d --build
```

`--build` **şarttır**: geliştirme makinesi amd64, Pi arm64 (`docs/11` §1).
İlk derleme 15–35 dakika sürer (tesseract apt paketleri + Python tekerlekleri).

**Doğrulama:** `curl -s localhost:8099/api/health` → `ocr.ready: true`

### Adım 4 — nginx: LAN vhost'u

`/etc/nginx/sites-available/sozlesmeanaliz.raspberrypi5.local.conf` (ve `.rasp.local` eşi):

```nginx
server {
    listen 80;                          # default_server YOK — o Grafana'da kalır
    server_name sozlesmeanaliz.raspberrypi5.local;

    client_max_body_size 25m;           # nginx varsayılanı 1 MB — PDF yüklenemezdi

    location / {
        proxy_pass http://127.0.0.1:8099;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        proxy_read_timeout  300s;       # varsayılan 60 sn — uzun yükleme kesilirdi
        proxy_send_timeout  300s;
    }
}
```

**Not:** Mevcut konfiglerdeki `Upgrade`/`Connection "upgrade"` başlıkları **bilinçli olarak
eklenmemiştir** — arayüz WebSocket/SSE kullanmıyor, yoklama (`setTimeout(poll, 700)`) yapıyor.
Gereksiz `Connection: upgrade` başlığı keepalive davranışını bozabilir.

**Doğrulama:** `nginx -t` → `syntax is ok` · sonra `systemctl reload nginx`

### Adım 4b — nginx: dış erişim (TLS)

Ön koşul: bir **alan adı** (kendi alan adın veya DuckDNS gibi bir DDNS kaydı) ve
router'da **WAN:80 → Pi:8081**, **WAN:443 → Pi:8443** yönlendirmesi.
certbot Pi'de kurulu değil; kurulacak.

`/etc/nginx/sites-available/sozlesmeanaliz-dis.conf`:

```nginx
# --- hız sınırı bölgesi (http bağlamı, conf.d altında) ---
# limit_req_zone $binary_remote_addr zone=sozlesme_login:10m rate=10r/m;

# ACME doğrulaması + HTTPS'e yönlendirme
server {
    listen 8081 default_server;
    server_name _;
    location /.well-known/acme-challenge/ { root /var/www/certbot; }
    location / { return 301 https://$host$request_uri; }
}

# Tanınmayan Host: sessizce düşür — Grafana/Pi-hole/OpenVAS sızmasın
server {
    listen 8443 ssl default_server;
    ssl_certificate     /etc/letsencrypt/live/<alan-adi>/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/<alan-adi>/privkey.pem;
    return 444;
}

server {
    listen 8443 ssl;
    server_name <alan-adi>;

    ssl_certificate     /etc/letsencrypt/live/<alan-adi>/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/<alan-adi>/privkey.pem;

    client_max_body_size 25m;

    add_header Strict-Transport-Security "max-age=31536000" always;
    add_header X-Content-Type-Options nosniff always;
    add_header X-Frame-Options DENY always;

    # Tek paylaşılan parola var — kaba kuvvete karşı
    location = /api/login {
        limit_req zone=sozlesme_login burst=5 nodelay;
        proxy_pass http://127.0.0.1:8099;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location / {
        proxy_pass http://127.0.0.1:8099;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout  300s;
        proxy_send_timeout  300s;
    }
}
```

Sertifika `certbot certonly --webroot -w /var/www/certbot -d <alan-adi>` ile alınır;
yenileme certbot'un systemd timer'ı ile otomatiktir.

**Doğrulama:** §6 tablosu.

### Adım 5 — mDNS alias (isim çözümü)

`avahi-utils` kurulur ve isimleri mDNS'te yayınlayan bir systemd servisi eklenir.
Bu adım aynı zamanda **hâlihazırda ölü olan 4 ismi de canlandırır**
(grafana, pihole, openvas, panel).

`/etc/systemd/system/mdns-alias@.service` şablon birimi oluşturulur; her isim için
bir örnek etkinleştirilir (`mdns-alias@sozlesmeanaliz.raspberrypi5.local.service` gibi).
Böylece isim eklemek/çıkarmak tek bir `systemctl enable/disable` komutudur.

```bash
sudo apt install -y avahi-utils
# şablon birim: ExecStart=/usr/bin/avahi-publish -a -R %I 192.168.1.100
# etkinleştirilecek örnekler:
#   sozlesmeanaliz.raspberrypi5.local   sozlesmeanaliz.rasp.local
#   grafana.raspberrypi5.local  grafana.rasp.local     ← mevcut, ölü isimler
#   pihole.*  openvas.*  panel.*                        ← mevcut, ölü isimler
```

**Doğrulama:** Mac'ten `ping sozlesmeanaliz.raspberrypi5.local` → `192.168.1.100`

### Adım 6 — Uçtan uca doğrulama

**İşlevsel**

| Kontrol | Beklenen |
|---|---|
| `curl -H 'Host: sozlesmeanaliz.raspberrypi5.local' http://192.168.1.100/api/health` | `200`, `ocr.ready: true` |
| LAN tarayıcıdan `http://sozlesmeanaliz.raspberrypi5.local` | giriş ekranı |
| Dışarıdan `https://<alan-adi>` | giriş ekranı, geçerli sertifika |
| 20 MB PDF yükleme | `413` **almamalı** |
| `docker compose ps` | `healthy` |
| `docker image inspect ... --format '{{.Architecture}}'` | `arm64` |

**Regresyon — mevcut kurulum bozulmadı mı**

| Kontrol | Beklenen |
|---|---|
| `curl http://192.168.1.100/` | **hâlâ Grafana** |
| `curl -H 'Host: pihole.raspberrypi5.local' http://192.168.1.100/` | Pi-hole |
| `ping grafana.raspberrypi5.local` (Mac'ten) | `192.168.1.100` — artık **çözülüyor** |

**Güvenlik — dışarıya yalnız bu uygulama açık mı**

| Kontrol | Beklenen |
|---|---|
| Dışarıdan `https://<wan-ip>:443` (Host eşleşmiyor) | bağlantı düşer (`444`) |
| Dışarıdan `Host: grafana.raspberrypi5.local` ile `:443` | bağlantı düşer — **Grafana'ya ulaşılmamalı** |
| Dışarıdan `Host: pihole.raspberrypi5.local` ile `:443` | bağlantı düşer |
| Dışarıdan `http://<wan-ip>` | `301` → `https://` |
| `/api/login`'e 15 hızlı istek | `503`/`429` ile sınırlanmalı |
| Dışarıdan `<wan-ip>:8080`, `:3000`, `:9392` | **erişilemez** (router yönlendirmiyor) |

---

## 6. Kaynak bütçesi

Mevcut müsait bellek 4.0 GB. Üç uygulama için tahsis:

| Uygulama | `mem_limit` | Not |
|---|---|---|
| Contract Manager | **1200m** | OCR tepe kullanımını karşılar |
| 2. uygulama | 800m | ayrılmış |
| 3. uygulama | 800m | ayrılmış |
| **Toplam** | **2800m** | ~1.2 GB sistem payı kalır |

Log şişmesi `docker-compose.yml`'de zaten sınırlı (json-file, 10 MB × 3).

**CPU:** load zaten 5.03. Contract Manager'ın OCR'ı tek çekirdek kullanır ve kısa
sürelidir; ancak eşzamanlı çok kullanıcı için uygun değildir (`docs/11` son bölüm).
İzleme için Grafana'da mevcut node-exporter panelleri kullanılabilir.

---

## 7. Geri alma (rollback)

| Adım | Geri alma |
|---|---|
| nginx vhost | `rm /etc/nginx/sites-enabled/sozlesmeanaliz.*` → `nginx -t` → `systemctl reload nginx` |
| Konteyner | `docker compose down` (veri `feneri-data` biriminde kalır) |
| Dış erişim (TLS) | `rm /etc/nginx/sites-enabled/sozlesmeanaliz-dis.conf` → `nginx -t` → reload; router yönlendirmesini kapat |
| mDNS alias | `systemctl disable --now <unit>` |
| Tümü | Yukarıdaki üçü; Pi ilk günkü haline döner |

Mevcut hiçbir dosya değiştirilmediği için, geri alma mevcut uygulamaları **hiç etkilemez**.

---

## 8. İleride 2 uygulama eklerken

Aynı desen tekrarlanır — bu plan bir şablondur:

1. Tabloya port ekle (8100, 8101) ve belgele.
2. Uygulamayı `127.0.0.1:<port>`'a bağla.
3. `sites-available/<ad>.raspberrypi5.local.conf` + `.rasp.local` eşi oluştur —
   **`default_server` yok**, `client_max_body_size` ve zaman aşımları uygulamaya göre ayarla.
4. mDNS alias servisine ismi ekle.
5. `nginx -t` → `systemctl reload nginx` → doğrulama tablosunu çalıştır.
6. Bellek bütçesini (§6) güncelle.

---

## 9. Riskler ve kabul edilenler

| Risk | Değerlendirme |
|---|---|
| **SD kart aşınması** | Kabul ediliyor — ama kaynağı bu uygulama değil. Ölçüm: OpenVAS postgres ~700 GB/gün, Contract Manager ~100 MB/gün (§3.3). Öncelik OpenVAS feed davranışı ve 422 MB'lık gravity-sync logu. USB SSD takıldığında `docker-compose.override.yml` ile `/mnt/ssd/feneri-data:/data`. |
| **Pi zaten yük altında (load 5.03)** | Kabul ediliyor. Bellek bütçesiyle sınırlandı; ilk hafta Grafana'dan izlenmeli. |
| **İnternete açık uygulama** | Bilinçli karar. Savunma katmanları: TLS, `:8443` üzerinde `444` dönen default_server, `/api/login` hız sınırı, güçlü `APP_PASSWORD`, `client_max_body_size`. Suricata zaten trafiği izliyor. **Tek paylaşılan parola sistemin tek savunma hattıdır** — uzun ve rastgele olmalı. |
| **LAN trafiği hâlâ düz HTTP** | Kabul ediliyor. `:80` üzerindeki LAN erişimi şifresizdir; router bu portu yönlendirmediği için dışarıya sızmaz. |
| **Dinamik WAN IP** | Alan adı DDNS ile güncellenmezse dış erişim kopar. DDNS istemcisi kurulmalı (henüz yok). |
| **root SSH anahtarı** | Kullanıcı tercihi. Anahtar tabanlı, parola girişi kapalı (Debian varsayılanı `prohibit-password`). Daha dar alternatif `pi`'yi `docker` grubuna alıp nginx/systemd adımlarını elle yürütmekti; kullanıcı tam yetkiyi seçti. Anahtar kaybı = Pi'nin tamamı; anahtar parolayla korunmalı. |
| **Grafana `default_server`** | Kullanıcı isteğiyle **korunuyor**; ayrıca mDNS alias ile `grafana.raspberrypi5.local` URL'i çalışır hale geliyor. Yalnızca `:80`'i (LAN) etkiler — dış `:8443` kendi `444` dönen default'una sahiptir. |
| **`.local` + unicast DNS** | mDNS ile çözüldü. Windows istemcilerde mDNS desteği kısmidir; gerekirse o cihazlarda `/etc/hosts` kullanılır. |
| **Port 7500'deki bilinmeyen servis** | Dokunulmuyor. Basic-auth arkasında; planla etkileşimi yok. |

---

## 10. Açık uçlar

- Port **9091'deki "panel"** yanıt vermiyor — vhost'u tanımlı ama servis ölü olabilir.
  Bu planın kapsamı dışında; istenirse ayrıca incelenir.
- **Tailscale çıkış yapılmış.** Yönetimsel uzaktan erişim (SSH, Grafana) için port açmak
  yerine Tailscale'e geri dönmek daha güvenli olurdu; ayrı bir iş.
- **OpenVAS feed güncellemesi ~700 GB/gün yazıyor** (§3.3). Bu planın kapsamı dışında,
  ancak SD kartın ömrü açısından en yüksek öncelikli iş budur.
- **`gravity-sync-push.log` 422 MB** — log2ram'ın `LOG_DISK_SIZE=200M` sınırını aşıyor.
  Logrotate kuralı gerekiyor; ayrı iş.
- **DDNS istemcisi yok.** WAN IP'si dinamikse dış erişim için kurulmalı.
