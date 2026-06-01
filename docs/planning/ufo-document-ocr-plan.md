# UFO Document Bulk OCR to Markdown Plan

## Goal

Convert the Department of War and Majestic-12 UFO document PDFs into searchable, auditable Markdown while preserving the original PDFs untouched.

Interpretation note: "ORC" is treated as "OCR" here, based on the prior request.

## Current Corpus

- Source folders: `Department of War`, `Majestic-12`
- Department of War `Release_01`: 116 PDFs, 4,149 pages
- Department of War `Release_02`: 6 PDFs, 128 pages
- Majestic-12 PDFs: 76 PDFs, 304 pages
- Majestic-12 photos: 18 image files, kept as reference assets and excluded from the baseline PDF OCR pass
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
Department of War/
  Release_01/
  Release_02/
  OCR/
    Release_01/
      searchable_pdf/
      text/
      markdown/
      logs/
      qc/
      manifest.csv
    Release_02/
      searchable_pdf/
      text/
      markdown/
      logs/
      qc/
      manifest.csv

Majestic-12/
  OCR/
    searchable_pdf/
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
collection: "Department of War"
release: "Release_01"
source_pdf: "Department of War/Release_01/example.pdf"
ocr_pdf: "Department of War/OCR/Release_01/searchable_pdf/example.pdf"
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

For Majestic-12 documents, use `collection: "Majestic-12"` and `release: null`.

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
Department of War/OCR/Release_01/qc/report.md
Department of War/OCR/Release_02/qc/report.md
Majestic-12/OCR/qc/report.md
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

- A few short modern mission reports from `DOW-UAP-*`
- A few long FBI files, especially `65_HS1-*`
- One or two NASA transcript files
- One image-heavy or sketch/photo PDF
- The longest Release 02 file: `DOW-UAP-D017_General_Correspondence_Of_Sandia.pdf`
- A few short Majestic-12 PDFs with clean type, for example `truman_forrestal.pdf` or `fdr.pdf`
- A few noisy or image-heavy Majestic-12 PDFs, for example `burnedmemo-s1-pgs1-2.pdf`, `som101_part1.pdf`, or `twining_whitehotreport.pdf`

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
3. Walk `Department of War/Release_01`, `Department of War/Release_02`, and root-level PDFs in `Majestic-12`.
4. Compute source SHA256 and page counts.
5. Skip completed files when manifest data still matches.
6. Run OCRmyPDF into `searchable_pdf`.
7. Extract complete text with `pdftotext -layout`.
8. Convert text to Markdown with page boundaries and front matter.
9. Write per-file logs.
10. Write manifest and QC report.

The script should support:

```bash
python3 scripts/ocr_ufo_documents.py --collection department-of-war --release Release_01 --limit 10
python3 scripts/ocr_ufo_documents.py --collection department-of-war --release Release_01
python3 scripts/ocr_ufo_documents.py --collection department-of-war --release Release_02
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
