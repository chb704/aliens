# UAP Document Archive

A research archive built around **declassified and publicly released UAP/UFO documents**. The goal is to convert source PDFs from government declassification and public-records releases into searchable, auditable **Markdown**, while keeping the original documents untouched.

The corpus currently holds **202 converted documents (~4,590 pages)** spanning roughly **1944–2026** — from the 1947 flying-disc reports and the Majestic-12 collection through the modern (2016–2025) military UAP mission reports.

## Source material and tone

The PDFs here are **primary-source documents** from government declassification and public-records releases (the Department of War UAP releases, the Majestic-12 collection, and related CIA/DoE/ODNI materials). They are treated as **genuine primary sources** and represented faithfully and directly — reporting what each document says, preserving each document's *own* qualifiers, and letting the documents speak for themselves. See [`CLAUDE.md`](CLAUDE.md) for the full editorial policy.

## Repository layout

The clean per-collection folders hold **only Markdown** (the research layer). Everything else — source PDFs, OCR PDFs, extracted text, logs, manifests, and QC reports — lives under `processing/` (the audit layer).

| Path | Contents |
|---|---|
| `department-of-war/release-01/` | 116 documents — FBI files, 1947 incident summaries, modern UAP mission-report cables |
| `department-of-war/release-02/` | 6 documents — CIA / DoE (Pantex, Sandia) / ODNI releases |
| `majestic-12/` | 76 documents — MJ-12 charter, recovery, technical & biological assessments |
| `narratives/` | 4 authored/testimonial accounts (**not** government documents) |
| `processing/` | Audit layer + immutable source PDFs (see below) |
| `docs/planning/` | Project plans (OCR pipeline, repository reorganization) |
| `docs/reports/` | Dated analysis reports |
| `scripts/` | `ocr_ufo_documents.py` — the OCR → Markdown pipeline |
| `inbox/` | Intake dropbox for new PDFs (gitignored) |

Under `processing/<collection>/<release>/`: `originals/` (source PDFs, untracked), `searchable-pdf/` (OCR PDFs, untracked), `logs/` (untracked), and the tracked `text/`, `qc/report.md`, and `manifest.csv`.

**Naming:** all files and folders are **kebab-case**, except `README.md` and `CLAUDE.md`.

## How documents are converted

The pipeline ([`docs/planning/ufo-document-ocr-plan.md`](docs/planning/ufo-document-ocr-plan.md)) produces two layers:

- **Audit layer** — searchable OCR PDFs + raw extracted text, so reruns and manual QC are possible.
- **Research layer** — one Markdown file per source PDF, with YAML front matter (provenance: source PDF, SHA-256, toolchain, page count) and explicit page boundaries. This is the usable corpus.

**Originals are immutable** — source PDFs are never modified. Toolchain: `tesseract`, Poppler (`pdfinfo` / `pdftotext`), and `ocrmypdf` (`brew install ocrmypdf`); plus `qpdf` to transparently decrypt owner-password-protected PDFs before OCR.

Run the pipeline:

```bash
# A single collection/release
python3 scripts/ocr_ufo_documents.py --collection department-of-war --release release-01

# Everything
python3 scripts/ocr_ufo_documents.py --all

# Route new PDFs dropped in inbox/
python3 scripts/ocr_ufo_documents.py --inbox
```

The pipeline is idempotent: a file is reprocessed only when its source SHA-256, the tool versions, or the OCR options change (or `--force` is given).

## Quality control

Each job writes a `manifest.csv` and a `qc/report.md`. Files are flagged `needs_review` when OCR text density is low or the empty-page ratio is high. **32 files** are currently flagged — these are inherently low-text scans (FBI photographs, fully redacted cables) and degraded originals (handwritten and fire-damaged MJ-12 memos) where no further text is recoverable; each is documented rather than reprocessed.

## Reports

Analysis reports live in [`docs/reports/`](docs/reports/):

- **[Executive summary](docs/reports/2026-06-01-uap-archive-executive-summary.md)** — overview of the converted corpus and key findings.
- **[EBE / EME entity reference](docs/reports/2026-06-01-ebe-eme-entity-reference.md)** — the document categories for non-human entities, their differences, and the field reports.
- **[Notable anecdotes](docs/reports/2026-06-01-notable-anecdotes.md)** — a curated set of the most striking individual moments in the corpus.

## Notes

- Source PDFs and generated OCR PDFs are **not** tracked in git (iCloud / local disk is the store of record for the heavy files); the clean doc folders and the audit layer's text/manifests/QC are tracked. See [`CLAUDE.md`](CLAUDE.md) for the full git policy.
- This repo lives at `~/Workspace/aliens`, outside the Obsidian vault.
