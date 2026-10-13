"""
Tests for the Streamlit screen. AppTest runs app.py without a browser
and lets us type into widgets and read what the page shows.
"""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).parent.parent / "app.py")


@pytest.fixture
def app():
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert not at.exception
    return at


def tab_labels(at):
    return [tab.label for tab in at.tabs]


def test_dashboard_numbers(app):
    metrics = {m.label: m.value for m in app.metric}
    assert metrics["Students checked"] == "100"
    assert metrics["Eligible"] == "81"
    assert metrics["Not eligible"] == "19"
    assert metrics["Qualification Rate"] == "81.0%"
    assert tab_labels(app)[:3] == ["Eligible (81)", "Not eligible (19)", "Data issues (0)"]
    assert "What-If Simulator" in tab_labels(app)
    assert "AI Assistant" in tab_labels(app)


def test_search_by_name(app):
    app.text_input(key="search").input("sharma").run()
    assert tab_labels(app)[:2] == ["Eligible (1)", "Not eligible (0)"]


def test_search_with_no_match_shows_help(app):
    app.text_input(key="search").input("zzz").run()
    assert any("No students match" in info.value for info in app.info)


def test_filter_exact_and_at_least(app):
    app.selectbox(key="tier").select("25%").run()
    assert tab_labels(app)[0] == "Eligible (28)"
    app.radio(key="match_mode").set_value("At least").run()
    assert tab_labels(app)[0] == "Eligible (54)"


def test_cgpa_checker(app):
    app.number_input(key="cgpa_check").set_value(6.5).run()
    assert any("does not qualify" in w.value for w in app.sidebar.warning)
    app.number_input(key="cgpa_check").set_value(9.0).run()
    assert any("Gold Merit" in s.value for s in app.sidebar.success)


def test_error_dataset_shows_issues_without_crashing(app):
    app.radio(key="dataset").set_value("Sample with data errors").run()
    assert not app.exception
    metrics = {m.label: m.value for m in app.metric}
    assert metrics["Students checked"] == "2"
    assert any("8 student row(s) were skipped" in w.value for w in app.warning)
    assert tab_labels(app)[2] == "Data issues (8)"
