# Running the Smart Class Planning Tool — setup and demo

CPSC 4175, Team 1. Everything runs from inside the `project` folder.

Every command below is one line. Copy **one at a time** — pasting several at
once gives you a `>>` continuation prompt in PowerShell, which looks like a
hang. And ignore the word above each grey box (`powershell`, `text`); that is
the code-block label, not something you type.

---

## 1. Setup

You need **Python 3.10 or newer** and, for the audit parser only, **Tesseract**.

### 1.1 Create and activate a virtual environment

Use one. Your global Python may have PuLP 4 in it, which this project cannot
run on (§5).

```
python -m venv venv
```
```
.\venv\Scripts\Activate.ps1
```

Your prompt should now start with `(venv)`.

**If you get "running scripts is disabled on this system"** — that is
PowerShell's execution policy. Allow it for this window only:

```
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

then run the activate line again.

**In VS Code** there is an easier route. After creating the venv, press
`Ctrl+Shift+P` → **Python: Select Interpreter** → choose
`.\venv\Scripts\python.exe`. Close the terminal with the bin icon, open a new
one, and it activates itself.

**Or skip activation entirely** and call the venv's Python directly. This
always works whatever the shell is doing:

```
.\venv\Scripts\python.exe -m pip install -r requirements.txt
```

### 1.2 Install the Python packages

```
python -m pip install -r requirements.txt
```

Use `python -m pip`, not bare `pip`. If the two point at different
interpreters — which is common on Windows — bare `pip` installs into the wrong
place and you get `No module named ...` from a package you just installed.

### 1.3 Install Tesseract (only for the audit parser)

Tesseract is a program, not a pip package, so `pip install` will never get it.
`plan` and `check` do not need it; only `parse` does.

1. Download `tesseract-ocr-w64-setup-....exe` from
   https://github.com/UB-Mannheim/tesseract/wiki
2. Install it and **accept the default location**
   (`C:\Program Files\Tesseract-OCR`)
3. **Close and reopen the terminal.** A shell that was already running will
   not see the new install.

The parser looks in four places — the `TESSERACT_CMD` environment variable,
`config.json`, your `PATH`, then the usual Windows install folders — so a
default install is found with no configuration. If it still says it cannot
find it, copy `config.example.json` to `config.json` and set `tesseract_cmd`
to wherever it actually landed.

### 1.4 Confirm everything works

```
python -m pytest
```

**62 passed.** If that is green, every command below works.

---

## 2. The demo, in order

Roughly eight minutes at a comfortable pace.

### Beat 1 — the inputs

```
dir data
```

Open `data\offerings.json` and scroll to CPSC 4175. Point at `"F- -- --"`:
face-to-face in fall, nothing in spring, nothing in summer. The `_codes` block
at the top of the file explains the notation, so the file documents itself.

> Nothing about CSU's curriculum is in the code. It is all in this folder.

### Beat 2 — parse a real audit

```
python parse_audit_ocr.py data/sample_audit.pdf -o remaining_courses.json
```

About ten seconds. Six courses come out, with the elective flagged
`<-- multi-option, verify`.

> DegreeWorks exports the audit with the text drawn as vector outlines. There
> is no text layer at all — pdfplumber and pypdf both return zero characters —
> so we render each page at 300 DPI and run OCR over it. That was the finding
> from our spike and it shaped the whole story.

`data/sample_audit.pdf` is **synthetic**: "SAMPLE STUDENT", ID all zeros, a
banner on every page. A real audit carries a name and a CSU ID, so it cannot
live in the repository. Say that out loud — then say the parser was validated
against a real audit, and the plan it produced matched the advisor's own
handwritten notes for that student (Beat 5).

### Beat 3 — plan straight from that parse

```
python planner.py --remaining remaining_courses.json --start "Fall 2026" --summer -o plan_from_audit.xlsx
```

No hand-editing between stages. CPSC 4175 lands in Fall 2027, CPSC 4176 in
Spring 2028.

**Expect a question about the gaps.** The plan skips Spring and Summer 2027
and that is correct, not padding: CPSC 3175 is in Fall 2026, CPSC 4175 needs
it finished *and* only runs in fall, so Fall 2027 is the earliest it can go.
CPSC 4176 then needs 4175 finished and only runs in spring. The empty terms
are the constraint, visible.

### Beat 4 — the whole degree

```
python planner.py --remaining data/sample_freshman.json --start "Fall 2026" --summer --prior-credits 45 -o freshman_plan.xlsx
```

Walk the terms, then stop on:

```
Fall 2028    CPSC 4175   Software Engineering
Spring 2029  CPSC 4176   Senior Software Engineering
```

> CPSC 4175 is fall only. CPSC 4176 requires it and is spring only. So that
> sequence spans three academic years. You cannot compress it by taking more
> credits and you cannot compress it with summer. Nothing in the catalog tells
> you this — you would have to look up each course, notice the term
> restrictions and trace the chain yourself.

Pause there. It is the most memorable thing in the demo.

### Beat 5 — the oracle

```
python planner.py --remaining data/sample_senior.json --start "Spring 2027" -o senior_plan.xlsx
```

Four courses, one term: MISM 4168, CPSC 4176, CPSC 4148, CPSC 4000.

> A real DegreeWorks audit had advisor notes from Dr. Hodhod listing Spring
> 2027: MISM 4168, CPSC 4176, CPSC 4148. We gave the planner only the parsed
> course list, the prerequisite graph and the offering data. It produced the
> same four courses in the same term. **It never saw her notes.**

Be precise about what the program was and was not given. Most student demos
show output that looks plausible; this one matches a plan a human advisor
actually wrote.

MISM 4168 prints with no title and raises a warning — it belongs to a second
major and is not in our catalog file. Point at the warning rather than hoping
nobody notices.

### Beat 6 — the validator catching a mistake

```
python validator.py freshman_plan.xlsx
```

Passes. Now break it: open `freshman_plan.xlsx`, change CPSC 4175's term to
`Spring 2029`, save, **close Excel**, and run the same command again:

```
Errors (2)
  - CPSC 4175 is scheduled in Spring 2029 but is not offered in spring.
    It runs in: fall. [row 32]
  - CPSC 4176 (Spring 2029) requires CPSC 4175, but that is scheduled the
    same term as it (Spring 2029, row 32). [row 36]
FAIL — 2 prerequisite issues found.
```

Two different rules caught from one edit, each naming the course, the term and
the spreadsheet row. This is the specification's second functional requirement
and the strongest beat in the demo — it shows the tool reasoning, not printing.

Undo the edit, or regenerate with the Beat 4 command.

### Beat 7 — the deliverable

```
start freshman_plan.xlsx
```

One block per term, a credit subtotal per term, a Warnings sheet carrying
every assumption the planner made. Click a subtotal and show it is a live
`=SUM()`, not a baked-in number — an advisor can edit the sheet and the totals
follow. The grand total reads **58 credits**, which is the required hours for
the track.

### Beat 8 (optional) — the configurability requirement

Edit `data/offerings.json`, change CPSC 4175 from `"F- -- --"` to
`"F- F- --"`, save, and re-run the Beat 4 command. The plan shortens. No
Python file was touched and nothing was rebuilt.

> That is the non-functional requirement about separating the inputs from the
> software, demonstrated rather than asserted.

Put the file back afterwards.

---

## 3. Using a real audit instead of the sample

Only if you want to. The sample is safer and the parser is already verified.

**Export it correctly** — this is where it goes wrong:

1. Open the audit in DegreeWorks
2. **Expand every requirement block.** A collapsed block is not written into
   the PDF at all and nothing can recover it afterwards
3. Use DegreeWorks' own **print view**, not Ctrl+P on the dashboard and not
   Chrome's "Save as PDF"
4. Save with **Microsoft Print to PDF**, into `data\`

Then:

```
python parse_audit_ocr.py data/my_audit.pdf -o remaining_courses.json
```

If it finds nothing, the parser tells you which of three situations you are in:

| Message | Meaning |
|---|---|
| "This PDF has a real text layer" | Chrome export. Redo with Microsoft Print to PDF. |
| "found no 'Still needed' anywhere" | Blocks were collapsed. Expand and re-export. |
| "No remaining courses to plan… completed set of major requirements" | The export is fine. There is genuinely nothing left to schedule. |

That third one is not an error. A student who has finished their major still
has "Still needed" lines — graduation application, exit survey, constitution
exam — and none of them is a course.

**Privacy.** A real audit has a name and a CSU ID on it. The parser only ever
prints course codes, so the terminal is safe, but the PDF is not. Do not open
it on screen, do not run with `--dump` while sharing, and delete `dump.txt`
and the audit afterwards. Both are gitignored, but tidy up anyway.

---

## 4. Building the Windows executable

```
pyinstaller classplanner.spec
```

Produces `dist\classplanner.exe`. Copy `data\` next to it:

```
classplanner.exe
data\
  prereqs.json
  offerings.json
  sections.json
```

The data is deliberately **outside** the executable, because the specification
requires the inputs to be separated from the software.

```
classplanner parse  data\sample_audit.pdf -o remaining_courses.json
classplanner plan   --remaining remaining_courses.json --start "Fall 2026"
classplanner check  class_plan.xlsx
```

Tesseract is still a separate install; it is not bundled.

---

## 5. Things that will bite you

**PuLP must be below 4.0.** Version 4 is a Rust-core rewrite with an
incompatible `LpVariable`, and the planner dies with
`TypeError: ... unexpected keyword argument 'cat'`. `requirements.txt` pins it.
Never run `pip install -U pulp`. Check with:

```
python -c "import pulp; print(pulp.__version__)"
```

Anything starting `3.` is correct. If you see `4.`, fix it with
`python -m pip install "pulp<4"` — keep the quotes, or PowerShell eats the `<`.

**Close Excel before re-running.** An open workbook gives you a
`PermissionError` on the output file.

**The first solve takes about two seconds** while the CBC solver warms up, and
well under a second after that. Say "a couple of seconds," not "instantly."

**Pre-generate the spreadsheets before you present.** If a live run fails,
open the saved one, say "I have the output here," and keep talking. Do not
debug in front of the room.

```
python planner.py --remaining data/sample_freshman.json --start "Fall 2026" --summer --prior-credits 45 -o freshman_plan.xlsx
python planner.py --remaining data/sample_senior.json --start "Spring 2027" -o senior_plan.xlsx
```

**Terminal font at about 18pt**, and have tabs ready in order: terminal in
`project\`, the `data\` folder, both spreadsheets.

---

## 6. Likely questions

**Why an integer program and not a topological sort?**
A sort gives a valid order, not a short one. The solver minimises graduation
term subject to credit caps, term availability, prerequisites, corequisites
and class standing all at once.

**How do you know the output is correct?**
The senior case reproduces an advisor's own plan from notes the program never
saw. Beyond that, 62 automated tests and a full diff of the course data against
the official catalogs.

**Where does the prerequisite data come from?**
The official CPSC, MATH and CYBR catalog pages. All 20 records are verified;
eleven were wrong when we first checked, carried over from a 2021–22 list.

**Does it handle electives?**
No, and the specification says not to. Required courses only.

**Why does the freshman case need `--summer`?**
CPSC 3165 is online-only in fall and spring and we scope out online sections,
so face-to-face it exists only in summer. Without the flag the tool refuses and
explains why, rather than producing a plan the student cannot follow.

**Is 15 credits a term realistic?**
The cap applies only to courses in the model, so that means 15 credits of
*major* coursework. A student mixing in core classes would pass a lower cap.

**What is not finished?**
`data/sections.json` holds placeholder meeting times, CPSC 4000's offered
terms are assumed rather than confirmed, and the Windows executable has been
specified and built but not yet shipped. Everything else is done.
