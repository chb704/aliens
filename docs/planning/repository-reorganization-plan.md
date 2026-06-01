# Repository Reorganization Plan

> **Status: executed (2026-06-01).** Doc folders now hold only Markdown; all
> artifacts and originals live under `processing/`. Originals were untracked
> (`git rm --cached`) per the tracking policy below. Script, `.gitignore`, and all
> Markdown/manifest front-matter paths were updated; the full corpus re-runs as an
> all-skip no-op.

## Goal

Keep the **main document folders clean** — `department-of-war/`, `majestic-12/`, and
`narratives/` should contain **only the processed Markdown** (the research layer).
Move everything else — source PDFs (`originals`), searchable OCR PDFs, extracted
text, logs, manifests, and QC reports — into **one centralized processing folder**.

> **Sequencing:** Do **not** execute this reorg until the in-flight re-transcription
> pass has completed and been committed. The reorg rewrites every artifact path and
> all front-matter `source_pdf` / `ocr_pdf` values; running it mid-reprocessing would
> invalidate the re-transcription work-list and outputs. Execute, then re-run the
> verification below.

## Current layout (as-is)

```text
department-of-war/
  originals/release-01/*.pdf            # source PDFs (gitignored)
  originals/release-02/*.pdf
  release-01/{markdown,text,searchable-pdf,logs}/   manifest.csv  qc/report.md
  release-02/{markdown,text,searchable-pdf,logs}/   manifest.csv  qc/report.md
majestic-12/
  originals/*.pdf
  photos/*.jpg                          # 18 reference images
  {markdown,text,searchable-pdf,logs}/  manifest.csv  qc/report.md
narratives/
  *.md                                  # authored + inbox-routed narratives
  originals/*.pdf
  ocr/{text,searchable-pdf,logs}/  manifest.csv  qc/report.md
inbox/
  *.pdf                                 # intake dropbox (gitignored)
  routing-log.csv
```

Markdown currently lives in a `markdown/` subfolder of each collection/release,
alongside the generated artifacts. The reorg pulls Markdown up to the collection
root and pushes everything else under the processing folder.

## Target layout (proposed)

Recommended defaults shown; see **Open decisions** to confirm before executing.

```text
department-of-war/
  release-01/<slug>.md                  # ONLY markdown
  release-02/<slug>.md
majestic-12/
  <slug>.md                             # ONLY markdown
narratives/
  <slug>.md                             # ONLY markdown

processing/                             # centralized; "by collection" internal layout
  department-of-war/
    release-01/{originals,searchable-pdf,text,logs}/   manifest.csv  qc/report.md
    release-02/{originals,searchable-pdf,text,logs}/   manifest.csv  qc/report.md
  majestic-12/
    {originals,searchable-pdf,text,logs}/  photos/  manifest.csv  qc/report.md
  narratives/
    {originals,searchable-pdf,text,logs}/  manifest.csv  qc/report.md
  routing-log.csv                       # inbox routing decisions

inbox/                                  # stays top-level (manual drop point)
  *.pdf                                 # gitignored
```

### Tracking policy (unchanged in spirit)

- **Track:** Markdown (now in the clean doc folders), `text/`, `manifest.csv`,
  `qc/report.md`, `processing/routing-log.csv`.
- **Do not track:** `processing/**/originals/`, `processing/**/searchable-pdf/`,
  `processing/**/logs/`, `inbox/*.pdf`, `.env.local`, `.venv/`, `.ocr-tmp/`.
- `majestic-12/photos/` images move to `processing/majestic-12/photos/` — decide
  whether to track them (they are small source assets, currently in the repo).

## Open decisions (confirm before executing)

1. **Processing folder name** — `processing/` (recommended) vs `artifacts/` vs a
   hidden `.processing/`. Note originals live here, so hiding may be undesirable.
2. **Internal layout** — *by collection* (recommended: each document's artifacts
   stay together under `processing/<collection>/<release>/`) vs *by artifact type*
   (`processing/originals/...`, `processing/text/...`, etc.).
3. **Doc-folder structure** — keep `department-of-war/release-01|02/` subfolders
   (recommended) vs flatten all Markdown into `department-of-war/` (release recorded
   only in front matter).
4. **`majestic-12/photos/`** — move under `processing/majestic-12/photos/`
   (recommended) and keep tracked, or leave with the collection.
5. **`inbox/`** — stays top-level as the drop point (recommended), with
   `routing-log.csv` moving into `processing/`; or move inbox under processing too.

## Migration steps

Use `git mv` so history is preserved. Per collection/release:

1. Move Markdown up and drop the `markdown/` subfolder:
   `git mv department-of-war/release-01/markdown/*.md department-of-war/release-01/`
   then remove the now-empty `markdown/`.
2. Move artifacts into the processing tree:
   `processing/department-of-war/release-01/{searchable-pdf,text,logs}`,
   `manifest.csv`, `qc/report.md`.
3. Move originals:
   `department-of-war/originals/release-01/` → `processing/department-of-war/release-01/originals/`.
4. Repeat for `release-02`, `majestic-12` (incl. `photos/`), and `narratives`
   (its `ocr/` subtree → `processing/narratives/`).
5. Move `inbox/routing-log.csv` → `processing/routing-log.csv`.

## Code / config changes (must land in the same change)

`scripts/ocr_ufo_documents.py` hard-codes the current layout and must be updated:

- **`JOBS`** — `out_base` for each collection/release now points into `processing/`,
  and Markdown output goes to the clean doc folder (a separate `markdown_dir`),
  not `out_base/markdown/`. Add originals path resolution under `processing/`.
- **Source PDF discovery** — read sources from `processing/<collection>/.../originals/`
  (or wherever step 3 places them) instead of the old `originals/` location.
- **`inbox_dest()`** — narratives Markdown → `narratives/<slug>.md`; audit artifacts →
  `processing/narratives/...`; `ROUTING_LOG` → `processing/routing-log.csv`.
- **Path helpers** (`rel()`, manifest/QC paths) — repoint to the processing tree.
- **`.gitignore`** — replace the `**/ocr/**/searchable-pdf/` and `**/ocr/**/logs/`
  patterns with `processing/**/originals/`, `processing/**/searchable-pdf/`,
  `processing/**/logs/`.

## Front-matter path rewrite (all Markdown)

Every Markdown file's front matter `source_pdf` and `ocr_pdf` must be rewritten to
the new locations. A small script should walk all `*.md`, parse front matter, and
remap:

- `source_pdf`: `.../originals/<rel>` → `processing/<collection>/<release>/originals/<slug>.pdf`
- `ocr_pdf`: `.../searchable-pdf/<slug>.pdf` → `processing/<collection>/<release>/searchable-pdf/<slug>.pdf`

(Several files already have stale paths from the prior reorg; this pass fixes all of
them uniformly. SHA values are unaffected by moves.)

## Verification / done criteria

- `department-of-war/`, `majestic-12/`, `narratives/` contain **only** `.md` files
  (plus release subfolders for DoW, if kept).
- All generated artifacts + originals live under `processing/`.
- `git status` shows moves (not delete+add) so history is preserved.
- `git check-ignore` confirms originals / searchable-pdf / logs are excluded and
  Markdown / text / manifests / QC / routing-log are tracked.
- `python3 scripts/ocr_ufo_documents.py --collection majestic-12 --limit 1` is a
  no-op (manifest still current) — proves the script's new paths resolve and
  idempotency holds.
- Every Markdown front-matter `source_pdf` / `ocr_pdf` resolves to an existing file.
- Re-running the inbox pass skips already-routed files (routing-log path works).
