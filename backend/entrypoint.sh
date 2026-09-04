#!/bin/sh
# Uygulama root olarak calismaz. Ama bagli birim (/data) daha once root'la
# olusturulmus olabilir; o zaman yetkisiz kullanici yazamaz ve konteyner
# "attempt to write a readonly database" ile acilmaz. Bu yuzden giriste bir
# an root kalinip birim devralinir, sonra yetki dusurulur.
set -e

KULLANICI_UID=10001
KULLANICI_GID=100

if [ "$(id -u)" = "0" ]; then
    chown -R "$KULLANICI_UID:$KULLANICI_GID" /data 2>/dev/null || true
    exec setpriv --reuid="$KULLANICI_UID" --regid="$KULLANICI_GID" --init-groups "$@"
fi

# Zaten yetkisiz baslatilmissa (compose'da user: verilmisse) oldugu gibi devam.
exec "$@"
