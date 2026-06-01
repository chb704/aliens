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

```
department-of-war/      Primary corpus — official UAP document releases
  release-01/           116 PDFs (~4,149 pages)
  release-02/           6 PDFs (~128 pages)
majestic-12/            MJ-12 document collection (~76 PDFs) + photos/
narratives/             Authored / narrative accounts (not government documents)
docs/
  planning/             Project plans (see ufo-document-ocr-plan.md)
```

**Naming convention:** all files and folders are **kebab-case** (lowercase, hyphen-separated). Exceptions: `README.md` and `CLAUDE.md` keep their conventional names. Keep new additions kebab-case.

## OCR → Markdown workflow

The conversion plan lives in **`docs/planning/ufo-document-ocr-plan.md`**. Key principles:

- **Two layers:** an *audit layer* (searchable OCR PDFs + raw extracted text) and a *research layer* (Markdown). Markdown is the usable corpus; the text/PDF artifacts make reruns and manual QC possible.
- **Originals are immutable.** Never modify or overwrite source PDFs. Generated output goes in dedicated `OCR/` subfolders, kept out of the source release folders.
- Toolchain: `tesseract`, Poppler (`pdfinfo`/`pdftotext`), and `ocrmypdf` (`brew install ocrmypdf`).

## Git policy

- **Track:** Markdown, manifests, and QC reports — the research layer.
- **Do not track:** source PDFs, generated OCR PDFs, and other large binaries. The two files exceeding GitHub's 100 MB hard limit are listed explicitly in `.gitignore`; iCloud / local disk is the store of record for the heavy PDFs.
- `.DS_Store` and macOS junk are gitignored.
- Several source PDFs are 50–69 MB — above GitHub's 50 MB *recommendation* but under the 100 MB hard limit, so they push fine (with an advisory warning only).

## Notes

- Remote: `git@github.com:chb704/aliens.git` (branch `main`).
- This repo lives at `~/Workspace/aliens`, **outside** the Obsidian vault. Converted Markdown won't appear in Obsidian unless the vault is pointed here or the output is symlinked back in.
