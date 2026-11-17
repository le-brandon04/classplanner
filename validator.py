"""
validator.py — Story 6: check an existing class plan for prerequisite problems.

This is the specification's second functional requirement:

    "Given a prerequisite graph and a class plan Excel doc, the software
     should be able to report the prerequisite issues in the plan."

It is the planner run backwards. Instead of building a schedule that satisfies
the constraints, it takes a schedule somebody already wrote — one of ours, or
one an advisor typed by hand — and reports every constraint it breaks.

The course data is loaded with planner.py's own loaders, so the two programs
can never disagree about what the prerequisite graph says. Nothing about CSU's
curriculum is in this file either.

Usage:
    python validator.py freshman_plan.xlsx
    python validator.py my_plan.xlsx --max-credits 12
    python validator.py my_plan.xlsx --strict --out issues.xlsx

Exit status is 0 when the plan is clean and 1 when it has errors, so the
checker can be used from a script or a test.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    from openpyxl import Workbook, load_workbook
except ImportError:
    sys.exit("openpyxl not installed. Run: pip install openpyxl")

# Reuse the planner's loaders so both programs read the data the same way.
from planner import (SEASONS, base_dir, load_catalog, load_offerings,
                     norm)

HERE = base_dir()

# Spring comes before Summer comes before Fall inside one calendar year.
SEASON_ORDER = {"spring": 0, "summer": 1, "fall": 2}
SEASON_BY_RANK = ("spring", "summer", "fall")

ERROR, WARNING, NOTE = "ERROR", "WARNING", "NOTE"


# ============================================================
# 1. Reading the plan
# ============================================================

@dataclass
class Entry:
    """One scheduled course as it appears in the spreadsheet."""
    course: str           # normalised id, e.g. "CPSC4175"
    display: str          # as written in the sheet
    term_label: str       # "Fall 2028"
    term_key: Tuple[int, int]
    credits: float
    row: int              # worksheet row, so the report can point at it


@dataclass
class Issue:
    severity: str
    code: str
    message: str
    term: str = ""
    course: str = ""
    row: Optional[int] = None


@dataclass
class Plan:
    entries: List[Entry] = field(default_factory=list)
    issues: List[Issue] = field(default_factory=list)

    @property
    def terms(self) -> List[Tuple[Tuple[int, int], str]]:
        """Every term used, in chronological order."""
        seen = {}
        for e in self.entries:
            seen[e.term_key] = e.term_label
        return sorted(seen.items())


def parse_term(label: str) -> Optional[Tuple[int, int]]:
    """'Fall 2028' -> (2028, 2). None if it isn't a term label at all."""
    parts = str(label).strip().split()
    if len(parts) != 2:
        return None
    season, year = parts[0].lower(), parts[1]
    if season not in SEASON_ORDER or not year.isdigit():
        return None
    return int(year), SEASON_ORDER[season]


def _header_row(ws) -> Optional[Tuple[int, Dict[str, int]]]:
    """Find the header row and map our four column names onto it.

    Accepts anything with a Course column; Term, Title and Credits are
    matched when present. This way a hand-made sheet works as well as ours.
    """
    wanted = {
        "term": ("term", "semester"),
        "course": ("course", "course id", "course code", "class"),
        "name": ("title", "name", "course title"),
        "credits": ("credits", "credit", "hours", "credit hours"),
    }
    for row in range(1, min(ws.max_row, 25) + 1):
        found: Dict[str, int] = {}
        for col in range(1, min(ws.max_column, 20) + 1):
            value = ws.cell(row=row, column=col).value
            if not isinstance(value, str):
                continue
            text = value.strip().lower()
            for key, aliases in wanted.items():
                if key not in found and text in aliases:
                    found[key] = col
        if "course" in found:
            return row, found
    return None


def read_plan(path: Path, sheet: Optional[str] = None) -> Plan:
    """Read a class plan spreadsheet into Entry records.

    Tolerant on purpose. Subtotal rows, blank spacer rows and a term written
    only once per block are all normal in a plan a human made, and none of
    them are errors.
    """
    if not path.is_file():
        sys.exit(f"Class plan not found: {path}")
    try:
        wb = load_workbook(path, data_only=True)
    except Exception as exc:                       # noqa: BLE001 - surfaced to user
        sys.exit(f"Could not open {path} as a spreadsheet: {exc}")

    ws = wb[sheet] if sheet else wb.worksheets[0]
    header = _header_row(ws)
    if header is None:
        sys.exit(
            f"No course table found in '{ws.title}'. The sheet needs a header "
            "row with a 'Course' column (and ideally 'Term' and 'Credits'). "
            "Pass --sheet to choose a different worksheet."
        )
    header_row, cols = header

    plan = Plan()
    if "term" not in cols:
        plan.issues.append(Issue(
            WARNING, "no-term-column",
            "The sheet has no Term column, so the order of courses cannot be "
            "checked. Only duplicate and unknown-course checks will run."))

    current_term = ""
    for row in range(header_row + 1, ws.max_row + 1):
        raw_course = ws.cell(row=row, column=cols["course"]).value
        if raw_course is None or not str(raw_course).strip():
            continue
        display = str(raw_course).strip()
        if "total" in display.lower():            # subtotal / grand-total row
            continue

        if "term" in cols:
            raw_term = ws.cell(row=row, column=cols["term"]).value
            if raw_term is not None and str(raw_term).strip():
                current_term = str(raw_term).strip()

        key = parse_term(current_term) if current_term else None
        if "term" in cols and key is None:
            plan.issues.append(Issue(
                ERROR, "bad-term", row=row, course=display, term=current_term,
                message=(f"term {current_term or '(blank)'!r} is not a term "
                         "label. Expected something like 'Fall 2028'.")))
            continue

        raw_credits = ws.cell(row=row, column=cols["credits"]).value if "credits" in cols else None
        credits = float(raw_credits) if isinstance(raw_credits, (int, float)) else 0.0

        plan.entries.append(Entry(
            course=norm(display), display=display,
            term_label=current_term, term_key=key or (0, 0),
            credits=credits, row=row))

    if not plan.entries and not plan.issues:
        sys.exit(f"No courses found in '{ws.title}'. Is this the right sheet?")
    return plan


# ============================================================
# 2. The checks
# ============================================================

def check_plan(
    plan: Plan,
    catalog: Dict[str, dict],
    offered: Dict[str, Dict[str, bool]],
    *,
    max_credits: Optional[int] = None,
    prior_credits: int = 0,
    strict: bool = False,
    ordered: bool = True,
) -> List[Issue]:
    """Every rule the planner enforces, checked against a finished plan."""
    issues: List[Issue] = list(plan.issues)
    placed: Dict[str, Entry] = {}

    def label(cid: str) -> str:
        return catalog.get(cid, {}).get("display", cid)

    # --- one entry per course -------------------------------------------
    for e in plan.entries:
        if e.course in placed:
            first = placed[e.course]
            issues.append(Issue(
                ERROR, "duplicate", row=e.row, course=e.display, term=e.term_label,
                message=(f"{e.display} appears twice: {first.term_label} "
                         f"(row {first.row}) and {e.term_label} (row {e.row}).")))
        else:
            placed[e.course] = e

    # --- courses we have no data for -------------------------------------
    for cid, e in placed.items():
        if cid not in catalog:
            issues.append(Issue(
                WARNING, "unknown-course", row=e.row, course=e.display, term=e.term_label,
                message=(f"{e.display} is not in the prerequisite file, so its "
                         "prerequisites and term availability were not checked.")))

    if not ordered:
        return issues

    last_key = max((e.term_key for e in plan.entries), default=(0, 0))

    # --- prerequisites and corequisites ----------------------------------
    for cid, e in placed.items():
        record = catalog.get(cid)
        if not record:
            continue

        for p in record["prereqs"]:
            other = placed.get(p)
            if other is None:
                issues.append(Issue(
                    ERROR if strict else NOTE, "prereq-not-in-plan",
                    row=e.row, course=e.display, term=e.term_label,
                    message=(f"{e.display} requires {label(p)}, which is not in "
                             "the plan. " + ("Assumed already completed."
                                             if not strict else
                                             "--strict: every prerequisite must appear."))))
            elif other.term_key >= e.term_key:
                when = ("the same term as" if other.term_key == e.term_key
                        else "after")
                issues.append(Issue(
                    ERROR, "prereq-order", row=e.row, course=e.display, term=e.term_label,
                    message=(f"{e.display} ({e.term_label}) requires "
                             f"{other.display}, but that is scheduled {when} it "
                             f"({other.term_label}, row {other.row}). A "
                             "prerequisite must finish in an earlier term.")))

        for p in record["coreqs"]:
            other = placed.get(p)
            if other is None:
                issues.append(Issue(
                    ERROR if strict else NOTE, "coreq-not-in-plan",
                    row=e.row, course=e.display, term=e.term_label,
                    message=(f"{e.display} must be taken with or after "
                             f"{label(p)}, which is not in the plan. "
                             + ("Assumed already completed." if not strict else
                                "--strict: every corequisite must appear."))))
            elif other.term_key > e.term_key:
                issues.append(Issue(
                    ERROR, "coreq-order", row=e.row, course=e.display, term=e.term_label,
                    message=(f"{e.display} ({e.term_label}) must be taken with or "
                             f"after {other.display}, but that is scheduled later "
                             f"({other.term_label}, row {other.row}).")))

    # --- offered in that term --------------------------------------------
    for cid, e in placed.items():
        avail = offered.get(cid)
        if not avail or e.term_key == (0, 0):
            continue
        season = SEASON_BY_RANK[e.term_key[1]]
        if not avail.get(season, True):
            runs = [s for s in SEASONS if avail.get(s)]
            issues.append(Issue(
                ERROR, "not-offered", row=e.row, course=e.display, term=e.term_label,
                message=(f"{e.display} is scheduled in {e.term_label} but is not "
                         f"offered in {season}. It runs in: "
                         f"{', '.join(runs) if runs else 'no term in our data'}. "
                         "(Online-only sections are not counted.)")))

    # --- courses the catalog pins to the final term -----------------------
    for cid, e in placed.items():
        if catalog.get(cid, {}).get("final_term") and e.term_key != last_key:
            final_label = next(lbl for key, lbl in plan.terms if key == last_key)
            issues.append(Issue(
                ERROR, "final-term", row=e.row, course=e.display, term=e.term_label,
                message=(f"{e.display} must be taken in the last term before "
                         f"graduation, but it is in {e.term_label} and the plan "
                         f"ends in {final_label}.")))

    # --- credit load per term ---------------------------------------------
    if max_credits:
        per_term: Dict[Tuple[int, int], float] = {}
        for e in plan.entries:
            per_term[e.term_key] = per_term.get(e.term_key, 0) + e.credits
        for key, lbl in plan.terms:
            total = per_term.get(key, 0)
            if total > max_credits:
                issues.append(Issue(
                    WARNING, "credit-load", term=lbl,
                    message=(f"{lbl} carries {total:g} credits, above the "
                             f"{max_credits}-credit limit set for this check.")))

    # --- class standing ----------------------------------------------------
    standing_credits = {"SO": 30, "JR": 60, "SR": 90}
    if prior_credits:
        running = prior_credits
        for key, lbl in plan.terms:
            for cid, e in placed.items():
                need = standing_credits.get(catalog.get(cid, {}).get("standing") or "")
                if need and e.term_key == key and running < need:
                    issues.append(Issue(
                        WARNING, "standing", row=e.row, course=e.display, term=lbl,
                        message=(f"{e.display} needs "
                                 f"{catalog[cid]['standing']} standing ({need} "
                                 f"credits) but only about {running:g} are earned "
                                 f"by {lbl}.")))
            running += sum(e.credits for e in plan.entries if e.term_key == key)

    return issues


# ============================================================
# 3. Reporting
# ============================================================

RANK = {ERROR: 0, WARNING: 1, NOTE: 2}


def print_report(path: Path, plan: Plan, issues: List[Issue]) -> int:
    errors = [i for i in issues if i.severity == ERROR]
    warnings = [i for i in issues if i.severity == WARNING]
    notes = [i for i in issues if i.severity == NOTE]

    terms = plan.terms
    span = f"{terms[0][1]} to {terms[-1][1]}" if terms else "no terms"
    n = len(terms)
    print(f"\nChecking {path.name}")
    print(f"{len(plan.entries)} courses across {n} term{'' if n == 1 else 's'} "
          f"({span})")

    for group, title in ((errors, "Errors"), (warnings, "Warnings"),
                         (notes, "Assumptions")):
        if not group:
            continue
        print(f"\n{title} ({len(group)})")
        for i in sorted(group, key=lambda x: (x.term, x.course)):
            where = f" [row {i.row}]" if i.row else ""
            print(f"  - {i.message}{where}")

    print()
    if errors:
        print(f"FAIL — {len(errors)} prerequisite "
              f"{'issue' if len(errors) == 1 else 'issues'} found.")
    else:
        print("PASS — no prerequisite issues found.")
        if warnings or notes:
            print("       See the warnings and assumptions above.")
    return 1 if errors else 0


def write_report(path: Path, source: Path, plan: Plan, issues: List[Issue]) -> None:
    """Optional spreadsheet version of the report, for handing to an advisor."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Issues"
    ws["A1"] = f"Prerequisite check — {source.name}"
    ws["A2"] = (f"{len(plan.entries)} courses, "
                f"{len([i for i in issues if i.severity == ERROR])} errors")

    headers = ["Severity", "Check", "Term", "Course", "Row", "Detail"]
    for col, text in enumerate(headers, 1):
        ws.cell(row=4, column=col, value=text)
    for n, i in enumerate(sorted(issues, key=lambda x: (RANK[x.severity], x.term)), 5):
        for col, value in enumerate(
                [i.severity, i.code, i.term, i.course, i.row, i.message], 1):
            ws.cell(row=n, column=col, value=value)
    if not issues:
        ws.cell(row=5, column=6, value="No issues found.")
    for col, width in zip("ABCDEF", (10, 20, 14, 14, 7, 100)):
        ws.column_dimensions[col].width = width
    ws.freeze_panes = "A5"
    wb.save(path)


# ============================================================
# 4. Main
# ============================================================

def main() -> None:
    ap = argparse.ArgumentParser(
        description="Check a class plan spreadsheet for prerequisite issues.")
    ap.add_argument("plan", help="the class plan .xlsx to check")
    ap.add_argument("--sheet", help="worksheet name (default: the first one)")
    ap.add_argument("--max-credits", type=int,
                    help="flag any term above this many credits")
    ap.add_argument("--prior-credits", type=int, default=0,
                    help="credits already earned, for class-standing checks")
    ap.add_argument("--strict", action="store_true",
                    help="treat a prerequisite missing from the plan as an "
                         "error instead of assuming it is already completed")
    ap.add_argument("--include-online", action="store_true",
                    help="count online-only sections as available")
    ap.add_argument("-o", "--out", help="also write the report to an .xlsx")
    args = ap.parse_args()

    cfg_path = HERE / "config.json"
    cfg = json.loads(cfg_path.read_text()) if cfg_path.is_file() else {}

    prereq_path = HERE / cfg.get("prereq_file", "data/prereqs.json")
    offer_path = HERE / cfg.get("offerings_file", "data/offerings.json")

    load_warnings: List[str] = []
    catalog = load_catalog(prereq_path)
    ignore_online = not (args.include_online or cfg.get("include_online", False))
    offered = load_offerings(offer_path, load_warnings, ignore_online)

    plan_path = Path(args.plan)
    plan = read_plan(plan_path, args.sheet)

    issues = check_plan(
        plan, catalog, offered,
        max_credits=args.max_credits or cfg.get("max_credits_per_term"),
        prior_credits=args.prior_credits or cfg.get("prior_credits", 0),
        strict=args.strict,
        ordered=not any(i.code == "no-term-column" for i in plan.issues),
    )

    status = print_report(plan_path, plan, issues)

    if args.out:
        out = Path(args.out)
        write_report(out, plan_path, plan, issues)
        print(f"\nWrote {out}")

    sys.exit(status)


if __name__ == "__main__":
    main()
