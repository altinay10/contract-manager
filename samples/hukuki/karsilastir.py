"""İki sürümü karşılaştırıp farkı terminale döker (arayüz henüz bağlı değil).

    .venv/bin/python samples/hukuki/karsilastir.py <eski.txt> <yeni.txt>

Uygulamanın kendi hattını kullanır: coverage.units_of + compare.align.
Model çağrısı yapmaz; yalnızca deterministik katmanı gösterir.
"""
from __future__ import annotations

import sys
from pathlib import Path

KOK = Path(__file__).resolve().parents[2] / "backend"
sys.path.insert(0, str(KOK))

from app.pipeline.compare import align, stats  # noqa: E402
from app.pipeline.coverage import units_of  # noqa: E402

ISARET = {"EKLENDI": "+", "SILINDI": "-", "DEGISTI": "~", "TASINDI": "»", "AYNI": " "}


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    eski = units_of(Path(sys.argv[1]).read_text(encoding="utf-8"))
    yeni = units_of(Path(sys.argv[2]).read_text(encoding="utf-8"))
    degisiklikler = align(eski, yeni)

    for d in degisiklikler:
        if d.change_type == "AYNI":
            continue
        birim = d.new or d.old
        print(f"{ISARET[d.change_type]} {d.change_type:8s} {birim.number or '—':9s} "
              f"{birim.heading[:60]}")
        if d.change_type == "DEGISTI":
            for parca in d.word_diff:
                if parca["op"] == "delete":
                    print(f"      - {parca['text'].strip()}")
                elif parca["op"] == "insert":
                    print(f"      + {parca['text'].strip()}")

    print("\n" + ", ".join(f"{k}={v}" for k, v in stats(degisiklikler).items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
