"""
app.py - Upgraded Scholarship Eligibility Agent Dashboard.

Features:
  1. Deterministic Rule Engine & Explainability (Thresholds, Margins, Decision Logic).
  2. Dynamic Metrics & Scholarship Distribution Charts.
  3. Interactive Student Inspector & Search/Filter Engine.
  4. What-If Simulator (Individual Candidate & Cohort Policy Sensitivity).
  5. Comprehensive Data Quality Audit & Error Diagnostics.
  6. Grounded AI Natural Language Assistant (Dual: Deterministic Tool Dispatch + Gemini LLM).
  7. CSV Upload Support with Validation Summary.
"""

from pathlib import Path
import pandas as pd
import streamlit as st

import assistant
import data_loader
import eligibility as el

st.set_page_config(
    page_title="Scholarship Eligibility Agent",
    page_icon="🎓",
    layout="wide",
)

DATASETS = {
    "Sample students": data_loader.STUDENTS_FILE,
    "Sample with data errors": data_loader.DATA_DIR / "students_with_errors.csv",
}

TABLE_COLUMNS = {
    "student_id": st.column_config.TextColumn("Student ID"),
    "student_name": st.column_config.TextColumn("Name"),
    "cgpa": st.column_config.NumberColumn("CGPA", format="%.2f"),
    "scholarship_name": st.column_config.TextColumn("Scholarship"),
    "scholarship_percentage": st.column_config.NumberColumn("Scholarship %", format="%d%%"),
    "threshold_diff": st.column_config.NumberColumn("Margin (vs Cutoff)", format="%+.2f"),
    "explanation": st.column_config.TextColumn("Decision Explanation"),
}


def percent(value) -> str:
    """Show 25.0 as '25%' and 12.5 as '12.5%'."""
    return f"{float(value):g}%"


def show_table(df: pd.DataFrame, empty_message: str) -> None:
    """Show results table with explainability columns or helpful empty message."""
    if df.empty:
        st.info(empty_message)
        return
    cols = [col for col in TABLE_COLUMNS if col in df.columns]
    st.dataframe(
        df[cols],
        column_config=TABLE_COLUMNS,
        hide_index=True,
        width="stretch",
    )


# ---------------------------------------------------------------------------
# Sidebar: Dataset selection, CSV Upload, Rules & Quick Check
# ---------------------------------------------------------------------------

with st.sidebar:
    st.header("Data")
    dataset_options = list(DATASETS) + ["Upload custom CSV"]
    dataset_label = st.radio(
        "Student file",
        dataset_options,
        key="dataset",
        help="Switch to error file or upload your own CSV file to test validation.",
    )

    raw_students = None
    upload_file = None
    if dataset_label == "Upload custom CSV":
        upload_file = st.file_uploader("Upload student CSV", type=["csv"], key="csv_upload")
        if upload_file is not None:
            try:
                raw_students = data_loader.load_from_buffer(upload_file.getvalue(), name=upload_file.name)
                st.caption(f"Loaded {len(raw_students)} raw row(s) from `{upload_file.name}`")
            except Exception as e:
                st.error(f"Upload error: {e}")
                st.stop()
        else:
            st.info("Upload a CSV file containing columns: student_id, student_name, cgpa.")
            st.stop()
    else:
        try:
            raw_students = data_loader.load_students(DATASETS[dataset_label])
        except (data_loader.DataLoadError, ValueError) as error:
            st.error(f"The data could not be loaded: {error}")
            st.stop()

# Load rules and evaluate pipeline
try:
    raw_rules = data_loader.load_scholarships()
    report = el.build_report(raw_students, raw_rules)
except (data_loader.DataLoadError, ValueError) as error:
    st.error(f"The data could not be processed: {error}")
    st.stop()

results, rules = report.results, report.rules
summary = el.summarize(results, rules)

with st.sidebar:
    st.subheader("Scholarship rules")
    st.caption("Illustrative rules for this demo, not an official institutional policy.")
    for _, rule in rules.iterrows():
        st.markdown(f"**{percent(rule['scholarship_percentage'])}** · CGPA {rule['minimum_cgpa']:.2f} or above")

    st.divider()
    st.subheader("Check a CGPA")
    cgpa_input = st.number_input(
        "CGPA",
        min_value=0.0,
        max_value=10.0,
        value=8.5,
        step=0.01,
        format="%.2f",
        key="cgpa_check",
    )
    answer = el.scholarship_for_cgpa(cgpa_input, rules)
    if answer["eligible"]:
        st.success(
            f"A CGPA of {answer['cgpa']:.2f} qualifies for the {answer['scholarship_name']} "
            f"({percent(answer['scholarship_percentage'])})."
        )
    else:
        st.warning(f"A CGPA of {answer['cgpa']:.2f} does not qualify for any scholarship.")

    st.divider()
    st.caption("AI Assistant Status:")
    if assistant.is_gemini_available():
        st.badge("Gemini LLM Connected", icon="🤖")
    else:
        st.caption("Offline Deterministic Engine (Zero Hallucination). To enable Gemini, add `GEMINI_API_KEY` in `.env`.")


# ---------------------------------------------------------------------------
# Main Page: Dashboard Header & Cohort Metrics
# ---------------------------------------------------------------------------

st.title("Scholarship eligibility")
st.write(
    "See which students qualify for a merit scholarship based on their CGPA. "
    "Each student gets the highest tier they qualify for."
)

skipped = len(report.student_issues)
if skipped:
    st.warning(
        f"{skipped} student row(s) were skipped because of data problems. "
        "Open the **Data issues** tab to see what to fix."
    )
if not report.rule_issues.empty:
    st.warning(
        f"{len(report.rule_issues)} scholarship rule(s) were skipped because of data problems. "
        "Open the **Data issues** tab."
    )
if rules.empty:
    st.error("No valid scholarship rules were found, so no student can be marked eligible. Check data/scholarships.csv.")

# Metrics Row
m_col1, m_col2, m_col3, m_col4 = st.columns(4)
m_col1.metric("Students checked", summary["total_students"])
m_col2.metric("Eligible", summary["eligible_students"])
m_col3.metric("Not eligible", summary["ineligible_students"])
acceptance_rate = (
    f"{(summary['eligible_students'] / summary['total_students'] * 100):.1f}%"
    if summary["total_students"] > 0
    else "0%"
)
m_col4.metric("Qualification Rate", acceptance_rate)

# Distribution Chart & Table
counts = summary["counts_by_scholarship"]
if not counts.empty:
    st.subheader("Students per scholarship")
    chart_col, table_col = st.columns([1, 1])
    with chart_col:
        chart_data = counts.assign(tier=counts["scholarship_percentage"].map(percent))
        st.bar_chart(
            chart_data,
            x="tier",
            y="students",
            x_label="Scholarship",
            y_label="Students",
            horizontal=True,
            sort=False,
            color="#3A5A40",
            height=220,
        )
    with table_col:
        st.dataframe(
            counts[["scholarship_name", "scholarship_percentage", "students"]],
            column_config={
                "scholarship_name": st.column_config.TextColumn("Scholarship"),
                "scholarship_percentage": st.column_config.NumberColumn("Award", format="%d%%"),
                "students": st.column_config.NumberColumn("Students"),
            },
            hide_index=True,
            width="stretch",
        )


# ---------------------------------------------------------------------------
# Search and Filtering Engine
# ---------------------------------------------------------------------------

st.subheader("Find students")
search_col, tier_col, mode_col = st.columns([2, 1, 1])
query = search_col.text_input(
    "Search by name or student ID",
    placeholder="e.g. Sharma or S004",
    key="search",
)

tier_options = ["All scholarships"] + [percent(p) for p in rules["scholarship_percentage"]]
tier_choice = tier_col.selectbox("Scholarship", tier_options, key="tier")
match_mode = mode_col.radio(
    "Match",
    ["Exactly", "At least"],
    horizontal=True,
    key="match_mode",
    disabled=tier_choice == "All scholarships",
)

selected_percentage = None if tier_choice == "All scholarships" else float(tier_choice.rstrip("%"))
filtered = el.search_students(results, query)
filtered = el.filter_by_percentage(
    filtered, selected_percentage, at_least=(match_mode == "At least")
)
eligible, ineligible = el.split_by_eligibility(filtered)

no_match = "No students match this search. Try a different name or ID, or set the scholarship filter to All scholarships."


# ---------------------------------------------------------------------------
# Interactive Tabs: Roster, Data Issues, What-If Simulator & AI Assistant
# ---------------------------------------------------------------------------

tab_eligible, tab_ineligible, tab_issues, tab_simulator, tab_assistant = st.tabs([
    f"Eligible ({len(eligible)})",
    f"Not eligible ({len(ineligible)})",
    f"Data issues ({skipped + len(report.rule_issues)})",
    "What-If Simulator",
    "AI Assistant",
])

# Tab 1: Eligible Students
with tab_eligible:
    show_table(eligible, no_match)
    if not eligible.empty:
        with st.expander("🔍 Explain Student Eligibility Decision", expanded=False):
            student_choices = [
                f"{row['student_id']} - {row['student_name']} (CGPA {row['cgpa']:.2f})"
                for _, row in eligible.iterrows()
            ]
            picked = st.selectbox("Select student to inspect", student_choices, key="inspect_eligible")
            picked_id = picked.split(" - ")[0]
            info = el.explain_student_by_id(picked_id, results)
            if info:
                i1, i2, i3, i4 = st.columns(4)
                i1.metric("Student ID", info["student_id"])
                i2.metric("CGPA", f"{info['cgpa']:.2f}")
                i3.metric("Threshold Met", f"{info['required_threshold']:.2f}")
                i4.metric("Margin", f"{info['threshold_diff']:+.2f}")
                st.info(f"**Decision logic:** {info['explanation']}")
                st.caption(f"**Status for Higher Tier:** {info['next_tier']}")

# Tab 2: Ineligible Students
with tab_ineligible:
    if selected_percentage is not None:
        st.info("Not-eligible students are hidden while a scholarship filter is on. Choose All scholarships to see them.")
    else:
        show_table(ineligible, no_match if query else "Every student qualifies for at least one scholarship.")
        if not ineligible.empty:
            with st.expander("🔍 Explain Ineligibility Reason", expanded=False):
                student_choices = [
                    f"{row['student_id']} - {row['student_name']} (CGPA {row['cgpa']:.2f})"
                    for _, row in ineligible.iterrows()
                ]
                picked = st.selectbox("Select student to inspect", student_choices, key="inspect_ineligible")
                picked_id = picked.split(" - ")[0]
                info = el.explain_student_by_id(picked_id, results)
                if info:
                    i1, i2, i3, i4 = st.columns(4)
                    i1.metric("Student ID", info["student_id"])
                    i2.metric("CGPA", f"{info['cgpa']:.2f}")
                    i3.metric("Minimum Cutoff", f"{info['required_threshold']:.2f}")
                    i4.metric("Cutoff Gap", f"{info['threshold_diff']:+.2f}")
                    st.warning(f"**Decision logic:** {info['explanation']}")
                    st.caption(f"**Target to Qualify:** {info['next_tier']}")

# Tab 3: Data Quality & Issues Audit
with tab_issues:
    st.subheader("Data Quality Audit")
    dq = report.data_quality or el.audit_data_quality(raw_students, report.student_issues)

    q1, q2, q3, q4 = st.columns(4)
    q1.metric("Total Records Received", dq["total_records"])
    q2.metric("Valid Processed", dq["valid_records"])
    q3.metric("Invalid Skipped", dq["invalid_records"])
    q4.metric("Duplicate IDs", dq["duplicates_count"])

    st.caption(
        f"Missing Field Rows: **{dq['missing_values_count']}** | "
        f"Non-Numeric / Out-of-Bounds CGPAs: **{dq['non_numeric_cgpa_count'] + dq['out_of_bounds_cgpa_count']}**"
    )

    st.divider()
    if report.student_issues.empty and report.rule_issues.empty:
        st.success("No data problems found. Every student record and rule passed validation.")
    if not report.student_issues.empty:
        st.write("### Rejected Student Records")
        st.write("These rows were excluded from processing to safeguard data integrity. Line number refers to the CSV line.")
        st.dataframe(report.student_issues, hide_index=True, width="stretch")
    if not report.rule_issues.empty:
        st.write("### Rejected Scholarship Rules")
        st.dataframe(report.rule_issues, hide_index=True, width="stretch")

# Tab 4: What-If Simulator
with tab_simulator:
    st.subheader("What-If Scholarship Simulator")
    st.caption("Hypothetical simulation only — does not alter actual student records or baseline policies.")

    sim_tab1, sim_tab2 = st.tabs(["Candidate Simulator", "Cohort Policy Simulator"])

    with sim_tab1:
        st.markdown("#### Test a Hypothetical CGPA")
        sim_cgpa = st.slider(
            "Hypothetical CGPA",
            min_value=0.0,
            max_value=10.0,
            value=8.45,
            step=0.01,
            format="%.2f",
            key="sim_slider",
        )
        sim_res = el.scholarship_for_cgpa(sim_cgpa, rules)

        s_col1, s_col2, s_col3 = st.columns(3)
        s_col1.metric("Hypothetical CGPA", f"{sim_cgpa:.2f}")
        s_col2.metric("Projected Award", sim_res["scholarship_name"])
        s_col3.metric("Award Percentage", percent(sim_res["scholarship_percentage"]))

        if sim_res["eligible"]:
            st.success(f"**Explanation:** {sim_res['explanation']}")
        else:
            st.warning(f"**Explanation:** {sim_res['explanation']}")
        st.info(f"**Next Tier Trajectory:** {sim_res['next_tier']}")

    with sim_tab2:
        st.markdown("#### Policy Threshold Sensitivity Analysis")
        st.write(
            "Simulate what happens to the current valid student cohort if institutional thresholds are modified."
        )

        p_col1, p_col2, p_col3 = st.columns(3)
        sim_gold = p_col1.slider("Gold Minimum CGPA", 8.5, 9.5, 9.0, 0.05, key="sim_gold")
        sim_silver = p_col2.slider("Silver Minimum CGPA", 7.5, 8.5, 8.0, 0.05, key="sim_silver")
        sim_bronze = p_col3.slider("Bronze Minimum CGPA", 6.5, 7.5, 7.0, 0.05, key="sim_bronze")

        custom_rules = pd.DataFrame([
            {"scholarship_name": "Gold Merit Scholarship", "minimum_cgpa": sim_gold, "scholarship_percentage": 50.0},
            {"scholarship_name": "Silver Merit Scholarship", "minimum_cgpa": sim_silver, "scholarship_percentage": 25.0},
            {"scholarship_name": "Bronze Merit Scholarship", "minimum_cgpa": sim_bronze, "scholarship_percentage": 10.0},
        ])

        sim_output = el.simulate_policy(results[el.STUDENT_COLUMNS], custom_rules)
        sim_summary = sim_output["summary"]

        base_eligible = summary["eligible_students"]
        sim_eligible = sim_summary["eligible_students"]
        delta_eligible = sim_eligible - base_eligible

        st.metric(
            label="Total Projected Eligible Students",
            value=sim_eligible,
            delta=f"{delta_eligible:+d} vs baseline",
        )

        st.write("##### Projected Tier Breakdown")
        comp_df = pd.DataFrame({
            "Scholarship": [
                "Gold Merit Scholarship",
                "Silver Merit Scholarship",
                "Bronze Merit Scholarship",
                "Not eligible",
            ],
            "Threshold": [f"≥ {sim_gold:.2f}", f"≥ {sim_silver:.2f}", f"≥ {sim_bronze:.2f}", f"< {sim_bronze:.2f}"],
            "Baseline Count": [
                int((results["scholarship_name"] == "Gold Merit Scholarship").sum()),
                int((results["scholarship_name"] == "Silver Merit Scholarship").sum()),
                int((results["scholarship_name"] == "Bronze Merit Scholarship").sum()),
                int((~results["eligible"]).sum()),
            ],
            "Simulated Count": [
                int((sim_output["results"]["scholarship_name"] == "Gold Merit Scholarship").sum()),
                int((sim_output["results"]["scholarship_name"] == "Silver Merit Scholarship").sum()),
                int((sim_output["results"]["scholarship_name"] == "Bronze Merit Scholarship").sum()),
                int((~sim_output["results"]["eligible"]).sum()),
            ],
        })
        comp_df["Net Difference"] = comp_df["Simulated Count"] - comp_df["Baseline Count"]
        st.dataframe(comp_df, hide_index=True, width="stretch")

# Tab 5: AI Assistant
with tab_assistant:
    st.subheader("AI Scholarship Assistant")
    st.write(
        "Ask questions in natural language. The assistant queries the actual dataset using verified Python tools."
    )

    # Preset quick-prompt buttons
    st.write("##### Suggested Queries:")
    quick_col1, quick_col2 = st.columns(2)
    with quick_col1:
        if st.button("How many students qualify for Gold?", key="qp_gold"):
            st.session_state["ai_query"] = "How many students qualify for Gold?"
        if st.button("Show students with CGPA between 8.0 and 9.0", key="qp_range"):
            st.session_state["ai_query"] = "Show students with CGPA between 8.0 and 9.0"
        if st.button("Explain why student S001 qualifies for its scholarship", key="qp_s001"):
            st.session_state["ai_query"] = "Explain why student S001 qualifies for its scholarship"
    with quick_col2:
        if st.button("Which records contain invalid CGPA values?", key="qp_invalid"):
            st.session_state["ai_query"] = "Which records contain invalid CGPA values?"
        if st.button("Summarize the scholarship distribution", key="qp_summary"):
            st.session_state["ai_query"] = "Summarize the scholarship distribution"
        if st.button("What scholarship does a CGPA of 8.45 get?", key="qp_sim"):
            st.session_state["ai_query"] = "What scholarship does a CGPA of 8.45 get?"

    user_query = st.text_input(
        "Your Question",
        value=st.session_state.get("ai_query", ""),
        placeholder="e.g. How many students qualify for Gold?",
        key="assistant_input",
    )

    if user_query:
        with st.spinner("Analyzing dataset..."):
            res = assistant.ask_assistant(user_query, report)
            st.markdown(res["answer"])
            with st.expander("🛠️ Execution Details (Deterministic Grounding)", expanded=False):
                st.json({
                    "Engine": res["engine"],
                    "Tool Invoked": res["tool_called"],
                    "Parameters": res["tool_args"],
                })
