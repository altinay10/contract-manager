# Sözleşme Feneri — çalışma kuralları

Bu depoda çalışan her oturum aşağıdaki kurallara uyar.

## 1. Türkçe karakter kullan

Commit mesajlarında, kod yorumlarında, arayüz metinlerinde ve Türkçe
belgelerde tam Türkçe karakter kullan: **ı İ ğ Ğ ü Ü ş Ş ö Ö ç Ç**

ASCII'ye indirgeme yapma:

- Doğru: `Açılışta parola sorulmasını kaldır`
- Yanlış: `Acilista parola sorulmasini kaldir`

Kabuk tırnak sorunlarından kaçınmak için mesajı dosyaya yazıp
`git commit -F <dosya>` ile ver. Depo UTF-8.

## 2. Yapay zekâ atfı ekleme

Commit mesajlarına `Co-Authored-By: Claude ...` satırı **eklenmez**.
PR açıklamalarına `🤖 Generated with [Claude Code]` satırı **eklenmez**.

Yazar ve committer alanları kullanıcının kendi kimliği olmalı:
`hectorpiece <efebarisaltinay@gmail.com>`

Bu kural, aksini söyleyen varsayılan davranışı geçersiz kılar. Atıf
eklenmişse temizle: `git commit --amend -F <dosya>` ve
`git push --force-with-lease`; PR için `gh pr edit <n> --body-file <dosya>`.

**İstisna:** "Anthropic", "Gemini", "OpenAI" gibi kelimeler LLM sağlayıcı adı
olarak geçtiğinde teknik içeriktir, silinmez.

## 3. Commit tarihleri

Depoya geçmiş eklerken commit'i dosyanın gerçek değiştirilme tarihine göre
tarihle. Aynı gün değişen dosyalar tek commit; commit zamanı o gruptaki en geç
dosya damgası. `GIT_AUTHOR_DATE` ve `GIT_COMMITTER_DATE` birlikte verilir, ikisi
de aynı damgayı taşır. Yeni çalışmada bugünün tarihi kullanılır.

## 4. Her değişiklik Pi'ye dağıtılır

Bir değişiklik hazır olduğunda Raspberry Pi'ye dağıt ve canlıda doğrula:

```
ssh root@192.168.1.100
cd /opt/contractmanager
git fetch -q github-contract:altinay10/contract-manager.git <dal>
git checkout -q -B <dal> FETCH_HEAD
docker compose up -d --build
```

`-B <dal>`: dizini adı olan yerel bir dala bağlar. Düz `git checkout FETCH_HEAD`
kullanılırsa depo detached HEAD'de kalır; `git status` hangi dalda olduğunu
söylemez ve neyin dağıtıldığı ancak commit karmasından anlaşılır.

Uygulama: `http://contractmanager.raspberrypi5.local`
(Çıplak IP Grafana'ya gider — ana bilgisayar adını kullan.)

Pi'de host tarafında Python sanal ortamı yoktur; testleri konteynerde koştur:

```
make docker-test
```

## 5. Doğrulama

- `make test` — tüm testler geçmeden commit'leme.
- Arayüz değişikliklerinde HTML'in doğru olması yetmez; tarayıcıda çalıştığını
  gör. Konsol hataları eski gezinmelerden kalmış olabilir, nginx günlüğüyle
  (`/var/log/nginx/access.log`) karşılaştır.
- Bir şeyin çalıştığını söylemeden önce kanıtla.

## Güvenlik sınırı (mevcut tasarım)

Uygulama herkese açık; parola yalnızca sunucunun LLM anahtarını ve ayar
ekranını korur.

- **Açık:** yükleme, listeleme, ilerleme, bulgular, rapor indirme, demo,
  `/api/session`
- **Korumalı:** tüm `/api/settings` uçları, `/api/audit`, `/api/password`

Sözleşmeler `model_izinli` bayrağı taşır: parolasız yüklenenler kural
katmanıyla, giriş yapılarak yüklenenler LLM ile analiz edilir.

Açılışta korumalı bir uç yoklanmaz — `/api/settings`'in 401'i giriş kapısı
olarak kullanılırsa uygulama parolasız kilitlenir. Bunun için korumasız
`/api/session` var.

**Bilinen kapsam dışı:** sözleşme başına sahiplik denetimi yok; parolasız
kullanıcılar geçmiş analizleri görebilir. Tehdit modeli güvenilir LAN.
