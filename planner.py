"""
planner.py — Story 4: build a semester-by-semester plan.

Adapted from Brian's ILP scheduler. The solver and its constraints are his;
what changed is where the data comes from:

  before: prerequisites and courses hardcoded as Python lists (2021-22 catalog)
  now:    read from data/prereqs.json and data/offerings.json (Stories 2 and 3),
          and only the courses in remaining_courses.json (Story 1) are planned

Also added:
  - term availability (a fall-only course can't land in spring)
  - corequisites (dashed arrows: same term allowed)
  - real term labels ("Spring 2027") instead of semester numbers

Usage:
    python planner.py                                   # uses config.json
    python planner.py --remaining data/sample_freshman.json
    python planner.py --start "Fall 2027" --summer
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    import pulp
except ImportError:
    sys.exit("PuLP not installed. Run: pip install pulp")

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
SEASONS = ("fall", "spring", "summer")


def norm(course_id: str) -> str:
    """'CPSC 1301K' and 'cpsc1301k' both become 'CPSC1301K'.

    The parser, the data files and Brian's code all wrote IDs slightly
    differently. Normalising at load time means nobody has to agree on one.
    """
    return course_id.replace(" ", "").upper()


def prettify(course_id: str) -> str:
    """'MISM4168' -> 'MISM 4168'.

    Course ids are normalised on load, so a course with no catalog record has
    nothing to take a display name from. Put the space back rather than
    printing a run-together id into the plan.
    """
    m = re.match(r"^([A-Z]+)\s*(\d.*)$", course_id)
    return f"{m.group(1)} {m.group(2)}" if m else course_id


# ============================================================
# 0. Section times (Brian's bitmask model) — OPTIONAL
# ============================================================
# Only used if data/sections.json exists with real meeting times. The old
# version assigned made-up time slots round-robin, which created conflicts
# that don't exist. With no real section data, time conflicts are skipped.

DAY_TO_BIT = {"M": 0, "T": 1, "W": 2, "R": 3, "F": 4, "S": 5, "U": 6}


@dataclass
class Offering:
    course_id: str
    offering_id: str
    day_mask: int
    hour_mask: int


def encode_days(day_string: str) -> int:
    mask = 0
    for ch in day_string:
        mask |= 1 << DAY_TO_BIT[ch]
    return mask


def encode_hours(start_hour: int, end_hour: int) -> int:
    mask = 0
    for h in range(start_hour, end_hour):
        mask |= 1 << h
    return mask


def offerings_conflict(a: Offering, b: Offering) -> bool:
    return (a.day_mask & b.day_mask) != 0 and (a.hour_mask & b.hour_mask) != 0


# Time-block codes used in data/sections.json, e.g. "MWM" = Monday/Wednesday
# morning, "MWE" = Monday/Wednesday evening. Days come first, then one letter
# for the part of day. Two sections clash when they share a day AND a block.
DAY_GROUPS = {"MW": "MW", "TR": "TR", "MWF": "MWF", "M": "M", "T": "T",
              "W": "W", "R": "R", "F": "F"}
BLOCK_HOURS = {"M": (8, 12), "A": (12, 17), "E": (17, 22)}


def parse_block_code(code: str) -> Tuple[int, int]:
    """'MWM' -> (day_mask, hour_mask). Raises ValueError on an unknown code."""
    code = code.strip().upper()
    for days in sorted(DAY_GROUPS, key=len, reverse=True):
        if code.startswith(days) and code[len(days):] in BLOCK_HOURS:
            start, end = BLOCK_HOURS[code[len(days):]]
            return encode_days(days), encode_hours(start, end)
    raise ValueError(
        f"unrecognised time-block code {code!r}. Expected days (MW, TR, MWF, "
        "M, T, W, R, F) followed by M (morning), A (afternoon) or E (evening), "
        'e.g. "MWM" or "TRE".'
    )


def load_conflict_pairs(path: Path, courses: List[str],
                        warnings: Optional[List[str]] = None
                        ) -> List[Tuple[str, str]]:
    """Read data/sections.json and return pairs that cannot share a term.

    Two shapes are accepted per course:
        "CPSC 4115": "MWM"                       one section
        "CPSC 4115": ["MWM", "TRE"]              several sections
    A course with several sections only clashes when EVERY one of its sections
    clashes with every one of the other course's - otherwise the student can
    just pick a different section.
    """
    if not path.is_file():
        return []
    raw = json.loads(path.read_text())

    # The file ships with made-up meeting times so the format is documented
    # and testable. Those must never reach the solver: a fabricated clash is
    # a hard constraint, so it can push a course into a later term and the
    # resulting plan looks exactly like a real one. Refusing to use them is
    # the only safe default - a plan with no time-conflict checking is
    # honestly incomplete, where a plan built on invented times is wrong.
    #
    # To turn checking on, replace the times with real ones from the CSU
    # schedule of classes and set "placeholder" to false.
    if raw.get("placeholder", False):
        if warnings is not None:
            warnings.append(
                "Time-conflict checking is OFF. data/sections.json still "
                "holds placeholder meeting times, so the plan is valid by "
                "term but two courses in the same term may meet at the same "
                "hour. Replace them with real times from the schedule of "
                "classes and set \"placeholder\": false to enable it.")
        return []

    sections: Dict[str, List[Tuple[int, int]]] = {}
    for cid, codes in raw.get("sections", {}).items():
        key = norm(cid)
        if key not in courses:
            continue
        if isinstance(codes, str):
            codes = [codes]
        try:
            sections[key] = [parse_block_code(c) for c in codes]
        except ValueError as exc:
            if warnings is not None:
                warnings.append(f"{cid}: {exc}")

    pairs = []
    for a, b in combinations(sorted(sections), 2):
        if all(
            (da & db) and (ha & hb)
            for da, ha in sections[a]
            for db, hb in sections[b]
        ):
            pairs.append((a, b))
    return pairs


# ============================================================
# 1. Loading the three inputs
# ============================================================

def load_json(path: Path, label: str) -> dict:
    if not path.is_file():
        sys.exit(f"{label} not found: {path}")
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        sys.exit(f"{label} is not valid JSON ({path}): {exc}")


def load_catalog(path: Path) -> Dict[str, dict]:
    """Story 2 input -> {norm_id: course record}."""
    data = load_json(path, "Prerequisite file")
    catalog = {}
    for c in data["courses"]:
        catalog[norm(c["id"])] = {
            "display": c["id"],
            "name": c.get("name", ""),
            "credits": c.get("credits", 3),
            "prereqs": [norm(p) for p in c.get("prereqs", [])],
            "coreqs": [norm(p) for p in c.get("coreqs", [])],
            "standing": c.get("standing"),
            # Catalog: "must be taken in the last semester prior to graduation"
            "final_term": c.get("final_term", False),
        }
    return catalog


def decode_term(code: str, ignore_online: bool = True) -> bool:
    """Is the course available this term?

    'F' = face-to-face, 'O' = online, '*' = sometimes, '-' = not in that mode.
    With ignore_online (the team's decision, and the default) only a
    face-to-face section counts, so '-O' reads as NOT offered.
    """
    return "F" in code if ignore_online else any(ch in "FO" for ch in code)


def load_offerings(path: Path, warnings: List[str],
                   ignore_online: bool = True) -> Dict[str, Dict[str, bool]]:
    """Story 3 input -> {norm_id: {'fall': bool, 'spring': bool, 'summer': bool}}."""
    data = load_json(path, "Offerings file")
    result = {}
    for cid, entry in data["courses"].items():
        raw = entry.get("raw")
        if not raw:
            warnings.append(f"{cid}: offering unknown, assuming every term")
            result[norm(cid)] = {s: True for s in SEASONS}
            continue
        parts = raw.split()
        if len(parts) != 3:
            sys.exit(f"Offerings file: {cid} has malformed code '{raw}' "
                     "(expected three groups like 'FO FO --')")
        result[norm(cid)] = {s: decode_term(p, ignore_online)
                            for s, p in zip(SEASONS, parts)}
    return result


def load_remaining(path: Path) -> List[str]:
    """Story 1 output. Accepts the parser's format or a plain list of IDs."""
    data = load_json(path, "Remaining-courses file")
    items = data["courses"] if isinstance(data, dict) else data
    return [norm(c["id"] if isinstance(c, dict) else c) for c in items]


# ============================================================
# 2. Terms
# ============================================================

def build_terms(start: str, count: int, include_summer: bool) -> List[Tuple[str, int]]:
    """'Spring 2027', 6 -> [('spring',2027), ('fall',2027), ...]."""
    try:
        season, year = start.split()
        season, year = season.lower(), int(year)
    except ValueError:
        sys.exit(f"start_term must look like 'Spring 2027', got '{start}'")
    order = ["spring", "summer", "fall"] if include_summer else ["spring", "fall"]
    if season not in order:
        sys.exit(f"start_term season '{season}' not allowed "
                 f"(summer requires include_summer)")
    terms, i = [], order.index(season)
    while len(terms) < count:
        terms.append((order[i], year))
        i += 1
        if i == len(order):
            i, year = 0, year + 1
    return terms


def term_label(term: Tuple[str, int]) -> str:
    return f"{term[0].capitalize()} {term[1]}"


# ============================================================
# 3. The ILP (Brian's model, extended)
# ============================================================

def plan_with_ilp(
    courses: List[str],
    catalog: Dict[str, dict],
    offered: Dict[str, Dict[str, bool]],
    terms: List[Tuple[str, int]],
    max_credits: int,
    conflict_pairs: Optional[List[Tuple[str, str]]] = None,
    prior_credits: int = 0,
    warnings: Optional[List[str]] = None,
) -> Tuple[Dict[int, List[str]], float]:

    S = range(1, len(terms) + 1)
    remaining = set(courses)
    model = pulp.LpProblem("Class_Plan", pulp.LpMinimize)

    x = {(c, s): pulp.LpVariable(f"x_{c}_{s}", cat=pulp.LpBinary)
         for c in courses for s in S}
    T = pulp.LpVariable("T", lowBound=1, upBound=len(terms), cat=pulp.LpInteger)

    # Each remaining course is taken exactly once.
    for c in courses:
        model += pulp.lpSum(x[c, s] for s in S) == 1, f"once_{c}"

    # Credit cap per term.
    for s in S:
        model += (pulp.lpSum(catalog[c]["credits"] * x[c, s] for c in courses)
                  <= max_credits), f"cap_{s}"

    # Term availability: can't take a course in a term it isn't offered.
    for c in courses:
        for s in S:
            season = terms[s - 1][0]
            if not offered[c][season]:
                model += x[c, s] == 0, f"offered_{c}_{s}"

    # Prerequisites: strictly earlier term. A prereq that isn't in the
    # remaining list is already done (or in progress), so it's satisfied.
    for c in courses:
        for p in catalog[c]["prereqs"]:
            if p not in remaining:
                continue
            for s in S:
                model += (x[c, s] <= pulp.lpSum(x[p, t] for t in S if t < s),
                          f"pre_{p}_{c}_{s}")

    # Corequisites: same term or earlier.
    for c in courses:
        for p in catalog[c]["coreqs"]:
            if p not in remaining:
                continue
            for s in S:
                model += (x[c, s] <= pulp.lpSum(x[p, t] for t in S if t <= s),
                          f"co_{p}_{c}_{s}")

    # Optional time conflicts (Brian's bitmask model; needs real section data).
    for a, b in conflict_pairs or []:
        if a in remaining and b in remaining:
            for s in S:
                model += x[a, s] + x[b, s] <= 1, f"clash_{a}_{b}_{s}"

    # Class-standing restrictions. The catalog phrases these as enrollment
    # restrictions, not prerequisites: CPSC 3165 says "Freshman or Sophomore
    # students may not enroll". Junior standing is 60 earned credits, senior 90.
    #
    # This only works if we know credits earned outside the courses being
    # planned (core curriculum, electives), which the audit does not give us.
    # Pass --prior-credits to enable it. If the threshold is unreachable from
    # the data we have, the rule is skipped with a warning rather than making
    # the whole plan infeasible.
    STANDING_CREDITS = {"SO": 30, "JR": 60, "SR": 90}
    reachable = prior_credits + sum(catalog[c]["credits"] for c in courses)
    for c in courses:
        need = STANDING_CREDITS.get(catalog[c].get("standing"))
        if not need:
            continue
        if need > reachable - catalog[c]["credits"]:
            if warnings is not None:
                warnings.append(
                    f"{catalog[c]['display']}: requires {catalog[c]['standing']} standing "
                    f"({need} credits) but only {reachable} are known to the planner. "
                    "Rule not enforced - pass --prior-credits with credits already earned."
                )
            continue
        for s in S:
            earned = prior_credits + pulp.lpSum(
                catalog[d]["credits"] * x[d, t] for d in courses for t in S if t < s
            )
            model += earned >= need - need * (1 - x[c, s]), f"standing_{c}_{s}"

    # Courses the catalog requires in the final term (CPSC 4000 Baccalaureate
    # Survey: "must be taken in the last semester prior to graduation"). It has
    # no prereqs and 0 credits, so without this it would land in term 1.
    for c in courses:
        if catalog[c].get("final_term"):
            for s in S:
                model += s * x[c, s] >= T - len(terms) * (1 - x[c, s]), f"final_{c}_{s}"

    # T is the last term used.
    for c in courses:
        for s in S:
            model += s * x[c, s] <= T, f"T_{c}_{s}"

    # Minimise graduation term first; among equally short plans, prefer
    # taking courses earlier. (Brian's version minimised T only, so ties were
    # broken arbitrarily and courses could drift late for no reason.)
    model += 1000 * T + pulp.lpSum(s * x[c, s] for c in courses for s in S)

    start = time.perf_counter()
    model.solve(pulp.PULP_CBC_CMD(msg=False))
    elapsed = time.perf_counter() - start

    status = pulp.LpStatus[model.status]
    if status != "Optimal":
        raise RuntimeError(
            f"No valid plan exists (solver status: {status}). Usually this means "
            "the credit cap is too low, too few terms were allowed, or a course "
            "is never offered in any allowed term."
        )

    by_term: Dict[int, List[str]] = {}
    for c in courses:
        for s in S:
            if pulp.value(x[c, s]) > 0.5:
                by_term.setdefault(s, []).append(c)
    return dict(sorted(by_term.items())), elapsed


# ============================================================
# 4. Main
# ============================================================

def main():
    ap = argparse.ArgumentParser(description="Build a class plan.")
    ap.add_argument("--remaining", help="courses still needed (parser output)")
    ap.add_argument("--start", help="first term to plan, e.g. 'Spring 2027'")
    ap.add_argument("--summer", action="store_true", help="allow summer terms")
    ap.add_argument("--max-credits", type=int)
    ap.add_argument("--terms", type=int, help="how many terms to allow at most")
    ap.add_argument("--include-online", action="store_true",
                    help="count online-only sections as available "
                         "(default: face-to-face only)")
    ap.add_argument("--prior-credits", type=int,
                    help="credits already earned, for class-standing rules")
    ap.add_argument("-o", "--out", help="output .xlsx path")
    args = ap.parse_args()

    cfg_path = HERE / "config.json"
    cfg = json.loads(cfg_path.read_text()) if cfg_path.is_file() else {}

    def setting(cli, key, default):
        return cli if cli not in (None, False) else cfg.get(key, default)

    prereq_path = HERE / cfg.get("prereq_file", "data/prereqs.json")
    offer_path = HERE / cfg.get("offerings_file", "data/offerings.json")
    remaining_path = Path(setting(args.remaining, "remaining_file",
                                  "remaining_courses.json"))
    start_term = setting(args.start, "start_term", "Spring 2027")
    summer = args.summer or cfg.get("include_summer", False)
    max_credits = setting(args.max_credits, "max_credits_per_term", 15)
    n_terms = setting(args.terms, "max_terms", 12)
    prior_credits = setting(args.prior_credits, "prior_credits", 0)
    out_path = Path(setting(args.out, "output_file", "class_plan.xlsx"))

    warnings: List[str] = []
    catalog = load_catalog(prereq_path)
    ignore_online = not (args.include_online or cfg.get("include_online", False))
    offered = load_offerings(offer_path, warnings, ignore_online)
    courses = load_remaining(remaining_path)

    if not courses:
        sys.exit(
            f"{remaining_path} lists no courses, so there is nothing to plan.\n"
            "If it came from parse_audit_ocr.py, the parser found nothing - "
            "re-export the audit with every requirement block expanded."
        )

    # Courses the audit lists but our catalog doesn't know (e.g. MISM 4168
    # for a student with a second major). Still planned, just unconstrained.
    for c in courses:
        if c not in catalog:
            warnings.append(f"{prettify(c)}: not in prerequisite file, planned "
                            "with no prereqs and 3 credits")
            catalog[c] = {"display": prettify(c), "name": "", "credits": 3,
                          "prereqs": [], "coreqs": [], "standing": None}
        if c not in offered:
            offered[c] = {s: True for s in SEASONS}

    # Only warn about unknown offerings for courses we're actually planning.
    warnings = [w for w in warnings
                if not w.endswith("assuming every term")
                or norm(w.split(":")[0]) in courses]

    for c in courses:
        if not any(offered[c][s] for s in (SEASONS if summer else SEASONS[:2])):
            sys.exit(f"{catalog[c]['display']} is never offered in any allowed "
                     "term. Check offerings.json, or try --summer.")

    terms = build_terms(start_term, n_terms, summer)
    conflicts = load_conflict_pairs(HERE / "data" / "sections.json",
                                    courses, warnings)

    try:
        plan, elapsed = plan_with_ilp(courses, catalog, offered, terms,
                                      max_credits, conflicts, prior_credits,
                                      warnings)
    except RuntimeError as exc:
        sys.exit(f"\n{exc}")

    # ---- report --------------------------------------------------------
    print(f"\nPlan for {len(courses)} remaining courses "
          f"(max {max_credits} credits/term, summer "
          f"{'on' if summer else 'off'}, "
          f"{'face-to-face only' if ignore_online else 'online included'})")
    for s, cs in plan.items():
        credits = sum(catalog[c]["credits"] for c in cs)
        print(f"\n{term_label(terms[s - 1])}  ({credits} credits)")
        for c in sorted(cs):
            print(f"  {catalog[c]['display']:<12} {catalog[c]['name']}")
    last = max(plan) if plan else 0
    if last:
        print(f"\nGraduates after {term_label(terms[last - 1])} "
              f"({last} term{'s' if last != 1 else ''}).  Solved in {elapsed:.2f}s")

    if warnings:
        print("\nWarnings:")
        for w in warnings:
            print(f"  - {w}")

    rows = [
        {"term": term_label(terms[s - 1]), "order": s,
         "course": catalog[c]["display"], "name": catalog[c]["name"],
         "credits": catalog[c]["credits"]}
        for s, cs in plan.items() for c in sorted(cs)
    ]

    try:
        from export_excel import write_plan
        write_plan(rows, out_path, warnings)
        print(f"\nWrote {out_path}")
    except ImportError:
        json_path = out_path.with_suffix(".json")
        json_path.write_text(json.dumps(rows, indent=2))
        print(f"\nexport_excel.py not found; wrote {json_path} instead")


if __name__ == "__main__":
    main()
