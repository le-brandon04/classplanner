"""One test per constraint the ILP generates, plus the helpers around it."""
import json

import pytest

from planner import (build_terms, decode_term, norm, parse_block_code,
                     plan_with_ilp, prettify, term_label)

ALL = ["CPSC 1301K", "CPSC 1302K", "MATH 1113", "MATH 2125", "CPSC 2105",
       "MATH 5125U", "CPSC 2108", "CPSC 3175", "CPSC 3125", "CPSC 3131",
       "CPSC 4115", "CPSC 4155", "CPSC 4157", "CPSC 4175", "CPSC 4176",
       "CPSC 4148", "CPSC 4000", "CYBR 2159", "CYBR 2160"]


def solve(courses, catalog, offered, *, start="Fall 2026", terms=12,
          summer=True, max_credits=15, prior_credits=0):
    """Solve and return {course_id: (season, year)}."""
    term_list = build_terms(start, terms, summer)
    plan, _ = plan_with_ilp([norm(c) for c in courses], catalog, offered,
                            term_list, max_credits, None, prior_credits, [])
    return {c: term_list[s - 1] for s, cs in plan.items() for c in cs}, term_list


# ---------------------------------------------------------------- helpers

def test_norm_accepts_every_spelling_the_project_uses():
    assert norm("CPSC 1301K") == norm("cpsc1301k") == norm("Cpsc 1301k") == "CPSC1301K"


def test_prettify_restores_the_space_for_unknown_courses():
    assert prettify("MISM4168") == "MISM 4168"
    assert prettify("CPSC1301K") == "CPSC 1301K"
    assert prettify("") == ""


def test_decode_term_ignores_online_only_sections_by_default():
    assert decode_term("F-") is True
    assert decode_term("FO") is True
    assert decode_term("-O") is False          # online only
    assert decode_term("--") is False
    assert decode_term("-O", ignore_online=False) is True


def test_build_terms_skips_summer_unless_asked():
    assert build_terms("Fall 2026", 4, False) == [
        ("fall", 2026), ("spring", 2027), ("fall", 2027), ("spring", 2028)]
    assert build_terms("Fall 2026", 4, True) == [
        ("fall", 2026), ("spring", 2027), ("summer", 2027), ("fall", 2027)]


def test_term_label_is_what_the_spreadsheet_shows():
    assert term_label(("spring", 2027)) == "Spring 2027"


def test_parse_block_code_round_trip():
    days, hours = parse_block_code("MWM")
    assert days and hours
    assert parse_block_code("MWM") != parse_block_code("MWE")   # morning vs evening
    assert parse_block_code("MWM") != parse_block_code("TRM")   # different days


def test_parse_block_code_rejects_nonsense():
    with pytest.raises(ValueError, match="unrecognised time-block code"):
        parse_block_code("XYZ")


# ---------------------------------------------------------------- the model

def test_every_course_is_scheduled_exactly_once(catalog, offered):
    placed, _ = solve(ALL, catalog, offered)
    assert sorted(placed) == sorted(norm(c) for c in ALL)


def test_prerequisites_land_in_a_strictly_earlier_term(catalog, offered):
    placed, term_list = solve(ALL, catalog, offered)
    order = {t: i for i, t in enumerate(term_list)}
    for cid, term in placed.items():
        for p in catalog[cid]["prereqs"]:
            if p in placed:
                assert order[placed[p]] < order[term], (
                    f"{catalog[cid]['display']} is not after {catalog[p]['display']}")


def test_corequisites_may_share_a_term_but_never_come_later(catalog, offered):
    placed, term_list = solve(ALL, catalog, offered)
    order = {t: i for i, t in enumerate(term_list)}
    for cid, term in placed.items():
        for p in catalog[cid]["coreqs"]:
            if p in placed:
                assert order[placed[p]] <= order[term]


def test_no_course_is_scheduled_in_a_term_it_is_not_offered(catalog, offered):
    placed, _ = solve(ALL, catalog, offered)
    for cid, (season, _year) in placed.items():
        assert offered[cid][season], (
            f"{catalog[cid]['display']} placed in {season}, which it does not run in")


def test_credit_cap_is_respected(catalog, offered):
    placed, _ = solve(ALL, catalog, offered, max_credits=9)
    per_term = {}
    for cid, term in placed.items():
        per_term[term] = per_term.get(term, 0) + catalog[cid]["credits"]
    assert max(per_term.values()) <= 9


def test_cpsc_4000_lands_in_the_last_term(catalog, offered):
    placed, term_list = solve(ALL, catalog, offered)
    order = {t: i for i, t in enumerate(term_list)}
    last = max(order[t] for t in placed.values())
    assert order[placed[norm("CPSC 4000")]] == last


def test_the_three_year_chain_cannot_be_compressed(catalog, offered):
    """The project's headline result, asserted end to end: even with summer
    allowed and a generous credit cap, 3175 -> 4175 -> 4176 spans three
    academic years because of the fall-only / spring-only restrictions."""
    placed, _ = solve(ALL, catalog, offered, max_credits=30, summer=True)
    assert placed[norm("CPSC 4175")][0] == "fall"
    assert placed[norm("CPSC 4176")][0] == "spring"
    span = placed[norm("CPSC 4176")][1] - placed[norm("CPSC 3175")][1]
    assert span >= 2, "the fall-only / spring-only chain collapsed unexpectedly"


def test_taking_more_credits_does_not_shorten_the_chain(catalog, offered):
    tight, _ = solve(ALL, catalog, offered, max_credits=12)
    loose, _ = solve(ALL, catalog, offered, max_credits=30)
    assert tight[norm("CPSC 4176")] == loose[norm("CPSC 4176")]


def test_an_impossible_plan_raises_instead_of_inventing_one(catalog, offered):
    with pytest.raises(RuntimeError, match="No valid plan exists"):
        solve(ALL, catalog, offered, terms=2, summer=False)


def test_time_conflicts_keep_two_courses_apart(catalog, offered):
    """Brian's bitmask conflict model, driven by real section codes."""
    courses = [norm(c) for c in ("CPSC 4115", "CPSC 4155", "CPSC 4157")]
    term_list = build_terms("Fall 2026", 8, False)
    pairs = [(norm("CPSC 4115"), norm("CPSC 4155"))]
    plan, _ = plan_with_ilp(courses, catalog, offered, term_list, 15, pairs, 0, [])
    where = {c: s for s, cs in plan.items() for c in cs}
    assert where[norm("CPSC 4115")] != where[norm("CPSC 4155")]


def test_placeholder_section_times_are_refused_and_announced(tmp_path):
    """The shipped sections.json holds invented meeting times.

    A fabricated clash is a hard constraint, so if it reached the solver it
    could push a course into a later term and the plan would look completely
    normal. The planner has to ignore the file and say so.
    """
    from planner import load_conflict_pairs

    path = tmp_path / "sections.json"
    path.write_text(json.dumps({
        "placeholder": True,
        "sections": {"CPSC 4115": "MWM", "CPSC 4175": "MWM"},
    }))
    warnings = []
    pairs = load_conflict_pairs(path, [norm("CPSC 4115"), norm("CPSC 4175")],
                                warnings)
    assert pairs == [], "placeholder times must never become constraints"
    assert any("OFF" in w for w in warnings), (
        "silently ignoring them is as bad as silently using them - the plan "
        "has to carry the fact that nothing checked time conflicts")


def test_real_section_times_are_used_once_the_flag_is_cleared(tmp_path):
    """The other half: with placeholder false, the clash is enforced."""
    from planner import load_conflict_pairs

    path = tmp_path / "sections.json"
    path.write_text(json.dumps({
        "placeholder": False,
        "sections": {"CPSC 4115": "MWM", "CPSC 4175": "MWM"},
    }))
    warnings = []
    pairs = load_conflict_pairs(path, [norm("CPSC 4115"), norm("CPSC 4175")],
                                warnings)
    assert pairs == [(norm("CPSC 4115"), norm("CPSC 4175"))]
    assert warnings == []


def test_the_shipped_sections_file_is_still_marked_placeholder(data_dir):
    """If someone fills in real times they must clear the flag deliberately,
    and if they clear it without filling them in, this fails."""
    raw = json.loads((data_dir / "sections.json").read_text())
    assert raw.get("placeholder") is True, (
        "sections.json no longer claims to be placeholder data - if the real "
        "meeting times went in, delete this test; if not, restore the flag")


def test_class_standing_is_skipped_with_a_warning_when_unreachable(catalog, offered):
    """CPSC 3165 needs junior standing (60 credits). The audit only lists
    remaining major requirements, so the threshold often cannot be reached.
    The rule must degrade to a warning, not make the plan infeasible."""
    warnings = []
    courses = [norm("CPSC 3165")]
    term_list = build_terms("Summer 2027", 6, True)
    plan, _ = plan_with_ilp(courses, catalog, offered, term_list, 15, None, 0,
                            warnings)
    assert plan, "a 2-credit course with no prereqs should always be schedulable"
    assert any("3165" in w and "not enforced" in w.lower() for w in warnings)
