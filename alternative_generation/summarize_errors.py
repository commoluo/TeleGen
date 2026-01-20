
import pandas as pd
import re
from collections import Counter
import argparse

def extract_error_type(message: str) -> str:
    """
    Extracts a standardized error type from a log message using a series of checks.
    """
    # Pre-compiled regex patterns for efficiency
    patterns = {
        re.compile(r"Cannot find module '([^']*)'"): "Cannot find module: {}",
        re.compile(r"Warning: ReactDOM.render is no longer supported in React 18"): "React 18 ReactDOM.render Warning",
        re.compile(r"Failed to load resource: the server responded with a status of (\d+ \([^)]*\))"): "HTTP Error: {}",
        re.compile(r"Failed to load resource: net::(ERR_\w+)"): "Network Error: {}",
        re.compile(r"⚠️ React Router Future Flag Warning: (.*)"): "React Router Future Flag Warning",
        re.compile(r"Uncaught TypeError: (.*)"): "Uncaught TypeError: {}",
        re.compile(r"Uncaught ReferenceError: (.*)"): "Uncaught ReferenceError: {}",
        re.compile(r"Uncaught SyntaxError: (.*)"): "Uncaught SyntaxError: {}",
    }

    for pattern, error_template in patterns.items():
        match = pattern.search(message)
        if match:
            # Use the matched group to make the error message more specific
            if "{}" in error_template:
                # For HTTP errors, the group might be "404 (Not Found)"
                # For module errors, it's the module name
                detail = match.group(1).strip()
                # Sanitize detail for better grouping, e.g., remove query strings
                if "HTTP Error" in error_template and "?" in detail:
                    detail = detail.split("?")[0]
                return error_template.format(detail)
            return error_template

    # Fallback for severe logs that don't match specific patterns
    if "SEVERE" in message:
        return "Uncategorized SEVERE Log"
        
    return "Uncategorized Log"

def analyze_logs(file_path):
    """
    Reads a CSV file, extracts error types from the 'message' column,
    and prints the frequency of each error type.
    """
    try:
        df = pd.read_csv(file_path)
    except FileNotFoundError:
        print(f"Error: The file '{file_path}' was not found.")
        return
    except Exception as e:
        print(f"An error occurred while reading the CSV file: {e}")
        return

    if 'message' not in df.columns:
        print("Error: CSV file must have a 'message' column.")
        return

    # Handle potential NaN values in the message column
    df['message'] = df['message'].fillna('')
    
    # Extract error types and count them
    error_types = [extract_error_type(msg) for msg in df['message']]
    error_counts = Counter(error_types)

    print("--- Full Error Report ---")
    if not error_counts:
        print("No errors found.")
        return
        
    # Sort by count descending
    sorted_errors = sorted(error_counts.items(), key=lambda item: item[1], reverse=True)
    
    for error, count in sorted_errors:
        print(f"{error}: {count}")
    print("-------------------------")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Summarize errors from an aggregated console log CSV file.")
    parser.add_argument("file_path", type=str, help="The path to the aggregated_console_logs.csv file.")
    args = parser.parse_args()
    
    analyze_logs(args.file_path)
