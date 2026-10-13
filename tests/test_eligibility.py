"""
Automated tests. Run them with:  python -m pytest

Each test builds a tiny table by hand, so we know exactly what the
correct answer should be.
"""

import pandas as pd
import pytest

import data_loader
import eligibility as el


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def rules():
    """The three illustrative rules from the project brief, already validated."""
    raw = pd.DataFrame({
        "scholarship_name": ["Gold", "Silver", "Bronze"],
        "minimum_cgpa": ["9.0", "8.0", "7.0"],
        "scholarship_percentage": ["50", "25", "10"],
    })
    valid, issues = el.validate_rules(raw)
    assert issues.empty
    return valid


def students(*rows):
    """Build a raw students table: students(("S1", "Asha", "8.0"), ...)."""
    return pd.DataFrame(rows, columns=["student_id", "student_name", "cgpa"])


def award_for(cgpa, rules):
    """Run one student through the full pipeline and return their row."""
    report = el.build_report(students(("S1", "Test Student", cgpa)), rules)
    assert len(report.results) == 1
    return report.results.iloc[0]


# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("cgpa, expected", [("9.0", 50), ("8.0", 25), ("7.0", 10)])
def test_cgpa_exactly_at_threshold_qualifies(cgpa, expected, rules):
    assert award_for(cgpa, rules)["scholarship_percentage"] == expected


@pytest.mark.parametrize("cgpa, expected", [("8.99", 25), ("7.99", 10), ("6.99", 0)])
def test_cgpa_just_below_threshold_gets_lower_tier(cgpa, expected, rules):
    assert award_for(cgpa, rules)["scholarship_percentage"] == expected


@pytest.mark.parametrize("cgpa", ["9.5", "10", "10.0"])
def test_highest_scholarship(cgpa, rules):
    row = award_for(cgpa, rules)
    assert row["scholarship_name"] == "Gold"
    assert row["scholarship_percentage"] == 50


@pytest.mark.parametrize("cgpa", ["0", "4.5", "6.5"])
def test_below_every_threshold_is_not_eligible(cgpa, rules):
    row = award_for(cgpa, rules)
    assert row["scholarship_name"] == el.NOT_ELIGIBLE
    assert row["scholarship_percentage"] == 0
    assert not row["eligible"]


def test_highest_tier_wins_not_first_listed(rules):
    # Rules listed in a different order must give the same answer.
    shuffled = rules.sample(frac=1, random_state=1)
    assert el.find_scholarship(9.2, shuffled)["scholarship_percentage"] == 50


def test_float_noise_does_not_cross_threshold(rules):
    # 7.999999 rounds to 8.00, the value a person would see on a mark sheet.
    assert award_for("7.999999", rules)["scholarship_percentage"] == 25


# ---------------------------------------------------------------------------
# Invalid CGPA values
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad_cgpa, problem", [
    ("10.5", "CGPA must be between 0 and 10"),
    ("-1", "CGPA must be between 0 and 10"),
    ("abc", "CGPA is not a number"),
    ("", "Missing CGPA"),
    (None, "Missing CGPA"),
    ("inf", "CGPA must be between 0 and 10"),
])
def test_invalid_cgpa_is_rejected_with_reason(bad_cgpa, problem, rules):
    raw = students(("S1", "Valid", "8.5"), ("S2", "Invalid", bad_cgpa))
    report = el.build_report(raw, rules)

    assert list(report.results["student_id"]) == ["S1"]
    assert list(report.student_issues["student_id"]) == ["S2"]
    assert report.student_issues.iloc[0]["problem"] == problem


def test_missing_id_and_name_are_rejected(rules):
    raw = students((None, "No ID", "8"), ("S2", "  ", "8"), ("S3", "Fine", "8"))
    report = el.build_report(raw, rules)
    assert list(report.results["student_id"]) == ["S3"]
    assert list(report.student_issues["problem"]) == ["Missing student ID", "Missing student name"]


def test_whitespace_is_trimmed(rules):
    report = el.build_report(students(("  S1 ", "  Asha  ", " 8.2 ")), rules)
    row = report.results.iloc[0]
    assert row["student_id"] == "S1"
    assert row["student_name"] == "Asha"
    assert row["cgpa"] == 8.2


@pytest.mark.parametrize("bad", [11, -0.5, "nine", None])
def test_scholarship_for_cgpa_rejects_invalid_input(bad, rules):
    with pytest.raises(ValueError):
        el.scholarship_for_cgpa(bad, rules)


def test_scholarship_for_cgpa_answers_question(rules):
    answer = el.scholarship_for_cgpa(8.5, rules)
    assert answer["cgpa"] == 8.5
    assert answer["scholarship_name"] == "Silver"
    assert answer["scholarship_percentage"] == 25.0
    assert answer["eligible"] is True
    assert answer["required_threshold"] == 8.0
    assert answer["threshold_diff"] == 0.50



# ---------------------------------------------------------------------------
# Empty datasets and missing columns
# ---------------------------------------------------------------------------

def test_empty_student_table(rules):
    report = el.build_report(pd.DataFrame(), rules)
    assert report.results.empty
    summary = el.summarize(report.results, report.rules)
    assert summary["total_students"] == 0
    assert summary["eligible_students"] == 0
    assert list(summary["counts_by_scholarship"]["students"]) == [0, 0, 0]


def test_header_only_student_table(rules):
    report = el.build_report(students(), rules)
    assert report.results.empty
    assert report.student_issues.empty


def test_no_rules_means_nobody_eligible():
    report = el.build_report(students(("S1", "Asha", "9.9")), pd.DataFrame())
    assert report.results.iloc[0]["scholarship_name"] == el.NOT_ELIGIBLE
    assert el.summarize(report.results, report.rules)["eligible_students"] == 0


def test_missing_column_raises_clear_error(rules):
    raw = pd.DataFrame({"student_id": ["S1"], "student_name": ["Asha"]})
    with pytest.raises(ValueError, match="cgpa"):
        el.build_report(raw, rules)


def test_invalid_rule_rows_are_reported():
    raw = pd.DataFrame({
        "scholarship_name": ["Good", "Bad CGPA", "Bad %", "Good"],
        "minimum_cgpa": ["8", "12", "7", "9"],
        "scholarship_percentage": ["25", "10", "150", "50"],
    })
    valid, issues = el.validate_rules(raw)
    assert valid.empty  # both "Good" rows are duplicates, others invalid
    assert list(issues["problem"]) == [
        "Duplicate scholarship name",
        "Minimum CGPA must be between 0 and 10",
        "Percentage must be above 0 and at most 100",
        "Duplicate scholarship name",
    ]


# ---------------------------------------------------------------------------
# Duplicate student IDs
# ---------------------------------------------------------------------------

def test_duplicate_ids_are_all_rejected(rules):
    raw = students(("S1", "Asha", "9.1"), ("S1", "Asha K", "6.0"), ("S2", "Ravi", "8.0"))
    report = el.build_report(raw, rules)
    assert list(report.results["student_id"]) == ["S2"]
    assert len(report.student_issues) == 2
    assert set(report.student_issues["problem"]) == {"Duplicate student ID"}


def test_duplicate_ids_ignore_letter_case(rules):
    report = el.build_report(students(("s1", "A", "8"), ("S1", "B", "8")), rules)
    assert report.results.empty
    assert len(report.student_issues) == 2


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------

def test_same_input_same_output_regardless_of_row_order(rules):
    raw = students(("S3", "C", "7.5"), ("S1", "A", "9.5"), ("S2", "B", "9.5"), ("S4", "D", "5"))
    first = el.build_report(raw, rules).results
    second = el.build_report(raw.iloc[::-1], rules).results
    pd.testing.assert_frame_equal(first, second)
    assert list(first["student_id"]) == ["S1", "S2", "S3", "S4"]


# ---------------------------------------------------------------------------
# Search and filters
# ---------------------------------------------------------------------------

@pytest.fixture
def results(rules):
    raw = students(
        ("S001", "Aarav Sharma", "9.4"),
        ("S002", "Diya Patel", "8.7"),
        ("S003", "Rohan Verma", "7.2"),
        ("S004", "Kabir Singh", "6.1"),
    )
    return el.build_report(raw, rules).results


def test_search_by_partial_name_ignores_case(results):
    found = el.search_students(results, "sHaRmA")
    assert list(found["student_id"]) == ["S001"]


def test_search_by_student_id(results):
    found = el.search_students(results, "s003")
    assert list(found["student_name"]) == ["Rohan Verma"]


def test_search_with_no_match_returns_empty(results):
    assert el.search_students(results, "Zoya").empty


def test_blank_search_returns_everyone(results):
    assert len(el.search_students(results, "   ")) == 4


def test_search_text_is_not_treated_as_regex(results):
    assert el.search_students(results, "(.*)").empty


def test_filter_exact_percentage(results):
    found = el.filter_by_percentage(results, 25)
    assert list(found["student_id"]) == ["S002"]


def test_filter_at_least_percentage(results):
    found = el.filter_by_percentage(results, 25, at_least=True)
    assert list(found["student_id"]) == ["S001", "S002"]


def test_filter_none_returns_everyone(results):
    assert len(el.filter_by_percentage(results, None)) == 4


def test_split_eligible_and_ineligible(results):
    eligible, ineligible = el.split_by_eligibility(results)
    assert list(eligible["student_id"]) == ["S001", "S002", "S003"]
    assert list(ineligible["student_id"]) == ["S004"]


def test_search_and_filter_combined(results):
    found = el.filter_by_percentage(el.search_students(results, "a"), 10, at_least=True)
    assert set(found["student_id"]) == {"S001", "S002", "S003"}


def test_summary_counts(results, rules):
    summary = el.summarize(results, rules)
    assert summary["total_students"] == 4
    assert summary["eligible_students"] == 3
    assert summary["ineligible_students"] == 1
    counts = dict(zip(summary["counts_by_scholarship"]["scholarship_name"],
                      summary["counts_by_scholarship"]["students"]))
    assert counts == {"Gold": 1, "Silver": 1, "Bronze": 1}


# ---------------------------------------------------------------------------
# Data loader
# ---------------------------------------------------------------------------

def test_missing_file_raises_data_load_error(tmp_path):
    with pytest.raises(data_loader.DataLoadError):
        data_loader.load_students(tmp_path / "nope.csv")


def test_completely_empty_file_loads_as_empty_table(tmp_path):
    path = tmp_path / "empty.csv"
    path.write_text("")
    assert data_loader.load_students(path).empty


def test_column_names_are_normalised(tmp_path):
    path = tmp_path / "students.csv"
    path.write_text(" Student_ID , Student_Name , CGPA \nS1,Asha,8.1\n")
    df = data_loader.load_students(path)
    assert list(df.columns) == ["student_id", "student_name", "cgpa"]


def test_bundled_sample_data_is_clean():
    report = el.build_report(data_loader.load_students(), data_loader.load_scholarships())
    assert len(report.results) == 100
    assert report.student_issues.empty
    assert report.rule_issues.empty


def test_bundled_error_sample_flags_bad_rows():
    raw = data_loader.load_students(data_loader.DATA_DIR / "students_with_errors.csv")
    report = el.build_report(raw, data_loader.load_scholarships())
    assert list(report.results["student_id"]) == ["S101", "S108"]
    assert len(report.student_issues) == 8


# ---------------------------------------------------------------------------
# Advanced Threshold Boundaries (Explicit Requirement 4)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "cgpa, expected_pct, expected_name, expected_threshold, expected_diff",
    [
        ("6.99", 0.0, el.NOT_ELIGIBLE, 7.0, -0.01),
        ("7.00", 10.0, "Bronze", 7.0, 0.0),
        ("7.99", 10.0, "Bronze", 7.0, 0.99),
        ("8.00", 25.0, "Silver", 8.0, 0.0),
        ("8.99", 25.0, "Silver", 8.0, 0.99),
        ("9.00", 50.0, "Gold", 9.0, 0.0),
        ("10.00", 50.0, "Gold", 9.0, 1.0),
    ],
)
def test_explicit_boundary_thresholds(
    cgpa, expected_pct, expected_name, expected_threshold, expected_diff, rules
):
    result = el.find_scholarship(cgpa, rules)
    assert result["scholarship_percentage"] == expected_pct
    assert result["scholarship_name"] == expected_name
    assert result["required_threshold"] == pytest.approx(expected_threshold, 0.01)
    assert result["threshold_diff"] == pytest.approx(expected_diff, 0.01)
    assert "explanation" in result
    assert "next_tier" in result


def test_explainable_engine_fields(rules):
    raw = students(
        ("S1", "Aarav", "9.50"),
        ("S2", "Meera", "8.00"),
        ("S3", "Kabir", "6.85"),
    )
    report = el.build_report(raw, rules)
    res = report.results

    assert "required_threshold" in res.columns
    assert "threshold_diff" in res.columns
    assert "explanation" in res.columns
    assert "next_tier" in res.columns

    s1 = el.explain_student_by_id("S1", res)
    assert s1["eligible"] is True
    assert s1["required_threshold"] == 9.0
    assert s1["threshold_diff"] == 0.50
    assert "Qualified for Gold" in s1["explanation"]
    assert s1["next_tier"] == "Highest tier achieved"

    s3 = el.explain_student_by_id("S3", res)
    assert s3["eligible"] is False
    assert s3["required_threshold"] == 7.0
    assert s3["threshold_diff"] == -0.15
    assert "Not eligible" in s3["explanation"]
    assert "Bronze" in s3["next_tier"]


def test_what_if_policy_simulation(rules):
    raw = students(
        ("S1", "Gold Candidate", "9.20"),
        ("S2", "Silver Candidate", "8.40"),
        ("S3", "Bronze Candidate", "7.50"),
        ("S4", "Ineligible Candidate", "6.80"),
    )
    # Lower Gold cutoff to 8.20 and Bronze cutoff to 6.50
    custom_rules = pd.DataFrame([
        {"scholarship_name": "Gold", "minimum_cgpa": 8.20, "scholarship_percentage": 50.0},
        {"scholarship_name": "Silver", "minimum_cgpa": 7.50, "scholarship_percentage": 25.0},
        {"scholarship_name": "Bronze", "minimum_cgpa": 6.50, "scholarship_percentage": 10.0},
    ])
    sim = el.simulate_policy(raw, custom_rules)
    assert sim["summary"]["total_students"] == 4
    assert sim["summary"]["eligible_students"] == 4  # S4 now qualifies for Bronze!


def test_data_quality_audit_breakdown():
    raw_error_data = pd.DataFrame([
        {"student_id": "S1", "student_name": "Valid Student", "cgpa": "8.50"},
        {"student_id": "", "student_name": "Missing ID", "cgpa": "9.00"},
        {"student_id": "S3", "student_name": "", "cgpa": "8.00"},
        {"student_id": "S4", "student_name": "Missing CGPA", "cgpa": ""},
        {"student_id": "S5", "student_name": "Non numeric", "cgpa": "invalid"},
        {"student_id": "S6", "student_name": "Out of bounds high", "cgpa": "15.0"},
        {"student_id": "S7", "student_name": "Duplicate A", "cgpa": "8.00"},
        {"student_id": "S7", "student_name": "Duplicate B", "cgpa": "7.50"},
    ])
    students_valid, issues = el.validate_students(raw_error_data)
    audit = el.audit_data_quality(raw_error_data, issues)

    assert audit["total_records"] == 8
    assert audit["valid_records"] == 1  # Only S1 is valid
    assert audit["invalid_records"] == 7
    assert audit["duplicates_count"] == 2
    assert audit["missing_values_count"] == 3
    assert audit["non_numeric_cgpa_count"] == 1
    assert audit["out_of_bounds_cgpa_count"] == 1


def test_load_from_buffer():
    csv_str = "student_id,student_name,cgpa\nS999,Buffer Student,9.90\n"
    df = data_loader.load_from_buffer(csv_str)
    assert len(df) == 1
    assert list(df.columns) == ["student_id", "student_name", "cgpa"]
    assert df.iloc[0]["student_id"] == "S999"


def test_assistant_deterministic_queries():
    import assistant

    report = el.build_report(data_loader.load_students(), data_loader.load_scholarships())

    # 1. Tier count query
    q1 = assistant.run_deterministic_query("How many students qualify for Gold?", report)
    assert q1["tool_called"] == "tool_count_by_tier"
    assert q1["raw_data"]["count"] == 26

    # 2. CGPA range query
    q2 = assistant.run_deterministic_query("Show students with CGPA between 8.0 and 9.0", report)
    assert q2["tool_called"] == "tool_filter_by_cgpa_range"
    assert q2["raw_data"]["matching_count"] > 0

    # 3. Explain student query
    q3 = assistant.run_deterministic_query("Explain why student S001 qualifies for its scholarship", report)
    assert q3["tool_called"] == "tool_explain_student"
    assert q3["raw_data"]["student_id"] == "S001"
    assert q3["raw_data"]["eligible"] is True

    # 4. Summary query
    q4 = assistant.run_deterministic_query("Summarize the scholarship distribution", report)
    assert q4["tool_called"] == "tool_get_summary"
    assert q4["raw_data"]["total_students"] == 100

