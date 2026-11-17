"""Tests for the DegreeWorks audit parser.

Until Cycle 2 the parser was the only stage with no coverage, because testing
it needed a real audit and a real audit can't go in the repository. It runs
against data/sample_audit.pdf instead — a synthetic, clearly-labelled fixture
with no student data in it, built by tests/make_sample_audit.py.

These skip rather than fail where Tesseract or PyMuPDF are missing, so the
rest of the suite still runs on a machine without the OCR stack installed.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parent.parent
SAMPLE = PROJECT / "data" / "sample_audit.pdf"

pymupdf = pytest.importorskip("pymupdf", reason="PyMuPDF not installed")
pytest.importorskip("pytesseract", reason="pytesseract not installed")

def _tesseract_available() -> bool:
    """Use the parser's own resolver, not just PATH.

    resolve_tesseract() checks an env var, config.json, PATH and then the
    usual Windows install locations. Gating these tests on shutil.which()
    alone skipped them on any machine with a default Tesseract install —
    which is most of them.
    """
    sys.path.insert(0, str(PROJECT))
    try:
        from parse_audit_ocr import load_config, resolve_tesseract
        return resolve_tesseract(load_config()) is not None
    except Exception:
        return shutil.which("tesseract") is not None


needs_tesseract = pytest.mark.skipif(
    not _tesseract_available(),
    reason="Tesseract is not installed (checked env var, config.json, PATH "
           "and the default install locations)")
needs_sample = pytest.mark.skipif(
    not SAMPLE.is_file(),
    reason="data/sample_audit.pdf missing — run tests/make_sample_audit.py")


# ------------------------------------------------------- the fixture itself

@needs_sample
def test_sample_audit_has_no_text_layer():
    """The fixture has to reproduce the property that makes this hard.

    If it ever gains a text layer it stops testing the thing we care about,
    because the parser would no longer need OCR at all.
    """
    doc = pymupdf.open(SAMPLE)
    assert sum(len(p.get_text()) for p in doc) == 0
    assert doc.page_count >= 2


@needs_sample
def test_sample_audit_is_labelled_as_synthetic():
    assert "not a real student" in (pymupdf.open(SAMPLE).metadata
                                    .get("title", "").lower())


# ----------------------------------------------------------- pure functions

def test_or_group_marks_a_requirement_for_review():
    sys.path.insert(0, str(PROJECT))
    from parse_audit_ocr import find_remaining

    found = find_remaining([
        "O CPSC 4115  Still needed: 3 Credits in CPSC 4115",
        "O Area F     Still needed: 4 Credits in MSAL 1216 or 1216L or 2225",
    ])
    assert found["CPSC4115"]["needs_review"] is False
    assert found["MSAL1216"]["needs_review"] is True, (
        "a pick-one line must be flagged. DegreeWorks drops the subject after "
        "the first option, so counting course codes alone never catches it.")


def test_non_course_requirements_are_ignored():
    sys.path.insert(0, str(PROJECT))
    from parse_audit_ocr import find_remaining

    found = find_remaining([
        "O Graduation Application  Still needed: 1 Class in Graduation Application",
        "O Exit Survey             Still needed: See Exit Survey",
    ])
    assert found == {}


def test_completed_sections_are_cut_off():
    sys.path.insert(0, str(PROJECT))
    from parse_audit_ocr import find_remaining, trim_to_requirements

    lines = [
        "O CPSC 4176  Still needed: 3 Credits in CPSC 4176",
        "Fall Through Courses",
        "O CPSC 1301K Still needed: 4 Credits in CPSC 1301K",
    ]
    found = find_remaining(trim_to_requirements(lines))
    assert "CPSC4176" in found
    assert "CPSC1301K" not in found, (
        "a course under Fall Through is already complete")


# ------------------------------------------------------------- end to end

@needs_tesseract
@needs_sample
def test_parses_the_sample_audit_end_to_end(tmp_path):
    """The whole stage: render at 300 dpi, OCR, filter, write JSON."""
    out = tmp_path / "remaining.json"
    result = subprocess.run(
        [sys.executable, str(PROJECT / "parse_audit_ocr.py"),
         str(SAMPLE), "-o", str(out)],
        capture_output=True, text=True, timeout=300, cwd=PROJECT)
    assert result.returncode == 0, result.stderr

    data = json.loads(out.read_text())
    ids = {c["id"] for c in data["courses"]}

    # the five still-needed courses in the fixture
    assert {"CPSC3175", "CPSC4115", "CPSC4175", "CPSC4176",
            "CPSC4000"} <= ids

    # nothing from Fall Through, In-progress or Insufficient
    for complete in ("CPSC1301K", "CPSC1302K", "CPSC2108", "MATH1113",
                     "MATH2125", "CPSC3125", "CPSC3131", "CPSC2105"):
        assert complete not in ids, f"{complete} is already complete"

    # the elective is found but flagged
    msal = next((c for c in data["courses"] if c["id"] == "MSAL1216"), None)
    assert msal is not None and msal["needs_review"] is True


@needs_tesseract
@needs_sample
def test_the_parsed_audit_feeds_the_planner(tmp_path):
    """Stage 1 output has to be stage 2 input, with no hand-editing."""
    remaining = tmp_path / "remaining.json"
    subprocess.run(
        [sys.executable, str(PROJECT / "parse_audit_ocr.py"),
         str(SAMPLE), "-o", str(remaining)],
        capture_output=True, text=True, timeout=300, cwd=PROJECT, check=True)

    plan = tmp_path / "plan.xlsx"
    planned = subprocess.run(
        [sys.executable, str(PROJECT / "planner.py"),
         "--remaining", str(remaining), "--start", "Fall 2026",
         "--summer", "-o", str(plan)],
        capture_output=True, text=True, timeout=300, cwd=PROJECT)
    assert planned.returncode == 0, planned.stderr
    assert plan.is_file()

    # and the plan it produced has to pass the validator
    checked = subprocess.run(
        [sys.executable, str(PROJECT / "validator.py"), str(plan)],
        capture_output=True, text=True, timeout=300, cwd=PROJECT)
    assert checked.returncode == 0, checked.stdout + checked.stderr
    assert "PASS" in checked.stdout


# ------------------------------------------- a finished set of requirements

def test_an_audit_with_only_admin_items_is_not_called_a_bad_export():
    """A student who has finished their major still has "Still needed" lines.

    Real case from our own testing: the graduation application, the exit
    survey and a constitution exam were the only ones left. The parser used
    to report that as a probable bad export and send the user off to
    re-export a file that was perfectly correct.
    """
    sys.path.insert(0, str(PROJECT))
    from parse_audit_ocr import find_remaining, summarize_still_needed

    lines = [
        "O Graduation Application  Still needed: Graduation Application Needed.",
        "O Exit Survey             Still needed: Graduation Exit Survey",
        "O Legislative Constitution  Still needed: POLS 1101 or GA Constitution Exam",
    ]
    total, admin, unreadable = summarize_still_needed(lines)
    assert (total, admin, unreadable) == (3, 3, 0)
    assert find_remaining(lines) == {}


def test_an_unreadable_elective_line_is_counted_separately():
    """DegreeWorks draws multi-option markers as circled symbols. OCR reads
    'MSAL 1216 or 1216L' as 'MSAL 1@ or 2@', which has no course number in
    it at all. That is a known limitation, not a broken export."""
    sys.path.insert(0, str(PROJECT))
    from parse_audit_ocr import summarize_still_needed

    total, admin, unreadable = summarize_still_needed(
        ["Still needed:  2 Credits in MSAL 1@ or 2@ or 3@ or 4@"])
    assert (total, admin, unreadable) == (1, 0, 1)


def test_a_real_course_still_counts_as_plannable():
    sys.path.insert(0, str(PROJECT))
    from parse_audit_ocr import summarize_still_needed

    total, admin, unreadable = summarize_still_needed(
        ["O CPSC 4176  Still needed: 3 Credits in CPSC 4176"])
    assert (total, admin, unreadable) == (1, 0, 0)
