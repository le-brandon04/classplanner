# Spike: Can DegreeWorks audit PDFs be parsed reliably?

**Project:** A Smart Class Planning Tool for Academic Advising (CPSC 4175)
**Team:** Brian Ganzler, Carter Sloan, Kameryn Redd, Dajour Johnson, Brandon Le
**Cycle:** 1
**Timebox:** 6 hours

## Question

Input 1 of the tool is the list of courses a student still needs, taken from a
DegreeWorks audit PDF. Before estimating that story we needed to know whether
the course list can actually be extracted from the PDF, and with which library.

## What we found

DegreeWorks audits can be exported two ways, and **each one loses something the
other keeps**:

| Export path | Full requirement detail | Text layer | Result |
|---|:--:|:--:|---|
| DegreeWorks print view → Microsoft Print to PDF | Yes | No | Text is converted to vector outlines. `pdfplumber` and `pypdf` both return 0 characters. |
| Dashboard → Chrome "Save as PDF" | No | Yes | Real text, but requirement blocks print collapsed, so "Still needed:" never appears. |

Diagnostics on the Microsoft Print to PDF file showed 0 characters and 0 images
per page, but roughly 2,000 vector curves per page — every letter drawn as
shapes. The file's Producer metadata confirms it: `Microsoft: Print To PDF`.

Expanding the requirement blocks in the dashboard before printing did not
change the Chrome output; the two exports were byte-identical apart from the
timestamp.

## Decision

Use **OCR on the full-content export**. Pages are rendered with PyMuPDF at
300 DPI grayscale and read with Tesseract. PyMuPDF was chosen over poppler's
`pdftoppm` so that Tesseract is the only non-pip dependency teammates must
install.

## Verification

Run against a real 9-page audit, the parser returned:

| Course | Requirement line |
|---|---|
| CPSC 4000 | Still needed: 1 Class in CPSC 4000 |
| CPSC 4148 | Still needed: 3 Credits in CPSC 4148 |
| CPSC 4176 | Still needed: 3 Credits in CPSC 4176 |
| MISM 4168 | Still needed: 1 Class in MISM 4168 |
| MSAL 1216 | Still needed: 4 Credits in MSAL 1216 or 1216L or 2225 … |

The same audit contains advisor notes written by Dr. Hodhod:

> Fall 2026: CPSC 3125, CPSC 4115, CPSC 4155, CPSC 3175, and CPSC 4175 — Apply
> for graduation. Spring 2027: MISM 4168, CPSC 4176, and CPSC 4148
>
> Spring 2027: Register for CPSC 4000

All four required courses the parser found match the advisor's plan exactly.
This is independent confirmation that the extraction is correct rather than
merely plausible.

## Known limitations

- **Multi-option electives are unreliable.** Lines like "4 Credits in MSAL 1216
  or 1216L or 2225…" use circled footnote symbols that Tesseract mangles. The
  parser flags these with `needs_review` and takes only the first option. The
  project scope covers required courses only, so this is out of scope.
- **Collapsed blocks are invisible.** Any requirement block collapsed at export
  time does not appear in the PDF at all. An 8-page export missed CPSC 4176
  that a 9-page export caught.
- **OCR can misread characters.** Course numbers such as `1301K` and `5125U`
  are the risky cases. Every extracted code should be validated against the
  known course list in `prereqs.json`; anything unrecognised gets flagged.
- **Tesseract is a system dependency.** Not installable via pip. Each developer
  must install the binary separately.

## Effect on estimates

Story 1 stays at 12 hours. The OCR route is more setup but less regex work than
parsing raw text would have been.

## User documentation requirement

The tool must tell users to export their audit from **DegreeWorks' own print
view with all requirement blocks expanded**. Any other export path silently
produces an empty or incomplete course list.

## Recommended future work

If CSU ever exposes a DegreeWorks API or a machine-readable export, replace the
OCR path entirely. The parser is isolated behind `remaining_courses.json`, so
nothing downstream would need to change.
