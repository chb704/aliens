# UFO Document Bulk OCR to Markdown Plan

## Goal

Convert the Department of War and Majestic-12 UFO document PDFs into searchable, auditable Markdown while preserving the original PDFs untouched.

Interpretation note: "ORC" is treated as "OCR" here, based on the prior request.

## Naming Convention

All files and folders in this repo use **kebab-case** (lowercase, hyphen-separated). The paths below reflect that. Note that data-schema identifiers — YAML front-matter keys, manifest CSV column names, and shell variables (`source_pdf`, `ocr_pdf`, `text_file`, …) — intentionally stay snake_case, since those are field/variable names, not file paths.

## Current Corpus

- Source folders: `department-of-war`, `majestic-12`
- `department-of-war/release-01`: 116 PDFs, 4,149 pages
- `department-of-war/release-02`: 6 PDFs, 128 pages
- `majestic-12` PDFs: 76 PDFs, 304 pages
- `majestic-12/photos`: 18 image files, kept as reference assets and excluded from the baseline PDF OCR pass
- Total PDF OCR target: 198 PDFs, 4,581 pages

Local prerequisite check:

- `tesseract` is installed.
- `pdfinfo` and `pdftotext` are installed through Poppler.
- `ocrmypdf` is not currently installed and should be added before the first run.

## Recommended Approach

Use a two-layer pipeline:

1. Build searchable OCR PDFs and extracted text as generated artifacts.
2. Convert the extracted text into Markdown as the repo-facing corpus.

Do not OCR directly into Markdown as the only output. Markdown is the usable research layer, but OCR PDFs and raw text are the audit layer. They make reruns, debugging, and manual review much easier.

## Target Output Layout

Keep generated content out of the source release folders:

```text
department-of-war/
  release-01/
  release-02/
  ocr/
    release-01/
      searchable-pdf/
      text/
      markdown/
      logs/
      qc/
      manifest.csv
    release-02/
      searchable-pdf/
      text/
      markdown/
      logs/
      qc/
      manifest.csv

majestic-12/
  ocr/
    searchable-pdf/
    text/
    markdown/
    logs/
    qc/
    manifest.csv
```

Recommended Git policy:

- Track Markdown, manifests, and QC reports.
- Do not track searchable OCR PDFs by default unless we explicitly want generated binary artifacts in the repo.
- Keep source PDFs as the immutable originals.

## Toolchain

Install:

```bash
brew install ocrmypdf
```

Baseline command per file:

```bash
ocrmypdf \
  -l eng \
  --mode skip \
  --rotate-pages \
  --deskew \
  --clean \
  --optimize 1 \
  "$source_pdf" \
  "$ocr_pdf"
```

Then extract complete text from the OCR PDF:

```bash
pdftotext -layout "$ocr_pdf" "$text_file"
```

Reason: OCRmyPDF sidecar text is useful, but it may omit pages that already contained embedded text. Extracting text from the final searchable PDF produces one complete text stream per document.

## Markdown Format

Each source PDF should produce one Markdown file with front matter and explicit page boundaries:

```markdown
---
title: "Original PDF stem"
collection: "department-of-war"
release: "release-01"
source_pdf: "department-of-war/release-01/example.pdf"
ocr_pdf: "department-of-war/ocr/release-01/searchable-pdf/example.pdf"
source_sha256: "..."
ocr_sha256: "..."
pages: 12
ocr_engine: "ocrmypdf + tesseract"
text_extractor: "pdftotext -layout"
needs_review: false
---

# Original PDF stem

## Page 1

OCR text...

## Page 2

OCR text...
```

For `majestic-12` documents, use `collection: "majestic-12"` and `release: null`.

Use form-feed page separators from `pdftotext` to split pages. Keep page numbers stable even when a page is blank.

## Metadata Manifest

Generate one `manifest.csv` per release or collection with:

- `collection`
- `release`
- `source_pdf`
- `source_sha256`
- `source_bytes`
- `pages`
- `ocr_pdf`
- `ocr_sha256`
- `text_file`
- `markdown_file`
- `ocr_exit_code`
- `ocr_seconds`
- `text_chars`
- `chars_per_page`
- `empty_pages`
- `needs_review`
- `error`

This makes the run idempotent. If the source SHA256 and tool versions have not changed, skip the file.

## Quality Control

Flag files for review when:

- OCR command fails or times out.
- Extracted text is empty.
- Average text density is suspiciously low, for example under 80 characters per page.
- More than 20 percent of pages are empty.
- Output contains obvious binary garbage or repeated replacement characters.
- `pdfinfo` cannot read the source PDF.

Produce:

```text
department-of-war/ocr/release-01/qc/report.md
department-of-war/ocr/release-02/qc/report.md
majestic-12/ocr/qc/report.md
```

Each report should list:

- Completed files
- Failed files
- Review-needed files
- Longest files by page count
- Lowest text-density files
- Total pages processed
- Total runtime

## Pilot Run

Before processing all 4,581 pages, run a 15 to 20 document pilot across both collections:

- A few short modern mission reports from `dow-uap-*`
- A few long FBI files, especially `65-hs1-*`
- One or two NASA transcript files
- One image-heavy or sketch/photo PDF
- The longest release-02 file: `dow-uap-d017-general-correspondence-of-sandia.pdf`
- A few short `majestic-12` PDFs with clean type, for example `truman-forrestal.pdf` or `fdr.pdf`
- A few noisy or image-heavy `majestic-12` PDFs, for example `burnedmemo-s1-pgs1-2.pdf`, `som101-part1.pdf`, or `twining-whitehotreport.pdf`

Review:

- OCR readability
- Page splitting
- Whether `--clean` harms stamps, handwriting, images, or faint type
- Whether rotated pages are handled correctly
- Whether Markdown is useful in Obsidian search

If `--clean` damages visible content, rerun without it. Do not use `--clean-final` in the baseline because it can alter the visible page image more aggressively.

## Implementation Plan

1. Add `scripts/ocr_ufo_documents.py`.
2. Add a small config section at the top of the script for source and output directories.
3. Walk `department-of-war/release-01`, `department-of-war/release-02`, and root-level PDFs in `majestic-12`.
4. Compute source SHA256 and page counts.
5. Skip completed files when manifest data still matches.
6. Run OCRmyPDF into `searchable-pdf`.
7. Extract complete text with `pdftotext -layout`.
8. Convert text to Markdown with page boundaries and front matter.
9. Write per-file logs.
10. Write manifest and QC report.

The script should support:

```bash
python3 scripts/ocr_ufo_documents.py --collection department-of-war --release release-01 --limit 10
python3 scripts/ocr_ufo_documents.py --collection department-of-war --release release-01
python3 scripts/ocr_ufo_documents.py --collection department-of-war --release release-02
python3 scripts/ocr_ufo_documents.py --collection majestic-12 --limit 10
python3 scripts/ocr_ufo_documents.py --collection majestic-12
python3 scripts/ocr_ufo_documents.py --all
python3 scripts/ocr_ufo_documents.py --all --force
```

## Cleanup Rules

Keep cleanup conservative:

- Normalize repeated blank lines.
- Trim trailing spaces.
- Preserve page boundaries.
- Preserve classification markings, dates, headers, stamps, handwritten-note text, and uncertain OCR.
- Do not rewrite names or inferred acronyms automatically.
- Do not summarize in the OCR pass.

Later, add a separate enrichment pass for summaries, entities, timelines, and cross-document links. That should not be mixed into raw OCR generation.

## Optional Second Pass

Use Docling selectively after the baseline run, not as the baseline:

- Good candidate: tables, structured reports, clean born-digital PDFs.
- Weak candidate: poor scans, stamps, marginalia, handwritten notes, messy photocopies.

The baseline pipeline is more deterministic and easier to audit. Docling can produce richer Markdown or JSON where layout matters, but it should be compared against the raw OCR text before replacing it.

## Done Criteria

- All 198 PDFs have manifest entries.
- All readable PDFs have Markdown outputs.
- Failed PDFs are listed with errors.
- Review-needed PDFs are listed with concrete reasons.
- No source PDFs are modified.
- Re-running the script is safe and skips unchanged work.
- Markdown files are searchable and page-addressable.

## Sources

- OCRmyPDF Cookbook: https://ocrmypdf.readthedocs.io/en/latest/cookbook.html
- OCRmyPDF Advanced Features: https://ocrmypdf.readthedocs.io/en/latest/advanced.html
- Tesseract Command Line Usage: https://tesseract-ocr.github.io/tessdoc/Command-Line-Usage.html
- Tesseract User Manual: https://tesseract-ocr.github.io/tessdoc/
- Docling Usage: https://docling-project.github.io/docling/usage/
