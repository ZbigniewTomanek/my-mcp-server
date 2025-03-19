import re
import subprocess
import tempfile
from pathlib import Path
from typing import Optional, List, Dict, Any

from marker.converters.pdf import PdfConverter
import io
import contextlib
from marker.models import create_model_dict
from marker.output import text_from_rendered

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("zbigniew-mcp")


@mcp.tool(
    description="""
    Execute a shell command and return the complete results including stdout, stderr, and exit code.

    Provide the command as a list of strings where the first element is the command name and 
    subsequent elements are arguments. This approach prevents shell injection vulnerabilities.

    Examples:
    - List files: execute_shell_command(["ls", "-la"])
    - Find text in files: execute_shell_command(["grep", "-r", "TODO", "./src"])
    - Run a Python script: execute_shell_command(["python", "analysis.py", "--input", "data.csv"])
    - Get system info: execute_shell_command(["uname", "-a"])

    The command will timeout after the specified seconds (default: 60) to prevent hanging.
    """,
)
def execute_shell_command(
        command: list[str],
        timeout: int = 60,
        working_dir: str = None
) -> dict:
    """Execute a shell command and return comprehensive results."""
    try:
        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            cwd=working_dir,
            text=True
        )

        return {
            "stdout": result.stdout,
            "stderr": result.stderr,
            "exit_code": result.returncode,
            "command": " ".join(command),
            "success": result.returncode == 0
        }
    except subprocess.TimeoutExpired:
        return {
            "stdout": "",
            "stderr": f"Command timed out after {timeout} seconds",
            "exit_code": -1,
            "command": " ".join(command),
            "success": False
        }
    except Exception as e:
        return {
            "stdout": "",
            "stderr": f"Error executing command: {str(e)}",
            "exit_code": -1,
            "command": " ".join(command),
            "success": False
        }


@mcp.tool(
    description="""
    Show contents of a file with options to display specific line ranges.

    This tool allows you to view file content with control over which lines to display.

    Parameters:
    - file_path: Path to the file to display
    - start_line: Line number to start from (1-based indexing, defaults to 1)
    - num_lines: Number of lines to display (defaults to all lines)

    Examples:
    - Show entire file: show_file("/path/to/file.txt")
    - Show first 10 lines: show_file("/path/to/file.txt", num_lines=10)
    - Show lines 5-15: show_file("/path/to/file.txt", start_line=5, num_lines=10)

    Returns the content as a string and information about the lines shown.
    """,
)
def show_file(
        file_path: Path,
        start_line: int = 1,
        num_lines: Optional[int] = None
) -> dict:
    """Display content of a file with optional line range specification."""
    if not file_path.exists():
        return {
            "success": False,
            "error": f"File {file_path} does not exist",
            "content": "",
            "lines_shown": 0,
            "total_lines": 0
        }

    try:
        # Ensure start_line is at least 1 (1-based indexing)
        start_line = max(1, start_line)

        # Read all lines from the file
        all_lines = file_path.read_text().splitlines()
        total_lines = len(all_lines)

        # Adjust start_line if it's beyond file length
        if start_line > total_lines:
            return {
                "success": False,
                "error": f"Start line {start_line} is beyond the file length ({total_lines} lines)",
                "content": "",
                "lines_shown": 0,
                "total_lines": total_lines
            }

        # Convert to 0-based indexing for slicing
        start_idx = start_line - 1

        # Determine end index based on num_lines
        if num_lines is None:
            end_idx = total_lines
        else:
            end_idx = min(start_idx + num_lines, total_lines)

        # Extract the requested lines
        selected_lines = all_lines[start_idx:end_idx]
        content = "\n".join(selected_lines)

        return {
            "success": True,
            "content": content,
            "lines_shown": len(selected_lines),
            "total_lines": total_lines,
            "start_line": start_line,
            "end_line": start_idx + len(selected_lines)
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Error reading file: {str(e)}",
            "content": "",
            "lines_shown": 0,
            "total_lines": 0
        }


@mcp.tool(
    description="""
    Search for patterns in a file using Python regular expressions.

    This tool allows you to search through a file for lines matching a regular expression pattern.

    Parameters:
    - file_path: Path to the file to search
    - pattern: Python regular expression pattern to search for
    - case_sensitive: Whether the search should be case-sensitive (default: True)
    - max_matches: Maximum number of matches to return (default: 100, use -1 for all matches)

    Examples:
    - Find all function definitions: search_in_file("/path/to/script.py", r"def\\s+\\w+\\s*\\(")
    - Find all TODO comments: search_in_file("/path/to/code.py", r"#\\s*TODO", case_sensitive=False)

    Returns the matching lines with their line numbers and the total count of matches.
    """,
)
def search_in_file(
        file_path: Path,
        pattern: str,
        case_sensitive: bool = True,
        max_matches: int = 100
) -> dict:
    """Search for regex patterns in a file and return matching lines with line numbers."""
    if not file_path.exists():
        return {
            "success": False,
            "error": f"File {file_path} does not exist",
            "matches": [],
            "match_count": 0
        }

    try:
        # Compile the regex pattern
        flags = 0 if case_sensitive else re.IGNORECASE
        regex = re.compile(pattern, flags)

        # Read the file and search for matches
        matches = []
        with open(file_path, 'r') as f:
            for i, line in enumerate(f, 1):
                if regex.search(line):
                    matches.append({
                        "line_number": i,
                        "content": line.rstrip('\n')
                    })
                    if max_matches > 0 and len(matches) >= max_matches:
                        break

        return {
            "success": True,
            "matches": matches,
            "match_count": len(matches),
            "truncated": max_matches > 0 and len(matches) >= max_matches
        }
    except re.error as e:
        return {
            "success": False,
            "error": f"Invalid regular expression: {str(e)}",
            "matches": [],
            "match_count": 0
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Error searching file: {str(e)}",
            "matches": [],
            "match_count": 0
        }


@mcp.tool(
    description="""
    Efficiently edit a file with advanced options for text manipulation.

    This tool allows making precise changes to file content with multiple modes of operation:

    1. String replacements: Replace exact text strings throughout the file
    2. Line-based operations: Insert, modify, or delete specific lines by number

    Examples:
    - Replace text: edit_file("config.json", replacements={"\"debug\": false": "\"debug\": true"})
    - Insert at line 5: edit_file("script.py", line_operations=[{"operation": "insert", "line": 5, "content": "# New comment"}])
    - Delete lines 10-15: edit_file("file.txt", line_operations=[{"operation": "delete", "start_line": 10, "end_line": 15}])
    - Replace line 20: edit_file("file.txt", line_operations=[{"operation": "replace", "line": 20, "content": "Updated content"}])
    - Mixed operations: Combine both replacements and line operations in a single call

    Returns a summary of all changes made to the file.
    """,
)
def edit_file(
        file_path: Path,
        replacements: Optional[Dict[str, str]] = None,
        line_operations: Optional[List[Dict[str, Any]]] = None,
        create_if_missing: bool = False
) -> dict:
    """Edit a file with advanced options for string replacements and line operations."""
    if not file_path.exists():
        if create_if_missing:
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text("")
        else:
            return {
                "success": False,
                "error": f"File {file_path} does not exist",
                "replacements_made": {},
                "line_operations_performed": []
            }

    try:
        # Read the original file content
        original_content = file_path.read_text()
        content = original_content

        # Track changes made
        replacement_counts = {}
        line_ops_performed = []

        # Perform string replacements if specified
        if replacements:
            for old, new in replacements.items():
                count = content.count(old)
                if count > 0:
                    content = content.replace(old, new)
                    replacement_counts[old] = count

        # Perform line operations if specified
        if line_operations:
            # Convert content to lines for line-based operations
            lines = content.splitlines()
            original_line_count = len(lines)

            # Sort operations by line number (descending) to avoid index shifting
            # This ensures operations at higher line numbers are processed first
            sorted_ops = sorted(
                line_operations,
                key=lambda op: -(op.get("line", 0) if "line" in op else op.get("start_line", 0))
            )

            for op in sorted_ops:
                operation_type = op.get("operation", "").lower()

                if operation_type == "insert":
                    line_num = op.get("line", 0)
                    new_content = op.get("content", "")

                    # Convert to 0-based index
                    idx = min(max(0, line_num - 1), len(lines))

                    # Insert the new content
                    if isinstance(new_content, list):
                        for i, line in enumerate(new_content):
                            lines.insert(idx + i, line)
                    else:
                        lines.insert(idx, new_content)

                    line_ops_performed.append({
                        "operation": "insert",
                        "line": line_num,
                        "success": True
                    })

                elif operation_type == "replace":
                    line_num = op.get("line", 0)
                    new_content = op.get("content", "")

                    # Convert to 0-based index
                    idx = line_num - 1

                    # Validate line number
                    if 0 <= idx < len(lines):
                        old_line = lines[idx]
                        lines[idx] = new_content

                        line_ops_performed.append({
                            "operation": "replace",
                            "line": line_num,
                            "success": True,
                            "old_content": old_line
                        })
                    else:
                        line_ops_performed.append({
                            "operation": "replace",
                            "line": line_num,
                            "success": False,
                            "error": f"Line {line_num} is out of range (1-{len(lines)})"
                        })

                elif operation_type == "delete":
                    start_line = op.get("start_line", 0)
                    end_line = op.get("end_line", start_line)

                    # Convert to 0-based indices
                    start_idx = max(0, start_line - 1)
                    end_idx = min(len(lines), end_line)

                    # Validate line range
                    if start_idx < end_idx:
                        deleted_lines = lines[start_idx:end_idx]
                        lines[start_idx:end_idx] = []

                        line_ops_performed.append({
                            "operation": "delete",
                            "start_line": start_line,
                            "end_line": end_line,
                            "lines_deleted": end_idx - start_idx,
                            "success": True,
                            "deleted_content": deleted_lines
                        })
                    else:
                        line_ops_performed.append({
                            "operation": "delete",
                            "start_line": start_line,
                            "end_line": end_line,
                            "success": False,
                            "error": f"Invalid line range: {start_line}-{end_line}"
                        })

                else:
                    line_ops_performed.append({
                        "operation": operation_type,
                        "success": False,
                        "error": f"Unknown operation type: {operation_type}"
                    })

            # Convert lines back to content
            content = "\n".join(lines)

        # Write the modified content back to the file
        with open(file_path, "w") as f:
            f.write(content)

        return {
            "success": True,
            "original_size": len(original_content),
            "new_size": len(content),
            "changed": original_content != content,
            "replacements_made": replacement_counts,
            "line_operations_performed": line_ops_performed
        }

    except Exception as e:
        return {
            "success": False,
            "error": f"Error editing file: {str(e)}",
            "replacements_made": {},
            "line_operations_performed": []
        }


@mcp.tool(
    description="""
    Write content to a file with options to append or overwrite existing content.
    
    This tool allows you to write content to a file with options to append or overwrite the existing content.
    
    Parameters:
    - file_path: Path to the file to write
    - content: Text content to write to the file
    - mode: Write mode to use: 'w' (overwrite) or 'a' (append, default)
    
    Examples:
    - Overwrite file: write_file("/path/to/file.txt", "New content")
    - Append to file: write_file("/path/to/log.txt", "Log entry", mode="a")
    """
)
def write_file(file_path: Path, content: str, mode: str = "w") -> dict:
    """Write content to a file."""
    try:
        with open(file_path, mode) as f:
            f.write(content)
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool(
    description="""
    Fetch a web page by converting it to PDF and then extracting text.
    
    This tool fetches a web page by converting it to PDF using Chromium and then extracts the text content.
    
    Parameters:
    - url: URL of the web page to fetch
    
    Returns the extracted text content of the web page.
    """
)
def fetch_page(url: str) -> str:
    """
    Fetch a web page by converting it to PDF and then extracting text.
    Utilizes a temporary file and suppresses any stdout produced by the PDF converter.
    """
    # Create a named temporary file and immediately close it so Chromium can write to it.
    with tempfile.NamedTemporaryFile(prefix="page", suffix=".pdf", delete=False) as tmp_pdf:
        temp_pdf_path = tmp_pdf.name

    try:
        # Build the command for Chromium to convert the page to PDF.
        command = [
            "chromium",
            "--headless",
            "--disable-gpu",
            f"--print-to-pdf={temp_pdf_path}",
            url
        ]
        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        if result.returncode != 0:
            return f"Error fetching page: {result.stderr}"

        with io.StringIO() as buf, contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            converter = PdfConverter(artifact_dict=create_model_dict())
            rendered = converter(temp_pdf_path)
            text, _, images = text_from_rendered(rendered)
        return text

    finally:
        try:
            Path(temp_pdf_path).unlink()
        except Exception:
            pass

