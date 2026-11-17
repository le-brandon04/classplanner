# planner.py vs ILP_Time.py

For Brian. This is your ILP with the data moved out of the source file and two
constraints added. The solver is unchanged in structure — same binary `x[c,s]`,
same `T`, same CBC call.

## Kept as-is

- The ILP formulation: one binary per (course, semester), `T` as the last
  semester used, minimise `T`
- Take-each-course-once constraint
- Credit cap per semester
- Prerequisite constraint (`x[c,s] <= sum(x[p,t] for t < s)`)
- The `Offering` dataclass and the day/hour bitmask conflict model
- `encode_days`, `encode_hours`, `offerings_conflict` — unchanged

## Changed

### 1. Curriculum comes from JSON, not `build_cs_curriculum()`

`data/prereqs.json` holds courses, credits, prereq edges, coreq edges and
credit hours. `data/offerings.json` holds the Fa/Sp/Su codes. This is what the
project spec's non-functional requirement asks for ("inputs must be separated
from the software and be parsed by the software").

It also means the Math major drops out — this project is CS Software Systems
only — and the catalog is 2024-25 rather than 2021-22.

### 2. Only remaining courses are planned

The planner reads `remaining_courses.json` (the audit parser's output) and
plans only those. Anything not in that list is treated as already completed, so
its prerequisites are automatically satisfied. Your version planned the whole
degree from scratch every time.

### 3. Semester availability is now a constraint

This is the main functional addition. Each semester in the model now has a
season, and a course can't be placed in a term it isn't offered:

```python
for c in courses:
    for s in S:
        season = terms[s - 1][0]          # "fall" | "spring" | "summer"
        if not offered[c][season]:
            model += x[c, s] == 0
```

`terms` is built from a start term ("Fall 2026") so semester 1 is a real
labelled term, not just the integer 1. CPSC 4115 is `F- -- --` in the
2024-25 diagram, so it can now only land in a fall term.

### 4. Corequisites

The diagram's dashed arrows are concurrent-prerequisites — same term is
allowed, which the strict `t < s` prereq constraint forbids. Added as a
separate edge type:

```python
model += x[c, s] <= pulp.lpSum(x[p, t] for t in S if t <= s)
```

### 5. Invented time slots removed from the default path

`build_offerings()` assigned meeting times round-robin from five hardcoded
patterns. With 44 courses that produced 5 distinct time slots of ~9 courses
each, and since no two courses in a slot can share a semester, it acted as a
hard cap of 5 courses per term. Measured on your file: 172 conflict pairs out
of 946 possible, and 11 semesters with them versus 10 without.

The bitmask conflict code is still there and still used — it just needs real
data now. Drop a `data/sections.json` in and it switches on:

```json
{ "sections": { "CPSC 4115": { "days": "MWF", "start": 9, "end": 10 } } }
```

With no such file, no time-conflict constraints are generated.

### 6. Tiebreaker on the objective

Your objective was `model += T`. Among plans of equal length the solver could
place a course in any term, so courses drifted later for no reason. Now:

```python
model += 1000 * T + pulp.lpSum(s * x[c, s] for c in courses for s in S)
```

`T` still dominates, so plan length is still minimised first; the second term
breaks ties toward taking courses earlier.

### 7. Infeasible plans report instead of raising

`RuntimeError` is caught in `main()` and printed as a plain message naming the
likely causes (credit cap too low, too few terms, a course never offered in an
allowed term) rather than dumping a traceback.

## Known gaps

- Six courses in `offerings.json` have `"raw": null` — offering data wasn't
  legible on our copy of the diagram. The planner assumes they run every term
  and prints a warning. This makes summer plans optimistic.
- 12 courses in `prereqs.json` are marked `"verified": false` and need checking
  against the 2024-25 diagram.
- `"*"` (sometimes offered) is treated as available. MATH 5125U is `F* F* F*`.
- The `standing` field ("Must be Jr/Sr" on CPSC 3165) is stored but not
  enforced.

## Running it

```
pip install pulp openpyxl
python planner.py --remaining data/sample_freshman.json --start "Fall 2026"
python planner.py --remaining data/sample_senior.json  --start "Spring 2027"
python planner.py --remaining data/sample_freshman.json --start "Fall 2026" --summer
```
