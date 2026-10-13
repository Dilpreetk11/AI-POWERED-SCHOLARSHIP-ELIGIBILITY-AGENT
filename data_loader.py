"""
data_loader.py - Reads raw data from CSV files.

This module ONLY reads data. It does not decide what is valid or who is
eligible; that is the job of eligibility.py.

Keeping loading separate means we can later add a Google Sheets loader
that returns the same kind of DataFrame, and nothing else in the app
needs to change.
"""

from pathlib import Path

import pandas as pd

# Folder that holds the sample CSV files (next to this file).
DATA_DIR = Path(__file__).parent / "data"
STUDENTS_FILE = DATA_DIR / "students.csv"
SCHOLARSHIPS_FILE = DATA_DIR / "scholarships.csv"


class DataLoadError(Exception):
    """Raised when a data file is missing or cannot be read."""


def load_csv(path) -> pd.DataFrame:
    """
    Read a CSV file and return it as a DataFrame.

    - Every column is read as text (dtype=str). Converting CGPA to a number
      happens during validation, so a bad value like "eleven" is reported
      clearly instead of crashing the program here.
    - Column names are trimmed and lower-cased, so " CGPA " still works.
    - A completely empty file returns an empty DataFrame.
    """
    path = Path(path)
    if not path.exists():
        raise DataLoadError(f"File not found: {path}")

    try:
        df = pd.read_csv(path, dtype=str)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()
    except (pd.errors.ParserError, UnicodeDecodeError) as error:
        raise DataLoadError(f"Could not read {path.name}: {error}") from error

    df.columns = [str(column).strip().lower() for column in df.columns]
    return df


def load_students(path=STUDENTS_FILE) -> pd.DataFrame:
    """Load raw student records (student_id, student_name, cgpa)."""
    return load_csv(path)


def load_scholarships(path=SCHOLARSHIPS_FILE) -> pd.DataFrame:
    """Load raw scholarship rules (scholarship_name, minimum_cgpa, scholarship_percentage)."""
    return load_csv(path)


def load_from_buffer(buffer, name: str = "uploaded file") -> pd.DataFrame:
    """
    Read a CSV from a file-like buffer, bytes, or string and return it as a DataFrame.

    Normalises column names (trimmed, lowercase) and keeps all columns as strings
    for safe upstream validation.
    """
    import io

    try:
        if isinstance(buffer, (bytes, bytearray)):
            buffer = io.BytesIO(buffer)
        elif isinstance(buffer, str):
            buffer = io.StringIO(buffer)
        df = pd.read_csv(buffer, dtype=str)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()
    except (pd.errors.ParserError, UnicodeDecodeError, ValueError) as error:
        raise DataLoadError(f"Could not parse {name}: {error}") from error

    df.columns = [str(column).strip().lower() for column in df.columns]
    return df

