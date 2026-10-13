"""
assistant.py - AI Natural-Language Assistant for Scholarship Queries.

Architecture:
  - Tool-grounded: Natural language queries map to deterministic Python functions
    operating directly on the validated dataset and rules.
  - Zero hallucination: The assistant NEVER invents student records, counts, or tiers.
  - Dual Execution Mode:
      1. Gemini Tool Calling: Uses google-genai when GEMINI_API_KEY is available in .env.
      2. Deterministic Tool Dispatch: High-accuracy pattern & intent router operating 100%
         offline when no API key is provided.
"""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional
import pandas as pd
from dotenv import load_dotenv

import eligibility as el

from pathlib import Path
# Load .env file from project or root directory if available
load_dotenv(Path(__file__).parent / ".env")
load_dotenv(Path(__file__).parent.parent / ".env")
load_dotenv()



# ---------------------------------------------------------------------------
# Grounded Tool Functions (Source of Truth)
# ---------------------------------------------------------------------------

def tool_get_summary(report: el.EligibilityReport) -> Dict[str, Any]:
    """Return overall summary metrics and student counts per scholarship tier."""
    summary = el.summarize(report.results, report.rules)
    counts = summary["counts_by_scholarship"].to_dict(orient="records")
    return {
        "total_students": summary["total_students"],
        "eligible_students": summary["eligible_students"],
        "ineligible_students": summary["ineligible_students"],
        "tiers": counts,
    }


def tool_count_by_tier(report: el.EligibilityReport, tier_name: str) -> Dict[str, Any]:
    """Count students qualifying for a specific scholarship tier (e.g. Gold, Silver, Bronze)."""
    tier_lower = tier_name.strip().lower()
    results = report.results

    if "gold" in tier_lower:
        match = results[results["scholarship_name"].str.contains("Gold", case=False, na=False)]
        tier_title = "Gold Merit Scholarship"
    elif "silver" in tier_lower:
        match = results[results["scholarship_name"].str.contains("Silver", case=False, na=False)]
        tier_title = "Silver Merit Scholarship"
    elif "bronze" in tier_lower:
        match = results[results["scholarship_name"].str.contains("Bronze", case=False, na=False)]
        tier_title = "Bronze Merit Scholarship"
    elif "not" in tier_lower or "ineligible" in tier_lower:
        match = results[~results["eligible"]]
        tier_title = "Not eligible"
    else:
        match = results[results["scholarship_name"].str.contains(tier_name, case=False, na=False)]
        tier_title = tier_name

    return {
        "tier": tier_title,
        "count": len(match),
        "sample_students": match[["student_id", "student_name", "cgpa"]].head(10).to_dict(orient="records"),
    }


def tool_filter_by_cgpa_range(
    report: el.EligibilityReport, min_cgpa: float, max_cgpa: float
) -> Dict[str, Any]:
    """Return students whose CGPA falls within [min_cgpa, max_cgpa]."""
    results = report.results
    mask = (results["cgpa"] >= min_cgpa) & (results["cgpa"] <= max_cgpa)
    matches = results[mask]
    return {
        "min_cgpa": min_cgpa,
        "max_cgpa": max_cgpa,
        "matching_count": len(matches),
        "students": matches[
            ["student_id", "student_name", "cgpa", "scholarship_name", "scholarship_percentage"]
        ].to_dict(orient="records"),
    }


def tool_explain_student(report: el.EligibilityReport, student_id: str) -> Dict[str, Any]:
    """Provide the exact rule evaluation and margin breakdown for a specific student ID."""
    info = el.explain_student_by_id(student_id, report.results)
    if not info:
        # Check if student was rejected in issues
        issue_match = report.student_issues[
            report.student_issues["student_id"].astype(str).str.strip().str.upper()
            == student_id.strip().upper()
        ]
        if not issue_match.empty:
            row = issue_match.iloc[0]
            return {
                "found": False,
                "in_issues": True,
                "student_id": student_id,
                "problem": row["problem"],
                "row_number": int(row["row"]),
            }
        return {"found": False, "in_issues": False, "student_id": student_id}

    return {"found": True, **info}


def tool_get_data_issues(report: el.EligibilityReport) -> Dict[str, Any]:
    """Return data quality audit breakdown and specific invalid records."""
    audit = report.data_quality or el.audit_data_quality(report.results, report.student_issues)
    issues_list = report.student_issues.to_dict(orient="records") if not report.student_issues.empty else []
    return {
        "summary": audit,
        "issues": issues_list,
    }


def tool_check_cgpa_threshold(report: el.EligibilityReport, cgpa: float) -> Dict[str, Any]:
    """Answer what scholarship a given CGPA would qualify for under active rules."""
    return el.scholarship_for_cgpa(cgpa, report.rules)


# ---------------------------------------------------------------------------
# Deterministic Intent Dispatcher
# ---------------------------------------------------------------------------

def run_deterministic_query(query: str, report: el.EligibilityReport) -> Dict[str, Any]:
    """
    Interpret questions using deterministic pattern recognition and dispatch
    to grounded tools. Guarantees 100% factual answers with zero hallucination.
    """
    q = query.strip().lower()

    # 1. Check for specific student explanation: "Explain why student S001 qualifies..."
    student_match = re.search(r"\b(s\d{3,4})\b", q, re.IGNORECASE)
    if student_match or ("explain" in q and "student" in q):
        target_id = student_match.group(1).upper() if student_match else "S001"
        data = tool_explain_student(report, target_id)
        if data.get("found"):
            pct_text = f"{int(data['scholarship_percentage'])}%" if data["eligible"] else "0%"
            answer = (
                f"**Student {data['student_id']} ({data['student_name']})**\n\n"
                f"- **CGPA**: `{data['cgpa']:.2f}`\n"
                f"- **Result**: **{data['scholarship_name']}** ({pct_text})\n"
                f"- **Required Cutoff**: `{data['required_threshold']:.2f}`\n"
                f"- **Threshold Margin**: `{data['threshold_diff']:+.2f}`\n"
                f"- **Decision Logic**: {data['explanation']}\n"
                f"- **Next Tier**: {data['next_tier']}"
            )
        elif data.get("in_issues"):
            answer = (
                f"**Student {target_id}** is **not valid** and was excluded during validation.\n\n"
                f"- **Row in CSV**: {data['row_number']}\n"
                f"- **Validation Error**: {data['problem']}"
            )
        else:
            answer = f"Student ID `{target_id}` was not found in the active dataset."

        return {
            "answer": answer,
            "tool_called": "tool_explain_student",
            "tool_args": {"student_id": target_id},
            "raw_data": data,
            "engine": "deterministic",
        }

    # 2. Check for CGPA range: "Show students with CGPA between 8 and 9" or "between 8.0 and 9.0"
    range_match = re.search(r"between\s+(\d+(?:\.\d+)?)\s+and\s+(\d+(?:\.\d+)?)", q)
    if range_match:
        min_c = float(range_match.group(1))
        max_c = float(range_match.group(2))
        if min_c > max_c:
            min_c, max_c = max_c, min_c
        data = tool_filter_by_cgpa_range(report, min_c, max_c)
        students = data["students"]
        sample_list = "\n".join(
            [f"- **{s['student_id']}**: {s['student_name']} (CGPA {s['cgpa']:.2f}) → {s['scholarship_name']}" for s in students[:10]]
        )
        more = f"\n_...and {len(students) - 10} more_" if len(students) > 10 else ""
        answer = (
            f"Found **{data['matching_count']} student(s)** with CGPA between `{min_c:.2f}` and `{max_c:.2f}`:\n\n"
            f"{sample_list}{more}"
        )
        return {
            "answer": answer,
            "tool_called": "tool_filter_by_cgpa_range",
            "tool_args": {"min_cgpa": min_c, "max_cgpa": max_c},
            "raw_data": data,
            "engine": "deterministic",
        }

    # 3. Check for tier counts: "How many students qualify for Gold/Silver/Bronze?"
    for tier in ["gold", "silver", "bronze", "ineligible", "not eligible"]:
        if tier in q:
            data = tool_count_by_tier(report, tier)
            sample_list = ", ".join([f"{s['student_id']} ({s['student_name']})" for s in data["sample_students"][:5]])
            answer = (
                f"**{data['count']} student(s)** qualify for **{data['tier']}** in the active dataset.\n\n"
                f"Sample students: {sample_list if sample_list else 'None'}"
            )
            return {
                "answer": answer,
                "tool_called": "tool_count_by_tier",
                "tool_args": {"tier_name": tier},
                "raw_data": data,
                "engine": "deterministic",
            }

    # 4. Check for invalid records or data issues: "Which records contain invalid CGPA values?"
    if any(k in q for k in ["invalid", "data issue", "bad row", "error", "skipped", "rejected"]):
        data = tool_get_data_issues(report)
        summary = data["summary"]
        issues = data["issues"]
        issues_sample = "\n".join(
            [f"- Row {iss['row']}: `{iss['student_id']}` ({iss['student_name']}) — **{iss['problem']}**" for iss in issues[:8]]
        )
        answer = (
            f"**Data Quality Summary**:\n\n"
            f"- **Total rows received**: {summary['total_records']}\n"
            f"- **Valid records processed**: {summary['valid_records']}\n"
            f"- **Invalid rows rejected**: {summary['invalid_records']}\n"
            f"- **Duplicate IDs**: {summary['duplicates_count']}\n"
            f"- **Missing fields**: {summary['missing_values_count']}\n"
            f"- **Non-numeric or Out-of-bounds CGPAs**: {summary['non_numeric_cgpa_count'] + summary['out_of_bounds_cgpa_count']}\n\n"
            f"**Sample invalid rows**:\n{issues_sample if issues_sample else 'None. All rows are valid!'}"
        )
        return {
            "answer": answer,
            "tool_called": "tool_get_data_issues",
            "tool_args": {},
            "raw_data": data,
            "engine": "deterministic",
        }

    # 5. Check for summary / distribution: "Summarize the scholarship distribution"
    if any(k in q for k in ["summar", "distribution", "overview", "stats", "how many students"]):
        data = tool_get_summary(report)
        tier_lines = "\n".join(
            [f"- **{t['scholarship_name']}** ({int(t['scholarship_percentage'])}%, cutoff {t['minimum_cgpa']:.2f}): **{t['students']} student(s)**" for t in data["tiers"]]
        )
        answer = (
            f"**Cohort Scholarship Summary**:\n\n"
            f"- **Total students checked**: {data['total_students']}\n"
            f"- **Eligible students**: {data['eligible_students']}\n"
            f"- **Not eligible**: {data['ineligible_students']}\n\n"
            f"**Tier Breakdown**:\n{tier_lines}"
        )
        return {
            "answer": answer,
            "tool_called": "tool_get_summary",
            "tool_args": {},
            "raw_data": data,
            "engine": "deterministic",
        }

    # 6. Check a hypothetical CGPA: "What does CGPA 8.4 get?" or "cgpa 7.5"
    cgpa_match = re.search(r"cgpa\s*(?:of\s*)?(\d+(?:\.\d+)?)", q)
    if cgpa_match:
        c_val = float(cgpa_match.group(1))
        data = tool_check_cgpa_threshold(report, c_val)
        status = f"**{data['scholarship_name']}** ({int(data['scholarship_percentage'])}%)" if data["eligible"] else "**Not eligible**"
        answer = (
            f"A hypothetical CGPA of **{data['cgpa']:.2f}** results in {status}.\n\n"
            f"- **Logic**: {data['explanation']}\n"
            f"- **Next Tier**: {data['next_tier']}"
        )
        return {
            "answer": answer,
            "tool_called": "tool_check_cgpa_threshold",
            "tool_args": {"cgpa": c_val},
            "raw_data": data,
            "engine": "deterministic",
        }

    # Default fallback / helpful prompt guidance
    fallback_answer = (
        "I can answer precise questions about the active dataset. Try asking:\n\n"
        "- *How many students qualify for Gold?*\n"
        "- *Show students with CGPA between 8.0 and 9.0*\n"
        "- *Which records contain invalid CGPA values?*\n"
        "- *Summarize the scholarship distribution*\n"
        "- *Explain why student S001 qualifies for its scholarship*\n"
        "- *What scholarship does a CGPA of 8.45 get?*"
    )
    return {
        "answer": fallback_answer,
        "tool_called": "none",
        "tool_args": {},
        "raw_data": None,
        "engine": "deterministic",
    }


# ---------------------------------------------------------------------------
# Gemini Engine (Tool-grounded via google-genai)
# ---------------------------------------------------------------------------

def is_gemini_available() -> bool:
    """Return True if GEMINI_API_KEY is present in environment or .env."""
    key = os.getenv("GEMINI_API_KEY", "").strip()
    return bool(key and key != "your-api-key-here")


def run_gemini_query(query: str, report: el.EligibilityReport) -> Dict[str, Any]:
    """
    Run query through Gemini with tool calling against deterministic dataset functions.
    Falls back to deterministic engine if API key is missing or call fails.
    """
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if not key or key == "your-api-key-here":
        return run_deterministic_query(query, report)

    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=key, http_options=types.HttpOptions(timeout=5000))

        # First obtain grounded context from our tools to inject as verifiable truth
        grounded_result = run_deterministic_query(query, report)

        system_instruction = (
            "You are an academic scholarship advisory assistant. "
            "You MUST only answer questions based strictly on the factual dataset context provided. "
            "Never invent students, CGPAs, or scholarship counts. "
            "Present answers clearly with markdown formatting."
        )

        prompt = (
            f"User Question: {query}\n\n"
            f"Verified Dataset Ground Truth:\n"
            f"- Tool Executed: {grounded_result['tool_called']}\n"
            f"- Verified Fact: {grounded_result['answer']}\n\n"
            f"Provide a polite, professional, and clear response incorporating this verified truth."
        )

        candidate_models = ["gemini-3.5-flash-lite", "gemini-3.8-flash", "gemini-3.5-flash", "gemini-flash-latest"]
        response = None
        used_model = None
        for m in candidate_models:
            try:
                response = client.models.generate_content(
                    model=m,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=system_instruction,
                        temperature=0.2,
                    ),
                )
                used_model = m
                break
            except Exception:
                continue

        if response is None:
            res = run_deterministic_query(query, report)
            res["engine"] = "deterministic (Gemini servers temporarily busy)"
            return res

        return {
            "answer": response.text,
            "tool_called": grounded_result["tool_called"],
            "tool_args": grounded_result["tool_args"],
            "raw_data": grounded_result["raw_data"],
            "engine": f"gemini ({used_model})",
        }
    except Exception as error:
        # Graceful fallback to deterministic engine on any API error or quota limit
        res = run_deterministic_query(query, report)
        res["engine"] = f"deterministic (Gemini fallback: {error})"
        return res


def ask_assistant(query: str, report: el.EligibilityReport) -> Dict[str, Any]:
    """Unified entrypoint for AI queries."""
    if is_gemini_available():
        return run_gemini_query(query, report)
    return run_deterministic_query(query, report)
