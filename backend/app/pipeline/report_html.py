"""Raporun tarayicida okunabilir hali.

Hukukcu her seferinde DOCX indirmek zorunda kalmasin: ayni payload'dan
kendi kendine yeten (tek dosya) bir HTML belgesi uretilir.
"""
from __future__ import annotations

import html
from pathlib import Path

from ..playbook.loader import load_playbook
from .scoring import BAND_LABEL

SEV_ORDER = ["KRITIK", "YUKSEK", "ORTA", "DUSUK", "BILGI"]
SEV_TR = {"KRITIK": "Kritik", "YUKSEK": "Yüksek", "ORTA": "Orta",
          "DUSUK": "Düşük", "BILGI": "Bilgi"}
TYPE_TR = {
    "RED_LINE": "Kırmızı çizgi ihlali", "MISSING": "Eksik madde",
    "WEAK": "Zayıf madde", "ONE_SIDED": "Tek taraflı yükümlülük",
    "AMBIGUOUS": "Belirsiz ifade", "INTERNAL_CONFLICT": "İç çelişki",
    "CROSS_REF_ERROR": "Atıf hatası", "DRAFTING_DEFECT": "Taslak kusuru", "INFO": "Bilgi",
}

CSS = """
:root{
  --paper:#F6F7FA; --surface:#FFFFFF; --surface-2:#EFF1F6;
  --ink:#10131C; --ink-2:#3E465C; --muted:#737C93;
  --rule:#DCE0EA; --rule-soft:#E8EBF2;
  --indigo:#3B4A78;
  --crit:#A32029; --high:#8A5A00; --mid:#4A5468; --low:#737C93; --ok:#1F6B4A;
}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    --paper:#0D1017; --surface:#141924; --surface-2:#1B2130;
    --ink:#E9ECF4; --ink-2:#AEB6C8; --muted:#79839A;
    --rule:#252C3C; --rule-soft:#1E2431;
    --indigo:#93A4DA;
    --crit:#E8737A; --high:#D9A040; --mid:#98A3BA; --low:#79839A; --ok:#5FBE90;
  }
}
:root[data-theme="dark"]{
  --paper:#0D1017; --surface:#141924; --surface-2:#1B2130;
  --ink:#E9ECF4; --ink-2:#AEB6C8; --muted:#79839A;
  --rule:#252C3C; --rule-soft:#1E2431;
  --indigo:#93A4DA;
  --crit:#E8737A; --high:#D9A040; --mid:#98A3BA; --low:#79839A; --ok:#5FBE90;
}

*{box-sizing:border-box}
body{
  margin:0; background:var(--paper); color:var(--ink);
  font-family:"IBM Plex Sans","Helvetica Neue",Arial,sans-serif;
  font-size:15px; line-height:1.6; -webkit-font-smoothing:antialiased;
}
.sheet{max-width:860px;margin:0 auto;padding:0 28px 88px}
h1,h2,h3{font-family:"Spectral",Georgia,serif;margin:0;text-wrap:balance;font-weight:600}
p{margin:0}
.mono{font-family:"IBM Plex Mono",ui-monospace,monospace;font-variant-numeric:tabular-nums}
.label{
  font-family:"IBM Plex Mono",ui-monospace,monospace;
  font-size:10.5px;letter-spacing:.14em;text-transform:uppercase;color:var(--muted);
}

/* --- başlık --- */
header{padding:52px 0 26px;border-bottom:2px solid var(--ink)}
header h1{font-size:clamp(26px,3.6vw,38px);line-height:1.15;letter-spacing:-.015em;margin:10px 0 8px}
header .sub{color:var(--ink-2);font-size:14px;max-width:60ch}

/* --- künye --- */
.kunye{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:0;
  border-bottom:1px solid var(--rule);margin-bottom:34px}
.kunye div{padding:15px 18px 15px 0;border-right:1px solid var(--rule-soft)}
.kunye div:last-child{border-right:0}
.kunye dt{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:10px;
  letter-spacing:.13em;text-transform:uppercase;color:var(--muted);margin-bottom:4px}
.kunye dd{margin:0;font-size:14px;font-weight:500}

/* --- skor --- */
.score{display:flex;gap:30px;align-items:flex-start;flex-wrap:wrap;
  padding:26px 0 24px;border-bottom:1px solid var(--rule)}
.score .n{font-family:"Spectral",Georgia,serif;font-size:66px;line-height:.9;
  font-weight:600;font-variant-numeric:tabular-nums;letter-spacing:-.03em}
.score .n small{font-size:19px;color:var(--muted);font-weight:400}
.score .side{flex:1 1 300px;min-width:0}
.band{display:inline-block;font-family:"IBM Plex Mono",ui-monospace,monospace;
  font-size:11px;font-weight:600;letter-spacing:.11em;text-transform:uppercase;
  padding:5px 11px;border:1px solid currentColor;border-radius:2px}
.veto{margin-top:12px;font-size:14px;line-height:1.55}

/* --- sayaçlar --- */
.counts{display:grid;grid-template-columns:repeat(auto-fit,minmax(112px,1fr));
  gap:0;border-bottom:1px solid var(--rule)}
.counts div{padding:18px 16px 18px 0;border-right:1px solid var(--rule-soft)}
.counts div:last-child{border-right:0}
.counts b{display:block;font-family:"Spectral",Georgia,serif;font-size:30px;
  font-weight:600;line-height:1;font-variant-numeric:tabular-nums}

/* --- bölüm --- */
h2.sec{font-size:20px;margin:44px 0 4px;letter-spacing:-.01em}
.sec-note{color:var(--muted);font-size:13.5px;margin-bottom:8px}

/* --- bulgu --- */
.f{--sev:var(--mid);padding:22px 0 22px 20px;border-top:1px solid var(--rule-soft);position:relative}
.f::before{content:"";position:absolute;left:0;top:22px;bottom:22px;width:3px;
  background:var(--sev);border-radius:2px}
.f[data-sev="KRITIK"]{--sev:var(--crit)}
.f[data-sev="YUKSEK"]{--sev:var(--high)}
.f[data-sev="ORTA"]{--sev:var(--mid)}
.f[data-sev="DUSUK"],.f[data-sev="BILGI"]{--sev:var(--low)}
.f .meta{display:flex;gap:10px;align-items:baseline;flex-wrap:wrap;margin-bottom:6px}
.f .num{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:12px;color:var(--muted)}
.f .sev{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:10px;font-weight:600;
  letter-spacing:.12em;text-transform:uppercase;color:var(--sev)}
.f .loc{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:12px;color:var(--ink-2)}
.f h3{font-size:17px;line-height:1.35;margin-bottom:8px;letter-spacing:-.008em}
.f .why{color:var(--ink-2);font-size:14.5px;margin-bottom:10px;max-width:68ch}
.plain{margin:0 0 11px;padding:11px 14px;background:var(--surface-2);border-radius:3px;
  font-size:14px;line-height:1.6;color:var(--ink-2);max-width:70ch}
.plain b{display:block;font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:10px;
  letter-spacing:.12em;text-transform:uppercase;color:var(--indigo);margin-bottom:5px;
  font-weight:500}
.sozluk dt{font-weight:600;font-size:14.5px;margin-top:16px}
.sozluk dd{margin:4px 0 0;color:var(--ink-2);font-size:14px;line-height:1.6;max-width:70ch}
blockquote.ctx{border-left-color:var(--muted);border-left-style:dashed;font-style:normal}
blockquote .qlabel{display:block;font-family:"IBM Plex Mono",ui-monospace,monospace;
  font-size:9.5px;letter-spacing:.11em;text-transform:uppercase;color:var(--muted);
  margin-bottom:5px;font-style:normal}
blockquote{margin:0 0 12px;padding:11px 16px;background:var(--surface-2);
  border-left:2px solid var(--rule);font-family:"Spectral",Georgia,serif;
  font-size:14.5px;font-style:italic;line-height:1.55;color:var(--ink-2)}
.prop{border:1px solid var(--rule);border-radius:3px;padding:13px 16px;background:var(--surface)}
.prop .label{margin-bottom:6px;color:var(--indigo)}
.prop p{font-size:14px;line-height:1.6}
.basis{margin-top:9px;font-size:12.5px;color:var(--muted)}
.basis b{color:var(--ink-2);font-weight:600}
.tags{margin-top:9px;display:flex;gap:14px;flex-wrap:wrap;
  font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:11px;color:var(--muted)}

.notice{margin:14px 0 4px;padding:12px 15px;border-left:3px solid var(--high);
  background:var(--surface-2);font-size:13.5px;line-height:1.55;color:var(--ink-2)}
.notice b{color:var(--ink)}

/* --- model kullanımı --- */
.usage{margin-top:40px;border-top:1px solid var(--rule);padding-top:24px}
.usage-top{display:grid;grid-template-columns:repeat(auto-fit,minmax(128px,1fr));
  gap:0;margin:16px 0 22px}
.usage-top div{padding:0 18px 0 0;border-right:1px solid var(--rule-soft)}
.usage-top div:last-child{border-right:0}
.usage-top b{display:block;font-family:"Spectral",Georgia,serif;font-size:26px;
  font-weight:600;line-height:1.1;font-variant-numeric:tabular-nums;letter-spacing:-.02em}
.usage-top b .u{font-size:13px;color:var(--muted);font-weight:400;letter-spacing:0}

.bar{display:flex;height:10px;border-radius:2px;overflow:hidden;background:var(--surface-2);
  border:1px solid var(--rule-soft)}
.bar span{display:block;height:100%}
.bar .b-in{background:var(--indigo)}
.bar .b-cache{background:color-mix(in srgb,var(--indigo) 45%,var(--surface))}
.bar .b-out{background:var(--high)}
.legend{display:flex;gap:20px;flex-wrap:wrap;margin-top:11px;
  font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:11.5px;color:var(--ink-2)}
.legend i{display:inline-block;width:9px;height:9px;border-radius:2px;margin-right:7px;
  vertical-align:baseline}
.legend .n{color:var(--muted);margin-left:5px}

.usage table td:first-child{width:auto}
.usage table th{text-align:left;padding:8px 12px 8px 0;border-bottom:1px solid var(--rule);
  font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:10px;letter-spacing:.11em;
  text-transform:uppercase;color:var(--muted);font-weight:500;white-space:nowrap}
.usage table td{font-variant-numeric:tabular-nums;white-space:nowrap}
.usage table td.agent{font-weight:500;color:var(--ink);white-space:normal}
.num-r{text-align:right}

/* --- yöntem --- */
.method{margin-top:44px;border-top:2px solid var(--ink);padding-top:22px}
table{width:100%;border-collapse:collapse;font-size:13.5px}
td{padding:8px 12px 8px 0;border-bottom:1px solid var(--rule-soft);vertical-align:top}
td:first-child{color:var(--muted);width:44%}
td:last-child{font-variant-numeric:tabular-nums}
.wrapscroll{overflow-x:auto}

footer{margin-top:34px;padding-top:18px;border-top:1px solid var(--rule);
  font-size:12.5px;color:var(--muted);line-height:1.6;max-width:72ch}
footer strong{color:var(--ink-2)}
@media (prefers-reduced-motion:reduce){*{transition:none!important;animation:none!important}}
"""


def _e(s) -> str:
    return html.escape(str(s or ""))


def build_html(payload: dict, out_path: Path) -> Path:
    pb = load_playbook()
    c = payload["contract"]
    findings = payload["findings"]
    counts = payload["counts"]
    meta = c.get("meta") or {}
    band = c.get("risk_band") or "SARI"
    band_renk = {"KIRMIZI": "var(--crit)", "SARI": "var(--high)", "YESIL": "var(--ok)"}.get(band, "var(--mid)")

    o: list[str] = []
    o.append("<title>Sözleşme Risk Raporu</title>")
    o.append('<link rel="preconnect" href="https://fonts.googleapis.com">')
    o.append('<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>')
    o.append('<link rel="stylesheet" href="https://fonts.googleapis.com/css2?'
             'family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans:wght@400;500;600&'
             'family=Spectral:ital,wght@0,400;0,600;1,400&display=swap">')
    o.append(f"<style>{CSS}</style>")
    o.append('<div class="sheet">')

    # --- başlık ---
    o.append("<header>")
    o.append('<div class="label">Tedarik sözleşmesi · Madde bazlı risk değerlendirmesi</div>')
    o.append("<h1>Sözleşme Risk Raporu</h1>")
    o.append(f'<p class="sub">{_e(c.get("filename"))} · {_e(c.get("counterparty") or "karşı taraf belirtilmemiş")}'
             f' · {_e(payload.get("generated_at"))}</p>')
    o.append("</header>")

    # --- künye ---
    kunye = [
        ("Karşı taraf", c.get("counterparty")),
        ("Sözleşme tipi", c.get("contract_type")),
        ("Bedel", c.get("value_text")),
        ("Süre", c.get("term_text")),
        ("Otomatik yenileme", "Evet" if meta.get("auto_renew") else "Hayır / belirtilmemiş"),
        ("Damga vergisi", meta.get("stamp_duty")),
        ("İncelenen madde", c.get("clause_count")),
        ("Metin kaynağı", ("OCR · güven %{:.0f}".format(meta["ocr_confidence"])
                           if meta.get("ocr_used") and meta.get("ocr_confidence") is not None
                           else ("OCR" if meta.get("ocr_used") else "PDF metin katmanı"))),
        ("Analiz motoru", payload.get("engine")),
    ]
    o.append('<dl class="kunye">')
    for k, v in kunye:
        o.append(f"<div><dt>{_e(k)}</dt><dd>{_e(v) or '—'}</dd></div>")
    o.append("</dl>")

    # --- skor ---
    o.append('<section class="score">')
    o.append(f'<div class="n" style="color:{band_renk}">{_e(c.get("risk_score"))}<small> / 100</small></div>')
    o.append('<div class="side">')
    o.append(f'<span class="band" style="color:{band_renk}">{_e(BAND_LABEL.get(band, band))}</span>')
    if c.get("veto_reason"):
        o.append(f'<p class="veto" style="color:{band_renk}">{_e(c["veto_reason"])}</p>')
    o.append("</div></section>")

    o.append('<section class="counts">')
    for etiket, deger in [
        ("Kritik", counts.get("KRITIK", 0)), ("Yüksek", counts.get("YUKSEK", 0)),
        ("Orta", counts.get("ORTA", 0)), ("Eksik madde", counts.get("MISSING", 0)),
        ("Toplam bulgu", len(findings)),
    ]:
        o.append(f'<div><b>{deger}</b><span class="label">{_e(etiket)}</span></div>')
    o.append("</section>")

    # --- öncelikli aksiyonlar ---
    top = [f for f in findings if f["severity"] in ("KRITIK", "YUKSEK")][:5]
    if top:
        o.append('<h2 class="sec">Öncelikli aksiyonlar</h2>')
        o.append('<p class="sec-note">İmza öncesinde müzakere edilmesi gereken maddeler.</p>')
        for i, f in enumerate(top, 1):
            yer = f"Madde {f['clause_number']}" if f.get("clause_number") else "Sözleşmede yok"
            o.append(f'<div class="f" data-sev="{_e(f["severity"])}">'
                     f'<div class="meta"><span class="num">{i}</span>'
                     f'<span class="sev">{_e(SEV_TR.get(f["severity"], f["severity"]))}</span>'
                     f'<span class="loc">{_e(yer)}</span></div>'
                     f'<h3>{_e(f["title"])}</h3></div>')

    # --- bulgular ---
    o.append('<h2 class="sec">Bulgular</h2>')
    o.append('<p class="sec-note">Her bulgu, sözleşme metninden birebir alıntıyla doğrulanmıştır.</p>')

    gruplu: dict[str, list] = {s: [] for s in SEV_ORDER}
    for f in findings:
        gruplu.setdefault(f["severity"], []).append(f)

    n = 0
    for sev in SEV_ORDER:
        grup = gruplu.get(sev) or []
        if not grup:
            continue
        o.append(f'<h2 class="sec" style="font-size:16px;margin-top:34px">'
                 f'{_e(SEV_TR.get(sev, sev))} <span class="mono" style="color:var(--muted);'
                 f'font-size:13px">({len(grup)})</span></h2>')
        for f in grup:
            n += 1
            ct = pb.get(f["code"])
            yer = f"Madde {f['clause_number']}" if f.get("clause_number") else "SÖZLEŞMEDE YOK"
            o.append(f'<article class="f" data-sev="{_e(sev)}">')
            o.append('<div class="meta">'
                     f'<span class="num">{n}</span>'
                     f'<span class="sev">{_e(TYPE_TR.get(f["finding_type"], f["finding_type"]))}</span>'
                     f'<span class="loc">{_e(yer)} · {_e(ct.name_tr if ct else f["code"])}</span></div>')
            o.append(f"<h3>{_e(f['title'])}</h3>")
            if f.get("quote"):
                if f.get("quote_is_evidence", True):
                    o.append(f"<blockquote>{_e(f['quote'])}</blockquote>")
                else:
                    # Alinti iddiayi kanitlamaz; korumanin bulunmadigi maddeyi gosterir.
                    o.append('<blockquote class="ctx"><span class="qlabel">İlgili madde '
                             "— aranan koruma bu metinde yok</span>"
                             f"{_e(f['quote'])}</blockquote>")
            if f.get("plain"):
                o.append('<div class="plain"><b>Bu ne demek?</b>'
                         f'{_e(f["plain"])}</div>')
            if f.get("rationale"):
                o.append(f'<p class="why">{_e(f["rationale"])}</p>')
            if f.get("rebuttal"):
                o.append(f'<p class="why"><b>Karşı-görüş:</b> {_e(f["rebuttal"])}</p>')
            if f.get("proposed_text"):
                o.append('<div class="prop"><div class="label">Önerilen madde metni</div>'
                         f'<p>{_e(f["proposed_text"])}</p></div>')
            if f.get("negotiation_note"):
                o.append(f'<p class="basis"><b>Müzakere argümanı:</b> {_e(f["negotiation_note"])}</p>')
            if f.get("legal_basis"):
                o.append(f'<p class="basis"><b>Dayanak:</b> {_e("; ".join(f["legal_basis"]))}</p>')
            o.append('<div class="tags">'
                     f'<span>güven {int(round(float(f.get("confidence", 0)) * 100))}%</span>'
                     f'<span>tespit: {_e(f.get("detected_by"))}</span>'
                     + (f'<span>mercek: {_e(f["lens"])}</span>' if f.get("lens") else "")
                     + "</div>")
            o.append("</article>")

    if not findings:
        o.append("<p>Playbook kontrollerinde bulgu üretilmedi.</p>")

    # --- sözlük: raporda geçen madde tiplerinin sade anlatımı ---
    gecen = []
    goruldu: set[str] = set()
    for f in findings:
        kod = f.get("code", "")
        if kod and kod not in goruldu and (pb.get(kod) and pb[kod].plain_tr):
            goruldu.add(kod)
            gecen.append(pb[kod])
    if gecen:
        gecen.sort(key=lambda c: c.name_tr)
        o.append('<h2 class="sec">Terimler sözlüğü</h2>')
        o.append('<p class="sec-note">Raporda geçen madde tiplerinin hukuk dili '
                 "kullanmadan açıklaması.</p>")
        o.append('<dl class="sozluk">')
        for ct in gecen:
            o.append(f"<dt>{_e(ct.name_tr)}</dt><dd>{_e(ct.plain_tr)}</dd>")
        o.append("</dl>")

    # --- model kullanımı ---
    u = payload.get("usage") or {}
    if u.get("calls") or u.get("budget_disabled_reason"):
        gi, ci, co = (u.get("input_tokens", 0), u.get("cache_read_tokens", 0),
                      u.get("output_tokens", 0))
        toplam_token = gi + ci + co
        top = max(toplam_token, 1)
        basarisiz = int(u.get("failed", 0) or 0)
        o.append('<section class="usage"><h2 class="sec" style="margin-top:0">Model kullanımı</h2>')
        o.append('<p class="sec-note">Bu analiz için harcanan token ve maliyet.</p>')

        # Model devre disi kaldiysa rapor bunu SUSMAZ.
        if u.get("budget_disabled_reason"):
            o.append('<p class="notice">'
                     f'<b>Model devre dışı bırakıldı:</b> {_e(u["budget_disabled_reason"])}. '
                     "Etkilenen maddeler kural katmanıyla işlendi; bu bulgular playbook'tan "
                     "deterministik olarak çıkarılmıştır."
                     + (f' İlk hata: {_e(u.get("first_error"))}' if u.get("first_error") else "")
                     + "</p>")
        elif basarisiz:
            o.append('<p class="notice">'
                     f"<b>{basarisiz} model çağrısı başarısız oldu</b>; ilgili maddeler kural "
                     "katmanıyla işlendi."
                     + (f' İlk hata: {_e(u.get("first_error"))}' if u.get("first_error") else "")
                     + "</p>")

        o.append('<div class="usage-top">')
        for etiket, deger in [
            ("Toplam token", f'{u.get("total_tokens", 0):,}'.replace(",", ".")),
            ("Girdi", f'{gi:,}'.replace(",", ".")),
            ("Çıktı", f'{co:,}'.replace(",", ".")),
            ("Model çağrısı", f'{u.get("succeeded", u.get("calls", 0))}'
                              + (f' / {u.get("calls", 0)}' if basarisiz else "")),
            ("Maliyet", (f'${u.get("cost_usd", 0):.4f}' if u.get("cost_known", True)
                         else '—')),
            ("Ort. gecikme", f'{u.get("avg_latency_ms", 0):,}'.replace(",", ".") + '<span class="u"> ms</span>'),
        ]:
            o.append(f'<div><b>{deger}</b><span class="label">{_e(etiket)}</span></div>')
        o.append("</div>")

        if toplam_token:
            o.append('<div class="bar">'
                     f'<span class="b-in" style="width:{gi/top*100:.2f}%"></span>'
                     f'<span class="b-cache" style="width:{ci/top*100:.2f}%"></span>'
                     f'<span class="b-out" style="width:{co/top*100:.2f}%"></span>'
                     "</div>")
        if toplam_token:
            o.append('<div class="legend">'
                     f'<span><i style="background:var(--indigo)"></i>Girdi<span class="n">'
                     f'{gi:,}'.replace(",", ".") + f' · %{gi/top*100:.0f}</span></span>'
                     + (f'<span><i style="background:color-mix(in srgb,var(--indigo) 45%,var(--surface))"></i>'
                        f'Önbellekten okunan<span class="n">{ci:,}'.replace(",", ".")
                        + f' · %{ci/top*100:.0f}</span></span>' if ci else "")
                     + f'<span><i style="background:var(--high)"></i>Çıktı<span class="n">'
                     + f'{co:,}'.replace(",", ".") + f' · %{co/top*100:.0f}</span></span>'
                     + "</div>")
        else:
            o.append('<p class="basis">Başarılı model çağrısı olmadığı için token '
                     "harcanmamıştır. Analiz tamamen kural katmanıyla üretilmiştir.</p>")
        if toplam_token and not u.get("cost_known", True):
            o.append('<p class="basis">Bu modelin birim fiyatı bilinmediği için maliyet '
                     "hesaplanmadı. Model ayarları panelinden 1M token fiyatlarını "
                     "girerseniz maliyet raporlanır.</p>")

        if u.get("by_agent"):
            o.append('<div class="wrapscroll" style="margin-top:22px"><table>')
            o.append("<tr><th>Görev</th><th>Model</th><th class=\"num-r\">Çağrı</th>"
                     "<th class=\"num-r\">Hata</th>"
                     "<th class=\"num-r\">Girdi</th><th class=\"num-r\">Çıktı</th>"
                     "<th class=\"num-r\">Maliyet</th><th class=\"num-r\">Ort. süre</th></tr>")
            for a in u["by_agent"]:
                o.append(
                    f'<tr><td class="agent">{_e(a["agent"])}</td>'
                    f'<td>{_e(a.get("model"))}</td>'
                    f'<td class="num-r">{a["calls"]}</td>'
                    f'<td class="num-r">{a.get("failed", 0) or "—"}</td>'
                    f'<td class="num-r">{a["input_tokens"]:,}'.replace(",", ".") + "</td>"
                    f'<td class="num-r">{a["output_tokens"]:,}'.replace(",", ".") + "</td>"
                    f'<td class="num-r">${a["cost_usd"]:.5f}</td>'
                    f'<td class="num-r">{a["avg_latency_ms"]:,}'.replace(",", ".") + " ms</td></tr>")
            o.append("</table></div>")

        o.append("</section>")

    # --- yöntem ---
    m = payload.get("method", {}) or {}
    b = m.get("budget") or {}
    o.append('<section class="method"><h2 class="sec" style="margin-top:0">Yöntem ve kapsam</h2>')
    o.append('<div class="wrapscroll"><table>')
    satirlar = [
        ("Playbook madde tipi sayısı", m.get("playbook_size")),
        ("Bu sözleşme tipi için zorunlu madde", m.get("mandatory_count")),
        ("Analiz motoru", payload.get("engine")),
        ("Doğrulamada düşen bulgu", m.get("dropped")),
        ("Model çağrısı", m.get("llm_calls")),
        ("Tahmini model maliyeti",
         (f"${float(m.get('cost_usd', 0) or 0):.4f}" if (payload.get("usage") or {}).get("cost_known", True)
          else "— (modelin birim fiyatı bilinmiyor)")),
    ]
    if b.get("disabled_reason"):
        satirlar.append(("Model bütçesi", b["disabled_reason"]))
    for k, v in satirlar:
        o.append(f"<tr><td>{_e(k)}</td><td>{_e(v)}</td></tr>")
    o.append("</table></div>")
    o.append('<p class="basis" style="margin-top:14px">Her bulgu, sözleşme metninden birebir '
             "alıntı ile doğrulanmıştır; alıntısı kaynak metinde bulunamayan bulgular rapora "
             "alınmaz. Dayanak alanları playbook'ta tanımlı listeden seçilir.</p>")
    o.append("</section>")

    o.append("<footer><strong>Bu rapor hukuki mütalaa yerine geçmez.</strong> "
             "Karar-destek çıktısıdır; bulgular alıcının sözleşme playbook'una ve ilgili "
             "mevzuata göre otomatik üretilmiştir ve imza öncesinde Hukuk Müşavirliği "
             "tarafından değerlendirilmelidir.</footer>")
    o.append("</div>")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(o), encoding="utf-8")
    return out_path
