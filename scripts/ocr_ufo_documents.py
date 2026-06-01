#!/usr/bin/env python3
"""Bulk OCR of the UFO/UAP document corpus into searchable PDFs, raw text, and Markdown.

Implements docs/planning/ufo-document-ocr-plan.md.

Two layers are produced:
  * audit layer    - searchable OCR PDFs (searchable-pdf/) + raw extracted text (text/)
  * research layer - one Markdown file per source PDF (markdown/), with front matter
                     and explicit page boundaries.

Originals are never modified. All generated output lives under dedicated ocr/ trees.

Idempotency: a file is reprocessed only when its source SHA-256, the resolved tool
versions, or the OCR options change (or --force is given). Those three values are
recorded in the per-job manifest.csv, which is what makes the skip check evaluable.

Encryption note: the great majority of the Department of War PDFs report
"Encrypted: yes" but carry only an owner password (permissions flag) with an empty
*user* password -- their content is fully readable. ocrmypdf refuses encrypted input,
so such files are transparently decrypted to a temporary copy with `qpdf --decrypt`
before OCR. Only PDFs that genuinely require a user password (qpdf decrypt fails) are
flagged `encrypted` and skipped, per the plan's intent.

Usage:
  python3 scripts/ocr_ufo_documents.py --collection department-of-war --release release-01 --limit 10
  python3 scripts/ocr_ufo_documents.py --collection department-of-war --release release-01
  python3 scripts/ocr_ufo_documents.py --collection department-of-war --release release-02
  python3 scripts/ocr_ufo_documents.py --collection majestic-12 --limit 10
  python3 scripts/ocr_ufo_documents.py --collection majestic-12
  python3 scripts/ocr_ufo_documents.py --all
  python3 scripts/ocr_ufo_documents.py --all --force
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

REPO_ROOT = Path(__file__).resolve().parent.parent

# ocrmypdf rasterizes each page to a temp working dir and hands the image path to a
# child tesseract process. On sandboxed macOS shells the default per-session temp
# (e.g. /tmp/claude-...) is not reliably readable by those child processes, so
# tesseract/leptonica fails with "image file not found". Pinning TMPDIR to a stable
# workspace-local directory avoids that. The directory is recreated each run and is
# safe to delete; keep it out of git via .gitignore.
WORK_TMPDIR = REPO_ROOT / ".ocr-tmp"

# Baseline OCR options. --clean is deliberately NOT here: it runs the page image
# through unpaper, which can erase faint type, stamps, marginalia, and handwriting --
# exactly the content this corpus must preserve. Enable it per collection only if a
# pilot proves it helps without destroying visible content. --clean-final stays off
# everywhere.
BASE_OCR_OPTIONS = [
    "-l", "eng",
    "--mode", "skip",
    "--rotate-pages",
    "--deskew",
    "--optimize", "1",
]

# Per-file tesseract timeout (seconds) and overall wall-clock timeout per file.
# A single pathological page should fail that file into QC, not stall the whole run.
TESSERACT_TIMEOUT = 600
MAX_SECONDS = 1200

# ocrmypdf exit code for "the generated PDF failed validation". Some source PDFs
# (web captures, malformed government scans) carry image streams that trip this
# check even though the produced PDF opens and its text extracts fine. We tolerate
# it when a usable output was still written, and flag the file for review.
OCRMYPDF_INVALID_OUTPUT = 4

# QC thresholds.
MIN_CHARS_PER_PAGE = 80     # below this average density -> needs_review
MAX_EMPTY_PAGE_RATIO = 0.20  # more than this share of empty pages -> needs_review
# Treat output as binary garbage if replacement chars exceed this share of text.
MAX_REPLACEMENT_RATIO = 0.02

REPLACEMENT_CHAR = "�"

# --- Inbox intake + LLM routing -------------------------------------------- #
# `inbox/` is a general intake: drop a notable PDF in, run the script with no
# collection, and each file is classified by an OpenAI model into a destination
# collection. The same call returns descriptive front matter (title, summary,
# entities, tags). Provenance front matter (sha, pages, tool versions) is always
# computed by the script, never by the model.
INBOX_DIR = REPO_ROOT / "inbox"
ENV_FILE = REPO_ROOT / ".env.local"
ROUTING_LOG = INBOX_DIR / "routing-log.csv"

# Collections a document can be routed to.
ROUTING_COLLECTIONS = ["narratives", "department-of-war", "majestic-12"]

# Chars of extracted text sent to the model for classification.
ROUTE_SAMPLE_CHARS = 8000

ROUTING_LOG_COLUMNS = [
    "source_pdf", "source_sha256", "collection", "release",
    "markdown_file", "pages", "chars_per_page", "needs_review",
    "routing_model", "error",
]

# Strict JSON schema for the structured-output routing call. Strict mode requires
# every property listed in `required` and additionalProperties:false; nullable
# fields use a ["string","null"] type union.
ROUTING_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "collection": {"type": "string", "enum": ROUTING_COLLECTIONS},
        "release": {"type": ["string", "null"]},
        "title": {"type": "string"},
        "summary": {"type": "string"},
        "document_type": {"type": "string"},
        "date": {"type": ["string", "null"]},
        "people": {"type": "array", "items": {"type": "string"}},
        "organizations": {"type": "array", "items": {"type": "string"}},
        "tags": {"type": "array", "items": {"type": "string"}},
        "needs_review": {"type": "boolean"},
        "routing_rationale": {"type": "string"},
    },
    "required": [
        "collection", "release", "title", "summary", "document_type", "date",
        "people", "organizations", "tags", "needs_review", "routing_rationale",
    ],
}

ROUTING_SYSTEM_PROMPT = """\
You are a cataloguing assistant for an archive of declassified and publicly \
released UAP/UFO documents. You classify each incoming document into exactly one \
collection and produce faithful descriptive metadata.

Collections:
- "department-of-war": official government UAP/UAP-adjacent records from \
declassification and public-records releases (military, intelligence, and agency \
documents such as the Department of War / CIA / DOE / ODNI releases).
- "majestic-12": documents belonging to the Majestic-12 (MJ-12) collection.
- "narratives": authored or narrative accounts that are NOT official government \
documents -- first-person testimony, whistleblower statements, forum / Reddit / \
4chan posts, and similar personal or secondhand narrative material.

Guidance:
- Represent the document faithfully and directly. Summarize what it says plainly \
("The document describes..."), not with reflexive skepticism. Do not add \
"so-called", "supposed", "debunked", or "unverified" framing of your own. \
Preserve the document's own qualifiers if it marks something as a draft, rumor, \
or unconfirmed.
- "title" is a concise human-readable title. "summary" is 1-3 neutral sentences. \
"document_type" is a short label (e.g. "forum post", "whistleblower account", \
"memorandum", "intelligence report"). "date" is the document's own date if stated \
(ISO 8601 when possible), otherwise null. "people" and "organizations" list \
notable named entities. "tags" are a few short topical keywords. \
"release" is null unless the text clearly identifies a specific release. \
Set "needs_review" to true if classification or content is ambiguous. \
"routing_rationale" briefly explains the collection choice."""

# Job definitions: (collection, release, source_dir, out_base, recursive)
# release is None for majestic-12. majestic-12/photos is intentionally excluded
# (image reference assets, not part of the baseline PDF OCR pass).
JOBS = {
    ("department-of-war", "release-01"): dict(
        source_dir=REPO_ROOT / "department-of-war" / "release-01",
        out_base=REPO_ROOT / "department-of-war" / "ocr" / "release-01",
    ),
    ("department-of-war", "release-02"): dict(
        source_dir=REPO_ROOT / "department-of-war" / "release-02",
        out_base=REPO_ROOT / "department-of-war" / "ocr" / "release-02",
    ),
    ("majestic-12", None): dict(
        source_dir=REPO_ROOT / "majestic-12",
        out_base=REPO_ROOT / "majestic-12" / "ocr",
    ),
}

MANIFEST_COLUMNS = [
    "collection",
    "release",
    "source_pdf",
    "source_sha256",
    "source_bytes",
    "pages",
    "ocr_pdf",
    "ocr_sha256",
    "text_file",
    "markdown_file",
    "ocr_exit_code",
    "ocr_seconds",
    "text_chars",
    "chars_per_page",
    "empty_pages",
    "tool_versions",
    "ocr_options",
    "needs_review",
    "error",
]

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def run(cmd: list[str], timeout: int | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def resolve_tool_versions() -> str:
    """A stable string identifying the OCR toolchain, recorded for idempotency."""
    try:
        ocr_v = run(["ocrmypdf", "--version"]).stdout.strip().splitlines()[0].strip()
    except Exception:
        ocr_v = "unknown"
    try:
        tess_line = run(["tesseract", "--version"]).stdout.splitlines()[0]
        # e.g. "tesseract 5.5.2" -> "5.5.2"
        tess_v = tess_line.strip().split()[-1]
    except Exception:
        tess_v = "unknown"
    return f"ocrmypdf {ocr_v} / tesseract {tess_v}"


def probe_pdf(path: Path) -> dict:
    """Return {ok, pages, encrypted, raw} from pdfinfo. ok=False means unreadable."""
    proc = run(["pdfinfo", str(path)])
    info = {"ok": False, "pages": 0, "encrypted": False, "raw": proc.stdout}
    if proc.returncode != 0:
        info["raw"] = proc.stderr or proc.stdout
        return info
    pages = 0
    encrypted = False
    for line in proc.stdout.splitlines():
        if line.startswith("Pages:"):
            try:
                pages = int(line.split(":", 1)[1].strip())
            except ValueError:
                pages = 0
        elif line.startswith("Encrypted:"):
            encrypted = line.split(":", 1)[1].strip().lower().startswith("yes")
    info["ok"] = pages > 0
    info["pages"] = pages
    info["encrypted"] = encrypted
    return info


def try_decrypt(src: Path, dest: Path) -> bool:
    """Attempt an empty-user-password decrypt with qpdf. True on success."""
    proc = run(["qpdf", "--decrypt", "--password=", str(src), str(dest)])
    # qpdf returns 0 on success, 3 on success-with-warnings; both yield a usable file.
    return dest.exists() and proc.returncode in (0, 3)


def run_ocrmypdf(ocr_input: Path, out_pdf: Path, ocr_options: list[str],
                 log_lines: list[str]) -> dict:
    """Run ocrmypdf under the wall-clock timeout and interpret the result.

    Returns {ok, exit_code, seconds, soft_invalid, error}. Exit 4 (invalid output
    PDF) is tolerated when an output file was still produced and its text extracts;
    `soft_invalid` is set so the caller can flag the file for review.
    """
    cmd = ["ocrmypdf", *ocr_options, "--tesseract-timeout", str(TESSERACT_TIMEOUT),
           str(ocr_input), str(out_pdf)]
    log_lines.append(f"$ {' '.join(cmd)}")
    start = time.monotonic()
    try:
        proc = run(cmd, timeout=MAX_SECONDS)
    except subprocess.TimeoutExpired:
        msg = f"ocrmypdf wall-clock timeout (> {MAX_SECONDS}s)"
        log_lines.append(msg)
        return {"ok": False, "exit_code": "timeout",
                "seconds": f"{time.monotonic() - start:.1f}",
                "soft_invalid": False, "error": msg}
    seconds = f"{time.monotonic() - start:.1f}"
    log_lines.append(proc.stdout)
    log_lines.append(proc.stderr)
    if proc.returncode == 0:
        return {"ok": True, "exit_code": "0", "seconds": seconds,
                "soft_invalid": False, "error": None}
    if (proc.returncode == OCRMYPDF_INVALID_OUTPUT and out_pdf.exists()
            and run(["pdftotext", "-layout", str(out_pdf), "-"]).stdout.strip()):
        log_lines.append("ocrmypdf exit 4 (invalid output) tolerated: "
                         "output produced and text extractable")
        return {"ok": True, "exit_code": "4", "seconds": seconds,
                "soft_invalid": True, "error": None}
    return {"ok": False, "exit_code": str(proc.returncode), "seconds": seconds,
            "soft_invalid": False, "error": f"ocrmypdf exit {proc.returncode}"}


# --------------------------------------------------------------------------- #
# Markdown generation
# --------------------------------------------------------------------------- #

_TRAILING_WS = re.compile(r"[ \t]+$", re.MULTILINE)
_MANY_BLANKS = re.compile(r"\n{3,}")


def clean_page_text(raw: str) -> str:
    """Conservative cleanup: trim trailing spaces, collapse runs of blank lines.

    Preserves classification markings, dates, stamps, handwritten-note text, and
    uncertain OCR verbatim. Does not rewrite names or acronyms, and does not summarize.
    """
    txt = _TRAILING_WS.sub("", raw)
    txt = _MANY_BLANKS.sub("\n\n", txt)
    return txt.strip("\n")


def split_pages(text: str, expected_pages: int) -> list[str]:
    """Split pdftotext output on form-feed page separators.

    pdftotext -layout emits a form feed after each page, usually leaving one trailing
    empty element. Page numbers stay stable even when a page is blank.
    """
    pages = text.split("\f")
    # Drop a single trailing empty segment caused by the final form feed.
    if pages and pages[-1].strip() == "" and len(pages) > expected_pages:
        pages = pages[:-1]
    return pages


def yaml_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def build_markdown(
    *,
    title: str,
    collection: str,
    release: str | None,
    source_pdf_rel: str,
    ocr_pdf_rel: str,
    source_sha256: str,
    ocr_sha256: str,
    pages: int,
    tool_versions: str,
    ocr_options: str,
    needs_review: bool,
    page_texts: list[str],
) -> str:
    release_yaml = f'"{yaml_escape(release)}"' if release is not None else "null"
    fm = [
        "---",
        f'title: "{yaml_escape(title)}"',
        f'collection: "{collection}"',
        f"release: {release_yaml}",
        f'source_pdf: "{yaml_escape(source_pdf_rel)}"',
        f'ocr_pdf: "{yaml_escape(ocr_pdf_rel)}"',
        f'source_sha256: "{source_sha256}"',
        f'ocr_sha256: "{ocr_sha256}"',
        f"pages: {pages}",
        'ocr_engine: "ocrmypdf + tesseract"',
        f'tool_versions: "{yaml_escape(tool_versions)}"',
        f'ocr_options: "{yaml_escape(ocr_options)}"',
        'text_extractor: "pdftotext -layout"',
        f"needs_review: {'true' if needs_review else 'false'}",
        "---",
        "",
        f"# {title}",
        "",
    ]
    body: list[str] = []
    for idx, raw in enumerate(page_texts, start=1):
        cleaned = clean_page_text(raw)
        body.append(f"## Page {idx}")
        body.append("")
        body.append(cleaned if cleaned else "_(blank page)_")
        body.append("")
    return "\n".join(fm) + "\n" + "\n".join(body).rstrip("\n") + "\n"


# --------------------------------------------------------------------------- #
# Per-file processing
# --------------------------------------------------------------------------- #


@dataclass
class Result:
    collection: str
    release: str | None
    source_pdf: str
    source_sha256: str = ""
    source_bytes: int = 0
    pages: int = 0
    ocr_pdf: str = ""
    ocr_sha256: str = ""
    text_file: str = ""
    markdown_file: str = ""
    ocr_exit_code: str = ""
    ocr_seconds: str = ""
    text_chars: int = 0
    chars_per_page: float = 0.0
    empty_pages: int = 0
    tool_versions: str = ""
    ocr_options: str = ""
    needs_review: bool = False
    error: str = ""
    review_reasons: list[str] = field(default_factory=list)
    skipped: bool = False  # skipped by idempotency (already complete)

    def to_row(self) -> dict:
        return {
            "collection": self.collection,
            "release": self.release or "",
            "source_pdf": self.source_pdf,
            "source_sha256": self.source_sha256,
            "source_bytes": self.source_bytes,
            "pages": self.pages,
            "ocr_pdf": self.ocr_pdf,
            "ocr_sha256": self.ocr_sha256,
            "text_file": self.text_file,
            "markdown_file": self.markdown_file,
            "ocr_exit_code": self.ocr_exit_code,
            "ocr_seconds": self.ocr_seconds,
            "text_chars": self.text_chars,
            "chars_per_page": f"{self.chars_per_page:.1f}",
            "empty_pages": self.empty_pages,
            "tool_versions": self.tool_versions,
            "ocr_options": self.ocr_options,
            "needs_review": "true" if self.needs_review else "false",
            "error": self.error,
        }


def rel(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT))


def process_pdf(
    src: Path,
    *,
    collection: str,
    release: str | None,
    out_base: Path,
    ocr_options: list[str],
    tool_versions: str,
    log_lines: list[str],
) -> Result:
    stem = src.stem
    options_str = " ".join(ocr_options)
    res = Result(
        collection=collection,
        release=release,
        source_pdf=rel(src),
        tool_versions=tool_versions,
        ocr_options=options_str,
    )

    res.source_bytes = src.stat().st_size
    res.source_sha256 = sha256_of(src)

    # 1. Probe.
    info = probe_pdf(src)
    if not info["ok"]:
        res.error = "unreadable"
        res.needs_review = True
        res.review_reasons.append("pdfinfo could not read the source PDF")
        return res
    res.pages = info["pages"]

    searchable_dir = out_base / "searchable-pdf"
    text_dir = out_base / "text"
    md_dir = out_base / "markdown"
    ocr_pdf = searchable_dir / f"{stem}.pdf"
    text_file = text_dir / f"{stem}.txt"
    md_file = md_dir / f"{stem}.md"

    # 2. Resolve OCR input, decrypting empty-password PDFs to a temp copy if needed.
    ocr_input = src
    tmp_decrypted: Path | None = None
    if info["encrypted"]:
        tmp_fd = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        tmp_decrypted = Path(tmp_fd.name)
        tmp_fd.close()
        if try_decrypt(src, tmp_decrypted):
            ocr_input = tmp_decrypted
            log_lines.append(f"{stem}: decrypted owner-password PDF for OCR")
        else:
            tmp_decrypted.unlink(missing_ok=True)
            res.error = "encrypted"
            res.needs_review = True
            res.review_reasons.append("PDF requires a user password; OCR skipped")
            return res

    try:
        # 3. OCR.
        ocr = run_ocrmypdf(ocr_input, ocr_pdf, ocr_options, log_lines)
        res.ocr_seconds = ocr["seconds"]
        res.ocr_exit_code = ocr["exit_code"]
        if not ocr["ok"]:
            res.error = ocr["error"]
            res.needs_review = True
            res.review_reasons.append(res.error)
            return res
        if ocr["soft_invalid"]:
            res.review_reasons.append("ocrmypdf reported invalid output (malformed "
                                      "image streams); text extracted OK")

        res.ocr_pdf = rel(ocr_pdf)
        res.ocr_sha256 = sha256_of(ocr_pdf)

        # 4. Extract complete text from the final searchable PDF.
        txt_proc = run(["pdftotext", "-layout", str(ocr_pdf), str(text_file)])
        if txt_proc.returncode != 0 or not text_file.exists():
            res.error = "pdftotext failed"
            res.needs_review = True
            res.review_reasons.append(res.error)
            log_lines.append(txt_proc.stderr)
            return res
        res.text_file = rel(text_file)

        text = text_file.read_text(encoding="utf-8", errors="replace")
        page_texts = split_pages(text, res.pages)

        # 5. Markdown.
        res.text_chars = len(text)
        res.empty_pages = sum(1 for p in page_texts if p.strip() == "")
        res.chars_per_page = res.text_chars / res.pages if res.pages else 0.0

        # 6. QC flags.
        replacement_count = text.count(REPLACEMENT_CHAR)
        if res.text_chars == 0 or text.strip() == "":
            res.review_reasons.append("extracted text is empty")
        if res.pages and res.chars_per_page < MIN_CHARS_PER_PAGE and res.text_chars > 0:
            res.review_reasons.append(
                f"low text density ({res.chars_per_page:.1f} < {MIN_CHARS_PER_PAGE} chars/page)"
            )
        if res.pages and res.empty_pages / res.pages > MAX_EMPTY_PAGE_RATIO:
            res.review_reasons.append(
                f"{res.empty_pages}/{res.pages} pages empty "
                f"(> {int(MAX_EMPTY_PAGE_RATIO * 100)}%)"
            )
        if res.text_chars and replacement_count / res.text_chars > MAX_REPLACEMENT_RATIO:
            res.review_reasons.append(
                f"{replacement_count} replacement chars (possible binary garbage)"
            )
        res.needs_review = bool(res.review_reasons)

        md = build_markdown(
            title=stem,
            collection=collection,
            release=release,
            source_pdf_rel=res.source_pdf,
            ocr_pdf_rel=res.ocr_pdf,
            source_sha256=res.source_sha256,
            ocr_sha256=res.ocr_sha256,
            pages=res.pages,
            tool_versions=tool_versions,
            ocr_options=options_str,
            needs_review=res.needs_review,
            page_texts=page_texts,
        )
        md_file.write_text(md, encoding="utf-8")
        res.markdown_file = rel(md_file)
        return res
    finally:
        if tmp_decrypted is not None:
            tmp_decrypted.unlink(missing_ok=True)


# --------------------------------------------------------------------------- #
# Manifest + QC
# --------------------------------------------------------------------------- #


def load_manifest(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    with path.open(newline="", encoding="utf-8") as fh:
        return {row["source_pdf"]: row for row in csv.DictReader(fh)}


def write_manifest(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = sorted(rows, key=lambda r: r["source_pdf"])
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=MANIFEST_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def is_still_current(prev: dict, source_sha256: str, tool_versions: str,
                     ocr_options: str) -> bool:
    """A file is skipped only when sha, tool versions, and options all still match,
    the run completed without error, and its Markdown output exists."""
    if not prev:
        return False
    if prev.get("source_sha256") != source_sha256:
        return False
    if prev.get("tool_versions") != tool_versions:
        return False
    if prev.get("ocr_options") != ocr_options:
        return False
    if prev.get("error"):
        return False
    md = prev.get("markdown_file")
    if not md or not (REPO_ROOT / md).exists():
        return False
    return True


def write_qc_report(path: Path, results: list[Result], total_seconds: float,
                    collection: str, release: str | None) -> None:
    completed = [r for r in results if not r.error and not r.skipped]
    skipped = [r for r in results if r.skipped]
    failed = [r for r in results if r.error]
    review = [r for r in results if r.needs_review]
    total_pages = sum(r.pages for r in results)

    longest = sorted([r for r in results if r.pages], key=lambda r: r.pages,
                     reverse=True)[:10]
    densities = [r for r in results if r.markdown_file and not r.skipped]
    lowest_density = sorted(densities, key=lambda r: r.chars_per_page)[:10]

    label = collection if release is None else f"{collection} / {release}"
    lines = [
        f"# OCR QC Report — {label}",
        "",
        f"- Total files: **{len(results)}**",
        f"- Completed this run: **{len(completed)}**",
        f"- Skipped (already current): **{len(skipped)}**",
        f"- Failed: **{len(failed)}**",
        f"- Needs review: **{len(review)}**",
        f"- Total pages processed: **{total_pages}**",
        f"- Total runtime: **{total_seconds:.1f}s**",
        "",
        "## Failed files",
        "",
    ]
    if failed:
        for r in sorted(failed, key=lambda r: r.source_pdf):
            lines.append(f"- `{r.source_pdf}` — {r.error}")
    else:
        lines.append("_None._")

    lines += ["", "## Review-needed files", ""]
    review_only = [r for r in review if not r.error]
    if review_only:
        for r in sorted(review_only, key=lambda r: r.source_pdf):
            reasons = "; ".join(r.review_reasons) or "see manifest"
            lines.append(f"- `{r.source_pdf}` — {reasons}")
    elif failed:
        lines.append("_(All review-needed files are also failures, listed above.)_")
    else:
        lines.append("_None._")

    lines += ["", "## Longest files by page count", ""]
    if longest:
        for r in longest:
            lines.append(f"- `{r.source_pdf}` — {r.pages} pages")
    else:
        lines.append("_None._")

    lines += ["", "## Lowest text-density files", ""]
    if lowest_density:
        for r in lowest_density:
            lines.append(f"- `{r.source_pdf}` — {r.chars_per_page:.1f} chars/page "
                         f"({r.pages} pages)")
    else:
        lines.append("_None._")

    lines += ["", "## Completed files", ""]
    if completed:
        for r in sorted(completed, key=lambda r: r.source_pdf):
            flag = " ⚠ needs review" if r.needs_review else ""
            lines.append(f"- `{r.source_pdf}` — {r.pages} pages, "
                         f"{r.chars_per_page:.1f} chars/page{flag}")
    else:
        lines.append("_None this run._")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------- #
# Job orchestration
# --------------------------------------------------------------------------- #


def list_pdfs(source_dir: Path) -> list[Path]:
    # Non-recursive: root-level PDFs only (excludes majestic-12/photos and ocr/).
    return sorted(p for p in source_dir.glob("*.pdf") if p.is_file())


def run_job(collection: str, release: str | None, *, limit: int | None,
            force: bool, ocr_options: list[str], tool_versions: str) -> list[Result]:
    cfg = JOBS[(collection, release)]
    source_dir: Path = cfg["source_dir"]
    out_base: Path = cfg["out_base"]
    options_str = " ".join(ocr_options)

    label = collection if release is None else f"{collection}/{release}"
    if not source_dir.exists():
        print(f"[{label}] source dir missing: {source_dir}", file=sys.stderr)
        return []

    for sub in ("searchable-pdf", "text", "markdown", "logs", "qc"):
        (out_base / sub).mkdir(parents=True, exist_ok=True)

    pdfs = list_pdfs(source_dir)
    if limit is not None:
        pdfs = pdfs[:limit]

    manifest_path = out_base / "manifest.csv"
    prev_manifest = load_manifest(manifest_path)

    print(f"[{label}] {len(pdfs)} PDF(s) to consider")
    results: list[Result] = []
    job_start = time.monotonic()

    for i, src in enumerate(pdfs, start=1):
        src_rel = rel(src)
        source_sha = sha256_of(src)
        prev = prev_manifest.get(src_rel)

        if not force and is_still_current(prev, source_sha, tool_versions, options_str):
            r = Result(
                collection=collection, release=release, source_pdf=src_rel,
                tool_versions=tool_versions, ocr_options=options_str, skipped=True,
            )
            # Carry forward recorded values for an accurate manifest + QC report.
            r.source_sha256 = prev.get("source_sha256", source_sha)
            r.source_bytes = int(prev.get("source_bytes") or 0)
            r.pages = int(prev.get("pages") or 0)
            r.ocr_pdf = prev.get("ocr_pdf", "")
            r.ocr_sha256 = prev.get("ocr_sha256", "")
            r.text_file = prev.get("text_file", "")
            r.markdown_file = prev.get("markdown_file", "")
            r.ocr_exit_code = prev.get("ocr_exit_code", "")
            r.ocr_seconds = prev.get("ocr_seconds", "")
            r.text_chars = int(prev.get("text_chars") or 0)
            try:
                r.chars_per_page = float(prev.get("chars_per_page") or 0)
            except ValueError:
                r.chars_per_page = 0.0
            r.empty_pages = int(prev.get("empty_pages") or 0)
            r.needs_review = (prev.get("needs_review") == "true")
            results.append(r)
            print(f"  [{i}/{len(pdfs)}] skip (current): {src.name}")
            continue

        print(f"  [{i}/{len(pdfs)}] OCR: {src.name}", flush=True)
        log_lines: list[str] = [f"=== {src_rel} ==="]
        r = process_pdf(
            src, collection=collection, release=release, out_base=out_base,
            ocr_options=ocr_options, tool_versions=tool_versions, log_lines=log_lines,
        )
        (out_base / "logs" / f"{src.stem}.log").write_text(
            "\n".join(s for s in log_lines if s is not None), encoding="utf-8"
        )
        status = "OK"
        if r.error:
            status = f"FAIL ({r.error})"
        elif r.needs_review:
            status = "review"
        print(f"      -> {status}, {r.pages} pages, {r.chars_per_page:.0f} chars/page")
        results.append(r)

    # Manifest: merge new results over any prior rows not touched this run
    # (e.g. when --limit processed only part of the corpus).
    merged: dict[str, dict] = dict(prev_manifest)
    for r in results:
        merged[r.source_pdf] = r.to_row()
    write_manifest(manifest_path, list(merged.values()))

    total_seconds = time.monotonic() - job_start
    write_qc_report(out_base / "qc" / "report.md", results, total_seconds,
                    collection, release)
    print(f"[{label}] manifest: {rel(manifest_path)}  "
          f"qc: {rel(out_base / 'qc' / 'report.md')}  ({total_seconds:.1f}s)")
    return results


# --------------------------------------------------------------------------- #
# Inbox intake + LLM routing
# --------------------------------------------------------------------------- #


def load_env_local() -> None:
    """Load KEY=VALUE lines from .env.local into the environment (no override)."""
    if not ENV_FILE.exists():
        return
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


def ensure_openai_runtime() -> None:
    """Inbox mode needs the openai SDK. If it isn't importable but the repo .venv
    has it, transparently re-exec under that interpreter so `python3 scripts/...`
    just works."""
    try:
        import openai  # noqa: F401
        return
    except ImportError:
        pass
    venv_py = REPO_ROOT / ".venv" / "bin" / "python"
    if venv_py.exists() and Path(sys.executable).resolve() != venv_py.resolve():
        os.execv(str(venv_py), [str(venv_py), *sys.argv])
    sys.exit("openai SDK not found. Run: python3 -m venv .venv && "
             ".venv/bin/pip install -r requirements.txt")


def slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s or "document"


def classify_document(client, model: str, filename: str, sample_text: str) -> dict:
    """One structured-output call: routing collection + descriptive front matter."""
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": ROUTING_SYSTEM_PROMPT},
            {"role": "user", "content":
                f"Filename: {filename}\n\nDocument text (excerpt):\n{sample_text}"},
        ],
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "document_routing",
                "strict": True,
                "schema": ROUTING_SCHEMA,
            },
        },
    )
    return json.loads(resp.choices[0].message.content)


def inbox_dest(collection: str, slug: str) -> dict:
    """Output paths for a routed document. narratives gets flat Markdown at its
    root (matching the existing authored narratives); other collections receive an
    `ocr/inbox/` bucket so intake stays separate from the bulk-release manifests."""
    if collection == "narratives":
        base = REPO_ROOT / "narratives"
        ocr = base / "ocr"
        return {
            "markdown": base / f"{slug}.md",
            "searchable_pdf": ocr / "searchable-pdf" / f"{slug}.pdf",
            "text": ocr / "text" / f"{slug}.txt",
            "log": ocr / "logs" / f"{slug}.log",
            "manifest": ocr / "manifest.csv",
            "qc": ocr / "qc" / "report.md",
            "release": None,
        }
    base = REPO_ROOT / collection / "ocr" / "inbox"
    return {
        "markdown": base / "markdown" / f"{slug}.md",
        "searchable_pdf": base / "searchable-pdf" / f"{slug}.pdf",
        "text": base / "text" / f"{slug}.txt",
        "log": base / "logs" / f"{slug}.log",
        "manifest": base / "manifest.csv",
        "qc": base / "qc" / "report.md",
        "release": "inbox",
    }


def _yaml_list(values: list[str]) -> str:
    if not values:
        return "[]"
    return "[" + ", ".join(f'"{yaml_escape(v)}"' for v in values) + "]"


def build_inbox_markdown(*, meta: dict, collection: str, release: str | None,
                         source_pdf_rel: str, ocr_pdf_rel: str, source_sha256: str,
                         ocr_sha256: str, pages: int, tool_versions: str,
                         ocr_options: str, model: str, needs_review: bool,
                         page_texts: list[str]) -> str:
    """Front matter merges model-derived descriptive fields with computed
    provenance; body uses the same page-boundary structure as the rest of the corpus."""
    release_yaml = f'"{yaml_escape(release)}"' if release is not None else "null"
    date_yaml = f'"{yaml_escape(meta["date"])}"' if meta.get("date") else "null"
    title = meta.get("title") or source_pdf_rel
    fm = [
        "---",
        f'title: "{yaml_escape(title)}"',
        f'collection: "{collection}"',
        f"release: {release_yaml}",
        f'source_pdf: "{yaml_escape(source_pdf_rel)}"',
        f'ocr_pdf: "{yaml_escape(ocr_pdf_rel)}"',
        f'source_sha256: "{source_sha256}"',
        f'ocr_sha256: "{ocr_sha256}"',
        f"pages: {pages}",
        'ocr_engine: "ocrmypdf + tesseract"',
        f'tool_versions: "{yaml_escape(tool_versions)}"',
        f'ocr_options: "{yaml_escape(ocr_options)}"',
        'text_extractor: "pdftotext -layout"',
        "source_origin: \"inbox\"",
        f'routing_model: "{yaml_escape(model)}"',
        f'document_type: "{yaml_escape(meta.get("document_type", ""))}"',
        f"date: {date_yaml}",
        f'summary: "{yaml_escape(meta.get("summary", ""))}"',
        f"people: {_yaml_list(meta.get('people', []))}",
        f"organizations: {_yaml_list(meta.get('organizations', []))}",
        f"tags: {_yaml_list(meta.get('tags', []))}",
        f"needs_review: {'true' if needs_review else 'false'}",
        "---",
        "",
        f"# {title}",
        "",
    ]
    body: list[str] = []
    for idx, raw in enumerate(page_texts, start=1):
        cleaned = clean_page_text(raw)
        body.append(f"## Page {idx}")
        body.append("")
        body.append(cleaned if cleaned else "_(blank page)_")
        body.append("")
    return "\n".join(fm) + "\n" + "\n".join(body).rstrip("\n") + "\n"


def process_inbox_file(src: Path, *, client, model: str, ocr_options: list[str],
                       tool_versions: str, log_lines: list[str]) -> dict:
    """OCR an inbox PDF, classify it, and write outputs to the routed collection.
    Returns a routing-log record (also used for the destination manifest/QC)."""
    options_str = " ".join(ocr_options)
    src_rel = rel(src)
    rec = {
        "source_pdf": src_rel,
        "source_sha256": sha256_of(src),
        "collection": "", "release": "", "markdown_file": "",
        "pages": 0, "chars_per_page": "0.0", "needs_review": "false",
        "routing_model": model, "error": "",
        "_result": None, "_dest": None,
    }

    info = probe_pdf(src)
    if not info["ok"]:
        rec["error"] = "unreadable"; rec["needs_review"] = "true"
        return rec
    pages = info["pages"]

    # Decrypt empty-password PDFs to a temp copy, same as the bulk pipeline.
    ocr_input = src
    tmp_decrypted: Path | None = None
    if info["encrypted"]:
        tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        tmp_decrypted = Path(tmp.name); tmp.close()
        if try_decrypt(src, tmp_decrypted):
            ocr_input = tmp_decrypted
        else:
            tmp_decrypted.unlink(missing_ok=True)
            rec["error"] = "encrypted"; rec["needs_review"] = "true"
            return rec

    try:
        # Classify from a quick text sample (born-digital inbox docs extract directly;
        # if the source has no text layer, the sample falls back to empty and the
        # model classifies from the filename, flagging needs_review as appropriate).
        sample = run(["pdftotext", "-layout", str(ocr_input), "-"]).stdout
        sample = sample.replace("\f", "\n")[:ROUTE_SAMPLE_CHARS]
        log_lines.append(f"classifying with {model} ({len(sample)} sample chars)")
        meta = classify_document(client, model, src.name, sample)
        collection = meta["collection"]
        if collection not in ROUTING_COLLECTIONS:
            collection = "narratives"
        dest = inbox_dest(collection, slugify(src.stem))
        release = dest["release"]
        rec["collection"] = collection
        rec["release"] = release or ""
        rec["_dest"] = dest  # set early so the per-file log is written even on failure
        log_lines.append(f"routed -> {collection}: {meta.get('routing_rationale','')}")

        for key in ("searchable_pdf", "text", "log", "markdown", "manifest", "qc"):
            dest[key].parent.mkdir(parents=True, exist_ok=True)

        ocr = run_ocrmypdf(ocr_input, dest["searchable_pdf"], ocr_options, log_lines)
        ocr_seconds = ocr["seconds"]
        if not ocr["ok"]:
            rec["error"] = ocr["error"]; rec["needs_review"] = "true"
            return rec
        soft_invalid = ocr["soft_invalid"]

        ocr_sha = sha256_of(dest["searchable_pdf"])
        txt_proc = run(["pdftotext", "-layout", str(dest["searchable_pdf"]),
                        str(dest["text"])])
        if txt_proc.returncode != 0 or not dest["text"].exists():
            rec["error"] = "pdftotext failed"; rec["needs_review"] = "true"
            return rec

        text = dest["text"].read_text(encoding="utf-8", errors="replace")
        page_texts = split_pages(text, pages)
        text_chars = len(text)
        empty_pages = sum(1 for p in page_texts if p.strip() == "")
        chars_per_page = text_chars / pages if pages else 0.0

        reasons: list[str] = []
        if soft_invalid:
            reasons.append("ocrmypdf reported invalid output (malformed image "
                           "streams); text extracted OK")
        if bool(meta.get("needs_review")):
            reasons.append("model flagged for review")
        if text_chars == 0:
            reasons.append("extracted text is empty")
        if pages and chars_per_page < MIN_CHARS_PER_PAGE and text_chars > 0:
            reasons.append(f"low text density ({chars_per_page:.1f} chars/page)")
        if pages and empty_pages / pages > MAX_EMPTY_PAGE_RATIO:
            reasons.append(f"{empty_pages}/{pages} pages empty")
        needs_review = bool(reasons)

        md = build_inbox_markdown(
            meta=meta, collection=collection, release=release,
            source_pdf_rel=src_rel, ocr_pdf_rel=rel(dest["searchable_pdf"]),
            source_sha256=rec["source_sha256"], ocr_sha256=ocr_sha, pages=pages,
            tool_versions=tool_versions, ocr_options=options_str, model=model,
            needs_review=needs_review, page_texts=page_texts,
        )
        dest["markdown"].write_text(md, encoding="utf-8")

        rec.update(
            markdown_file=rel(dest["markdown"]), pages=pages,
            chars_per_page=f"{chars_per_page:.1f}",
            needs_review="true" if needs_review else "false",
        )
        # Build a manifest Result for the destination collection's manifest/QC.
        result = Result(
            collection=collection, release=release, source_pdf=src_rel,
            source_sha256=rec["source_sha256"], source_bytes=src.stat().st_size,
            pages=pages, ocr_pdf=rel(dest["searchable_pdf"]), ocr_sha256=ocr_sha,
            text_file=rel(dest["text"]), markdown_file=rel(dest["markdown"]),
            ocr_exit_code="0", ocr_seconds=ocr_seconds, text_chars=text_chars,
            chars_per_page=chars_per_page, empty_pages=empty_pages,
            tool_versions=tool_versions, ocr_options=options_str,
            needs_review=needs_review, error="", review_reasons=reasons,
        )
        rec["_result"] = result
        rec["_dest"] = dest
        return rec
    finally:
        if tmp_decrypted is not None:
            tmp_decrypted.unlink(missing_ok=True)


def load_routing_log() -> dict[str, dict]:
    if not ROUTING_LOG.exists():
        return {}
    with ROUTING_LOG.open(newline="", encoding="utf-8") as fh:
        return {r["source_pdf"]: r for r in csv.DictReader(fh)}


def write_routing_log(rows: list[dict]) -> None:
    ROUTING_LOG.parent.mkdir(parents=True, exist_ok=True)
    rows = sorted(rows, key=lambda r: r["source_pdf"])
    with ROUTING_LOG.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=ROUTING_LOG_COLUMNS)
        writer.writeheader()
        for r in rows:
            writer.writerow({k: r.get(k, "") for k in ROUTING_LOG_COLUMNS})


def run_inbox(*, inbox_dir: Path, limit: int | None, force: bool,
              ocr_options: list[str], tool_versions: str) -> list[dict]:
    load_env_local()
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    model = os.environ.get("OPENAI_MODEL", "gpt-5.4-mini").strip()
    if not api_key:
        sys.exit("OPENAI_API_KEY is not set. Add it to .env.local.")
    from openai import OpenAI
    client = OpenAI(api_key=api_key)

    pdfs = list_pdfs(inbox_dir)
    if limit is not None:
        pdfs = pdfs[:limit]
    if not pdfs:
        print(f"[inbox] no PDFs in {rel(inbox_dir)}")
        return []

    prev = load_routing_log()
    print(f"[inbox] {len(pdfs)} PDF(s); routing model: {model}")
    records: list[dict] = []
    # Group destination manifest Results so each touched collection's manifest +
    # QC report is refreshed once at the end of the run.
    dest_results: dict[Path, list] = {}
    dest_meta: dict[Path, tuple] = {}

    for i, src in enumerate(pdfs, start=1):
        src_rel = rel(src)
        sha = sha256_of(src)
        old = prev.get(src_rel)
        if (not force and old and old.get("source_sha256") == sha
                and old.get("markdown_file")
                and (REPO_ROOT / old["markdown_file"]).exists()):
            print(f"  [{i}/{len(pdfs)}] skip (routed): {src.name} -> {old['collection']}")
            records.append(old)
            continue

        print(f"  [{i}/{len(pdfs)}] {src.name}", flush=True)
        log_lines = [f"=== {src_rel} ==="]
        rec = process_inbox_file(src, client=client, model=model,
                                 ocr_options=ocr_options, tool_versions=tool_versions,
                                 log_lines=log_lines)
        dest = rec.pop("_dest", None)
        result = rec.pop("_result", None)
        if dest is not None:
            dest["log"].parent.mkdir(parents=True, exist_ok=True)
            dest["log"].write_text("\n".join(s for s in log_lines if s is not None),
                                   encoding="utf-8")
        if result is None and dest is not None and rec.get("error"):
            # OCR/extraction failed after routing: still record it in the
            # destination manifest + QC so the failure is auditable.
            result = Result(
                collection=rec["collection"], release=dest["release"],
                source_pdf=rec["source_pdf"], source_sha256=rec["source_sha256"],
                pages=int(rec.get("pages") or 0), tool_versions=tool_versions,
                ocr_options=" ".join(ocr_options), needs_review=True,
                error=rec["error"], review_reasons=[rec["error"]],
            )
        if result is not None:
            dest_results.setdefault(dest["manifest"], []).append(result)
            dest_meta[dest["manifest"]] = (result.collection, result.release,
                                           dest["qc"])
        status = rec["error"] or ("review" if rec["needs_review"] == "true" else "OK")
        print(f"      -> {rec['collection'] or '?'}: {status}, {rec['pages']} pages, "
              f"{rec['chars_per_page']} chars/page")
        records.append(rec)

    # Refresh each touched destination's manifest + QC report.
    for manifest_path, results in dest_results.items():
        prev_manifest = load_manifest(manifest_path)
        merged = dict(prev_manifest)
        for r in results:
            merged[r.source_pdf] = r.to_row()
        write_manifest(manifest_path, list(merged.values()))
        collection, release, qc_path = dest_meta[manifest_path]
        write_qc_report(qc_path, results, 0.0, collection, release)
        print(f"[inbox] updated {rel(manifest_path)}")

    # Persist routing decisions (merged so prior, untouched files survive).
    merged_log = dict(prev)
    for rec in records:
        merged_log[rec["source_pdf"]] = rec
    write_routing_log(list(merged_log.values()))
    print(f"[inbox] routing log: {rel(ROUTING_LOG)}")
    return records


def resolve_jobs(args) -> list[tuple[str, str | None]]:
    if args.all:
        return list(JOBS.keys())
    if args.collection == "department-of-war":
        if args.release:
            key = ("department-of-war", args.release)
            if key not in JOBS:
                sys.exit(f"unknown release: {args.release}")
            return [key]
        return [("department-of-war", "release-01"), ("department-of-war", "release-02")]
    if args.collection == "majestic-12":
        return [("majestic-12", None)]
    sys.exit("specify --all or --collection {department-of-war,majestic-12}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--collection", choices=["department-of-war", "majestic-12"])
    parser.add_argument("--release", help="e.g. release-01 (department-of-war only)")
    parser.add_argument("--limit", type=int, help="process only the first N PDFs per job")
    parser.add_argument("--all", action="store_true", help="process every job")
    parser.add_argument("--inbox", action="store_true",
                        help="process the inbox/ intake (the default with no other "
                             "target); classifies + routes each PDF via the OpenAI API")
    parser.add_argument("--path", help="override the inbox directory (inbox mode)")
    parser.add_argument("--force", action="store_true",
                        help="reprocess even if manifest says the file is current")
    parser.add_argument("--clean", action="store_true",
                        help="enable ocrmypdf --clean (unpaper). OFF by default; only "
                             "use for document classes a pilot proves it helps.")
    args = parser.parse_args()

    for tool in ("ocrmypdf", "pdfinfo", "pdftotext", "qpdf", "tesseract"):
        if shutil.which(tool) is None:
            sys.exit(f"required tool not found on PATH: {tool}")

    # Pin all child-process temp files to a stable workspace-local dir (see WORK_TMPDIR).
    WORK_TMPDIR.mkdir(parents=True, exist_ok=True)
    os.environ["TMPDIR"] = str(WORK_TMPDIR)
    tempfile.tempdir = str(WORK_TMPDIR)

    ocr_options = list(BASE_OCR_OPTIONS)
    if args.clean:
        ocr_options.append("--clean")
    tool_versions = resolve_tool_versions()

    # Inbox mode is the default when no bulk-collection target is given.
    inbox_mode = args.inbox or (not args.all and not args.collection)
    if inbox_mode:
        ensure_openai_runtime()
        inbox_dir = Path(args.path).resolve() if args.path else INBOX_DIR
        print(f"Toolchain: {tool_versions}")
        print(f"OCR options: {' '.join(ocr_options)}")
        records = run_inbox(inbox_dir=inbox_dir, limit=args.limit, force=args.force,
                            ocr_options=ocr_options, tool_versions=tool_versions)
        failed = sum(1 for r in records if r.get("error"))
        review = sum(1 for r in records
                     if r.get("needs_review") == "true" and not r.get("error"))
        print(f"\nInbox done. routed={len(records) - failed} review={review} "
              f"failed={failed} total={len(records)}")
        return

    jobs = resolve_jobs(args)
    print(f"Toolchain: {tool_versions}")
    print(f"OCR options: {' '.join(ocr_options)}")

    all_results: list[Result] = []
    for collection, release in jobs:
        all_results += run_job(
            collection, release, limit=args.limit, force=args.force,
            ocr_options=ocr_options, tool_versions=tool_versions,
        )

    failed = sum(1 for r in all_results if r.error)
    review = sum(1 for r in all_results if r.needs_review and not r.error)
    done = sum(1 for r in all_results if not r.error and not r.skipped)
    skipped = sum(1 for r in all_results if r.skipped)
    print(f"\nDone. processed={done} skipped={skipped} review={review} failed={failed} "
          f"total={len(all_results)}")


if __name__ == "__main__":
    main()
