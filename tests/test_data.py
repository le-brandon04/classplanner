"""The data files are the product. These tests guard them.

Every one of these failing means the planner would still run and would still
produce a plausible-looking plan - just a wrong one. That is the failure mode
this project has to defend against.
"""
import json

import pytest

from planner import SEASONS, decode_term, norm


@pytest.fixture(scope="module")
def raw_prereqs(data_dir):
    return json.loads((data_dir / "prereqs.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def raw_offerings(data_dir):
    return json.loads((data_dir / "offerings.json").read_text(encoding="utf-8"))


def test_every_course_has_a_unique_id(raw_prereqs):
    ids = [norm(c["id"]) for c in raw_prereqs["courses"]]
    assert len(ids) == len(set(ids))


def test_every_prereq_edge_points_at_a_known_course(catalog):
    for cid, record in catalog.items():
        for edge in record["prereqs"] + record["coreqs"]:
            assert edge in catalog, (
                f"{record['display']} references {edge}, which is not in "
                "prereqs.json")


def test_prerequisite_graph_is_acyclic(catalog):
    """The specification calls for a DAG. A cycle makes every plan infeasible."""
    colour = {}

    def visit(node, stack):
        if colour.get(node) == "done":
            return
        assert colour.get(node) != "open", f"prerequisite cycle: {' -> '.join(stack + [node])}"
        colour[node] = "open"
        for nxt in catalog[node]["prereqs"] + catalog[node]["coreqs"]:
            visit(nxt, stack + [node])
        colour[node] = "done"

    for cid in catalog:
        visit(cid, [])


def test_no_course_requires_itself(catalog):
    for cid, record in catalog.items():
        assert cid not in record["prereqs"] + record["coreqs"]


def test_every_course_has_an_offering_record(catalog, raw_offerings):
    known = {norm(k) for k in raw_offerings["courses"]}
    missing = sorted(set(catalog) - known)
    assert not missing, f"no offering data for: {missing}"


def test_every_offering_code_is_well_formed(raw_offerings):
    for cid, entry in raw_offerings["courses"].items():
        raw = entry.get("raw")
        assert raw, f"{cid} has no offering code"
        parts = raw.split()
        assert len(parts) == 3, f"{cid}: expected three groups (Fa Sp Su), got {raw!r}"
        for part in parts:
            assert 1 <= len(part) <= 2, f"{cid}: bad group {part!r} in {raw!r}"


def test_every_course_is_offered_at_least_once_a_year(raw_offerings):
    for cid, entry in raw_offerings["courses"].items():
        parts = entry["raw"].split()
        assert any(decode_term(p, ignore_online=False) for p in parts), (
            f"{cid} is never offered in any term")


def test_all_course_records_are_catalog_verified(raw_prereqs):
    """Cycle 2 closed the last two. If someone adds a course from a diagram
    instead of a catalog page, this fails and says so."""
    unverified = [c["id"] for c in raw_prereqs["courses"] if not c.get("verified")]
    assert not unverified, (
        f"not verified against a catalog page: {unverified}. Either check them "
        "or say so in the report - do not let them pass as checked data.")


def test_every_record_names_its_source(raw_prereqs):
    for c in raw_prereqs["courses"]:
        assert c.get("source"), f"{c['id']} does not say where its data came from"


def test_cybr_2160_is_a_corequisite_not_a_prerequisite(catalog):
    """The catalog says 'CYBR 2159 (may be taken concurrently)'. Recording that
    as a strict prerequisite would push graduation out by a term for no reason.
    """
    record = catalog[norm("CYBR 2160")]
    assert norm("CYBR 2159") in record["coreqs"]
    assert norm("CYBR 2159") not in record["prereqs"]


def test_cpsc_4000_is_pinned_to_the_final_term(catalog):
    record = catalog[norm("CPSC 4000")]
    assert record["final_term"] is True
    assert record["credits"] == 0


def test_cpsc_4000_matches_the_catalog_entry(catalog, offered):
    """Confirmed against catalog.columbusstate.edu/course-descriptions/cpsc/

    The catalog lists it as "Baccalaureate Survey (0-0-0)" and says it "must
    be taken in the last semester prior to graduation". It was carried as an
    assumption until Cycle 2; this pins it so it cannot drift back.

    Availability every term is not a guess either: the course is required in
    whatever term the student graduates, and CSU graduates students in fall,
    spring and summer. The final_term rule above is what actually places it.
    """
    record = catalog[norm("CPSC 4000")]
    assert record["name"] == "Baccalaureate Survey"
    terms = offered[norm("CPSC 4000")]
    for term in ("fall", "spring", "summer"):
        assert terms[term], (
            f"CPSC 4000 must be available in {term} - a student graduating "
            "that term cannot complete their degree without it")


def test_cpsc_3165_matches_the_catalog_entry(catalog):
    """Also confirmed against the catalog: "Professionalism in Computing
    (2-0-2)", no prerequisite. Earlier drafts of our own slides called it
    "Technical Communication" and gave it a prerequisite; the data file was
    right and the slides were wrong.
    """
    record = catalog[norm("CPSC 3165")]
    assert record["name"] == "Professionalism in Computing"
    assert record["credits"] == 2
    assert record["prereqs"] == []


def test_the_three_year_chain_is_still_in_the_data(catalog, offered):
    """The project's headline finding. If the offering data ever changes so
    that this is no longer true, the report and the deck are both wrong."""
    assert norm("CPSC 3175") in catalog[norm("CPSC 4175")]["prereqs"]
    assert norm("CPSC 4175") in catalog[norm("CPSC 4176")]["prereqs"]
    assert offered[norm("CPSC 4175")] == {"fall": True, "spring": False, "summer": False}
    assert offered[norm("CPSC 4176")] == {"fall": False, "spring": True, "summer": False}


def test_online_only_courses_are_excluded_by_default(offered, offered_with_online):
    """CPSC 3165 is '-O -O F-': online in fall and spring, face-to-face only in
    summer. The team's decision is that an online-only section does not count."""
    cid = norm("CPSC 3165")
    assert offered[cid] == {"fall": False, "spring": False, "summer": True}
    assert offered_with_online[cid] == {"fall": True, "spring": True, "summer": True}


def test_sections_file_uses_codes_the_planner_understands(data_dir):
    from planner import parse_block_code
    path = data_dir / "sections.json"
    if not path.is_file():
        pytest.skip("sections.json is optional")
    raw = json.loads(path.read_text(encoding="utf-8"))
    for cid, codes in raw.get("sections", {}).items():
        for code in ([codes] if isinstance(codes, str) else codes):
            parse_block_code(code)      # raises ValueError on a bad code
