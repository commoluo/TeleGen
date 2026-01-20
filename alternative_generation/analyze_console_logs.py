import argparse
import json
from pathlib import Path
import pandas as pd
import re

def analyze_logs(results_dir: Path):
    """
    Analyzes all console_logs.json files in a directory, aggregates the logs,
    and prints a summary.

    Args:
        results_dir: The path to the root directory containing the test results.
    """
    print(f"📊 Analyzing Console Logs in: {results_dir}")
    print("=" * 50)

    log_files = sorted(results_dir.rglob("console_logs.json"))

    if not log_files:
        print("No console_logs.json files found in the specified directory.")
        return

    all_logs = []
    log_counts = {}
    error_type_counts = {}

    for log_file in log_files:
        try:
            task_dir = log_file.parent
            project_dir = task_dir.parent
            project_name = project_dir.name
            task_name = task_dir.name

            if project_name not in log_counts:
                log_counts[project_name] = {'total': 0, 'SEVERE': 0, 'WARNING': 0, 'INFO': 0, 'other': 0, 'tasks': {}}

            with open(log_file, 'r', encoding='utf-8') as f:
                logs = json.load(f)

            task_log_count = len(logs)
            log_counts[project_name]['total'] += task_log_count
            log_counts[project_name]['tasks'][task_name] = {'count': task_log_count, 'logs': []}


            for log_entry in logs:
                level = log_entry.get("level", "UNKNOWN").upper()
                message = log_entry.get("message", "")

                if level == "SEVERE":
                    log_counts[project_name]['SEVERE'] += 1
                    error_type = extract_error_type(message)
                    error_type_counts[error_type] = error_type_counts.get(error_type, 0) + 1
                elif level == "WARNING":
                    log_counts[project_name]['WARNING'] += 1
                elif level == "INFO":
                    log_counts[project_name]['INFO'] += 1
                else:
                    log_counts[project_name]['other'] += 1
                
                all_logs.append({
                    "project": project_name,
                    "task": task_name,
                    "level": level,
                    "message": message,
                    "timestamp": log_entry.get("timestamp")
                })
                log_counts[project_name]['tasks'][task_name]['logs'].append(message)


        except json.JSONDecodeError:
            print(f"⚠️  Could not decode JSON from {log_file}")
        except Exception as e:
            print(f"❌ Error processing {log_file}: {e}")

    # Print summary
    total_logs_all_projects = 0
    for project, counts in log_counts.items():
        print(f"\n🔍 Project: {project} ({counts['total']} logs)")
        print("-" * 30)
        print(f"  - SEVERE: {counts['SEVERE']}")
        print(f"  - WARNING: {counts['WARNING']}")
        print(f"  - INFO: {counts['INFO']}")
        print(f"  - Other: {counts['other']}")
        # for task, task_data in counts['tasks'].items():
        #     if task_data['count'] > 0:
        #         print(f"    - Task: {task} ({task_data['count']} logs)")
        total_logs_all_projects += counts['total']

    print("\n" + "=" * 50)
    print("📈 Overall Summary")
    print("=" * 50)
    print(f"Total Projects Scanned: {len(log_counts)}")
    print(f"Total Log Files Found: {len(log_files)}")
    print(f"Total Log Entries: {total_logs_all_projects}")

    if error_type_counts:
        print("\n" + "=" * 50)
        print("🚨 SEVERE Error Type Analysis")
        print("=" * 50)
        sorted_errors = sorted(error_type_counts.items(), key=lambda item: item[1], reverse=True)
        for error_type, count in sorted_errors:
            print(f"  - {error_type}: {count} times")

    # Create a DataFrame and save to CSV
    if all_logs:
        df = pd.DataFrame(all_logs)
        output_csv = results_dir / "aggregated_console_logs.csv"
        df.to_csv(output_csv, index=False)
        print(f"\n📄 Aggregated logs saved to: {output_csv}")


def extract_error_type(message: str) -> str:
    """
    Extracts a standardized error type from a log message using a series of checks.
    """
    if not isinstance(message, str):
        return "Invalid Log Message"

    # Pattern matching for common JavaScript errors
    patterns = {
        # Specific Uncaught Errors
        r'Uncaught TypeError:': "TypeError",
        r'Uncaught ReferenceError:': "ReferenceError",
        r'Uncaught SyntaxError:': "SyntaxError",
        
        # Generic Uncaught Error (with refinement)
        r'Uncaught Error: Cannot find module': "Cannot find module",
        r'Uncaught Error:': "Uncaught Error (Generic)",

        # Module/Resource loading errors
        r'Cannot find module': "Cannot find module",
        r'Failed to load resource: the server responded with a status of (\d+)': "Failed to load resource (HTTP {})",
        r'Failed to load resource: net::ERR_CONNECTION_TIMED_OUT': "Network Error (Connection Timed Out)",
        r'Failed to load resource': "Failed to load resource (Generic)",

        # React specific warnings/errors
        r'Warning: ReactDOM.render is no longer supported': "React 18 ReactDOM.render Warning",
        r'Warning: Each child in a list should have a unique "key" prop': "React Missing Key Prop Warning",

        # Network & Other Errors
        r'net::ERR_CONNECTION_TIMED_OUT': "Network Error (Connection Timed Out)",
        r'favicon.ico': "Missing favicon.ico"
    }

    for pattern, error_type in patterns.items():
        match = re.search(pattern, message)
        if match:
            # If the pattern has a capture group (like for HTTP status), format it in.
            if '{}' in error_type:
                return error_type.format(match.group(1))
            return error_type

    return "Uncategorized SEVERE Log"




def main():
    parser = argparse.ArgumentParser(description="Analyze console logs from WebVoyager test results.")
    parser.add_argument(
        "results_dir",
        nargs="?",
        default=None,
        help="The path to the directory containing the test results. "
             "If not provided, it will search in common result locations."
    )
    args = parser.parse_args()

    if args.results_dir:
        results_path = Path(args.results_dir)
    else:
        # Default search paths if no directory is provided
        base_path = Path(__file__).parent
        potential_dirs = [
            base_path / "results_for_2_cycle" / "webvoyager_results_optimized",
            base_path / "results_for_2_cycle" / "webvoyager_results_unoptimized",
            base_path.parent / "webvoyager" / "webvoyager_results"
        ]
        for p in potential_dirs:
            if p.exists():
                results_path = p
                print(f"✅ Found results directory at: {results_path}")
                break
        else:
            print("❌ Could not find a default results directory. Please specify a path.")
            return

    if not results_path.is_dir():
        print(f"❌ Error: The specified path '{results_path}' is not a valid directory.")
        return

    analyze_logs(results_path)

if __name__ == "__main__":
    main()
