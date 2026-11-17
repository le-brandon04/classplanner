"""Shared fixtures. Tests run against the project's real data files, so a bad
edit to prereqs.json or offerings.json fails the suite rather than a demo.
"""
import sys
from pathlib import Path

import pytest
from openpyxl import Workbook

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))

from planner import load_catalog, load_offerings  # noqa: E402


@pytest.fixture(scope="session")
def data_dir() -> Path:
    return PROJECT / "data"


@pytest.fixture(scope="session")
def catalog(data_dir):
    return load_catalog(data_dir / "prereqs.json")


@pytest.fixture(scope="session")
def offered(data_dir):
    return load_offerings(data_dir / "offerings.json", [])


@pytest.fixture(scope="session")
def offered_with_online(data_dir):
    return load_offerings(data_dir / "offerings.json", [], ignore_online=False)


@pytest.fixture
def make_plan(tmp_path):
    """Build a class-plan spreadsheet in the layout export_excel.py writes.

    rows: [(term_label, course_id, credits), ...]
    """
    def _make(rows, name="plan.xlsx", header=("Term", "Course", "Title", "Credits")):
        wb = Workbook()
        ws = wb.active
        ws.title = "Class Plan"
        ws["A1"] = "Recommended Class Plan"
        for col, text in enumerate(header, 1):
            ws.cell(row=4, column=col, value=text)
        for n, (term, course, credits) in enumerate(rows, 5):
            ws.cell(row=n, column=1, value=term)
            ws.cell(row=n, column=2, value=course)
            ws.cell(row=n, column=3, value="")
            ws.cell(row=n, column=4, value=credits)
        path = tmp_path / name
        wb.save(path)
        return path
    return _make
