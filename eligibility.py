"""
eligibility.py - The rule engine. This is the "source of truth".

Everything that decides who gets which scholarship lives here:
  1. Validate student records and scholarship rules.
  2. Assign each valid student the best scholarship they qualify for.
  3. Search, filter and summarise the results.

This file has no Streamlit code and no AI code. That keeps it easy to test,
and later the Gemini integration will simply CALL these functions instead
of making its own decisions.
"""

from dataclasses import dataclass

import pandas as pd

STUDENT_COLUMNS = ["student_id", "student_name", "cgpa"]
RULE_COLUMNS = ["scholarship_name", "minimum_cgpa", "scholarship_percentage"]
RESULT_COLUMNS = [
    "student_id",
    "student_name",
    "cgpa",
    "scholarship_name",
    "scholarship_percentage",
    "eligible",
    "required_threshold",
    "threshold_diff",
    "explanation",
    "next_tier",
]
ISSUE_COLUMNS = ["row", "student_id", "student_name", "cgpa", "problem"]

MIN_CGPA = 0.0
MAX_CGPA = 10.0
NOT_ELIGIBLE = "Not eligible"


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _check_columns(df: pd.DataFrame, required: list, label: str) -> None:
    """Stop early with a clear message if a required column is missing."""
    missing = [column for column in required if column not in df.columns]
    if missing:
        raise ValueError(
            f"{label} data is missing required column(s): {', '.join(missing)}"
        )


def _clean_text(series: pd.Series) -> pd.Series:
    """Trim spaces and treat blank cells as missing values."""
    return series.astype("string").str.strip().replace("", pd.NA)


def _first_problem(index, checks) -> pd.Series:
    """
    For every row, record the FIRST check it fails ("" means no problem).

    checks is a list of (boolean_mask, message) pairs, in priority order.
    """
    problems = pd.Series("", index=index, dtype="object")
    for mask, message in checks:
        failed = mask.fillna(False).astype(bool)
        problems = problems.where(~(failed & (problems == "")), message)
    return problems


def _issue_rows(original: pd.DataFrame, problems: pd.Series, columns: list) -> pd.DataFrame:
    """Build a table of rejected rows. 'row' is the line number in the CSV file."""
    bad = problems != ""
    issues = original.loc[bad, columns].copy()
    # Line 1 of a CSV file is the header, so data row 0 is on line 2.
    issues.insert(0, "row", [position + 2 for position, flag in enumerate(bad) if flag])
    issues["problem"] = problems[bad]
    return issues.reset_index(drop=True)


# ---------------------------------------------------------------------------
# 1. Validation
# ---------------------------------------------------------------------------

def validate_students(raw: pd.DataFrame):
    """
    Split raw student rows into (valid_students, issues).

    A row is rejected if it has a missing ID, missing name, missing or
    non-numeric CGPA, a CGPA outside 0-10, or an ID that appears more than
    once. For duplicate IDs, ALL copies are rejected: we cannot know which
    record is correct, so an administrator should fix the source data.
    """
    empty_students = pd.DataFrame(columns=STUDENT_COLUMNS)
    empty_issues = pd.DataFrame(columns=ISSUE_COLUMNS)
    if raw is None or raw.empty:
        return empty_students, empty_issues

    _check_columns(raw, STUDENT_COLUMNS, "Student")
    raw = raw.reset_index(drop=True)

    student_id = _clean_text(raw["student_id"])
    student_name = _clean_text(raw["student_name"])
    cgpa_text = _clean_text(raw["cgpa"])
    cgpa = pd.to_numeric(cgpa_text, errors="coerce")

    id_upper = student_id.str.upper()  # "s001" and "S001" count as the same ID
    duplicate_id = id_upper.notna() & id_upper.duplicated(keep=False)

    problems = _first_problem(raw.index, [
        (student_id.isna(), "Missing student ID"),
        (student_name.isna(), "Missing student name"),
        (cgpa_text.isna(), "Missing CGPA"),
        (cgpa.isna(), "CGPA is not a number"),
        ((cgpa < MIN_CGPA) | (cgpa > MAX_CGPA), "CGPA must be between 0 and 10"),
        (duplicate_id, "Duplicate student ID"),
    ])

    display = pd.DataFrame({
        "student_id": student_id,
        "student_name": student_name,
        "cgpa": cgpa_text,
    })
    issues = _issue_rows(display, problems, STUDENT_COLUMNS)

    ok = problems == ""
    valid = pd.DataFrame({
        "student_id": student_id[ok],
        "student_name": student_name[ok],
        # Round to 2 decimals so 7.999999 is not mistaken for 8.0.
        "cgpa": cgpa[ok].astype(float).round(2),
    }).reset_index(drop=True)
    return valid, issues


def validate_rules(raw: pd.DataFrame):
    """
    Split raw scholarship rules into (valid_rules, issues).

    Valid rules are sorted from the highest percentage to the lowest.
    """
    empty_rules = pd.DataFrame(columns=RULE_COLUMNS)
    if raw is None or raw.empty:
        return empty_rules, pd.DataFrame(columns=["row", *RULE_COLUMNS, "problem"])

    _check_columns(raw, RULE_COLUMNS, "Scholarship rules")
    raw = raw.reset_index(drop=True)

    name = _clean_text(raw["scholarship_name"])
    minimum = pd.to_numeric(_clean_text(raw["minimum_cgpa"]), errors="coerce")
    percentage = pd.to_numeric(_clean_text(raw["scholarship_percentage"]), errors="coerce")
    name_upper = name.str.upper()
    duplicate_name = name_upper.notna() & name_upper.duplicated(keep=False)

    problems = _first_problem(raw.index, [
        (name.isna(), "Missing scholarship name"),
        (minimum.isna(), "Minimum CGPA is missing or not a number"),
        ((minimum < MIN_CGPA) | (minimum > MAX_CGPA), "Minimum CGPA must be between 0 and 10"),
        (percentage.isna(), "Percentage is missing or not a number"),
        ((percentage <= 0) | (percentage > 100), "Percentage must be above 0 and at most 100"),
        (duplicate_name, "Duplicate scholarship name"),
    ])

    display = pd.DataFrame({
        "scholarship_name": name,
        "minimum_cgpa": raw["minimum_cgpa"],
        "scholarship_percentage": raw["scholarship_percentage"],
    })
    issues = _issue_rows(display, problems, RULE_COLUMNS)

    ok = problems == ""
    valid = pd.DataFrame({
        "scholarship_name": name[ok],
        "minimum_cgpa": minimum[ok].astype(float).round(2),
        "scholarship_percentage": percentage[ok].astype(float),
    })
    valid = valid.sort_values(
        ["scholarship_percentage", "minimum_cgpa", "scholarship_name"],
        ascending=[False, False, True],
    ).reset_index(drop=True)
    return valid, issues


# ---------------------------------------------------------------------------
# 2. Eligibility
# ---------------------------------------------------------------------------

def find_scholarship(cgpa: float, rules: pd.DataFrame) -> dict:
    """
    Return the best scholarship a single CGPA qualifies for, along with
    explainability details (applied threshold, margin difference, explanation, next tier).

    "Best" means the highest percentage among the rules whose minimum CGPA
    the student meets. A CGPA exactly equal to a threshold qualifies.
    """
    no_award_empty_rules = {
        "scholarship_name": NOT_ELIGIBLE,
        "scholarship_percentage": 0.0,
        "eligible": False,
        "required_threshold": None,
        "threshold_diff": 0.0,
        "explanation": "No active scholarship rules to evaluate against.",
        "next_tier": "None",
    }
    if rules is None or rules.empty:
        return no_award_empty_rules

    cgpa = round(float(cgpa), 2)
    sorted_rules = rules.sort_values(
        ["scholarship_percentage", "minimum_cgpa", "scholarship_name"],
        ascending=[False, False, True],
    ).reset_index(drop=True)

    applicable = sorted_rules[sorted_rules["minimum_cgpa"] <= cgpa]
    if applicable.empty:
        lowest_rule = sorted_rules.iloc[-1]
        min_cutoff = float(lowest_rule["minimum_cgpa"])
        diff = round(cgpa - min_cutoff, 2)
        gap = round(abs(diff), 2)
        return {
            "scholarship_name": NOT_ELIGIBLE,
            "scholarship_percentage": 0.0,
            "eligible": False,
            "required_threshold": min_cutoff,
            "threshold_diff": diff,
            "explanation": (
                f"Not eligible: CGPA {cgpa:.2f} is below the minimum threshold of "
                f"{min_cutoff:.2f} for {lowest_rule['scholarship_name']} "
                f"({gap:.2f} point(s) below cutoff)."
            ),
            "next_tier": f"{lowest_rule['scholarship_name']} ({min_cutoff:.2f} required, gap: {gap:.2f})",
        }

    best = applicable.iloc[0]
    best_pct = float(best["scholarship_percentage"])
    threshold = float(best["minimum_cgpa"])
    diff = round(cgpa - threshold, 2)

    # Determine next higher tier if available
    higher_rules = sorted_rules[sorted_rules["scholarship_percentage"] > best_pct].sort_values(
        "scholarship_percentage", ascending=True
    )
    if not higher_rules.empty:
        next_rule = higher_rules.iloc[0]
        next_min = float(next_rule["minimum_cgpa"])
        next_gap = round(max(0.0, next_min - cgpa), 2)
        next_tier = f"{next_rule['scholarship_name']} ({next_min:.2f} required, gap: {next_gap:.2f})"
    else:
        next_tier = "Highest tier achieved"

    margin_text = f"+{diff:.2f}" if diff > 0 else "0.00 (exact threshold match)"
    explanation = (
        f"Qualified for {best['scholarship_name']}: CGPA {cgpa:.2f} meets the "
        f"{threshold:.2f} threshold ({margin_text})."
    )

    return {
        "scholarship_name": best["scholarship_name"],
        "scholarship_percentage": best_pct,
        "eligible": True,
        "required_threshold": threshold,
        "threshold_diff": diff,
        "explanation": explanation,
        "next_tier": next_tier,
    }


def scholarship_for_cgpa(cgpa, rules: pd.DataFrame) -> dict:
    """
    Answer "What scholarship does a CGPA of X qualify for?".

    Unlike find_scholarship, this checks the input first, because it may be
    called directly by a user (or later by the AI).
    """
    try:
        value = float(cgpa)
    except (TypeError, ValueError):
        raise ValueError(f"CGPA must be a number, got {cgpa!r}")
    if pd.isna(value) or not MIN_CGPA <= value <= MAX_CGPA:
        raise ValueError("CGPA must be between 0 and 10")
    return {"cgpa": round(value, 2), **find_scholarship(value, rules)}


def assign_scholarships(students: pd.DataFrame, rules: pd.DataFrame) -> pd.DataFrame:
    """
    Add scholarship and explainability columns to a table of VALID students.

    Output is sorted by CGPA (highest first) then student ID, so the same
    input always gives the same output in the same order.
    """
    if students.empty:
        return pd.DataFrame(columns=RESULT_COLUMNS)

    awards = [find_scholarship(cgpa, rules) for cgpa in students["cgpa"]]
    results = students.copy()
    results["scholarship_name"] = [award["scholarship_name"] for award in awards]
    results["scholarship_percentage"] = [award["scholarship_percentage"] for award in awards]
    results["eligible"] = [award["eligible"] for award in awards]
    results["required_threshold"] = [award["required_threshold"] for award in awards]
    results["threshold_diff"] = [award["threshold_diff"] for award in awards]
    results["explanation"] = [award["explanation"] for award in awards]
    results["next_tier"] = [award["next_tier"] for award in awards]

    results = results.sort_values(["cgpa", "student_id"], ascending=[False, True])
    return results[RESULT_COLUMNS].reset_index(drop=True)


# ---------------------------------------------------------------------------
# 3. Search, filters and summary
# ---------------------------------------------------------------------------

def search_students(results: pd.DataFrame, query: str) -> pd.DataFrame:
    """
    Find students whose name or ID contains the search text.

    Matching ignores upper/lower case. An empty search returns everyone.
    """
    query = (query or "").strip()
    if not query or results.empty:
        return results

    name_match = results["student_name"].astype(str).str.contains(query, case=False, regex=False)
    id_match = results["student_id"].astype(str).str.contains(query, case=False, regex=False)
    return results[name_match | id_match].reset_index(drop=True)


def filter_by_percentage(results: pd.DataFrame, percentage=None, at_least: bool = False) -> pd.DataFrame:
    """
    Keep students with a given scholarship percentage.

    - percentage=None returns everyone.
    - at_least=False -> exactly that percentage (e.g. only 25%).
    - at_least=True  -> that percentage or more (e.g. 25% and 50%).
    """
    if percentage is None or results.empty:
        return results

    value = float(percentage)
    column = results["scholarship_percentage"]
    mask = column >= value if at_least else column == value
    if at_least:
        mask = mask & results["eligible"]  # never include "Not eligible" for 0%
    return results[mask].reset_index(drop=True)


def split_by_eligibility(results: pd.DataFrame):
    """Return (eligible_students, ineligible_students)."""
    if results.empty:
        return results, results
    eligible = results[results["eligible"]].reset_index(drop=True)
    ineligible = results[~results["eligible"]].reset_index(drop=True)
    return eligible, ineligible


def summarize(results: pd.DataFrame, rules: pd.DataFrame) -> dict:
    """
    Dashboard numbers: totals plus a count for every scholarship tier
    (including tiers with zero students, so the table never looks broken).
    """
    total = len(results)
    eligible = int(results["eligible"].sum()) if total else 0

    counts = []
    for _, rule in rules.iterrows():
        count = int((results["scholarship_name"] == rule["scholarship_name"]).sum()) if total else 0
        counts.append({
            "scholarship_name": rule["scholarship_name"],
            "minimum_cgpa": rule["minimum_cgpa"],
            "scholarship_percentage": rule["scholarship_percentage"],
            "students": count,
        })

    return {
        "total_students": total,
        "eligible_students": eligible,
        "ineligible_students": total - eligible,
        "counts_by_scholarship": pd.DataFrame(
            counts,
            columns=["scholarship_name", "minimum_cgpa", "scholarship_percentage", "students"],
        ),
    }


def explain_student_by_id(student_id: str, results: pd.DataFrame) -> dict:
    """Look up a student by ID in processed results and return their complete explainability record."""
    if results is None or results.empty or not student_id:
        return {}
    match = results[results["student_id"].astype(str).str.strip().str.upper() == str(student_id).strip().upper()]
    if match.empty:
        return {}
    return match.iloc[0].to_dict()


def simulate_policy(students: pd.DataFrame, custom_rules: pd.DataFrame) -> dict:
    """
    Evaluate valid students against alternative/hypothetical scholarship rules.
    Returns simulated results and comparison metrics against original baseline.
    Never alters original student data.
    """
    if students is None or students.empty:
        empty_res = pd.DataFrame(columns=RESULT_COLUMNS)
        return {
            "results": empty_res,
            "summary": summarize(empty_res, custom_rules),
        }
    sim_results = assign_scholarships(students, custom_rules)
    sim_summary = summarize(sim_results, custom_rules)
    return {
        "results": sim_results,
        "summary": sim_summary,
    }


def audit_data_quality(raw_students: pd.DataFrame, student_issues: pd.DataFrame) -> dict:
    """
    Generate an audit breakdown of data quality:
    - total_records: raw rows received
    - valid_records: rows successfully validated and processed
    - invalid_records: rows rejected
    - category breakdown: duplicates, missing values, non-numeric, out-of-range
    """
    total = len(raw_students) if raw_students is not None else 0
    invalid = len(student_issues) if student_issues is not None else 0
    valid = max(0, total - invalid)

    dup_count = missing_id = missing_name = missing_cgpa = non_numeric = out_of_bounds = 0
    if student_issues is not None and not student_issues.empty and "problem" in student_issues.columns:
        problems = student_issues["problem"].astype(str)
        dup_count = int(problems.str.contains("Duplicate", case=False).sum())
        missing_id = int(problems.str.contains("Missing student ID", case=False).sum())
        missing_name = int(problems.str.contains("Missing student name", case=False).sum())
        missing_cgpa = int(problems.str.contains("Missing CGPA", case=False).sum())
        non_numeric = int(problems.str.contains("not a number", case=False).sum())
        out_of_bounds = int(problems.str.contains("between 0 and 10", case=False).sum())

    return {
        "total_records": total,
        "valid_records": valid,
        "invalid_records": invalid,
        "duplicates_count": dup_count,
        "missing_values_count": missing_id + missing_name + missing_cgpa,
        "missing_id_count": missing_id,
        "missing_name_count": missing_name,
        "missing_cgpa_count": missing_cgpa,
        "non_numeric_cgpa_count": non_numeric,
        "out_of_bounds_cgpa_count": out_of_bounds,
    }


# ---------------------------------------------------------------------------
# 4. One call that runs the whole pipeline (used by app.py)
# ---------------------------------------------------------------------------

@dataclass
class EligibilityReport:
    results: pd.DataFrame        # every valid student with their scholarship
    rules: pd.DataFrame          # valid scholarship rules
    student_issues: pd.DataFrame  # rejected student rows and why
    rule_issues: pd.DataFrame     # rejected rule rows and why
    data_quality: dict = None    # structured data quality audit breakdown


def build_report(raw_students: pd.DataFrame, raw_rules: pd.DataFrame) -> EligibilityReport:
    """Validate both datasets, assign scholarships, and audit data quality."""
    students, student_issues = validate_students(raw_students)
    rules, rule_issues = validate_rules(raw_rules)
    results = assign_scholarships(students, rules)
    quality = audit_data_quality(raw_students, student_issues)
    return EligibilityReport(results, rules, student_issues, rule_issues, quality)

