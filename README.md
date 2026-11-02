# Clearcost

**Making New York hospital prices readable.** Every U.S. hospital has to publish its
prices in a machine-readable file (MRF) under federal rule 45 CFR 180.50, but the files
are so large and messy that almost no one can use them. Clearcost parses the real filings
and lays one procedure next to itself across hospitals, so you can see the gap.

This repository is a complete, deployable project: a streaming parser, the real data it
produced, and a single self-contained web app. It runs with no server and no database.

## What the real data shows

Parsed from the spring 2026 filings of nine New York hospitals (Mount Sinai, NYU Langone,
NewYork-Presbyterian):

* An **MRI of the brain** ranges from about $1,043 to $4,860, a 4.7x gap.
* A **diagnostic colonoscopy** ranges from about $352 to $3,060, an 8.7x gap.
* Hospitals in the same system share one price list, so the real gap is *between* systems.

## Repository map

```
clearcost/
  index.html                  the built app (open it, or deploy it)
  clearcost.template.html      the app with a __DATA__ placeholder
  build.py                     bakes data/data.json into index.html
  pipeline/
    ingest.py                  the streaming MRF parser (the core of the project)
  data/
    data.json                  parsed, comparable dataset the app embeds
    mrfs/                       put downloaded hospital MRFs here (git-ignored)
  requirements.txt             ijson
  Makefile                     make install / data / build / serve
  .github/workflows/deploy.yml GitHub Pages deploy on push
```

## Quickstart

```bash
pip install -r requirements.txt      # or: make install

# 1. put one or more hospital MRFs (.json or .csv) into data/mrfs/
# 2. parse them into the dataset
python pipeline/ingest.py data/mrfs data/data.json    # or: make data
# 3. bake the data into the app
python build.py                                        # or: make build
# 4. preview
python -m http.server 8000                             # or: make serve
# open http://localhost:8000
```

Add a hospital by dropping its MRF into `data/mrfs/` and re-running. Add a procedure by
adding its billing code to the `SHOPPABLE` dictionary in `pipeline/ingest.py`.

## Where to get the real data

Each hospital hosts its own MRF. The reliable way to find one: open
`https://www.<hospital>.org/cms-hpt.txt`, which by law points to the file, or search
`"<hospital name> standard charges machine readable file"`. Aggregators such as Turquoise
Health and PatientRightsAdvocate.org list many at once. The CMS format reference lives at
https://github.com/CMSgov/hospital-price-transparency.

The files are big (a major hospital can be hundreds of MB to a few GB), which is why the
parser streams them.

## What `pipeline/ingest.py` had to handle

These are the real quirks the parser reconciles. They are the point of the project:

1. **CPT codes labelled "HCPCS".** Mount Sinai tags CPT codes as HCPCS. Keying strictly on
   CPT finds nothing, so the matcher treats CPT and HCPCS as equivalent.
2. **One procedure split across lines.** A code often appears on a chargemaster line (gross
   and cash) and a separate negotiated line (payer rates). The parser merges them so neither
   is lost.
3. **Three file shapes.** Mount Sinai and NewYork-Presbyterian ship JSON; NYU Langone ships
   a CSV "wide" file with 3,841 columns. One parser handles JSON, wide CSV, and tall CSV.
4. **Huge files.** 470 MB CSVs are stream-parsed, with a cheap row pre-filter that skips the
   vast majority of rows, so memory stays flat.
5. **Non-UTF-8 bytes.** NYU exports contain Windows-1252 characters; the reader decodes
   leniently rather than crashing.
6. **Multi-campus files.** NewYork-Presbyterian bundles several campuses under one name;
   names are normalised with a small lookup so the interface stays clean.

## Deploy it

`index.html` is one self-contained file (the data is inside it), so any static host works.

**GitHub Pages (push and go).** Push this repo to GitHub, then set repo Settings > Pages >
Source to "GitHub Actions". The included workflow publishes on every push to `main`; your
site goes live at `https://<you>.github.io/<repo>/`.

**Netlify or Vercel (drag and drop).** On Netlify, drag the project folder onto
app.netlify.com. On Vercel, run `vercel` in the folder.

**Locally.** Open `index.html` directly, or run `make serve`.

If you ever split `data.json` back out and load it with `fetch()` instead of inlining, serve
over http (the options above), not the `file://` protocol, or the browser will block the read.

## Honest limits

* The default figure is the **cash price**; many hospitals leave it blank for surgeries and
  deliveries, so use the **insurer rate** tab there.
* The insurer range reflects many plans and can include outlier or case-rate contracts, so
  read it as indicative, not a quote for your plan.
* Prices reflect the files as published in spring 2026 and change over time; re-run the
  pipeline to refresh.

This is a research prototype, not medical or billing advice.

## License

MIT, see `LICENSE`. Hospital price data is published under 45 CFR 180.50 and used here for
research and transparency.
