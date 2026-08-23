"""Playbook yükleyici ve doğrulayıcı.

Playbook koda gömülü değildir: YAML dosyalarından okunur, şeması doğrulanır ve
bellekte tutulur. Yeni bir kırmızı çizgi eklemek için deploy gerekmez.
"""
from __future__ import annotations

import glob
import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

import yaml

from ..config import settings

SEVERITIES = ["BILGI", "DUSUK", "ORTA", "YUKSEK", "KRITIK"]
SEV_RANK = {s: i for i, s in enumerate(SEVERITIES)}
OBLIGATIONS = {"ZORUNLU", "ONERILEN", "OPSIYONEL", "YASAK"}


@dataclass(frozen=True)
class RedLine:
    id: str
    text: str
    severity: str = "YUKSEK"
    patterns: tuple[re.Pattern, ...] = ()
    absent_patterns: tuple[re.Pattern, ...] = ()

    @property
    def is_absence_rule(self) -> bool:
        """absent_patterns: bu kalıpların HİÇBİRİ yoksa ihlal sayılır."""
        return bool(self.absent_patterns) and not self.patterns


@dataclass(frozen=True)
class ClauseType:
    code: str
    name_tr: str
    category: str
    obligation: str
    applies_to: tuple[str, ...]
    weight: int
    keywords: tuple[str, ...]
    red_lines: tuple[RedLine, ...]
    ideal_text_tr: str
    fallback_text_tr: str
    legal_basis: tuple[str, ...]
    negotiation_argument_tr: str
    severity_if_missing: str
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    def applies(self, contract_type: str) -> bool:
        return not self.applies_to or contract_type in self.applies_to


class PlaybookError(ValueError):
    pass


def _compile(patterns: list[str] | None) -> tuple[re.Pattern, ...]:
    out = []
    for p in patterns or []:
        try:
            out.append(re.compile(p, re.IGNORECASE | re.DOTALL))
        except re.error as exc:  # bozuk regex sessizce yutulmaz
            raise PlaybookError(f"Geçersiz regex: {p!r} ({exc})") from exc
    return tuple(out)


def _parse_entry(d: dict[str, Any], src: str) -> ClauseType:
    def need(k: str) -> Any:
        if k not in d:
            raise PlaybookError(f"{src}: '{d.get('code', '?')}' kaydında '{k}' alanı eksik")
        return d[k]

    code = need("code")
    obligation = need("obligation")
    if obligation not in OBLIGATIONS:
        raise PlaybookError(f"{src}: {code} geçersiz obligation={obligation}")

    sev_missing = d.get("severity_if_missing", "ORTA")
    if sev_missing not in SEV_RANK:
        raise PlaybookError(f"{src}: {code} geçersiz severity_if_missing={sev_missing}")

    det = d.get("detection", {}) or {}
    kws = tuple(
        k.strip().lower()
        for k in (det.get("keywords_tr", []) + det.get("keywords_en", []))
        if k and k.strip()
    )

    rls = []
    for r in d.get("red_lines", []) or []:
        sev = r.get("severity", "YUKSEK")
        if sev not in SEV_RANK:
            raise PlaybookError(f"{src}: {code}/{r.get('id')} geçersiz severity={sev}")
        rls.append(
            RedLine(
                id=r["id"],
                text=r["text"],
                severity=sev,
                patterns=_compile(r.get("patterns")),
                absent_patterns=_compile(r.get("absent_patterns")),
            )
        )

    return ClauseType(
        code=code,
        name_tr=need("name_tr"),
        category=d.get("category", "SOZLESMESEL"),
        obligation=obligation,
        applies_to=tuple(d.get("applies_to", []) or []),
        weight=int(d.get("weight", 3)),
        keywords=kws,
        red_lines=tuple(rls),
        ideal_text_tr=(d.get("ideal_text_tr") or "").strip(),
        fallback_text_tr=(d.get("fallback_text_tr") or "").strip(),
        legal_basis=tuple(d.get("legal_basis", []) or []),
        negotiation_argument_tr=(d.get("negotiation_argument_tr") or "").strip(),
        severity_if_missing=sev_missing,
        raw=d,
    )


@lru_cache(maxsize=1)
def load_playbook() -> dict[str, ClauseType]:
    out: dict[str, ClauseType] = {}
    files = sorted(glob.glob(str(settings.playbook_dir / "*.yaml")))
    if not files:
        raise PlaybookError(f"Playbook bulunamadı: {settings.playbook_dir}")
    for path in files:
        with open(path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or []
        if not isinstance(data, list):
            raise PlaybookError(f"{path}: kök öğe liste olmalı")
        for entry in data:
            ct = _parse_entry(entry, path)
            if ct.code in out:
                raise PlaybookError(f"Mükerrer playbook kodu: {ct.code}")
            out[ct.code] = ct
    return out


def mandatory_codes(contract_type: str) -> list[str]:
    """Bu sözleşme tipi için ZORUNLU madde kümesi — eksik madde tespitinin temeli."""
    pb = load_playbook()
    return [c.code for c in pb.values() if c.obligation == "ZORUNLU" and c.applies(contract_type)]
