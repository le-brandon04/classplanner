"""
parse_audit_ocr.py — Story 1: extract remaining courses from a DegreeWorks
audit PDF that has no text layer.

DegreeWorks exports are either readable OR complete, not both:
  - DegreeWorks print view -> Microsoft Print to PDF : full content, but text
    is converted to vector outlines (no text layer at all)
  - Dashboard -> Chrome "Save as PDF" : real text layer, but requirement
    blocks are collapsed, so "Still needed:" never appears

Use the first kind with this script.

Usage:
    python parse_audit_ocr.py audit_original.pdf
    python parse_audit_ocr.py audit_original.pdf --dump
    python parse_audit_ocr.py audit_original.pdf -o data/remaining_courses.json

Setup:
    pip install pymupdf pytesseract pillow
    Install the Tesseract binary, then either
      - add it to PATH, or
      - set the TESSERACT_CMD environment variable, or
      - copy config.example.json to config.json and set "tesseract_cmd"
"""

import argparse
import json
import os
import re
import shutil
import sys
from pathlib import Path

try:
    import pymupdf
    import pytesseract
    from PIL import Image
except ImportError as exc:
    sys.exit(f"Missing package ({exc.name}). Run: pip install pymupdf pytesseract pillow")



def base_dir() -> Path:
    """Where to look for data/ and config.json.

    Running from source: next to this file.
    Running as the packaged .exe: next to the executable, NOT inside it.

    That second case is the whole point. The specification requires the
    inputs to be separated from the software, so prereqs.json and
    offerings.json ship beside classplanner.exe where an advisor can edit
    them in Notepad. Bundling them into the executable would be easier and
    would break the requirement.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent

HERE = base_dir()

# Checked only when PATH, the env var and config.json all come up empty.
COMMON_TESSERACT_PATHS = [
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    "/opt/homebrew/bin/tesseract",
    "/usr/local/bin/tesseract",
    "/usr/bin/tesseract",
]

COURSE_RE = re.compile(r"\b([A-Z]{3,4})\s*(\d{4}[A-Z]?)\b")
STILL_NEEDED_RE = re.compile(r"[Ss]till\s+[Nn]eeded", re.IGNORECASE)

# "3 Credits in X or Y" - a choice, not a single required course.
OR_GROUP_RE = re.compile(r"\bor\b", re.IGNORECASE)

# Sections listing courses already taken, withdrawn, in progress, or named in
# advisor notes. None of them are remaining requirements.
STOP_SECTIONS = (
    "Fall Through",
    "Insufficient",
    "In-progress",
    "Over The Limit",
    "Exceptions",
    "Notes",
)

# "Still needed" items that are not courses.
NON_COURSE_RE = re.compile(
    r"graduation application|exit survey|constitution exam|see \d+major",
    re.IGNORECASE,
)




def load_config():
    path = HERE / "config.json"
    if path.is_file():
        try:
            return json.loads(path.read_text())
        except json.JSONDecodeError as exc:
            sys.exit(f"config.json is not valid JSON: {exc}")
    return {}


def resolve_tesseract(config):
    """Find the Tesseract binary: env var, then config, then PATH, then defaults."""
    for candidate in (
        os.environ.get("TESSERACT_CMD"),
        config.get("tesseract_cmd"),
        shutil.which("tesseract"),
        *COMMON_TESSERACT_PATHS,
    ):
        if candidate and Path(candidate).is_file():
            pytesseract.pytesseract.tesseract_cmd = candidate
            return candidate
    return None


def ocr_pages(pdf_path, dpi):
    """Render each page to a grayscale image and OCR it."""
    lines = []
    doc = pymupdf.open(pdf_path)
    matrix = pymupdf.Matrix(dpi / 72.0, dpi / 72.0)
    total = len(doc)
    for number, page in enumerate(doc, 1):
        pix = page.get_pixmap(matrix=matrix, colorspace=pymupdf.csGRAY)
        img = Image.frombytes("L", (pix.width, pix.height), pix.samples)
        text = pytesseract.image_to_string(
            img, config="--psm 6 -c preserve_interword_spaces=1"
        )
        print(f"  page {number}/{total} OCR'd", file=sys.stderr)
        lines.extend(text.splitlines())
    doc.close()
    return lines


def trim_to_requirements(lines):
    """Drop everything from the first completed-courses section onward."""
    for i, line in enumerate(lines):
        stripped = line.strip()
        if any(stripped.startswith(section) for section in STOP_SECTIONS):
            return lines[:i]
    return lines


def find_remaining(lines):
    """Pull course codes from 'Still needed:' lines only."""
    found = {}
    for line in lines:
        if not STILL_NEEDED_RE.search(line):
            continue
        tail = STILL_NEEDED_RE.split(line, maxsplit=1)[-1]
        if NON_COURSE_RE.search(tail):
            continue
        codes = COURSE_RE.findall(tail)
        for subject, number in codes:
            key = f"{subject}{number}"
            found.setdefault(key, {
                "id": key,
                "display": f"{subject} {number}",
                "requirement": " ".join(line.split())[:110],
                # A pick-one elective. Two full codes on the line is the
                # obvious case, but DegreeWorks usually drops the subject
                # after the first one - "4 Credits in MSAL 1216 or 1216L or
                # 2225" - so only MSAL 1216 ever matched and the flag never
                # fired on the one case it exists for. Treat an "or" in the
                # requirement as the real signal. A false positive only asks
                # someone to check; a false negative silently plans a course
                # the student may not need.
                "needs_review": len(codes) > 1 or OR_GROUP_RE.search(tail) is not None,
            })
    return found




def summarize_still_needed(lines):
    """Count the "Still needed" lines and say why each produced no course.

    Returns (total, administrative, unreadable).

    This exists because of a real case: a student who has finished their major
    requirements still has "Still needed" lines in the audit - the graduation
    application, the exit survey, a constitution exam. Those are not courses
    and nothing can schedule them. Reporting that as a bad export sends the
    user off to re-export a file that was perfectly correct.
    """
    total = administrative = unreadable = 0
    for line in lines:
        if not STILL_NEEDED_RE.search(line):
            continue
        total += 1
        tail = STILL_NEEDED_RE.split(line, maxsplit=1)[-1]
        if NON_COURSE_RE.search(tail):
            administrative += 1
        elif not COURSE_RE.findall(tail):
            unreadable += 1
    return total, administrative, unreadable


def diagnose(text: str, pdf_path) -> str:
    """Explain WHICH wrong export this is, instead of guessing.

    There are two ways to get a useless audit, and they need opposite fixes:

      * a Chrome "Save as PDF" of the dashboard - has a real text layer, but
        the requirement blocks print collapsed
      * a Microsoft Print to PDF taken while the blocks were collapsed - no
        text layer (so OCR is right), and no "Still needed" lines in it

    Both end here with zero courses. Telling the user it is "probably the
    Chrome one" when it is not sends them to re-export the same way again.
    """
    import pymupdf

    try:
        doc = pymupdf.open(pdf_path)
        chars = sum(len(page.get_text()) for page in doc)
        pages = doc.page_count
        producer = (doc.metadata or {}).get("producer") or "unknown"
    except Exception:
        chars, pages, producer = -1, -1, "unknown"

    found_phrase = "still needed" in text.lower()
    lines = [f"\nNo remaining courses found in {pages} page(s). "
             f"Producer: {producer}."]

    if chars > 100:
        lines += [
            "",
            "This PDF has a real text layer, so it is the Chrome "
            '"Save as PDF" export of the dashboard.',
            "That export always prints the requirement blocks collapsed, so",
            '"Still needed" never appears in it.',
        ]
    elif not found_phrase:
        lines += [
            "",
            'OCR read the file fine but found no "Still needed" anywhere, so',
            "the requirement blocks were COLLAPSED when the PDF was made.",
            "A collapsed block is not in the file at all - no tool can recover it.",
        ]
    else:
        total, admin, unreadable = summarize_still_needed(text.splitlines())
        if admin and admin + unreadable == total:
            # The export is fine. There is simply nothing left to schedule.
            lines = [f"\nNo remaining courses to plan. The audit has {total} "
                     f'"Still needed" item(s) and none of them is a course:']
            lines += [f"  - {admin} administrative (graduation application, "
                      "exit survey, constitution exam and the like)"]
            if unreadable:
                lines += [f"  - {unreadable} line(s) where no course code could "
                          "be read. DegreeWorks draws the multi-option markers "
                          "as circled symbols that OCR cannot resolve; these are "
                          "electives, which are out of scope. See "
                          "SPIKE_FINDINGS.md."]
            lines += [
                "",
                "This looks like a completed set of major requirements, not a "
                "bad export. Nothing to re-export and nothing to plan.",
            ]
            return "\n".join(lines)

        lines += ["", '"Still needed" is present but no course codes parsed out '
                  "of it. Run with --dump and check the OCR text."]

    lines += [
        "",
        "To get a usable audit:",
        "  1. Open the audit in DegreeWorks",
        "  2. Expand EVERY requirement block first (there is an expand-all "
        "control)",
        "  3. Use DegreeWorks' own print view",
        "  4. Save with Microsoft Print to PDF",
        "",
        "A good export is usually 9+ pages and has no text layer. "
        "See SPIKE_FINDINGS.md.",
    ]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="OCR a DegreeWorks audit PDF.")
    ap.add_argument("pdf", help="the full-content audit (Microsoft Print to PDF)")
    ap.add_argument("-o", "--out", default="remaining_courses.json")
    ap.add_argument("--dump", action="store_true", help="print OCR text and exit")
    ap.add_argument("--dpi", type=int, help="override OCR dpi (default 300)")
    args = ap.parse_args()

    path = Path(args.pdf)
    if not path.is_file():
        sys.exit(f"File not found: {path}")

    config = load_config()
    dpi = args.dpi or config.get("ocr_dpi", 300)

    binary = resolve_tesseract(config)
    if not binary:
        sys.exit(
            "Tesseract binary not found. Install it from\n"
            "  https://github.com/UB-Mannheim/tesseract/wiki\n"
            "then set TESSERACT_CMD, or copy config.example.json to "
            "config.json and set tesseract_cmd there."
        )

    print(f"Tesseract: {binary}", file=sys.stderr)
    print("Running OCR (this takes a minute)...", file=sys.stderr)
    lines = ocr_pages(path, dpi)

    if args.dump:
        for n, line in enumerate(lines, 1):
            print(f"{n:4d}| {line}")
        return

    courses = find_remaining(trim_to_requirements(lines))

    if not courses:
        print(
            diagnose("\n".join(lines), path),
            file=sys.stderr,
        )

    out_path = Path(args.out)
    if out_path.parent != Path("."):
        out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({
        "source": path.name,
        "method": "ocr",
        "count": len(courses),
        "courses": sorted(courses.values(), key=lambda c: c["id"]),
    }, indent=2))

    print(f"\nWrote {len(courses)} remaining courses to {out_path}")
    for course in sorted(courses.values(), key=lambda c: c["id"]):
        flag = "   <-- multi-option, verify" if course["needs_review"] else ""
        print(f"  {course['display']:<12} {course['requirement']}{flag}")
    print("\nOCR can misread characters. Check these against your audit.")


if __name__ == "__main__":
    main()
