"""Asama 9: Dogrulama.

Iki katman:
  1. GROUNDING (kod, model degil): alinti kaynak metinde birebir var mi? Yoksa bulgu DUSER.
     Modele ne kadar cok is verirsek, ciktisini o kadar siki denetleriz.
  2. K7 KARSI-GORUS (model): kritik bulgu tedarikcinin avukatina curuttululur.
     Bu ADIM BULGUYU SILMEZ - yalnizca guveni dusurur. Silme yetkisi insandadir.
"""
from __future__ import annotations

import logging

from ..config import settings
from ..llm.budget import Budget, BudgetExceeded
from ..llm.provider import Completion, LLMError, LLMProvider, Turn
from ..playbook.loader import SEV_RANK
from ..textutil import find_quote
from .analyze import FindingDraft

log = logging.getLogger(__name__)

REBUTTAL_SYSTEM = """Sen tedarikcinin avukatisin. Sana bir risk analistinin urettigi bulgu verilecek.

Gorevin bu bulguyu CURUTMEYE calismak:
- Madde aslinda bankayi koruyor olabilir mi?
- Sozlesmenin baska bir maddesi bu riski dengeliyor olabilir mi?
- Alinti baglamindan koparilmis mi?
- Bulgunun siddeti abartilmis mi?

Durust ol: bulgu gercekten yerindeyse bunu acikca soyle. Amac bulguyu ne pahasina olursa
olsun cürutmek degil, zayif bulgulari ayiklamaktir.
Yalnizca verilen JSON semasina uygun cikti uret."""

REBUTTAL_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["YERINDE", "ABARTILI", "GECERSIZ"]},
        "rebuttal": {"type": "string"},
        "suggested_severity": {"type": "string", "enum": ["KRITIK", "YUKSEK", "ORTA", "DUSUK", "BILGI"]},
    },
    "required": ["verdict", "rebuttal", "suggested_severity"],
    "additionalProperties": False,
}


def ground(drafts: list[FindingDraft], source_by_clause: dict[str, str], full_text: str):
    """Alinti dogrulamasi. (gecen, dusen) doner."""
    kept: list[FindingDraft] = []
    dropped: list[tuple[FindingDraft, str]] = []

    for d in drafts:
        # MISSING bulgular tanimi geregi metne dayanmaz.
        if d.finding_type == "MISSING" and not d.quote:
            kept.append(d)
            continue
        if not d.quote:
            # Bu tipler tanimi geregi metne dayanmaz: olmayan bir seyi isaret ederler.
            if d.finding_type in ("INFO", "MISSING", "CROSS_REF_ERROR"):
                kept.append(d)
            else:
                dropped.append((d, "alinti yok"))
            continue

        source = source_by_clause.get(d.clause_number, "")
        pos = find_quote(source, d.quote) if source else None
        if pos is None:
            # Madde sinirlari yanlis ayrilmis olabilir; tum metinde de ara.
            pos = find_quote(full_text, d.quote)
            if pos is None:
                dropped.append((d, "alinti kaynak metinde bulunamadi"))
                continue
            d.confidence = min(d.confidence, 0.6)
        kept.append(d)
    return kept, dropped


def rebut(
    provider: LLMProvider,
    draft: FindingDraft,
    clause_text: str,
    context_blocks: list[str],
    budget: Budget | None = None,
) -> tuple[FindingDraft, Completion | None]:
    """K7. Yalnizca KRITIK/YUKSEK bulgularda cagrilir."""
    if not provider.is_llm or not settings.enable_rebuttal:
        return draft, None
    if budget is not None and not budget.active:
        return draft, None

    task = "\n".join([
        "=== CURUTULECEK BULGU ===",
        f"Siddet: {draft.severity}   Tip: {draft.finding_type}",
        f"Baslik: {draft.title}",
        f"Gerekce: {draft.rationale}",
        f"Alinti: «{draft.quote}»",
        "",
        "=== MADDENIN TAM METNI ===",
        clause_text[:8000],
    ])
    turn = Turn(
        agent="Rebuttal",
        system=REBUTTAL_SYSTEM,
        context_blocks=context_blocks,
        task_block=task,
        schema=REBUTTAL_SCHEMA,
        effort="medium",
        max_tokens=2000,
    )
    try:
        comp = provider.complete_json(turn, budget)
    except BudgetExceeded as exc:
        log.info("Butce tavani: karsi-gorus atlandi (%s)", exc)
        return draft, None
    except LLMError as exc:
        log.warning("Karsi-gorus basarisiz (%s) - bulgu oldugu gibi kalir", exc)
        return draft, None

    verdict = comp.data.get("verdict", "YERINDE")
    draft.rebuttal = (comp.data.get("rebuttal") or "")[:1200]

    if verdict == "GECERSIZ":
        draft.confidence = round(draft.confidence * 0.45, 2)
        draft.finding_type = "AMBIGUOUS"
        draft.severity = "DUSUK"
    elif verdict == "ABARTILI":
        draft.confidence = round(draft.confidence * 0.75, 2)
        sug = comp.data.get("suggested_severity", draft.severity)
        if sug in SEV_RANK and SEV_RANK[sug] < SEV_RANK[draft.severity]:
            draft.severity = sug
    return draft, comp
