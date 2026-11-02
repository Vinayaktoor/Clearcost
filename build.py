#!/usr/bin/env python3
"""
build.py  —  bake data/data.json into the app template to produce index.html,
a single self-contained file you can host anywhere.

    python pipeline/ingest.py data/mrfs data/data.json   # 1. parse MRFs
    python build.py                                       # 2. bake into index.html
    python -m http.server 8000                            # 3. preview at localhost:8000
"""
import pathlib
import sys

root = pathlib.Path(__file__).parent
tpl = (root / "clearcost.template.html").read_text(encoding="utf-8")
data = (root / "data" / "data.json").read_text(encoding="utf-8")

if "__DATA__" not in tpl:
    sys.exit("clearcost.template.html has no __DATA__ placeholder")

(root / "index.html").write_text(tpl.replace("__DATA__", data, 1), encoding="utf-8")
print(f"built index.html  ({len((root / 'index.html').read_text()):,} bytes, "
      f"{len(data):,} bytes of data embedded)")
