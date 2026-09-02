"""Asama 10: Sonuc belgesi uretimi (DOCX + JSON).

Kullanicinin gercekte aldigi sey budur. Ekranda gezinmek zorunda kalmadan,
hukukcuya ve imza yetkilisine dogrudan gonderilebilecek tek bir belge.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt, RGBColor

from ..config import settings
from ..playbook.loader import SEV_RANK, load_playbook
from .redline import build_redline
from .report_html import build_html
from .scoring import BAND_LABEL

SEV_ORDER = ["KRITIK", "YUKSEK", "ORTA", "DUSUK", "BILGI"]
SEV_LABEL = {
    "KRITIK": "KRITIK", "YUKSEK": "YUKSEK", "ORTA": "ORTA",
    "DUSUK": "DUSUK", "BILGI": "BILGI",
}
SEV_COLOR = {
    "KRITIK": RGBColor(0xB3, 0x2A, 0x30),
    "YUKSEK": RGBColor(0x9A, 0x61, 0x00),
    "ORTA": RGBColor(0x55, 0x5D, 0x6E),
    "DUSUK": RGBColor(0x6E, 0x77, 0x89),
    "BILGI": RGBColor(0x6E, 0x77, 0x89),
}
BAND_COLOR = {
    "KIRMIZI": RGBColor(0xB3, 0x2A, 0x30),
    "SARI": RGBColor(0x9A, 0x61, 0x00),
    "YESIL": RGBColor(0x26, 0x71, 0x4E),
}
TYPE_LABEL = {
    "RED_LINE": "Kırmızı çizgi ihlali",
    "MISSING": "Eksik madde",
    "WEAK": "Zayıf madde",
    "ONE_SIDED": "Tek taraflı yükümlülük",
    "AMBIGUOUS": "Belirsiz ifade",
    "INTERNAL_CONFLICT": "İç çelişki",
    "CROSS_REF_ERROR": "Atıf hatası",
    "DRAFTING_DEFECT": "Taslak kusuru",
    "INFO": "Bilgi",
}

DISCLAIMER = (
    "Bu rapor bir karar-destek çıktısıdır ve hukuki mütalaa yerine geçmez. Bulgular "
    "Banka'nın sözleşme playbook'una ve ilgili mevzuata göre otomatik olarak üretilmiştir; "
    "imza öncesinde Hukuk Müşavirliği tarafından değerlendirilmelidir."
)


def _h(doc, text, size=13, bold=True, space_before=10, space_after=4, color=None):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(space_before)
    p.paragraph_format.space_after = Pt(space_after)
    r = p.add_run(text)
    r.bold = bold
    r.font.size = Pt(size)
    if color is not None:
        r.font.color.rgb = color
    return p


def _kv_table(doc, rows):
    t = doc.add_table(rows=0, cols=2)
    t.style = "Light Grid Accent 1"
    for k, v in rows:
        cells = t.add_row().cells
        cells[0].text = str(k)
        cells[1].text = str(v or "-")
        for para in cells[0].paragraphs:
            for run in para.runs:
                run.bold = True
                run.font.size = Pt(9)
        for para in cells[1].paragraphs:
            for run in para.runs:
                run.font.size = Pt(9)
    return t


def _quote(doc, text):
    p = doc.add_paragraph()
    p.paragraph_format.left_indent = Pt(18)
    p.paragraph_format.space_before = Pt(3)
    p.paragraph_format.space_after = Pt(3)
    r = p.add_run(f"“{text.strip()}”")
    r.italic = True
    r.font.size = Pt(9.5)
    return p


def _body(doc, label, text, size=9.5):
    if not text:
        return
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(2)
    r = p.add_run(f"{label}: ")
    r.bold = True
    r.font.size = Pt(size)
    r2 = p.add_run(text.strip())
    r2.font.size = Pt(size)


def build_docx(payload: dict, out_path: Path) -> Path:
    pb = load_playbook()
    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(10)

    c = payload["contract"]
    findings = payload["findings"]
    counts = payload["counts"]

    # --- Baslik ---
    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.LEFT
    tr = title.add_run("SÖZLEŞME RİSK ANALİZ RAPORU")
    tr.bold = True
    tr.font.size = Pt(20)
    sub = doc.add_paragraph()
    sr = sub.add_run("Banka tedarik sözleşmesi — madde bazlı risk değerlendirmesi")
    sr.font.size = Pt(10)
    sr.font.color.rgb = RGBColor(0x6E, 0x77, 0x89)

    # --- Kunye ---
    _h(doc, "1. Sözleşme Künyesi", 13)
    meta = c.get("meta") or {}
    _kv_table(doc, [
        ("Dosya", c.get("filename")),
        ("Karşı taraf", c.get("counterparty")),
        ("Sözleşme tipi", c.get("contract_type")),
        ("Bedel", c.get("value_text")),
        ("Süre", c.get("term_text")),
        ("Otomatik yenileme", "Evet" if meta.get("auto_renew") else "Hayır / belirtilmemiş"),
        ("Damga vergisi", meta.get("stamp_duty")),
        ("İncelenen madde sayısı", c.get("clause_count")),
        ("Metin kaynağı", "OCR (taranmış belge)" if meta.get("ocr_used") else "PDF/DOCX metin katmanı"),
        ("Analiz tarihi", payload.get("generated_at")),
        ("Analiz motoru", payload.get("engine")),
    ])

    # --- Yonetici ozeti ---
    _h(doc, "2. Yönetici Özeti", 13)
    band = c.get("risk_band") or "SARI"
    p = doc.add_paragraph()
    r = p.add_run(f"Risk skoru: {c.get('risk_score')} / 100   —   {BAND_LABEL.get(band, band)}")
    r.bold = True
    r.font.size = Pt(12)
    r.font.color.rgb = BAND_COLOR.get(band, RGBColor(0, 0, 0))

    if c.get("veto_reason"):
        pv = doc.add_paragraph()
        rv = pv.add_run(c["veto_reason"])
        rv.font.size = Pt(9.5)
        rv.font.color.rgb = BAND_COLOR["KIRMIZI"]

    _kv_table(doc, [
        ("Kritik bulgu", counts.get("KRITIK", 0)),
        ("Yüksek bulgu", counts.get("YUKSEK", 0)),
        ("Orta bulgu", counts.get("ORTA", 0)),
        ("Düşük bulgu", counts.get("DUSUK", 0)),
        ("Eksik zorunlu madde", counts.get("MISSING", 0)),
        ("Toplam bulgu", len(findings)),
    ])

    top = [f for f in findings if f["severity"] in ("KRITIK", "YUKSEK")][:5]
    if top:
        _h(doc, "Öncelikli aksiyonlar", 11, space_before=8)
        for i, f in enumerate(top, 1):
            loc = f"Madde {f['clause_number']}" if f.get("clause_number") else "Sözleşmede yok"
            pp = doc.add_paragraph(style="List Number")
            rr = pp.add_run(f"[{f['severity']}] {loc} — {f['title']}")
            rr.font.size = Pt(9.5)

    # --- Bulgular ---
    _h(doc, "3. Bulgular", 13, space_before=16)
    grouped: dict[str, list] = {s: [] for s in SEV_ORDER}
    for f in findings:
        grouped.setdefault(f["severity"], []).append(f)

    n = 0
    for sev in SEV_ORDER:
        items = grouped.get(sev) or []
        if not items:
            continue
        _h(doc, f"{SEV_LABEL[sev]} ({len(items)})", 12, space_before=12, color=SEV_COLOR[sev])
        for f in items:
            n += 1
            loc = f"Madde {f['clause_number']}" if f.get("clause_number") else "SÖZLEŞMEDE YOK"
            ct = pb.get(f["code"])
            head = doc.add_paragraph()
            head.paragraph_format.space_before = Pt(8)
            head.paragraph_format.space_after = Pt(1)
            hr = head.add_run(f"{n}. {loc} — {f['title']}")
            hr.bold = True
            hr.font.size = Pt(10.5)

            tagp = doc.add_paragraph()
            tagp.paragraph_format.space_after = Pt(2)
            tg = tagp.add_run(
                f"{TYPE_LABEL.get(f['finding_type'], f['finding_type'])}"
                f"  |  {ct.name_tr if ct else f['code']}"
                f"  |  güven {f.get('confidence', 0):.0%}"
                f"  |  tespit: {f.get('detected_by')}"
                + (f"  |  mercek: {f['lens']}" if f.get("lens") else "")
            )
            tg.font.size = Pt(8.5)
            tg.font.color.rgb = RGBColor(0x6E, 0x77, 0x89)

            if f.get("quote"):
                if f.get("quote_is_evidence", True):
                    _quote(doc, f["quote"])
                else:
                    _body(doc, "İlgili madde (aranan koruma bu metinde yok)",
                          f["quote"], size=9)
            if f.get("plain"):
                _body(doc, "Bu ne demek", f["plain"])
            _body(doc, "Neden riskli", f.get("rationale"))
            if f.get("legal_basis"):
                _body(doc, "Dayanak", "; ".join(f["legal_basis"]), size=9)
            if f.get("rebuttal"):
                _body(doc, "Karşı-görüş (güven değerlendirmesi)", f["rebuttal"], size=9)
            if f.get("proposed_text"):
                _body(doc, "Önerilen madde metni", f["proposed_text"])
            if f.get("negotiation_note"):
                _body(doc, "Müzakere argümanı", f["negotiation_note"], size=9)

    if not findings:
        doc.add_paragraph("Playbook kontrollerinde bulgu üretilmedi.")

    # --- Terimler sözlüğü ---
    gecen, goruldu = [], set()
    for f in findings:
        kod = f.get("code", "")
        if kod and kod not in goruldu and pb.get(kod) and pb[kod].plain_tr:
            goruldu.add(kod)
            gecen.append(pb[kod])
    if gecen:
        _h(doc, "4. Terimler Sözlüğü", 13, space_before=16)
        nt = doc.add_paragraph()
        nr = nt.add_run("Raporda geçen madde tiplerinin hukuk dili kullanmadan açıklaması.")
        nr.font.size = Pt(9)
        nr.font.color.rgb = RGBColor(0x6E, 0x77, 0x89)
        for ct in sorted(gecen, key=lambda c: c.name_tr):
            _body(doc, ct.name_tr, ct.plain_tr, size=9.5)

    # --- Model kullanımı ---
    u = payload.get("usage") or {}
    if u.get("calls"):
        _h(doc, "5. Model Kullanımı", 13, space_before=16)
        _kv_table(doc, [
            ("Toplam token", f'{u.get("total_tokens", 0):,}'.replace(",", ".")),
            ("Girdi tokeni", f'{u.get("input_tokens", 0):,}'.replace(",", ".")),
            ("Çıktı tokeni", f'{u.get("output_tokens", 0):,}'.replace(",", ".")),
            ("Önbellekten okunan", f'{u.get("cache_read_tokens", 0):,}'.replace(",", ".")),
            ("Model çağrısı", u.get("calls", 0)),
            ("Başarısız çağrı", u.get("failed", 0)),
            ("Ortalama gecikme", f'{u.get("avg_latency_ms", 0)} ms'),
            ("Tahmini maliyet", (f'${u.get("cost_usd", 0):.4f}' if u.get("cost_known", True)
                                 else "— (modelin birim fiyatı bilinmiyor)")),
        ])
        if u.get("by_agent"):
            _h(doc, "Göreve göre dağılım", 11, space_before=8)
            t = doc.add_table(rows=1, cols=6)
            t.style = "Light Grid Accent 1"
            for i, bas in enumerate(["Görev", "Model", "Çağrı", "Girdi", "Çıktı", "Maliyet"]):
                hucre = t.rows[0].cells[i]
                hucre.text = bas
                for para in hucre.paragraphs:
                    for run in para.runs:
                        run.bold = True
                        run.font.size = Pt(8.5)
            for a in u["by_agent"]:
                c2 = t.add_row().cells
                degerler = [
                    a["agent"], a.get("model", ""), str(a["calls"]),
                    f'{a["input_tokens"]:,}'.replace(",", "."),
                    f'{a["output_tokens"]:,}'.replace(",", "."),
                    f'${a["cost_usd"]:.5f}',
                ]
                for i, d in enumerate(degerler):
                    c2[i].text = d
                    for para in c2[i].paragraphs:
                        for run in para.runs:
                            run.font.size = Pt(8.5)

    # --- Metodoloji ---
    _h(doc, "6. Metodoloji ve Kapsam", 13, space_before=16)
    m = payload.get("method", {})
    _kv_table(doc, [
        ("Playbook madde tipi sayısı", m.get("playbook_size")),
        ("Bu sözleşme tipi için zorunlu madde", m.get("mandatory_count")),
        ("Analiz motoru", payload.get("engine")),
        ("Doğrulamada düşen bulgu", m.get("dropped")),
        ("Model çağrısı", m.get("llm_calls")),
        ("Tahmini model maliyeti",
         (f"${m.get('cost_usd', 0):.4f}" if (payload.get("usage") or {}).get("cost_known", True)
          else "— (birim fiyat bilinmiyor)")),
    ])
    note = doc.add_paragraph()
    nr = note.add_run(
        "Her bulgu, sözleşme metninden birebir alıntı ile doğrulanmıştır; alıntısı kaynak "
        "metinde bulunamayan bulgular rapora alınmaz. Dayanak alanları playbook'ta tanımlı "
        "listeden seçilir."
    )
    nr.font.size = Pt(8.5)
    nr.font.color.rgb = RGBColor(0x6E, 0x77, 0x89)

    dp = doc.add_paragraph()
    dp.paragraph_format.space_before = Pt(10)
    dr = dp.add_run(DISCLAIMER)
    dr.font.size = Pt(8.5)
    dr.italic = True

    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(out_path))
    return out_path


def build_reports(payload: dict, contract_id: str) -> list[dict]:
    """DOCX + JSON uretir, dosya bilgilerini dondurur."""
    base = settings.storage_dir / "reports" / contract_id
    base.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    safe = "".join(ch for ch in (payload["contract"].get("filename") or "sozlesme")
                   if ch.isalnum() or ch in "-_")[:40] or "sozlesme"

    out: list[dict] = []
    docx_path = base / f"risk-raporu-{safe}-{stamp}.docx"
    build_docx(payload, docx_path)
    out.append({"fmt": "DOCX", "path": str(docx_path), "filename": docx_path.name,
                "size_bytes": docx_path.stat().st_size})

    redline_path = base / f"redline-{safe}-{stamp}.docx"
    build_redline(payload, redline_path)
    out.append({"fmt": "REDLINE", "path": str(redline_path), "filename": redline_path.name,
                "size_bytes": redline_path.stat().st_size})

    html_path = base / f"rapor-{safe}-{stamp}.html"
    build_html(payload, html_path)
    out.append({"fmt": "HTML", "path": str(html_path), "filename": html_path.name,
                "size_bytes": html_path.stat().st_size})

    json_path = base / f"analiz-{safe}-{stamp}.json"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    out.append({"fmt": "JSON", "path": str(json_path), "filename": json_path.name,
                "size_bytes": json_path.stat().st_size})
    return out
