# Smart Class Planning Tool

Reads a student's DegreeWorks audit and produces a semester-by-semester class
plan as an Excel file — and checks a plan somebody has already written for
prerequisite problems.

## Description

Planning the rest of a degree is a constraint problem that is usually solved by
hand. Prerequisites chain, and some courses are offered in only one term a
year: CPSC 4175 runs in fall only, and CPSC 4176 requires it and runs in spring
only, so those two courses alone span three academic years. Nothing in the
course catalog says so — each course has its own page, and the interaction
between them is not written down anywhere.

This tool takes three inputs and solves for the shortest valid schedule:

1. **The courses a student still needs**, read directly out of a DegreeWorks
   audit PDF.
2. **A prerequisite graph** — a directed acyclic graph with three edge types:
   prerequisite (strictly earlier term), corequisite (same term or earlier) and
   recommended (ignored by the solver).
3. **A course offering schedule** — which terms each course runs in, and
   whether it is face-to-face or online.

It produces an Excel workbook with one block per term, a live `=SUM()` credit
subtotal on each, and a Warnings sheet carrying every assumption it had to
make. The same workbook can be fed back in: `check` reports every prerequisite
and term-availability problem in a plan, naming the course, the term and the
spreadsheet row.

Scope is the 20 required courses of the Computer Science — Software Systems
track, 58 credit hours, catalog year 2024–2025. Electives are deliberately out
of scope; where an audit offers a choice of courses, the requirement is flagged
for an advisor rather than guessed at.

Two design decisions are worth knowing up front:

- **The audit is read with OCR, not PDF text extraction.** DegreeWorks exports
  the audit with its text drawn as vector outlines, so the PDF contains zero
  characters — `pdfplumber` and `pypdf` both return nothing. Each page is
  rendered at 300 DPI and passed through Tesseract instead. See
  `SPIKE_FINDINGS.md`.
- **No curriculum data lives in the code.** Every course code, prerequisite and
  term restriction is in the JSON files under `data/`, which ship *beside* the
  executable rather than inside it. An advisor can edit them in Notepad when
  the catalog changes, and nothing is recompiled.

## Getting Started

### Dependencies

* **Python 3.10 or newer**
* **Windows 10/11**, macOS or Linux — the packaged executable is Windows only,
  but the source runs anywhere
* **Tesseract OCR**, for the `parse` command only. `plan` and `check` do not
  need it.
* Python packages, all pinned in `requirements.txt`:
  `pulp>=3.0,<4.0` · `openpyxl` · `pandas>=2.0` · `pymupdf` · `pytesseract` ·
  `pillow` · `pytest`

> **PuLP must stay below 4.0.** Version 4 is a Rust-core rewrite with an
> incompatible `LpVariable`, and the planner fails with
> `TypeError: ... unexpected keyword argument 'cat'`. Never run
> `pip install -U pulp`.

### Installing

Clone the repository, then create a virtual environment and install the
dependencies into it:

```
python -m venv venv
```
```
venv\Scripts\activate
```
```
python -m pip install -r requirements.txt
```

On macOS or Linux the second line is `source venv/bin/activate`.

Use `python -m pip`, not bare `pip`. On Windows the two often point at
different interpreters, which installs the packages somewhere the program
cannot see them.

**If PowerShell says "running scripts is disabled on this system"**, allow it
for that window only and run the activate line again:

```
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

**Install Tesseract** (only needed for `parse`). It is a separate program, not
a pip package:

* Windows: download the installer from
  https://github.com/UB-Mannheim/tesseract/wiki and accept the default
  location, then **close and reopen your terminal**
* macOS: `brew install tesseract`
* Linux: `sudo apt install tesseract-ocr`

The program looks for Tesseract in four places — the `TESSERACT_CMD`
environment variable, `config.json`, your `PATH`, then the usual Windows
install folders — so a default install needs no configuration. If it still
cannot be found, copy the config template and set the path explicitly:

```
copy config.example.json config.json
```

`config.json` is gitignored, so local paths stay out of the repository.

### Executing program

Verify the install first. This should report **67 passed**:

```
python -m pytest
```

**Read an audit into a course list.** `data/sample_audit.pdf` is a synthetic
fixture — "SAMPLE STUDENT", ID all zeros, labelled on every page — so this
works out of the box with no student data involved:

```
python parse_audit_ocr.py data/sample_audit.pdf -o remaining_courses.json
```

**Build a plan** from that output, with no hand-editing in between:

```
python planner.py --remaining remaining_courses.json --start "Fall 2026" --summer -o plan.xlsx
```

Useful options: `--summer` allows summer terms, `--max-credits` sets the per-term
cap (default 15), `--prior-credits` supplies earned credits so class-standing
rules apply, and `--include-online` counts online-only sections as available
(the default is face-to-face only).

**Check an existing plan** — this works on any plan in the same layout, not
just ones this tool wrote:

```
python validator.py plan.xlsx
```

It prints `PASS` and exits 0 when the plan is clean, or lists every problem and
exits non-zero:

```
Errors (2)
  - CPSC 4175 is scheduled in Spring 2029 but is not offered in spring. It runs in: fall. (Online-only sections are not counted.) [row 32]
  - CPSC 4176 (Spring 2029) requires CPSC 4175, but that is scheduled the same term as it (Spring 2029, row 32). A prerequisite must finish in an earlier term. [row 36]

FAIL — 2 prerequisite issues found.
```

Add `--strict` to treat a prerequisite that is missing from the plan as an
error rather than assuming it is already complete, and `-o issues.xlsx` to
write the report to a spreadsheet.

**Using the packaged executable** is the same three commands under one name:

```
classplanner parse data\sample_audit.pdf -o remaining_courses.json
```
```
classplanner plan --remaining remaining_courses.json --start "Fall 2026"
```
```
classplanner check class_plan.xlsx
```

`data\` must sit beside `classplanner.exe`. That is deliberate — it is how the
curriculum stays editable without a rebuild.

### Building the executable

From an activated environment on a **Windows** machine:

```
python -m pip install pyinstaller
```
```
pyinstaller classplanner.spec
```

This produces `dist\classplanner.exe`. Copy the `data\` folder next to it:

```
classplanner.exe
data\
  prereqs.json
  offerings.json
  sections.json
```

PyInstaller does not cross-compile, so a Windows executable has to be built on
Windows. Tesseract is a system program and is not bundled; `parse` still needs
it installed.

## Help

**`No module named ...` for a package you just installed.** Bare `pip` and
`python` are pointing at different interpreters. Use `python -m pip install`,
or call the environment's Python directly:
`.\venv\Scripts\python.exe -m pip install -r requirements.txt`

**`Tesseract binary not found`.** Tesseract is a separate program, so
`pip install` will never provide it. Install it (see above) and open a new
terminal — a shell that was already running will not see the new install.

**`TypeError: ... unexpected keyword argument 'cat'`.** PuLP 4 is installed.
Check and fix:

```
python -c "import pulp; print(pulp.__version__)"
```
```
python -m pip install "pulp<4"
```

Keep the quotes, or PowerShell interprets the `<` as a redirect.

**`PermissionError` writing the output file.** The workbook is open in Excel.
Close it and run again.

**The parser finds no courses.** It will tell you which of three situations you
are in:

| Message | What it means |
|---|---|
| "This PDF has a real text layer" | Exported from Chrome. Redo it with DegreeWorks' print view and Microsoft Print to PDF. |
| "found no 'Still needed' anywhere" | The requirement blocks were collapsed when you exported. Expand them all and export again. |
| "No remaining courses to plan… completed set of major requirements" | Not an error. The export is fine and there is genuinely nothing left to schedule. |

That third case is a real result: a student who has finished their major still
has "Still needed" lines for the graduation application, the exit survey and the
constitution exam, and none of those is a course.

**Exporting an audit correctly** matters more than anything else here. Expand
every requirement block first — a collapsed block is not written into the PDF
at all and nothing can recover it afterwards — then use DegreeWorks' own print
view and save with Microsoft Print to PDF.

> **Privacy.** A real audit carries the student's name and CSU ID. The parser
> only ever prints course codes, so the terminal is safe, but the PDF is not.
> `*.pdf`, `dump.txt` and `remaining_courses.json` are gitignored; delete them
> when you are done anyway.

Every command supports `--help`:

```
python planner.py --help
```

## Authors

CPSC 4175 — Software Engineering, Columbus State University, Team 1

* Brian Ganzler
* Carter Sloan
* Brandon Le
* Dajour Johnson
* Kameryn Redd

## Version History

* **0.2 — Cycle 2**
    * `validator.py`, which completes the second functional requirement of the
      specification: given a prerequisite graph and an existing plan, report
      the prerequisite issues in it
    * 67 automated tests across the solver, the validator, the parser and the
      course data
    * All 20 course records verified against the official CPSC, MATH and CYBR
      catalog pages — 11 were wrong, carried over from a 2021–22 list
    * CPSC 4000 confirmed against the catalog ("Baccalaureate Survey", 0-0-0,
      "must be taken in the last semester prior to graduation"), replacing the
      last remaining assumption in the course data
    * Placeholder section times can no longer reach the solver, where an
      invented clash would have silently distorted a plan
    * PyInstaller packaging, with the curriculum data kept outside the
      executable
    * A synthetic audit fixture, so the parser is testable without any real
      student data
    * Fixes: the multi-option elective flag had never fired since Cycle 1;
      three packaging bugs visible only once the `.exe` was built; the parser
      reported a completed degree as a bad export
* **0.1 — Cycle 1**
    * Audit parsing via OCR, the ILP planner, and Excel export

### Known limitations

* **Time-of-day conflicts are not checked.** `data/sections.json` ships with
  invented meeting times, so it is marked `"placeholder": true` and the
  planner refuses to use it, saying so in the terminal and on the Warnings
  sheet of every plan it writes. A plan is therefore valid by term, but two
  courses in the same term may meet at the same hour. Fill in real times from
  the schedule of classes and set `"placeholder": false` to turn checking on.
  Meeting times change every semester, so this needs refreshing each term.
* MISM 4168 belongs to a second major and is not in the catalog file, so it
  plans with no title and raises a warning

## License

Coursework for CPSC 4175 at Columbus State University. Not licensed for
redistribution.

## Acknowledgments

* Course data verified against the official Columbus State University
  [course catalog](https://catalog.columbusstate.edu/)
* [PuLP](https://github.com/coin-or/pulp) and the
  [CBC](https://github.com/coin-or/Cbc) solver
* [PyMuPDF](https://pymupdf.readthedocs.io/) and
  [Tesseract OCR](https://github.com/tesseract-ocr/tesseract)
* [openpyxl](https://openpyxl.readthedocs.io/)
* README structure from
  [DomPizzie's template](https://gist.github.com/DomPizzie/7a5ff55ffa9081f2de27c315f5018afc)
