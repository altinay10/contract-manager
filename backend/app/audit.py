"""Denetim izi kaydi."""
from __future__ import annotations

import logging

from fastapi import Request

from .db import session_scope
from .models import AuditLog

log = logging.getLogger("audit")


def kaydet(request: Request | None, kullanici: str, eylem: str,
           varlik_tipi: str = "", varlik_id: str = "", detay: str = "") -> None:
    ip = ""
    if request is not None:
        ip = (request.headers.get("x-forwarded-for", "").split(",")[0].strip()
              or (request.client.host if request.client else ""))
    try:
        with session_scope() as s:
            s.add(AuditLog(user=kullanici or "?", action=eylem,
                           entity_type=varlik_tipi, entity_id=varlik_id,
                           ip=ip, detail=detay[:400]))
    except Exception:
        # Denetim kaydi yazilamazsa istek basarisiz olmamali; ama sessiz de kalmamali.
        log.exception("Denetim kaydı yazılamadı: %s / %s", kullanici, eylem)
