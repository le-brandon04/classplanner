"""One test per check the validator makes.

Each test builds a small plan that breaks exactly one rule, so a failure here
names the rule that stopped working.
"""
import pytest

from validator import ERROR, NOTE, WARNING, check_plan, parse_term, read_plan

# A tiny plan that is legal: 1301K -> 1302K, with MATH 1113 concurrent.
GOOD = [("Fall 2026", "CPSC 1301K", 4),
        ("Fall 2026", "MATH 1113", 3),
        ("Spring 2027", "CPSC 1302K", 4)]


def codes(issues, severity=None):
    return sorted(i.code for i in issues
                  if severity is None or i.severity == severity)


def run(path, catalog, offered, **kw):
    plan = read_plan(path)
    return plan, check_plan(plan, catalog, offered, **kw)


# ---------------------------------------------------------------- reading

def test_parse_term_reads_the_labels_the_exporter_writes():
    assert parse_term("Spring 2027") < parse_term("Summer 2027") < parse_term("Fall 2027")
    assert parse_term("Fall 2027") < parse_term("Spring 2028")
    assert parse_term("Semester One") is None
    assert parse_term("") is None


def test_reads_a_plan_and_finds_every_course(make_plan, catalog, offered):
    plan, issues = run(make_plan(GOOD), catalog, offered)
    assert len(plan.entries) == 3
    assert [lbl for _k, lbl in plan.terms] == ["Fall 2026", "Spring 2027"]


def test_subtotal_and_blank_rows_are_not_courses(make_plan, catalog, offered, tmp_path):
    from openpyxl import load_workbook
    path = make_plan(GOOD)
    wb = load_workbook(path)
    ws = wb.active
    ws.cell(row=9, column=3, value="Spring 2027 total")   # a subtotal row
    ws.cell(row=9, column=4, value=7)
    ws.cell(row=11, column=3, value="Total credits")
    wb.save(path)
    plan, _ = run(path, catalog, offered)
    assert len(plan.entries) == 3


def test_a_term_written_once_per_block_carries_down(make_plan, catalog, offered):
    """A human-made sheet usually writes the term on the first row only."""
    rows = [("Fall 2026", "CPSC 1301K", 4),
            (None, "MATH 1113", 3),
            ("Spring 2027", "CPSC 1302K", 4)]
    plan, issues = run(make_plan(rows), catalog, offered)
    assert len(plan.entries) == 3
    assert plan.entries[1].term_label == "Fall 2026"
    assert "bad-term" not in codes(issues)


def test_a_clean_plan_reports_nothing(make_plan, catalog, offered):
    _plan, issues = run(make_plan(GOOD), catalog, offered)
    assert codes(issues, ERROR) == []


# ---------------------------------------------------------------- the checks

def test_prerequisite_in_the_same_term_is_an_error(make_plan, catalog, offered):
    rows = [("Fall 2026", "CPSC 1301K", 4),
            ("Fall 2026", "CPSC 1302K", 4),
            ("Fall 2026", "MATH 1113", 3)]
    _plan, issues = run(make_plan(rows), catalog, offered)
    assert "prereq-order" in codes(issues, ERROR)


def test_prerequisite_after_its_dependant_is_an_error(make_plan, catalog, offered):
    rows = [("Spring 2027", "CPSC 1301K", 4),
            ("Fall 2026", "CPSC 1302K", 4),
            ("Fall 2026", "MATH 1113", 3)]
    _plan, issues = run(make_plan(rows), catalog, offered)
    assert "prereq-order" in codes(issues, ERROR)


def test_a_missing_prerequisite_is_an_assumption_by_default(make_plan, catalog, offered):
    rows = [("Spring 2027", "CPSC 1302K", 4), ("Spring 2027", "MATH 1113", 3)]
    _plan, issues = run(make_plan(rows), catalog, offered)
    assert codes(issues, ERROR) == []
    assert "prereq-not-in-plan" in codes(issues, NOTE)


def test_strict_turns_that_assumption_into_an_error(make_plan, catalog, offered):
    rows = [("Spring 2027", "CPSC 1302K", 4), ("Spring 2027", "MATH 1113", 3)]
    _plan, issues = run(make_plan(rows), catalog, offered, strict=True)
    assert "prereq-not-in-plan" in codes(issues, ERROR)


def test_a_corequisite_may_share_a_term(make_plan, catalog, offered):
    """CPSC 1302K requires MATH 1113 concurrently - same term is legal."""
    rows = [("Fall 2026", "CPSC 1301K", 4),
            ("Spring 2027", "CPSC 1302K", 4),
            ("Spring 2027", "MATH 1113", 3)]
    _plan, issues = run(make_plan(rows), catalog, offered)
    assert "coreq-order" not in codes(issues, ERROR)


def test_a_corequisite_scheduled_later_is_an_error(make_plan, catalog, offered):
    rows = [("Fall 2026", "CPSC 1301K", 4),
            ("Spring 2027", "CPSC 1302K", 4),
            ("Fall 2027", "MATH 1113", 3)]
    _plan, issues = run(make_plan(rows), catalog, offered)
    assert "coreq-order" in codes(issues, ERROR)


def test_a_course_in_a_term_it_does_not_run_is_an_error(make_plan, catalog, offered):
    """CPSC 4175 is fall only."""
    rows = [("Spring 2029", "CPSC 4175", 3)]
    _plan, issues = run(make_plan(rows), catalog, offered)
    assert "not-offered" in codes(issues, ERROR)


def test_cpsc_4000_outside_the_final_term_is_an_error(make_plan, catalog, offered):
    rows = [("Fall 2026", "CPSC 4000", 0), ("Spring 2027", "MATH 1113", 3)]
    _plan, issues = run(make_plan(rows), catalog, offered)
    assert "final-term" in codes(issues, ERROR)


def test_cpsc_4000_in_the_final_term_is_fine(make_plan, catalog, offered):
    rows = [("Fall 2026", "MATH 1113", 3), ("Spring 2027", "CPSC 4000", 0)]
    _plan, issues = run(make_plan(rows), catalog, offered)
    assert "final-term" not in codes(issues, ERROR)


def test_the_same_course_twice_is_an_error(make_plan, catalog, offered):
    rows = [("Fall 2026", "MATH 1113", 3), ("Spring 2027", "MATH 1113", 3)]
    _plan, issues = run(make_plan(rows), catalog, offered)
    assert "duplicate" in codes(issues, ERROR)


def test_an_unparseable_term_is_reported_not_ignored(make_plan, catalog, offered):
    rows = [("Semester One", "MATH 1113", 3)]
    _plan, issues = run(make_plan(rows), catalog, offered)
    assert "bad-term" in codes(issues, ERROR)


def test_a_course_we_have_no_data_for_is_a_warning(make_plan, catalog, offered):
    rows = [("Fall 2026", "MISM 4168", 3)]
    _plan, issues = run(make_plan(rows), catalog, offered)
    assert "unknown-course" in codes(issues, WARNING)
    assert codes(issues, ERROR) == []


def test_an_overloaded_term_is_a_warning_not_an_error(make_plan, catalog, offered):
    rows = [("Fall 2026", "CPSC 1301K", 4), ("Fall 2026", "MATH 1113", 3)]
    _plan, issues = run(make_plan(rows), catalog, offered, max_credits=5)
    assert "credit-load" in codes(issues, WARNING)
    assert codes(issues, ERROR) == []


def test_case_and_spacing_in_course_ids_do_not_matter(make_plan, catalog, offered):
    rows = [("Fall 2026", "cpsc1301k", 4),
            ("Fall 2026", "CPSC 1301K", 4)]
    _plan, issues = run(make_plan(rows), catalog, offered)
    assert "duplicate" in codes(issues, ERROR), "the two spellings are one course"


# ---------------------------------------------------------------- round trip

def test_a_plan_the_planner_produced_passes_the_validator(tmp_path, catalog, offered):
    """The real guarantee: anything planner.py writes, validator.py accepts."""
    from export_excel import write_plan
    from planner import build_terms, norm, plan_with_ilp, term_label

    courses = [norm(c) for c in ("CPSC 1301K", "CPSC 1302K", "MATH 1113",
                                 "MATH 2125", "CPSC 2108", "CPSC 3175",
                                 "CPSC 4175", "CPSC 4176", "CPSC 4000")]
    terms = build_terms("Fall 2026", 12, True)
    plan, _ = plan_with_ilp(courses, catalog, offered, terms, 15, None, 0, [])
    rows = [{"term": term_label(terms[s - 1]), "course": catalog[c]["display"],
             "name": catalog[c]["name"], "credits": catalog[c]["credits"]}
            for s, cs in plan.items() for c in sorted(cs)]
    path = tmp_path / "round_trip.xlsx"
    write_plan(rows, path, [])

    parsed, issues = run(path, catalog, offered)
    assert len(parsed.entries) == len(courses)
    assert codes(issues, ERROR) == []
