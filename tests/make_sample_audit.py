"""Generate data/sample_audit.pdf — a synthetic DegreeWorks-style audit.

WHY THIS EXISTS
---------------
A real DegreeWorks audit carries the student's name and CSU ID, so it can
never go in the repository. That left the parser as the one part of the
pipeline nobody could run without a private file, and the only part with no
test coverage.

This builds a stand-in. It is deliberately NOT a real audit and is labelled
as such on every page: the student is "SAMPLE STUDENT", the ID is all zeros,
and a banner says so. It exists to exercise the parser, nothing else.

It reproduces the one property that makes this problem hard: the pages are
rendered as images, so the PDF has no text layer at all, exactly like the
Microsoft Print to PDF export the real audits come from. OCR is the only way
to read it, which is the whole point.

Regenerate with:  python tests/make_sample_audit.py
"""
from pathlib import Path

import pymupdf
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / "data" / "sample_audit.pdf"

W, H = 1700, 2200              # ~200 dpi letter
MARGIN = 90
LINE = 34

FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed.ttf",
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
]
BOLD_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
]


def _font(paths, size):
    for p in paths:
        if Path(p).is_file():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


REG = _font(FONT_CANDIDATES, 26)
BOLD = _font(BOLD_CANDIDATES or FONT_CANDIDATES, 28)
BIG = _font(BOLD_CANDIDATES or FONT_CANDIDATES, 36)

# (style, text) — "head" is a block header, "req" a requirement line
PAGE_1 = [
    ("banner", "SAMPLE — SYNTHETIC TEST FIXTURE, NOT A REAL STUDENT AUDIT"),
    ("big", "Degree Works  |  Academic Evaluation"),
    ("gap", ""),
    ("plain", "Student        SAMPLE STUDENT"),
    ("plain", "ID             000000000"),
    ("plain", "Degree         Bachelor of Science"),
    ("plain", "Major          Computer Science - Software Systems"),
    ("plain", "Catalog Year   2024-2025"),
    ("gap", ""),
    ("head", "Degree in Bachelor of Science                    INCOMPLETE"),
    ("plain", "Credits required: 123    Credits applied: 86"),
    ("gap", ""),
    ("head", "Major Requirements                               INCOMPLETE"),
    ("gap", ""),
    ("req", "O  CPSC 3175   Object-Oriented Design"),
    ("sub", "   Still needed:  3 Credits in CPSC 3175"),
    ("gap", ""),
    ("req", "O  CPSC 4115   Algorithms"),
    ("sub", "   Still needed:  3 Credits in CPSC 4115"),
    ("gap", ""),
    ("req", "O  CPSC 4175   Software Engineering"),
    ("sub", "   Still needed:  3 Credits in CPSC 4175"),
    ("gap", ""),
    ("req", "O  CPSC 4176   Senior Software Engineering Project"),
    ("sub", "   Still needed:  3 Credits in CPSC 4176"),
    ("gap", ""),
    ("req", "O  CPSC 4000   Baccalaureate Survey"),
    ("sub", "   Still needed:  1 Class in CPSC 4000"),
    ("gap", ""),
    ("req", "O  Graduation Application"),
    ("sub", "   Still needed:  1 Class in Graduation Application"),
    ("gap", ""),
    ("req", "O  Senior Exit Survey"),
    ("sub", "   Still needed:  See Exit Survey"),
    ("gap", ""),
    ("req", "O  Area F Elective"),
    ("sub", "   Still needed:  4 Credits in MSAL 1216 or 1216L or 2225 or 2226"),
    ("gap", ""),
    ("plain", "Advisor note: Fall 2028 - CPSC 4175. Spring 2029 - CPSC 4176."),
]

# Everything from here on must be IGNORED by the parser. If any of these
# course codes shows up in the output, the section filter has broken.
PAGE_2 = [
    ("banner", "SAMPLE — SYNTHETIC TEST FIXTURE, NOT A REAL STUDENT AUDIT"),
    ("head", "Fall Through Courses"),
    ("plain", "These are complete and must never appear as still needed."),
    ("gap", ""),
    ("plain", "CPSC 1301K   Computer Science I                  A    4"),
    ("plain", "CPSC 1302K   Computer Science II                 B    4"),
    ("plain", "CPSC 2108    Data Structures                     A    3"),
    ("plain", "MATH 1113    Pre-Calculus                        B    3"),
    ("plain", "MATH 2125    Intro to Discrete Mathematics       A    3"),
    ("gap", ""),
    ("head", "In-progress Courses"),
    ("plain", "CPSC 3125    Operating Systems                   IP   3"),
    ("plain", "CPSC 3131    Database Systems I                  IP   3"),
    ("gap", ""),
    ("head", "Insufficient Courses"),
    ("plain", "CPSC 2105    Computer Organization               W    0"),
]


def render(blocks) -> Image.Image:
    img = Image.new("L", (W, H), 255)
    d = ImageDraw.Draw(img)
    y = MARGIN
    for style, text in blocks:
        if style == "gap":
            y += LINE // 2
            continue
        if style == "banner":
            d.rectangle([MARGIN - 20, y - 8, W - MARGIN + 20, y + 40], fill=220)
            d.text((MARGIN, y), text, font=BOLD, fill=0)
            y += LINE + 24
            continue
        if style == "big":
            d.text((MARGIN, y), text, font=BIG, fill=0)
            y += LINE + 20
            continue
        if style == "head":
            d.rectangle([MARGIN - 20, y - 6, W - MARGIN + 20, y + 36], fill=235)
            d.text((MARGIN, y), text, font=BOLD, fill=0)
            y += LINE + 12
            continue
        d.text((MARGIN + (40 if style == "sub" else 0), y), text,
               font=REG, fill=0)
        y += LINE
    return img


def main() -> None:
    doc = pymupdf.open()
    for blocks in (PAGE_1, PAGE_2):
        img = render(blocks)
        # JPEG, not PNG: a lossless 200 dpi page is ~4 MB and this file lives
        # in the repository. Quality 85 on clean rendered text costs nothing
        # that OCR can see - test_parser.py checks the result either way.
        buf = HERE / "_tmp_page.jpg"
        img.save(buf, quality=85, optimize=True)
        page = doc.new_page(width=612, height=792)
        page.insert_image(pymupdf.Rect(0, 0, 612, 792), filename=str(buf))
        buf.unlink()
    doc.set_metadata({"producer": "Microsoft: Print To PDF",
                      "title": "SAMPLE synthetic audit - not a real student"})
    doc.save(OUT)
    doc.close()

    check = pymupdf.open(OUT)
    chars = sum(len(p.get_text()) for p in check)
    print(f"wrote {OUT}  ({check.page_count} pages, {chars} text characters "
          "— image-only, as intended)")


if __name__ == "__main__":
    main()
