"""
cli.py — one entry point, so the project ships as a single Windows executable.

The specification asks for "a Python based standalone application" that is
"executable in Windows". Three separate scripts are fine while developing but
make a poor deliverable, so this dispatches to them:

    classplanner parse  <audit.pdf> [-o remaining_courses.json]
    classplanner plan   [--remaining ...] [--start "Fall 2026"] [--summer] ...
    classplanner check  <plan.xlsx> [--strict] [--max-credits N]

Each subcommand takes exactly the flags the underlying script takes, so
anything in the README works here with `classplanner` in front of it.

Running from source is identical:  python cli.py plan --start "Fall 2026"
"""
from __future__ import annotations

import importlib
import sys

COMMANDS = {
    "parse": ("parse_audit_ocr", "read a DegreeWorks audit PDF"),
    "plan": ("planner", "build a semester-by-semester plan"),
    "check": ("validator", "check an existing plan for prerequisite issues"),
}

USAGE = """Smart Class Planning Tool

usage: classplanner <command> [options]

commands:
  parse   read a DegreeWorks audit PDF into remaining_courses.json
  plan    build a semester-by-semester plan and write it to Excel
  check   check an existing plan spreadsheet for prerequisite issues

Run a command with --help for its options, e.g.
  classplanner plan --help

The curriculum data lives in the data/ folder next to this program. Edit
those files to change the catalog; no part of it is inside the program.
"""


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "help"):
        print(USAGE)
        sys.exit(0)

    command = sys.argv[1]
    if command not in COMMANDS:
        print(f"Unknown command {command!r}.\n", file=sys.stderr)
        print(USAGE, file=sys.stderr)
        sys.exit(2)

    module_name, _description = COMMANDS[command]
    # importlib, not a plain import, so a command only pays for the libraries
    # it needs - `check` should not have to load PyMuPDF. PyInstaller cannot
    # see a dynamic import, so all three modules are listed as hiddenimports
    # in classplanner.spec; drop one from there and the .exe builds fine and
    # then fails here with ModuleNotFoundError.
    module = importlib.import_module(module_name)

    # Hand the remaining arguments to the real script untouched, with argv[0]
    # set so its --help text shows "classplanner plan", not "planner.py".
    sys.argv = [f"classplanner {command}"] + sys.argv[2:]
    module.main()


if __name__ == "__main__":
    main()
