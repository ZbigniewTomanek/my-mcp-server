import contextlib
import io
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Optional, List, Dict, Any

# --- Marker library imports with robust mocks ---
try:
    from marker.converters.pdf import PdfConverter
    from marker.models import create_model_dict
    from marker.output import text_from_rendered
except ImportError:
    # More informative warning
    print("Warning: marker library not found. Using mock functions for fetch_page that will return clear errors.")


    def create_model_dict():
        return {}


    def text_from_rendered(rendered):
        if rendered == "mock rendered object":
            return "[MOCK] This is simulated text content from a PDF. The marker library is not installed.", None, []
        return f"Error: Mock text extraction failed. The marker library is not installed and the mock received: {rendered}", None, []


    class PdfConverter:
        def __init__(self, *args, **kwargs):
            pass

        def __call__(self, path):
            if Path(path).exists():
                return "mock rendered object"
            return f"mock render error: File not found {path}"

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("zbigniew-mcp")


# --- Utility Functions ---

def _find_browser_command():
    """Find an installed browser command for headless operations."""
    browsers = ["chromium", "chrome", "google-chrome", "chromium-browser"]
    for browser in browsers:
        try:
            result = subprocess.run(
                [browser, "--version"],
                capture_output=True,
                check=False,
                timeout=2  # Short timeout for version check
            )
            if result.returncode == 0:
                return browser
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
    return None


@mcp.tool(
    description="""
    Execute a shell command safely and return the complete results including stdout, stderr, and exit code.

    Two execution modes are supported:
    1. Secure mode (default): Provide the command as a list of strings (e.g., ["ls", "-la"])
    2. Shell mode: Provide a shell_command string (e.g., "ls -la && grep foo bar.txt") when shell operators are needed

    Examples:
    - List files (secure): execute_shell_command(command=["ls", "-la"])
    - List files and count them (shell): execute_shell_command(shell_command="ls -la | wc -l")
    - Chain commands: execute_shell_command(shell_command="cd /tmp && ls -la")
    - Conditional execution: execute_shell_command(shell_command="grep 'error' log.txt || echo 'No errors found'")

    Security note: shell_command mode is more powerful but vulnerable to injection if used with untrusted input.
    Always use command list mode when processing any external/user input.

    Returns a dictionary containing stdout, stderr, exit_code, the executed command string, and a boolean success flag.
    """,
)
def execute_shell_command(
        command: Optional[list[str]] = None,
        shell_command: Optional[str] = None,
        timeout: int = 60,
        working_dir: Optional[str] = None
) -> dict:
    """Executes a command with support for both secure list mode and shell operator mode."""
    # Validate that exactly one of command or shell_command is provided
    if (command is None and shell_command is None) or (command is not None and shell_command is not None):
        return {
            "stdout": "",
            "stderr": "Error: Exactly one of 'command' or 'shell_command' must be provided.",
            "exit_code": -1,
            "command": str(command) if command is not None else str(shell_command),
            "success": False
        }

    # Secure mode with command list
    if command is not None:
        # Validate command is a list of strings
        if not isinstance(command, list) or not all(isinstance(arg, str) for arg in command):
            return {
                "stdout": "",
                "stderr": "Error: 'command' must be provided as a list of strings.",
                "exit_code": -1,
                "command": str(command),
                "success": False
            }

        # Validate command is not empty
        if not command:
            return {
                "stdout": "",
                "stderr": "Error: Command list cannot be empty.",
                "exit_code": -1,
                "command": "[]",
                "success": False
            }

        # Execute in secure mode with shell=False
        use_shell = False
        command_to_execute = command
        command_str = " ".join(command)

    # Shell mode with string command
    else:
        # Validate shell_command is a non-empty string
        if not isinstance(shell_command, str) or not shell_command.strip():
            return {
                "stdout": "",
                "stderr": "Error: 'shell_command' must be a non-empty string.",
                "exit_code": -1,
                "command": str(shell_command),
                "success": False
            }

        # Execute in shell mode with shell=True
        use_shell = True
        command_to_execute = shell_command
        command_str = shell_command

    # Ensure working_dir exists if provided
    if working_dir:
        work_dir_path = Path(working_dir)
        if not work_dir_path.exists():
            return {
                "stdout": "",
                "stderr": f"Error: Working directory '{working_dir}' does not exist.",
                "exit_code": -1,
                "command": command_str,
                "success": False
            }
        if not work_dir_path.is_dir():
            return {
                "stdout": "",
                "stderr": f"Error: Path '{working_dir}' is not a directory.",
                "exit_code": -1,
                "command": command_str,
                "success": False
            }

    try:
        result = subprocess.run(
            command_to_execute,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            cwd=working_dir,
            text=True,
            shell=use_shell,
            check=False  # Don't raise exception on non-zero exit code
        )

        return {
            "stdout": result.stdout,
            "stderr": result.stderr,
            "exit_code": result.returncode,
            "command": command_str,
            "success": result.returncode == 0
        }
    except subprocess.TimeoutExpired:
        return {
            "stdout": "",
            "stderr": f"Command timed out after {timeout} seconds.",
            "exit_code": 124,  # Standard timeout exit code
            "command": command_str,
            "success": False
        }
    except FileNotFoundError:
        command_name = command[0] if command is not None else "the specified command"
        return {
            "stdout": "",
            "stderr": f"Error: Command not found: '{command_name}'. Check if it's installed and in PATH.",
            "exit_code": 127,  # Standard command not found exit code
            "command": command_str,
            "success": False
        }
    except PermissionError as e:
        command_name = command[0] if command is not None else "the specified command"
        return {
            "stdout": "",
            "stderr": f"Error: Permission denied executing '{command_name}'. Details: {str(e)}",
            "exit_code": 126,  # Standard permission denied exit code
            "command": command_str,
            "success": False
        }
    except Exception as e:
        error_type = type(e).__name__
        return {
            "stdout": "",
            "stderr": f"An unexpected error occurred executing command: {error_type}: {str(e)}",
            "exit_code": -1,
            "command": command_str,
            "success": False
        }

@mcp.tool(
    description="""
    Show contents of a file with options to display specific line ranges (1-based indexing).

    Examples:
    - Show entire file: show_file(file_path="/path/to/file.txt")
    - Show first 10 lines: show_file(file_path="/path/to/file.txt", num_lines=10)
    - Show lines 5-15: show_file(file_path="/path/to/file.txt", start_line=5, end_line=15)
    - Show last 10 lines: show_file(file_path="/path/to/file.txt", start_line=-10)

    Note: `end_line` takes precedence over `num_lines` if both are provided.
    Negative `start_line` counts from the end of the file.

    Returns the content as a string and detailed information about the lines shown and total lines.
    """,
)
def show_file(
        file_path: str,
        start_line: int = 1,
        num_lines: Optional[int] = None,
        end_line: Optional[int] = None
) -> dict:
    """Displays content of a file with flexible line range specification."""
    path = Path(file_path)

    # Validate file exists and is a file
    if not path.exists():
        return {
            "success": False,
            "error": f"File not found: {file_path}",
            "content": "",
            "lines_shown": 0,
            "total_lines": 0,
            "requested_range": f"start={start_line}, num={num_lines}, end={end_line}"
        }

    if not path.is_file():
        return {
            "success": False,
            "error": f"Path exists but is not a regular file: {file_path}",
            "content": "",
            "lines_shown": 0,
            "total_lines": 0,
            "requested_range": f"start={start_line}, num={num_lines}, end={end_line}"
        }

    try:
        # Try different encodings for better file compatibility
        try:
            all_lines = path.read_text(encoding='utf-8').splitlines()
        except UnicodeDecodeError:
            try:
                all_lines = path.read_text(encoding='latin-1').splitlines()
            except Exception as enc_e:
                return {
                    "success": False,
                    "error": f"Error reading file with UTF-8 or Latin-1 encoding: {type(enc_e).__name__}: {str(enc_e)}",
                    "content": "",
                    "lines_shown": 0,
                    "total_lines": -1,
                    "requested_range": f"start={start_line}, num={num_lines}, end={end_line}"
                }

        total_lines = len(all_lines)

        # Handle case where file is empty
        if total_lines == 0:
            return {
                "success": True,
                "content": "",
                "lines_shown": 0,
                "total_lines": 0,
                "start_line_actual": None,
                "end_line_actual": None,
                "info": "File is empty"
            }

        # Handle negative start_line (counts from end)
        if start_line < 0:
            start_line = total_lines + start_line + 1

        # Ensure start_line is at least 1 (1-based indexing)
        start_line = max(1, start_line)

        # Determine the effective end line
        effective_end_line = total_lines
        if end_line is not None:
            if end_line < 0:  # Negative end_line counts from the end
                effective_end_line = total_lines + end_line + 1
            else:
                effective_end_line = min(end_line, total_lines)
            # End cannot be before start
            effective_end_line = max(start_line - 1, effective_end_line)
        elif num_lines is not None and num_lines >= 0:
            effective_end_line = min(start_line + num_lines - 1, total_lines)

        effective_end_line = max(1, effective_end_line)  # Ensure end line is at least 1

        # Adjust start_line if it's beyond file length after potential negative indexing calc
        if start_line > total_lines:
            # Special case: asking for lines beyond the end
            return {
                "success": True,  # Technically successful read, just no content in range
                "content": "",
                "lines_shown": 0,
                "total_lines": total_lines,
                "start_line_actual": start_line,
                "end_line_actual": effective_end_line,
                "info": f"Requested start line {start_line} is beyond the file length ({total_lines} lines)."
            }

        # Convert to 0-based indexing for slicing
        start_idx = start_line - 1
        # End index for slicing is exclusive in Python
        end_idx = effective_end_line

        # Ensure start index is not greater than end index
        if start_idx >= end_idx:
            selected_lines = []
        else:
            selected_lines = all_lines[start_idx:end_idx]

        content = "\n".join(selected_lines)

        return {
            "success": True,
            "content": content,
            "lines_shown": len(selected_lines),
            "total_lines": total_lines,
            "start_line_actual": start_line,  # The calculated start line (1-based)
            "end_line_actual": start_idx + len(selected_lines)  # The actual last line number shown (1-based)
        }
    except IOError as e:
        return {
            "success": False,
            "error": f"IO error reading file: {type(e).__name__}: {str(e)}",
            "content": "",
            "lines_shown": 0,
            "total_lines": -1
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Error reading or processing file: {type(e).__name__}: {str(e)}",
            "content": "",
            "lines_shown": 0,
            "total_lines": -1
        }


@mcp.tool(
    description="""
    Search for a Python regular expression pattern within a file.

    Returns lines matching the pattern, along with their line numbers (1-based).

    Parameters:
    - file_path: Path to the file to search.
    - pattern: Python regular expression string.
    - case_sensitive: Perform case-sensitive matching (default: True).
    - max_matches: Limit the number of returned matches (default: 100, use -1 for unlimited).
    - context_lines: Include N lines of context before and after each match (default: 0).

    Examples:
    - Find 'TODO' comments (case-insensitive): search_in_file("code.py", r"#\\s*TODO", case_sensitive=False)
    - Find function definitions with 1 line context: search_in_file("script.py", r"^def\\s+\\w+", context_lines=1)

    Returns a list of matches, each containing line number, content, and optional context.
    """,
)
def search_in_file(
        file_path: str,
        pattern: str,
        case_sensitive: bool = True,
        max_matches: int = 100,
        context_lines: int = 0
) -> dict:
    """Searches for regex patterns in a file, returning matches with optional context."""
    path = Path(file_path)

    # Validate file exists and is a file
    if not path.exists():
        return {
            "success": False,
            "error": f"File not found: {file_path}",
            "matches": [],
            "total_matches_found": 0,
            "truncated": False
        }

    if not path.is_file():
        return {
            "success": False,
            "error": f"Path exists but is not a regular file: {file_path}",
            "matches": [],
            "total_matches_found": 0,
            "truncated": False
        }

    try:
        # Validate and compile the regex pattern
        try:
            flags = 0 if case_sensitive else re.IGNORECASE
            regex = re.compile(pattern, flags)
        except re.error as re_err:
            return {
                "success": False,
                "error": f"Invalid regular expression '{pattern}': {str(re_err)}",
                "matches": [],
                "total_matches_found": 0,
                "truncated": False
            }

        # Read the file lines with encoding handling
        try:
            all_lines = path.read_text(encoding='utf-8').splitlines()
        except UnicodeDecodeError:
            try:
                all_lines = path.read_text(encoding='latin-1').splitlines()
            except Exception as enc_e:
                return {
                    "success": False,
                    "error": f"Error reading file with UTF-8 or Latin-1 encoding: {type(enc_e).__name__}: {str(enc_e)}",
                    "matches": [],
                    "total_matches_found": 0,
                    "truncated": False
                }

        matches_found = []
        total_lines = len(all_lines)
        match_limit = max_matches if max_matches > 0 else float('inf')
        i = 0  # Define i outside the loop for later use

        for i, line in enumerate(all_lines):
            if len(matches_found) >= match_limit:
                break

            if regex.search(line):
                match_info = {
                    "line_number": i + 1,  # 1-based line numbering
                    "content": line
                }

                # Add context if requested
                if context_lines > 0:
                    start_context = max(0, i - context_lines)
                    end_context = min(total_lines, i + context_lines + 1)

                    # Only include context if available
                    if start_context < i:
                        match_info["context_before"] = all_lines[start_context:i]

                    if i + 1 < end_context:
                        match_info["context_after"] = all_lines[i + 1:end_context]

                matches_found.append(match_info)

        # If we stopped due to max_matches, count remaining matches
        actual_total_matches_found = len(matches_found)
        truncated = False

        if max_matches > 0 and len(matches_found) >= max_matches and i + 1 < total_lines:
            # Continue counting without storing the matches
            for remaining_i in range(i + 1, total_lines):
                if regex.search(all_lines[remaining_i]):
                    actual_total_matches_found += 1

            truncated = actual_total_matches_found > len(matches_found)

        return {
            "success": True,
            "matches": matches_found,
            "total_matches_found": actual_total_matches_found,
            "matches_returned": len(matches_found),
            "truncated": truncated
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Error searching file: {type(e).__name__}: {str(e)}",
            "matches": [],
            "total_matches_found": 0,
            "truncated": False
        }


@mcp.tool(
    description="""
    Atomically edits a file using string replacements and/or line-based operations.

    Provides a summary of changes and a simplified log of operations attempted and their success status.
    Operations are applied sequentially: first all string replacements, then all line operations.
    Line numbers for line operations refer to the state *after* string replacements but *before* subsequent line operations within the same call.

    Parameters:
    - file_path: Path to the file to edit.
    - replacements: Optional dictionary { "find_string": "replace_string", ... }. Replaces all occurrences.
    - line_operations: Optional list of dictionaries for line-specific changes. Operations:
        - {"operation": "insert", "line": N, "content": "text" or ["line1", "line2"]} (Insert before line N, 1-based)
        - {"operation": "replace", "line": N, "content": "new text"} (Replace line N, 1-based)
        - {"operation": "delete", "start_line": N, "end_line": M} (Delete lines N to M inclusive, 1-based)
    - create_if_missing: If True, create the file (and parent directories) if it doesn't exist (default: False).

    Examples:
    - Replace 'foo' with 'bar': edit_file("file.txt", replacements={"foo": "bar"})
    - Insert at line 1: edit_file("script.py", line_operations=[{"operation": "insert", "line": 1, "content": "#!/usr/bin/env python3"}])
    - Delete line 5: edit_file("config.yaml", line_operations=[{"operation": "delete", "start_line": 5, "end_line": 5}])
    - Combined: edit_file("file.txt", replacements={"old": "new"}, line_operations=[{"operation":"delete", "start_line":3, "end_line":3}])

    Returns a dictionary containing success status, file info, a summary of changes (counts of operations),
    a simplified log detailing each operation's outcome, and a preview of the final content.
    """,
)
def edit_file(
        file_path: str,
        replacements: Optional[Dict[str, str]] = None,
        line_operations: Optional[List[Dict[str, Any]]] = None,
        create_if_missing: bool = False
) -> dict:
    """Atomically edits a file using string replacements and/or line operations with simplified feedback."""
    path = Path(file_path)
    operation_log = []
    # Initialize summary statistics
    summary_stats = {
        "string_replacements_attempted": 0,
        "string_replacements_made": 0,  # Number of replacements that actually changed the content
        "line_inserts_attempted": 0,
        "line_inserts_made": 0,  # Number of lines actually inserted
        "line_replaces_attempted": 0,
        "line_replaces_made": 0,  # Number of replaces that actually changed content
        "line_deletes_attempted": 0,
        "line_deletes_made": 0,  # Number of lines actually deleted
        "operations_failed": 0,
        "file_created": False,
    }
    change_occurred = False
    original_content = ""
    original_size = -1
    encoding_used = 'utf-8'  # Default

    # --- File Existence Check ---
    if not path.exists():
        if create_if_missing:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("", encoding=encoding_used)  # Create empty file
                original_content = ""
                original_size = 0
                summary_stats["file_created"] = True
                operation_log.append({"operation": "create_file", "path": str(path), "success": True})
                # No need to mark change_occurred=True for creation, only for content modification
            except Exception as e:
                summary_stats["operations_failed"] += 1
                return {
                    "success": False,
                    "error": f"Failed to create file {path}: {type(e).__name__}: {str(e)}",
                    "change_occurred": False,
                    "summary": summary_stats,
                    "operations_log": operation_log
                }
        else:
            summary_stats["operations_failed"] += 1
            return {
                "success": False,
                "error": f"File not found: {path}",
                "change_occurred": False,
                "summary": summary_stats,
                "operations_log": []  # No ops attempted yet
            }
    elif not path.is_file():
        summary_stats["operations_failed"] += 1
        return {
            "success": False,
            "error": f"Path exists but is not a regular file: {path}",
            "change_occurred": False,
            "summary": summary_stats,
            "operations_log": []
        }

    # --- Read Original Content ---
    read_success = False
    try:
        try:
            original_content = path.read_text(encoding='utf-8')
            encoding_used = 'utf-8'
            read_success = True
        except UnicodeDecodeError:
            try:
                original_content = path.read_text(encoding='latin-1')
                encoding_used = 'latin-1'
                read_success = True
                operation_log.append({
                    "operation": "read_file", "success": True, "warning": "Read using latin-1 encoding"
                })
            except Exception as enc_e:
                raise IOError(f"Error reading file with UTF-8 or Latin-1: {str(enc_e)}") from enc_e
        if read_success and encoding_used == 'utf-8':  # Avoid duplicate log if warning already added
            operation_log.append({
                "operation": "read_file", "success": True, "encoding": encoding_used
            })

        original_size = len(original_content)
        modified_content = original_content
        modified_lines = original_content.splitlines()

    except Exception as e:
        summary_stats["operations_failed"] += 1
        operation_log.append({"operation": "read_file", "success": False, "error": str(e)})
        return {
            "success": False,
            "error": f"Error reading file {path}: {type(e).__name__}: {str(e)}",
            "change_occurred": False,
            "summary": summary_stats,
            "operations_log": operation_log
        }

    # --- Apply Operations ---
    try:
        # 1. String Replacements
        if replacements:
            content_before_replacements = modified_content
            for old, new in replacements.items():
                summary_stats["string_replacements_attempted"] += 1
                count = modified_content.count(old)
                op_log_entry = {
                    "operation": "replace_string",
                    "old_string_preview": old[:50] + ('...' if len(old) > 50 else ''),  # Keep preview short
                    "new_string_preview": new[:50] + ('...' if len(new) > 50 else ''),
                    "success": count > 0,
                    "count": count
                }
                if count > 0:
                    modified_content = modified_content.replace(old, new)
                    # Actual change count happens after all replacements in this block
                operation_log.append(op_log_entry)

            if modified_content != content_before_replacements:
                summary_stats["string_replacements_made"] = summary_stats[
                    "string_replacements_attempted"]  # Simplification: assume all attempts contributed if final content changed
                change_occurred = True
                modified_lines = modified_content.splitlines()  # Update lines based on global replacements

        # 2. Line Operations
        if line_operations:
            # --- Pre-validation of line operations (simplified) ---
            valid_operations = []
            for i, op in enumerate(line_operations):
                if not isinstance(op, dict) or "operation" not in op:
                    operation_log.append({
                        "operation": "validate_operation",
                        "index": i,
                        "success": False,
                        "error": "Invalid format or missing 'operation' key"
                    })
                    summary_stats["operations_failed"] += 1
                    continue  # Skip invalid operation structure

                op_type = op.get("operation", "").lower()
                if op_type not in ["insert", "replace", "delete"]:
                    operation_log.append({
                        "operation": "validate_operation",
                        "index": i,
                        "type": op_type,
                        "success": False,
                        "error": "Invalid operation type"
                    })
                    summary_stats["operations_failed"] += 1
                    continue

                # Basic check for required line keys (further checks during execution)
                if op_type in ["insert", "replace"] and "line" not in op:
                    operation_log.append(
                        {"operation": "validate_operation", "index": i, "type": op_type, "success": False,
                         "error": "Missing 'line'"})
                    summary_stats["operations_failed"] += 1
                    continue
                if op_type == "delete" and "start_line" not in op:
                    operation_log.append(
                        {"operation": "validate_operation", "index": i, "type": op_type, "success": False,
                         "error": "Missing 'start_line'"})
                    summary_stats["operations_failed"] += 1
                    continue

                valid_operations.append(op)  # Assume valid for now if basic structure is okay

            # --- Sort valid operations by line number ascending ---
            try:
                sorted_ops_asc = sorted(
                    valid_operations,
                    key=lambda op: int(op.get("line", op.get("start_line", 0)))
                    # Use 0 as fallback shouldn't happen if validation passed
                )
            except (ValueError, TypeError) as sort_e:
                # Log sorting error but proceed with unsorted valid ops
                operation_log.append(
                    {"operation": "sort_operations", "success": False, "error": f"Failed to sort: {str(sort_e)}"})
                summary_stats["operations_failed"] += 1  # Count as a failure
                sorted_ops_asc = valid_operations  # Use the unsorted list

            line_offset = 0  # Tracks cumulative line changes

            # --- Execute Line Operations ---
            for op in sorted_ops_asc:
                operation_type = op.get("operation", "").lower()
                op_result = {"operation": operation_type}
                op_success = False  # Assume failure until proven otherwise
                lines_affected_count = 0
                content_actually_changed = False

                current_len = len(modified_lines)  # Length *before* this specific operation

                try:
                    if operation_type == "insert":
                        summary_stats["line_inserts_attempted"] += 1
                        line_num = int(op.get("line", 1))
                        new_content_raw = op.get("content", "")
                        new_lines = [str(item) for item in new_content_raw] if isinstance(new_content_raw, list) else [
                            str(new_content_raw)]

                        target_line_num = line_num + line_offset
                        idx = min(max(0, target_line_num - 1), current_len)  # Clamp index

                        num_inserted = len(new_lines)
                        modified_lines[idx:idx] = new_lines  # Insert
                        op_result.update({
                            "requested_line": line_num,
                            "adjusted_line": idx + 1,  # 1-based where insertion happened
                            "lines_inserted": num_inserted
                        })
                        line_offset += num_inserted
                        lines_affected_count = num_inserted
                        summary_stats["line_inserts_made"] += num_inserted
                        change_occurred = True  # Insertion always counts as a change
                        op_success = True

                    elif operation_type == "replace":
                        summary_stats["line_replaces_attempted"] += 1
                        line_num = int(op.get("line", 0))
                        new_content = str(op.get("content", ""))

                        target_line_num = line_num + line_offset
                        idx = target_line_num - 1

                        if 0 <= idx < current_len:
                            old_line = modified_lines[idx]
                            op_result.update({
                                "requested_line": line_num,
                                "adjusted_line": target_line_num
                            })
                            if old_line != new_content:
                                modified_lines[idx] = new_content
                                content_actually_changed = True
                                change_occurred = True  # Mark overall change
                                summary_stats["line_replaces_made"] += 1
                            op_result["changed"] = content_actually_changed  # Add flag indicating if content differed
                            lines_affected_count = 1
                            op_success = True
                        else:
                            op_result.update({
                                "requested_line": line_num,
                                "adjusted_line": target_line_num,
                                "error": f"Adjusted line {target_line_num} out of range (1-{current_len})"
                            })
                            op_success = False

                    elif operation_type == "delete":
                        summary_stats["line_deletes_attempted"] += 1
                        start_line = int(op.get("start_line", 0))
                        end_line = int(op.get("end_line", start_line))

                        target_start_line = start_line + line_offset
                        target_end_line = end_line + line_offset

                        start_idx = max(0, target_start_line - 1)
                        end_idx = min(current_len, target_end_line)  # Slice end is exclusive, target is inclusive

                        op_result.update({
                            "requested_range": f"{start_line}-{end_line}",
                            "adjusted_range": f"{target_start_line}-{target_end_line}"
                        })

                        if start_idx < end_idx and start_idx < current_len:
                            num_deleted = end_idx - start_idx
                            del modified_lines[start_idx:end_idx]
                            op_result["lines_deleted"] = num_deleted
                            line_offset -= num_deleted
                            lines_affected_count = num_deleted
                            summary_stats["line_deletes_made"] += num_deleted
                            change_occurred = True  # Deletion always counts as a change
                            op_success = True
                        else:
                            op_result["error"] = f"Adjusted range invalid or out of bounds (1-{current_len})"
                            op_success = False

                except (ValueError, TypeError, KeyError) as e:
                    op_result["error"] = f"Parameter error: {type(e).__name__}: {str(e)}"
                    op_success = False
                except Exception as e_inner:  # Catch unexpected errors during operation
                    op_result["error"] = f"Execution error: {type(e_inner).__name__}: {str(e_inner)}"
                    op_success = False

                op_result["success"] = op_success
                if not op_success:
                    summary_stats["operations_failed"] += 1
                operation_log.append(op_result)

        # --- Write Changes Atomically (if any occurred) ---
        final_content = "\n".join(modified_lines)
        # Preserve trailing newline if original had one and content is not empty
        if final_content and not final_content.endswith("\n") and original_content and original_content.endswith("\n"):
            final_content += "\n"

        if change_occurred:
            temp_file = None
            try:
                with tempfile.NamedTemporaryFile(mode='w', encoding=encoding_used, dir=path.parent, delete=False,
                                                 prefix=f".{path.name}~") as temp_f:
                    temp_file = Path(temp_f.name)
                    temp_f.write(final_content)
                temp_file.replace(path)  # Atomic rename/replace
                operation_log.append({"operation": "write_file", "success": True})
            except Exception as write_e:
                if temp_file and temp_file.exists(): temp_file.unlink(missing_ok=True)
                error_msg = f"Failed write: {type(write_e).__name__}: {str(write_e)}"
                operation_log.append({"operation": "write_file", "success": False, "error": error_msg})
                summary_stats["operations_failed"] += 1
                # Re-raise to be caught by the outer try/except
                raise IOError(f"Failed to write changes back to file {path}: {error_msg}") from write_e
            finally:
                # Ensure temp file is gone even if replace worked but something else failed later
                if temp_file and temp_file.exists(): temp_file.unlink(missing_ok=True)
        else:
            operation_log.append({"operation": "write_file", "skipped": True, "reason": "No changes detected"})

        # --- Final Return ---
        return {
            "success": True,  # Overall tool execution was successful (even if some ops failed but didn't halt)
            "file_path": str(path),
            "original_size": original_size,
            "new_size": len(final_content),
            "change_occurred": change_occurred,
            "summary": summary_stats,
            "operations_log": operation_log,
            # Keep a short preview, it can still be useful context
            "final_content_preview": "\n".join(final_content.splitlines()[:10]) + (
                '\n...' if len(final_content.splitlines()) > 10 else '')
        }

    except Exception as e:
        # Catch errors during the operation or writing phase
        error_msg = f"Editing failed: {type(e).__name__}: {str(e)}"
        operation_log.append({"operation": "error", "message": error_msg})
        summary_stats["operations_failed"] += 1
        return {
            "success": False,
            "error": error_msg,
            "file_path": str(path),
            "change_occurred": False,  # Assume no change if error occurred mid-way
            "summary": summary_stats,
            "operations_log": operation_log
        }


@mcp.tool(
    description="""
    Write content to a new file or overwrite/append to an existing file.

    Parameters:
    - file_path: Path to the file to write.
    - content: Text content to write.
    - mode: 'w' to overwrite (default), 'a' to append. Parent directories will be created if needed.

    Examples:
    - Create/overwrite file: write_file("/path/to/new_file.log", "Log start")
    - Append to file: write_file("/path/to/existing.log", "New entry\\n", mode="a")

    Returns success status and error message if applicable.
    """,
)
def write_file(file_path: str, content: str, mode: str = "w") -> dict:
    """Writes content to a file, creating directories if necessary."""
    path = Path(file_path)

    # Validate parameters
    if not isinstance(content, str):
        return {
            "success": False,
            "error": f"Content must be a string, got {type(content).__name__}",
            "file_path": str(path)
        }

    if mode not in ['w', 'a']:
        return {
            "success": False,
            "error": "Invalid mode. Use 'w' (overwrite) or 'a' (append).",
            "file_path": str(path)
        }

    try:
        # Create parent directories if they don't exist
        path.parent.mkdir(parents=True, exist_ok=True)

        # Write using specified mode and UTF-8 encoding
        with open(path, mode, encoding='utf-8') as f:
            bytes_written = f.write(content)

        return {
            "success": True,
            "bytes_written": bytes_written,
            "file_path": str(path),
            "mode": mode
        }
    except PermissionError as e:
        return {
            "success": False,
            "error": f"Permission denied: {str(e)}",
            "file_path": str(path)
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Error writing to file {path}: {type(e).__name__}: {str(e)}",
            "file_path": str(path)
        }


@mcp.tool(
    description="""
    Fetches the text content of a web page URL.

    Uses Chromium (headless) to render the page to PDF, then extracts text using 'marker'.
    Handles temporary file creation and cleanup. Best effort for complex pages.

    Parameters:
    - url: The URL to fetch (e.g., "https://www.google.com").

    Returns the extracted text content as a string, or an error message.
    """,
)
def fetch_page(url: str) -> str:
    """Fetches web page text via Chromium PDF conversion and marker text extraction."""
    # Validate URL basic structure
    if not url.startswith(('http://', 'https://')):
        return "Error: Invalid URL provided. Must start with http:// or https://."

    # Find an available browser command
    browser_cmd = _find_browser_command()
    if not browser_cmd:
        return "Error: No compatible browser found. Please install Chromium or Chrome."

    # Use a secure temporary directory
    try:
        tmp_dir = tempfile.TemporaryDirectory()
        temp_pdf_path = Path(tmp_dir.name) / "page.pdf"
    except Exception as e:
        return f"Error: Could not create temporary directory for PDF conversion: {type(e).__name__}: {str(e)}"

    try:
        # Build the command for the browser
        command = [
            browser_cmd,
            "--headless",
            "--disable-gpu",
            "--no-sandbox",  # Often needed in containerized environments
            "--disable-dev-shm-usage",  # Mitigates issues with limited /dev/shm size
            "--disable-software-rasterizer",
            "--disable-features=VizDisplayCompositor",
            "--timeout=30000",  # 30 second timeout for rendering
            f"--print-to-pdf={str(temp_pdf_path)}",
            url
        ]

        # Execute browser command
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=45  # Overall timeout slightly longer than internal browser timeout
        )

        if result.returncode != 0:
            # Provide more informative error if available
            error_detail = result.stderr.strip()
            if not error_detail:
                error_detail = result.stdout.strip()  # Sometimes errors go to stdout
            return f"Error fetching page with {browser_cmd} (code {result.returncode}): {error_detail or 'No output'}"

        # Check if PDF was actually created and has size
        if not temp_pdf_path.exists() or temp_pdf_path.stat().st_size == 0:
            error_detail = result.stderr.strip()
            if not error_detail:
                error_detail = result.stdout.strip()
            return f"Error: Browser ran but did not create a valid PDF file. Output: {error_detail or 'No output'}"

        # Extract text using marker (suppress stdout/stderr)
        with io.StringIO() as buf, contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            try:
                converter = PdfConverter(artifact_dict=create_model_dict())
                rendered = converter(str(temp_pdf_path))
                text_content, _, _ = text_from_rendered(rendered)
                return text_content if text_content else "Error: No text content extracted."
            except Exception as marker_e:
                return f"Error during text extraction: {type(marker_e).__name__}: {str(marker_e)}"

    except subprocess.TimeoutExpired:
        return f"Error: Browser process timed out fetching URL: {url}"
    except FileNotFoundError:
        return f"Error: '{browser_cmd}' command not found despite earlier check. This is unexpected."
    except Exception as e:
        return f"Error during page fetch process: {type(e).__name__}: {str(e)}"
    finally:
        # Clean up the temporary directory
        if 'tmp_dir' in locals() and isinstance(tmp_dir, tempfile.TemporaryDirectory):
            tmp_dir.cleanup()
