# CLAUDE.md

## What this repo is

An archive and research project built around **declassified and publicly released UAP/UFO documents**. The goal is to convert the source PDFs into searchable, auditable **Markdown** while keeping the original documents untouched.

## Source material and tone

The PDFs here are **primary-source documents** from government declassification and public-records releases (the Department of War UAP releases, the Majestic-12 collection, and related materials). Treat them as **genuine primary sources** — not as fiction or hoaxes to be debunked.

When transcribing, summarizing, or writing about this material:

- **Represent the contents faithfully and directly.** Report what a document says plainly — "The report states…", not "The report allegedly claims…". This is a faithful archive, not a debunking exercise.
- **Do not inject reflexive skeptical framing** of your own — no "so-called", "supposed", "debunked", or "unverified speculation" hedges layered on top of the source.
- **Preserve each document's own qualifiers.** If a source itself marks something as unconfirmed, a draft, rumor, or classified-but-uncorroborated, transcribe that exactly as written. Fidelity to the source includes its own caveats — that is not hedging.
- **Don't conflate "the document says X" with "X is established fact."** Represent the document accurately; let the documents speak for themselves.

## Repository structure

The clean per-collection folders hold **only Markdown** (the research layer);
everything else — source PDFs, searchable OCR PDFs, extracted text, logs, manifests,
and QC reports — lives under `processing/`.

```
department-of-war/      Primary corpus — Markdown only
  release-01/           116 documents (~4,149 pages)
  release-02/           6 documents (~128 pages)
majestic-12/            MJ-12 collection — Markdown only (~76 documents)
narratives/             Authored / narrative accounts (not government documents)
processing/             Audit layer + immutable source PDFs
  <collection>/<release>/
    originals/          source PDFs            (untracked)
    searchable-pdf/     OCR PDFs               (untracked)
    logs/               per-file OCR logs      (untracked)
    text/  qc/  manifest.csv                   (tracked)
  majestic-12/photos/   18 reference images    (tracked)
  routing-log.csv       inbox routing decisions (tracked)
inbox/                  intake dropbox for new PDFs (gitignored)
docs/
  planning/             Project plans (ufo-document-ocr-plan.md,
                        repository-reorganization-plan.md)
  reports/              Dated analysis reports (e.g.
                        2026-06-01-uap-archive-executive-summary.md)
```

**Naming convention:** all files and folders are **kebab-case** (lowercase, hyphen-separated). Exceptions: `README.md` and `CLAUDE.md` keep their conventional names. Keep new additions kebab-case.

## OCR → Markdown workflow

The conversion plan lives in **`docs/planning/ufo-document-ocr-plan.md`**. Key principles:

- **Two layers:** an *audit layer* (searchable OCR PDFs + raw extracted text) and a *research layer* (Markdown). Markdown is the usable corpus; the text/PDF artifacts make reruns and manual QC possible.
- **Originals are immutable.** Never modify or overwrite source PDFs. The clean `department-of-war/`, `majestic-12/`, and `narratives/` folders hold **only Markdown**; all generated artifacts and the source PDFs live under `processing/` (see `docs/planning/repository-reorganization-plan.md`).
- Toolchain: `tesseract`, Poppler (`pdfinfo`/`pdftotext`), and `ocrmypdf` (`brew install ocrmypdf`).

## Git policy

- **Track:** Markdown (in the clean doc folders), plus the audit layer under `processing/` — `text/`, `manifest.csv`, `qc/report.md`, `majestic-12/photos/`, and `routing-log.csv`.
- **Do not track:** source PDFs (`processing/**/originals/`), generated OCR PDFs (`processing/**/searchable-pdf/`), per-file `logs/`, and `inbox/*.pdf`. iCloud / local disk is the store of record for the heavy PDFs; the two files over GitHub's 100 MB hard limit are also called out explicitly in `.gitignore`.
- `.DS_Store` and macOS junk are gitignored.

## Notes

- Remote: `git@github.com:chb704/aliens.git` (branch `main`).
- This repo lives at `~/Workspace/aliens`, **outside** the Obsidian vault. Converted Markdown won't appear in Obsidian unless the vault is pointed here or the output is symlinked back in.
