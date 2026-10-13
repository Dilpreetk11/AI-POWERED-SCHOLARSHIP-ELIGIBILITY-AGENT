# Scholarship Eligibility Agent & AI Advisory System

An explainable, audit-grade Scholarship Eligibility Decision and Simulation Platform built with Python, Streamlit, and a tool-grounded AI Assistant.

> **Disclaimer**: The scholarship rules, student records, and thresholds in this project are fictional examples created for demonstration and testing purposes. They do not represent an official institutional policy.

---

## Architecture & System Overview

```
                          ┌───────────────────────────────┐
                          │   CSV Files / User Upload     │
                          │   (students.csv, custom.csv)  │
                          └──────────────┬────────────────┘
                                         │
                                         ▼
                                  data_loader.py
                                 (Raw text parse)
                                         │
                                         ▼
                                  eligibility.py
            ┌────────────────────────────┴────────────────────────────┐
            │                                                         │
            ▼                                                         ▼
   Validation & Audit Engine                               Explainable Decision Engine
   - Rejects missing ID / Name                             - Highest-tier assignment
   - Rejects non-numeric / out-of-range CGPA               - Cutoff margin (+/- calculation)
   - Flags all duplicate student IDs                       - Natural-language explanation
   - Generates issue row & CSV line #                      - Next tier trajectory & point gap
            │                                                         │
            └────────────────────────────┬────────────────────────────┘
                                         │
                   ┌─────────────────────┴─────────────────────┐
                   ▼                                           ▼
             assistant.py                                   app.py
    Tool-Grounded AI Assistant                   Interactive Streamlit Dashboard
    - Offline Deterministic Dispatcher           - Cohort metrics & qualification rate
    - Gemini Tool Calling (when API key set)     - Tier distribution charts
    - Zero hallucination (facts only)            - Student Inspector & multi-tier filter
                                                 - What-If Simulator (Candidate & Policy)
                                                 - Data Quality Audit log
```

### Separation of Concerns
1. **Rule Engine (`eligibility.py`)**: The deterministic source of truth. All eligibility calculations, thresholds, margins, and policy simulations are calculated here. No UI or LLM dependencies.
2. **Data Loader (`data_loader.py`)**: Pure I/O. Reads files or uploaded streams into DataFrames as text so malformed inputs are caught gracefully.
3. **AI Assistant (`assistant.py`)**: Grounded natural-language query interface. Dispatches queries to underlying Python functions to prevent hallucinations.
4. **Web Interface (`app.py`)**: Pure presentation layer. Renders metrics, charts, tables, interactive simulators, and chat UI.

---

## Key Features

### 1. Explainable Eligibility Engine
- Assigns students to **Gold** (≥ 9.00, 50%), **Silver** (≥ 8.00, 25%), or **Bronze** (≥ 7.00, 10%).
- For every candidate, computes:
  - **Required Cutoff**: The minimum CGPA needed for the awarded or closest tier.
  - **Cutoff Margin**: The exact signed delta (`cgpa - threshold`, e.g. `+0.45` or `-0.15`).
  - **Decision Logic**: A clear human-readable justification of the award.
  - **Next-Tier Trajectory**: Points needed to qualify for the next higher scholarship tier.
- Includes an interactive **Student Inspector** panel to view full decision breakdowns.

### 2. What-If Scholarship Simulator
- **Candidate Simulator**: Slide or enter any hypothetical CGPA (0.00 – 10.00) to see projected tier, margin, and trajectory without altering live records.
- **Cohort Policy Sensitivity Simulator**: Adjust hypothetical thresholds for Gold, Silver, and Bronze. The simulator computes the impact across all valid students, displaying a side-by-side comparison with the baseline.
- All simulations are non-destructive and clearly labeled as hypothetical.

### 3. Data Quality & Audit Reporting
- Comprehensive health metrics: Total Records, Valid Processed, Invalid Skipped, Duplicate Student IDs, Missing Values, and Non-numeric/Out-of-bounds CGPAs.
- Full diagnostic table identifying each rejected row, its original CSV line number, student ID, and the exact validation failure reason.

### 4. Grounded AI Natural-Language Assistant
- Dual-Execution Architecture:
  1. **Deterministic Tool Dispatcher (Offline / Default)**: Operates out-of-the-box with 0% hallucination. Directly parses and executes queries against the dataset.
  2. **Google Gemini LLM (Optional)**: Automatically activates when `GEMINI_API_KEY` is provided in `.env`. Calls registered tool functions to formulate verified answers.
- Sample questions supported:
  - *"How many students qualify for Gold?"*
  - *"Show students with CGPA between 8.0 and 9.0"*
  - *"Explain why student S001 qualifies for its scholarship"*
  - *"Which records contain invalid CGPA values?"*
  - *"Summarize the scholarship distribution"*
  - *"What scholarship does a CGPA of 8.45 get?"*

### 5. CSV File Upload
- Upload any custom student CSV directly from the sidebar.
- Performs column validation (`student_id`, `student_name`, `cgpa`) and runs the full audit pipeline before rendering.

---

## Datasets

- **`data/students.csv`**: Clean dataset expanded to 100 fictional student records with balanced distribution across Gold (26), Silver (28), Bronze (27), and Ineligible (19), including exact boundary test cases.
- **`data/students_with_errors.csv`**: Deliberately corrupted dataset testing 8 distinct validation errors:
  - Missing student ID
  - Missing student name
  - Missing CGPA
  - Non-numeric text CGPA (`"eleven"`)
  - Out-of-bounds CGPA (`10.5` and `-2.0`)
  - Duplicate student IDs (e.g., `S107` appearing twice; all copies rejected)
- **`data/scholarships.csv`**: Configurable scholarship rules table.

---

## Setup & Running Locally

### Prerequisites
- **Python 3.11+** (Python 3.11 or 3.12 recommended). Check with `python --version`.

### Installation

```powershell
# 1. Clone or navigate to the project directory
cd scholarship-agent

# 2. (Optional) Create and activate a virtual environment
python -m venv .venv
.venv\Scripts\Activate.ps1   # On Windows
# source .venv/bin/activate  # On Linux / macOS

# 3. Install dependencies
pip install -r requirements.txt
```

### Configuration (Optional for Gemini)
To enable Gemini LLM functionality in the AI Assistant:
1. Copy `.env.example` to `.env`:
   ```powershell
   cp .env.example .env
   ```
2. Edit `.env` and paste your Gemini API key:
   ```env
   GEMINI_API_KEY=your-actual-api-key-here
   ```
*If no key is configured, the assistant runs in deterministic tool dispatch mode.*

### Running the Application

```powershell
streamlit run app.py
```
Open [http://localhost:8501](http://localhost:8501) in your browser.

---

## Automated Test Suite

Run the full automated test suite with `pytest`:

```powershell
python -m pytest -v
```

### Test Coverage (69 Tests)
- **Explicit Threshold Boundaries**: Verifies exact behavior at `6.99`, `7.00`, `7.99`, `8.00`, `8.99`, `9.00`, and `10.00`.
- **Explainability Engine**: Verifies correct calculation of `required_threshold`, `threshold_diff`, explanation strings, and `next_tier`.
- **Policy Simulation**: Verifies hypothetical threshold recalculation without mutating base data.
- **Data Quality Audit**: Validates error taxonomy counts (duplicates, missing fields, out-of-bounds values).
- **Streamlit App Tests**: Uses Streamlit `AppTest` to verify metrics, filtering, tab navigation, and error handling without a browser.
- **AI Assistant Intent Dispatcher**: Verifies tool routing and parameter extraction for natural language queries.

---

## Project Structure

```
scholarship-agent/
├── app.py                  # Streamlit dashboard and user interface
├── eligibility.py          # Deterministic rule engine, explainability, simulation
├── assistant.py            # AI Natural Language Assistant (Tools + Gemini)
├── data_loader.py          # CSV & buffer file loader
├── data/
│   ├── students.csv            # 100 fictional student records
│   ├── students_with_errors.csv # Validation error test dataset
│   └── scholarships.csv        # Institutional rule definitions
├── tests/
│   ├── test_eligibility.py     # 63 unit tests (boundaries, explainability, audit, tools)
│   └── test_app.py             # 6 Streamlit UI integration tests
├── .streamlit/
│   └── config.toml             # Custom visual theme
├── pytest.ini              # Pytest path and runner configuration
├── requirements.txt        # Project dependencies
├── .env.example            # Environment variable template for Gemini
└── README.md               # Technical documentation
```
