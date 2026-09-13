"""Denetim izi kaydı.

Bu modül "kim, nereden, ne zaman, neyi yaptı" sorusunun evidir. İstemci
kimliğini (IP, tarayıcı künyesi) okuyan tek yer burasıdır: başka modüller
`istemci_kimligi` üzerinden sorar, böylece vekil başlıklarını çözen mantık
kopyalanmaz.

Detay iki biçimde tutulur:
  * `detail`  — insan okusun diye tek satır
  * `detail_json` — makine sorgulasın diye yapısal alanlar

Serbest metin sorgulanamıyordu: `"x.pdf · 4210 bayt · SAAS"` satırından
"10 MB'tan büyük yüklemeler" diye soramazsınız. Yapısal alan bunun için.
"""
from __future__ import annotations

import logging

from fastapi import Request

from .db import session_scope
from .models import AuditLog

log = logging.getLogger("audit")


def istemci_kimligi(request: Request | None) -> tuple[str, str]:
    """(ip, tarayıcı künyesi) döner.

    Ters vekil arkasında gerçek adres `X-Forwarded-For`'un İLK girdisidir;
    sonrakiler vekil zinciridir. Cloudflare `CF-Connecting-IP` de gönderir ama
    nginx zaten XFF'i doğru ilettiği için ona ayrıca bakmaya gerek yok.

    UYARI: bu başlık istemci tarafından uydurulabilir. Yalnızca uygulamaya
    doğrudan erişim kapalıysa (vekil dışından port açık değilse) güvenilir.
    """
    if request is None:
        return "", ""
    ip = (request.headers.get("x-forwarded-for", "").split(",")[0].strip()
          or (request.client.host if request.client else ""))
    ua = (request.headers.get("user-agent", "") or "")[:300]
    return ip, ua


def kaydet(request: Request | None, kullanici: str, eylem: str,
           varlik_tipi: str = "", varlik_id: str = "", detay: str = "",
           detay_json: dict | None = None) -> None:
    ip, ua = istemci_kimligi(request)
    try:
        with session_scope() as s:
            s.add(AuditLog(user=kullanici or "?", action=eylem,
                           entity_type=varlik_tipi, entity_id=varlik_id,
                           ip=ip, user_agent=ua,
                           detail=detay[:400], detail_json=detay_json or {}))
    except Exception:
        # Denetim kaydi yazilamazsa istek basarisiz olmamali; ama sessiz de kalmamali.
        log.exception("Denetim kaydı yazılamadı: %s / %s", kullanici, eylem)
