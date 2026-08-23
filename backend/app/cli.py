"""Terminalden tek sozlesme analizi: `python -m app.cli <dosya>`

Sunucu acmadan duman testi ve toplu isleme icin.
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

from .db import engine, session_scope
from .models import Base, Contract
from . import runner


def main() -> int:
    ap = argparse.ArgumentParser(description="Sozlesme risk analizi")
    ap.add_argument("path", help="PDF / DOCX / TXT dosya yolu")
    ap.add_argument("--type", default="SAAS", help="Sozlesme tipi (SAAS, YAZILIM, HIZMET, ...)")
    ap.add_argument("--no-personal-data", action="store_true")
    ap.add_argument("--outsourcing", action="store_true")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)-7s %(message)s",
    )

    src = Path(args.path)
    if not src.exists():
        print(f"Dosya bulunamadi: {src}", file=sys.stderr)
        return 2

    Base.metadata.create_all(engine)
    with session_scope() as s:
        c = Contract(
            title=src.stem,
            filename=src.name,
            storage_path=str(src.resolve()),
            contract_type=args.type,
            involves_personal_data=not args.no_personal_data,
            is_outsourcing=args.outsourcing,
        )
        s.add(c)
        s.flush()
        cid = c.id

    t0 = time.perf_counter()
    runner.execute(cid)
    elapsed = time.perf_counter() - t0

    p = runner.progress(cid)
    print()
    print(f"  Sozlesme : {p['filename']}")
    print(f"  Karsi taraf: {p['counterparty'] or '-'}")
    print(f"  Skor     : {p['risk_score']} / 100  [{p['risk_band']}]")
    if p["veto_reason"]:
        print(f"  Veto     : {p['veto_reason']}")
    print(f"  Sure     : {elapsed:.1f} sn")
    print()
    for r in p["reports"]:
        print(f"  {r['fmt']:5} {r['filename']}  ({r['size_bytes']/1024:.0f} KB)")
    return 0 if p["run_status"] == "DONE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
