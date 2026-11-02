#!/usr/bin/env python3
"""
ingest.py  —  CMS Hospital Price Transparency MRF normalizer (streaming)

Reads the machine-readable files (MRFs) U.S. hospitals must publish under
45 CFR 180.50 (CMS template v3.0.0) and flattens them into ONE comparable
dataset. Built against REAL files from Mount Sinai, NYU Langone, and
NewYork-Presbyterian, which between them use every shape the rule allows:

  - JSON                (Mount Sinai, NYP)        -> streamed with ijson
  - CSV "wide"  layout  (NYU Langone, 3800+ cols) -> one row per item
  - CSV "tall"  layout  (CMS sample, many systems)-> one row per payer line

Every reader streams: a 470 MB file is processed in a single pass with flat
memory, extracting only the shoppable billing codes we compare.

Usage:
    python ingest.py INPUT_DIR OUTPUT_JSON
"""

import csv
import json
import os
import re
import sys
from collections import defaultdict

import ijson

csv.field_size_limit(10 * 1024 * 1024)  # some cells are huge

# ------------------------------------------------------------------ what to compare

# Common, planned ("shoppable") procedures, keyed CODE_TYPE:CODE.
SHOPPABLE = {
    "CPT:70551": "MRI, brain (no contrast)",
    "CPT:74177": "CT, abdomen & pelvis (with contrast)",
    "CPT:45378": "Colonoscopy (diagnostic)",
    "CPT:77067": "Screening mammogram (both breasts)",
    "CPT:93306": "Echocardiogram (complete, with Doppler)",
    "CPT:80053": "Comprehensive metabolic panel (blood test)",
    "CPT:80048": "Basic metabolic panel (blood test)",
    "CPT:66984": "Cataract surgery (with lens implant)",
    "CPT:49505": "Inguinal hernia repair",
    "CPT:29881": "Knee arthroscopy (with meniscus repair)",
    "CPT:43239": "Upper GI endoscopy (with biopsy)",
    "CPT:59400": "Vaginal delivery (global care)",
    "CPT:59510": "Cesarean delivery (global care)",
    "CPT:36415": "Routine blood draw",
    "CPT:72148": "MRI, lower spine (no contrast)",
    "CPT:93000": "Electrocardiogram (EKG, complete)",
    "MS-DRG:470": "Major hip / knee joint replacement (no complications)",
    "MS-DRG:807": "Vaginal delivery (no complications)",
}
SHOP_CODES = {k.split(":", 1)[1] for k in SHOPPABLE}  # bare codes for pre-filter
PREFILTER = re.compile(r"(?<!\d)(" + "|".join(sorted(SHOP_CODES, key=len, reverse=True)) + r")(?!\d)")

# Clean display name + borough per file (an engineer-maintained normalization,
# so messy multi-campus hospital_name fields don't leak into the UI).
HOSPITAL_META = {
    "mount-sinai-hospital":            ("The Mount Sinai Hospital", "Manhattan", "academic"),
    "mount-sinai-brooklyn":            ("Mount Sinai Brooklyn", "Brooklyn", "community"),
    "mount-sinai-queens":              ("Mount Sinai Queens", "Queens", "community"),
    "newyork-presbyterian":            ("NewYork-Presbyterian", "Manhattan", "academic"),
    "nyu-langone-tisch":               ("NYU Langone (Tisch)", "Manhattan", "academic"),
    "nyu-langone-brooklyn":            ("NYU Langone Brooklyn", "Brooklyn", "community"),
    "nyu-langone-long-island":         ("NYU Langone Long Island", "Long Island", "community"),
    "nyu-langone-health-suffolk":      ("NYU Langone Suffolk", "Suffolk", "community"),
    "nyu-langone-orthopedic-hospital": ("NYU Langone Orthopedic", "Manhattan", "specialty"),
}
CODE_PREF = ("CPT", "HCPCS", "MS-DRG", "DRG", "APR-DRG")


def meta_for(filename):
    for key, m in HOSPITAL_META.items():
        if key in filename:
            return m
    return (filename, None, None)


def to_number(v):
    if v is None:
        return None
    s = str(v).strip().replace("$", "").replace(",", "")
    if s == "" or s.upper() in ("N/A", "NA", "NONE"):
        return None
    try:
        n = float(s)
        return n if n > 0 else None
    except ValueError:
        return None


CPT_LIKE = {"CPT", "HCPCS"}                       # hospitals label CPT codes either way
DRG_LIKE = {"MS-DRG", "MSDRG", "DRG", "APR-DRG", "APRDRG"}


def shoppable_key(codes):
    """codes: iterable of (code, type). Return the matching SHOPPABLE key, or None.
    Treats CPT and HCPCS as equivalent and normalises DRG spelling / leading zeros,
    because real files are wildly inconsistent about all three."""
    for code, ctype in codes:
        if not code or not ctype:
            continue
        c = str(code).strip()
        t = str(ctype).strip().upper().replace(" ", "")
        cands = []
        if t in CPT_LIKE:
            cands.append(f"CPT:{c}")
        if t in DRG_LIKE:
            cands.append(f"MS-DRG:{c.lstrip('0') or c}")
        cands.append(f"{t}:{c}")
        for k in cands:
            if k in SHOPPABLE:
                return k
    return None


# ------------------------------------------------------------------ JSON (streaming)

def parse_json_mrf(path, add):
    name, borough, htype = meta_for(os.path.basename(path))
    with open(path, "rb") as f:
        for item in ijson.items(f, "standard_charge_information.item"):
            desc = (item.get("description") or "").strip()
            codes = [(c.get("code"), c.get("type"))
                     for c in item.get("code_information", []) or []]
            key = shoppable_key(codes)
            if key is None:
                continue
            ctype, code = key.split(":", 1)
            for sc in item.get("standard_charges", []) or []:
                payer_dollars = [to_number(p.get("standard_charge_dollar"))
                                 for p in sc.get("payers_information", []) or []]
                payer_dollars = [d for d in payer_dollars if d]
                add(key, name, borough, htype, desc, code, ctype,
                    setting=sc.get("setting"),
                    gross=to_number(sc.get("gross_charge")),
                    cash=to_number(sc.get("discounted_cash")),
                    mn=to_number(sc.get("minimum")) or (min(payer_dollars) if payer_dollars else None),
                    mx=to_number(sc.get("maximum")) or (max(payer_dollars) if payer_dollars else None))


# ------------------------------------------------------------------ CSV (wide + tall)

def _read_headers(path):
    # real exports are often Windows-1252, not UTF-8 (stray 0xA0 etc.), so decode leniently
    f = open(path, "r", encoding="utf-8-sig", errors="replace", newline="")
    reader = csv.reader(f)
    next(reader, [])                       # meta headers (unused for pricing)
    next(reader, [])                       # meta values
    item_h = [h.strip() for h in next(reader, [])]
    return f, reader, item_h


def parse_csv_mrf(path, add):
    name, borough, htype = meta_for(os.path.basename(path))
    f, reader, hdr = _read_headers(path)
    idx = {h: i for i, h in enumerate(hdr)}

    def col(row, key):
        i = idx.get(key)
        return row[i].strip() if i is not None and i < len(row) and row[i] is not None else ""

    def codes_in(row):
        out = []
        for h in hdr:
            m = re.match(r"code\s*\|\s*(\d+)\s*$", h)
            if m:
                n = m.group(1)
                c = col(row, h)
                t = col(row, f"code|{n}|type") or col(row, f"code | {n} | type")
                if c and t:
                    out.append((c, t))
        return out

    wide = "payer_name" not in hdr   # tall has a bare payer_name column; wide does not

    def hkey_find(pattern):
        return next((h for h in hdr if re.fullmatch(pattern, h)), None)

    gross_k = hkey_find(r"standard_charge\s*\|\s*gross")
    cash_k  = hkey_find(r"standard_charge\s*\|\s*discounted_cash")
    min_k   = hkey_find(r"standard_charge\s*\|\s*min")
    max_k   = hkey_find(r"standard_charge\s*\|\s*max")

    if wide:
        neg_cols = [i for i, h in enumerate(hdr) if h.endswith("|negotiated_dollar")]
        for raw in reader:
            if not PREFILTER.search(",".join(raw)):
                continue
            key = shoppable_key(codes_in(raw))
            if key is None:
                continue
            ctype, code = key.split(":", 1)
            negs = [to_number(raw[i]) for i in neg_cols if i < len(raw)]
            negs = [d for d in negs if d]
            add(key, name, borough, htype, col(raw, "description"), code, ctype,
                setting=col(raw, "setting"),
                gross=to_number(col(raw, gross_k)) if gross_k else None,
                cash=to_number(col(raw, cash_k)) if cash_k else None,
                mn=to_number(col(raw, min_k)) if min_k else (min(negs) if negs else None),
                mx=to_number(col(raw, max_k)) if max_k else (max(negs) if negs else None))
    else:
        neg_k = hkey_find(r"standard_charge\s*\|\s*negotiated_dollar")
        items = {}
        for raw in reader:
            if not PREFILTER.search(",".join(raw)):
                continue
            key = shoppable_key(codes_in(raw))
            if key is None:
                continue
            ctype, code = key.split(":", 1)
            gk = (col(raw, "description"), key, col(raw, "setting"))
            it = items.setdefault(gk, {"negs": [], "row": raw, "code": code, "ctype": ctype})
            d = to_number(col(raw, neg_k)) if neg_k else None
            if d:
                it["negs"].append(d)
        for (desc, key, setting), it in items.items():
            raw = it["row"]
            add(key, name, borough, htype, desc, it["code"], it["ctype"],
                setting=setting,
                gross=to_number(col(raw, gross_k)) if gross_k else None,
                cash=to_number(col(raw, cash_k)) if cash_k else None,
                mn=to_number(col(raw, min_k)) if min_k else (min(it["negs"]) if it["negs"] else None),
                mx=to_number(col(raw, max_k)) if max_k else (max(it["negs"]) if it["negs"] else None))
    f.close()


# ------------------------------------------------------------------ orchestration

def normalize(input_dir):
    hospitals, hid = {}, {}
    best = defaultdict(dict)  # procedure key -> hospital_id -> offer

    def add(key, name, borough, htype, desc, code, ctype,
            setting, gross, cash, mn, mx):
        if cash is None and gross is None and mn is None:
            return
        if name not in hid:
            i = f"h{len(hid)+1}"
            hid[name] = i
            hospitals[i] = {"id": i, "name": name, "borough": borough,
                            "type": htype, "state": "NY"}
        h = hid[name]
        # One procedure is often split across several charge lines (facility vs
        # professional, chargemaster vs negotiated). MERGE their fields so we keep
        # the cash price AND the negotiated range rather than dropping either.
        rec = best[key].get(h)
        if rec is None:
            rec = {"hospital_id": h, "setting": setting,
                   "cash": None, "gross": None, "min_neg": None, "max_neg": None}
            best[key][h] = rec
        if cash is not None:
            rec["cash"] = cash if rec["cash"] is None else max(rec["cash"], cash)
        if gross is not None:
            rec["gross"] = gross if rec["gross"] is None else max(rec["gross"], gross)
        if mn is not None:
            rec["min_neg"] = mn if rec["min_neg"] is None else min(rec["min_neg"], mn)
        if mx is not None:
            rec["max_neg"] = mx if rec["max_neg"] is None else max(rec["max_neg"], mx)
        if setting and not rec.get("setting"):
            rec["setting"] = setting

    files = [fn for fn in sorted(os.listdir(input_dir))
             if fn.lower().endswith((".json", ".csv"))]
    for fn in files:
        path = os.path.join(input_dir, fn)
        size_mb = os.path.getsize(path) / 1e6
        sys.stdout.write(f"  {fn[:50]:50s} {size_mb:6.0f} MB … ")
        sys.stdout.flush()
        try:
            before = sum(len(v) for v in best.values())
            (parse_json_mrf if fn.lower().endswith(".json") else parse_csv_mrf)(path, add)
            after = sum(len(v) for v in best.values())
            print(f"ok (+{after - before} offers)")
        except Exception as e:
            print(f"SKIPPED: {e}")

    procedures = []
    for key, offers_by_h in best.items():
        offers = list(offers_by_h.values())
        if len({o["hospital_id"] for o in offers}) >= 2:
            code_type, code = key.split(":", 1)
            procedures.append({"key": key, "label": SHOPPABLE[key],
                               "code": code, "code_type": code_type,
                               "offers": offers})
    procedures.sort(key=lambda p: p["label"])
    return {
        "generated_from": os.path.basename(os.path.normpath(input_dir)),
        "hospital_count": len(hospitals),
        "procedure_count": len(procedures),
        "hospitals": list(hospitals.values()),
        "procedures": procedures,
    }


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__); sys.exit(1)
    in_dir, out_path = sys.argv[1], sys.argv[2]
    print(f"Reading MRFs from: {in_dir}")
    data = normalize(in_dir)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    print(f"\n✓ {data['hospital_count']} hospitals, "
          f"{data['procedure_count']} comparable procedures -> {out_path}")
