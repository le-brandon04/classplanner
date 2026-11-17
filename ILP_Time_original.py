from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from itertools import combinations
from typing import List, Dict, Tuple, Set, Optional
import time

import pulp  # pip install pulp


# ============================================================
# 0. Offering model + time encoding (days/hours as bitmasks)
# ============================================================

@dataclass
class Offering:
    """
    Represents a *specific* offering of a course in a given term.

    For now, we assume exactly one Offering per course, but the design
    supports multiple offerings later (different times/sections).

    Attributes:
        course_id:   Catalog ID, e.g. "CPSC 1301K".
        offering_id: Section label or CRN, e.g. "A" or "CRN12345".
        day_mask:    7-bit mask for days of week.
                     Bit 0 = Monday, 1 = Tuesday, ..., 6 = Sunday.
        hour_mask:   24-bit mask for hours of the day (0–23).
                     Bit h = class occupies hour h–(h+1).
    """
    course_id: str
    offering_id: str
    day_mask: int
    hour_mask: int


# Map single-character day codes to bit indices.
DAY_TO_BIT: Dict[str, int] = {
    "M": 0,  # Monday
    "T": 1,  # Tuesday
    "W": 2,  # Wednesday
    "R": 3,  # Thursday  (use 'R' so T/R are distinct)
    "F": 4,  # Friday
    "S": 5,  # Saturday
    "U": 6,  # Sunday
}


def encode_days(day_string: str) -> int:
    """
    Convert a string like "MWF" into a 7-bit day_mask.

    Example:
        "MWF" sets bits for Monday, Wednesday, Friday.
    """
    mask = 0
    for ch in day_string:
        bit = DAY_TO_BIT[ch]
        mask |= (1 << bit)
    return mask


def encode_hours(start_hour: int, end_hour: int) -> int:
    """
    Convert an integer hour range [start_hour, end_hour) into a 24-bit hour_mask.

    We treat each hour as a block from h:00 to (h+1):00.

    Example:
        start_hour=9, end_hour=11 -> bits 9 and 10 set (9–10am, 10–11am).
    """
    mask = 0
    for h in range(start_hour, end_hour):
        mask |= (1 << h)
    return mask


def offerings_conflict(a: Offering, b: Offering) -> bool:
    """
    Two offerings conflict if:
      - they share at least one day, AND
      - they share at least one hour.

    We detect this by bitwise-AND on their day and hour masks.
    """
    same_day = (a.day_mask & b.day_mask) != 0
    same_hour = (a.hour_mask & b.hour_mask) != 0
    return same_day and same_hour


# ============================================================
# 1. Curriculum & prerequisites (CS + Math double major)
# ============================================================
# def build_cs_curriculum():
#     """
#     Very small test curriculum to verify hard constraints:
#       - prerequisites
#       - credit cap
#       - time conflicts (via your Offering/time model)
#
#     Courses:
#       MATH 1111  -> CPSC 1301K -> CPSC 1302
#       ELECTIVE_A (no prereqs)
#       ELECTIVE_B (no prereqs)
#     """
#     prereqs = [
#         ("MATH 1111", "CPSC 1301K"),
#         ("CPSC 1301K", "CPSC 1302"),
#     ]
#
#     all_courses = [
#         "MATH 1111",
#         "CPSC 1301K",
#         "CPSC 1302",
#         "ELECTIVE_A",
#         "ELECTIVE_B",
#     ]
#
#     # Make credits non-trivial so the 7-credit cap actually constrains things
#     credits_by_course = {
#         "MATH 1111": 3,
#         "CPSC 1301K": 4,
#         "CPSC 1302": 3,
#         "ELECTIVE_A": 3,
#         "ELECTIVE_B": 3,
#     }
#
#     return prereqs, all_courses, credits_by_course

def build_cs_curriculum() -> Tuple[
    List[Tuple[str, str]], List[str], Dict[str, int]
]:
    """
    Build the combined curriculum:
      - CS – Software Systems 2021–2022
      - Math major

    Returns:
        prereqs: list of edges (prereq, course)
        all_courses: sorted list of unique course IDs
        credits_by_course: course -> credit hours
    """

    # ---------- CS side ----------

    cs_prereqs = [
        ("MATH 1113", "MATH 2125"),
        ("MATH 2125", "MATH 5125"),
        ("CPSC 1301K", "CPSC 1302"),
        ("CPSC 1301K", "CPSC 2105"),
        ("CPSC 1301K", "CYBR 2159"),
        ("CPSC 1302", "CPSC 2108"),
        ("MATH 2125", "CPSC 2108"),
        ("CPSC 2108", "CPSC 3131"),
        ("CPSC 2105", "CPSC 3121"),
        ("CPSC 2108", "CPSC 3125"),
        ("CPSC 2105", "CPSC 3125"),
        ("CYBR 2159", "CYBR 2160"),
        ("CPSC 2108", "CPSC 3175"),
        ("CPSC 2108", "CPSC 4135"),
        ("CPSC 2105", "CPSC 4155"),
        ("CPSC 3121", "CPSC 4155"),
        ("CYBR 2159", "CPSC 4157"),
        ("CPSC 2105", "CPSC 4157"),
        ("CPSC 2108", "CPSC/CYBR 3XXX-1"),
        ("CPSC 2108", "CPSC/CYBR 3XXX-2"),
        ("CPSC 2108", "CPSC 4115"),
        ("MATH 2125", "CPSC 4115"),
        ("CPSC 4115", "CPSC 4148"),
        ("MATH 5125", "CPSC 4148"),
        ("CPSC 3131", "CPSC 4175"),
        ("CPSC 3175", "CPSC 4175"),
        ("CPSC 4175", "CPSC 4176"),
        ("CPSC 2108", "CPSC 3165"),
        ("CPSC 4115", "CPSC 4000"),
        ("CPSC 4175", "CPSC 4000"),
    ]

    cs_courses = [
        "MATH 1113",
        "MATH 2125",
        "MATH 5125",
        "CPSC 1301K",
        "CPSC 1302",
        "CPSC 2105",
        "CYBR 2159",
        "CPSC 2108",
        "CPSC 3131",
        "CPSC 3121",
        "CPSC 3125",
        "CYBR 2160",
        "CPSC 3175",
        "CPSC 4115",
        "CPSC 4157",
        "CPSC 3165",
        "CPSC 4175",
        "CPSC 4135",
        "CPSC 4000",
        "CPSC 4155",
        "CPSC/CYBR 3XXX-1",
        "CPSC/CYBR 3XXX-2",
        "CPSC 4176",
        "CPSC 4148",
    ]

    cs_credits = {
        "MATH 1113": 3,
        "MATH 2125": 3,
        "MATH 5125": 3,
        "CPSC 1301K": 4,
        "CPSC 1302": 3,
        "CPSC 2105": 3,
        "CYBR 2159": 3,
        "CPSC 2108": 3,
        "CPSC 3131": 3,
        "CPSC 3121": 3,
        "CPSC 3125": 3,
        "CYBR 2160": 3,
        "CPSC 3175": 3,
        "CPSC 4115": 3,
        "CPSC 4157": 3,
        "CPSC 3165": 3,
        "CPSC 4175": 3,
        "CPSC 4135": 3,
        "CPSC 4000": 1,
        "CPSC 4155": 3,
        "CPSC/CYBR 3XXX-1": 3,
        "CPSC/CYBR 3XXX-2": 3,
        "CPSC 4176": 3,
        "CPSC 4148": 3,
    }

    math_prereqs = [
        ("MATH 1113", "MATH 1131"),
        ("MATH 1131", "MATH 1132"),
        ("MATH 1132", "MATH 2135"),
        ("MATH 1131", "MATH 2115"),
        ("MATH 2115", "MATH 3115"),
        ("MATH 2135", "MATH 3137"),
        ("MATH 3137", "MATH 4138"),
        ("MATH 2115", "MATH 3107"),
        ("MATH 3107", "MATH 3108"),
        ("MATH 1132", "MATH 3175"),
        ("MATH 3175", "STAT 3111"),
        ("STAT 3111", "STAT 4112"),
        ("MATH 1132", "MATH 4165"),
        ("MATH 2115", "MATH 4141"),
        ("MATH 2135", "MATH 4111"),
        ("MATH 3137", "MATH 4121"),

        ("MATH 2115", "MATH 4210"),
        ("MATH 2115", "MATH 4220"),
        ("MATH 2115", "MATH 4310"),
        ("MATH 3108", "MATH 4999"),
        ("MATH 3137", "MATH 4999"),
    ]

    math_courses = [
        "MATH 1131",
        "MATH 1132",
        "MATH 2135",
        "MATH 2115",
        "MATH 3115",
        "MATH 3137",
        "MATH 4138",
        "MATH 3107",
        "MATH 3108",
        "MATH 3175",
        "MATH 4141",
        "MATH 4165",
        "MATH 4111",
        "MATH 4121",
        "STAT 3111",
        "STAT 4112",
        "MATH 4210",
        "MATH 4220",
        "MATH 4310",
        "MATH 4999",
    ]

    math_credits = {
        "MATH 1131": 4,
        "MATH 1132": 4,
        "MATH 2135": 4,
        "MATH 2115": 3,
        "MATH 3115": 3,
        "MATH 3137": 3,
        "MATH 4138": 3,
        "MATH 3107": 3,
        "MATH 3108": 3,
        "MATH 3175": 3,
        "MATH 4141": 3,
        "MATH 4165": 3,
        "MATH 4111": 3,
        "MATH 4121": 3,
        "STAT 3111": 3,
        "STAT 4112": 3,
        "MATH 4210": 3,
        "MATH 4220": 3,
        "MATH 4310": 3,
        "MATH 4999": 3,
    }

    prereqs = cs_prereqs + math_prereqs

    course_set = set(cs_courses)
    for c in math_courses:
        course_set.add(c)
    all_courses = sorted(course_set)

    credits_by_course = cs_credits.copy()
    credits_by_course.update(math_credits)

    for c in all_courses:
        credits_by_course.setdefault(c, 3)

    return prereqs, all_courses, credits_by_course


def build_offerings(all_courses: List[str]) -> Dict[str, Offering]:
    offerings: Dict[str, Offering] = {}

    slot_patterns = [
        ("MWF", 9, 10),
        ("MWF", 10, 11),
        ("TR", 11, 12),
        ("TR", 14, 15),
        ("F", 13, 15),
    ]
    num_slots = len(slot_patterns)

    for i, c in enumerate(all_courses):
        days_str, start_h, end_h = slot_patterns[i % num_slots]
        day_mask = encode_days(days_str)
        hour_mask = encode_hours(start_h, end_h)

        offerings[c] = Offering(
            course_id=c,
            offering_id="A",
            day_mask=day_mask,
            hour_mask=hour_mask,
        )

    return offerings


def build_time_conflict_pairs_from_offerings(
    offerings: Dict[str, Offering]
) -> List[Tuple[str, str]]:
    conflict_pairs: List[Tuple[str, str]] = []
    courses = list(offerings.keys())

    for c1, c2 in combinations(courses, 2):
        o1 = offerings[c1]
        o2 = offerings[c2]
        if offerings_conflict(o1, o2):
            conflict_pairs.append((c1, c2))

    return conflict_pairs

def plan_with_ilp(
    prereq_edges: List[Tuple[str, str]],
    all_courses: List[str],
    credits_by_course: Dict[str, int],
    max_credits_per_sem: int = 15,
    max_semesters: int = 12,
    conflict_pairs: Optional[List[Tuple[str, str]]] = None,
) -> Tuple[Dict[int, List[str]], int, float]:
    semesters = list(range(1, max_semesters + 1))

    model = pulp.LpProblem("CS_Schedule_ILP", pulp.LpMinimize)

    x = {
        (c, s): pulp.LpVariable(
            f"x_{c.replace(' ', '_').replace('/', '_')}_{s}",
            lowBound=0,
            upBound=1,
            cat=pulp.LpBinary,
        )
        for c in all_courses
        for s in semesters
    }

    T = pulp.LpVariable("T", lowBound=1, upBound=max_semesters, cat=pulp.LpInteger)

    for c in all_courses:
        model += (
            pulp.lpSum(x[(c, s)] for s in semesters) == 1,
            f"Take_{c}_once",
        )

    for s in semesters:
        model += (
            pulp.lpSum(credits_by_course[c] * x[(c, s)] for c in all_courses)
            <= max_credits_per_sem,
            f"CreditCap_sem{s}",
        )

    for (p, c) in prereq_edges:
        for s in semesters:
            if s == 1:
                model += (
                    x[(c, s)] <= 0,
                    f"Prereq_{p}_before_{c}_sem{s}",
                )
            else:
                model += (
                    x[(c, s)]
                    <= pulp.lpSum(x[(p, t)] for t in semesters if t < s),
                    f"Prereq_{p}_before_{c}_sem{s}",
                )

    if conflict_pairs:
        for (c1, c2) in conflict_pairs:
            if c1 not in all_courses or c2 not in all_courses:
                continue
            for s in semesters:
                model += (
                    x[(c1, s)] + x[(c2, s)] <= 1,
                    f"TimeConflict_{c1}_{c2}_sem{s}",
                )

    for c in all_courses:
        for s in semesters:
            model += (
                s * x[(c, s)] <= T,
                f"T_ge_sem_{s}_for_{c}",
            )

    model += T

    start_solve = time.perf_counter()
    model.solve(pulp.PULP_CBC_CMD(msg=False))
    end_solve = time.perf_counter()
    solve_time = end_solve - start_solve

    status = pulp.LpStatus[model.status]
    if status != "Optimal":
        raise RuntimeError(f"ILP did not find optimal solution (status: {status})")

    schedule_by_sem: Dict[int, List[str]] = {s: [] for s in semesters}
    for c in all_courses:
        for s in semesters:
            if pulp.value(x[(c, s)]) > 0.5:
                schedule_by_sem[s].append(c)

    used_T = int(pulp.value(T))

    trimmed_schedule = {
        s: schedule_by_sem[s]
        for s in semesters
        if s <= used_T and schedule_by_sem[s]
    }

    return trimmed_schedule, used_T, solve_time


if __name__ == "__main__":
    start_total = time.perf_counter()

    prereqs, all_courses, credits_by_course = build_cs_curriculum()

    offerings = build_offerings(all_courses)

    conflict_pairs = build_time_conflict_pairs_from_offerings(offerings)

    schedule, T, solve_time = plan_with_ilp(
        prereq_edges=prereqs,
        all_courses=all_courses,
        credits_by_course=credits_by_course,
        max_credits_per_sem=15,
        max_semesters=12,
        conflict_pairs=conflict_pairs,
    )


    for s in sorted(schedule.keys()):
        courses = schedule[s]
        total_credits = sum(credits_by_course[c] for c in courses)
        print(f"\nSemester {s} (credits: {total_credits}):")
        for c in courses:
            print(f"  {c}")

    end_total = time.perf_counter()
    total_time = end_total - start_total
    print(f"Optimal number of semesters (T): {T}")
    print(f"ILP Total Time: {total_time:.6f} seconds")
