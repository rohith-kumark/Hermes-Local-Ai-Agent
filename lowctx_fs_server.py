from pathlib import Path
from typing import Optional
import argparse
import os
import shutil

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("lowctx-filesystem")

ROOT: Optional[Path] = None

MAX_READ_CHARS = 6000
MAX_LIST_ITEMS = 120
MAX_SEARCH_RESULTS = 30

BLOCKED_DIRS = {
    ".git",
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    ".cache",
    "dist",
    "build",
    ".next",
    ".pytest_cache",
}

TEXT_EXTENSIONS = {
    ".txt", ".md", ".py", ".js", ".ts", ".jsx", ".tsx",
    ".json", ".html", ".css", ".scss", ".sql", ".csv",
    ".yaml", ".yml", ".xml", ".sh", ".env", ".ini",
    ".toml", ".java", ".c", ".cpp", ".h", ".hpp",
    ".rs", ".go", ".php"
}


def set_root(root: str) -> None:
    global ROOT
    ROOT = Path(root).expanduser().resolve()
    ROOT.mkdir(parents=True, exist_ok=True)


def safe_path(path: str = ".") -> Path:
    if ROOT is None:
        raise ValueError("Root is not configured.")

    p = (ROOT / path).expanduser().resolve()

    if not (p == ROOT or ROOT in p.parents):
        raise ValueError("Access denied: path is outside workspace.")

    relative_parts = set(p.relative_to(ROOT).parts)
    if relative_parts.intersection(BLOCKED_DIRS):
        raise ValueError("Access denied: blocked directory.")

    return p


def is_text_file(path: Path) -> bool:
    if path.name in {"README", "Makefile", "Dockerfile"}:
        return True
    return path.suffix.lower() in TEXT_EXTENSIONS


@mcp.tool()
def list_dir(path: str = ".") -> str:
    """
    List files and folders in a directory.
    Returns a small capped list to avoid large context.
    """
    p = safe_path(path)

    if not p.exists():
        return f"Path not found: {path}"

    if not p.is_dir():
        return f"Not a directory: {path}"

    items = []
    count = 0

    for child in sorted(p.iterdir(), key=lambda x: (x.is_file(), x.name.lower())):
        if child.name in BLOCKED_DIRS:
            continue

        kind = "DIR " if child.is_dir() else "FILE"
        rel = child.relative_to(ROOT)
        items.append(f"{kind}: {rel}")

        count += 1
        if count >= MAX_LIST_ITEMS:
            items.append("...list truncated...")
            break

    return "\n".join(items) if items else "Directory is empty."


@mcp.tool()
def tree(path: str = ".", max_depth: int = 2) -> str:
    """
    Show a small directory tree.
    Uses low depth to avoid sending too much context.
    """
    start = safe_path(path)

    if not start.exists():
        return f"Path not found: {path}"

    if not start.is_dir():
        return f"Not a directory: {path}"

    lines = []

    def walk(current: Path, depth: int):
        if depth > max_depth:
            return

        try:
            children = sorted(current.iterdir(), key=lambda x: (x.is_file(), x.name.lower()))
        except PermissionError:
            return

        shown = 0
        for child in children:
            if child.name in BLOCKED_DIRS:
                continue

            rel = child.relative_to(ROOT)
            indent = "  " * depth
            prefix = "📁" if child.is_dir() else "📄"
            lines.append(f"{indent}{prefix} {rel}")

            shown += 1
            if shown >= 80:
                lines.append(f"{indent}...tree truncated...")
                return

            if child.is_dir():
                walk(child, depth + 1)

    walk(start, 0)
    return "\n".join(lines) if lines else "No files found."


@mcp.tool()
def read_file(path: str, start_line: int = 1, max_lines: int = 120) -> str:
    """
    Read only a slice of a text file.
    Never reads full large files.
    """
    p = safe_path(path)

    if not p.exists():
        return f"File not found: {path}"

    if not p.is_file():
        return f"Not a file: {path}"

    if not is_text_file(p):
        return "Blocked: only text/code files can be read."

    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return f"Read failed: {e}"

    lines = text.splitlines()
    start = max(start_line - 1, 0)
    end = min(start + max_lines, len(lines))

    selected = lines[start:end]
    numbered = [
        f"{i + 1}: {line}"
        for i, line in enumerate(selected, start=start)
    ]

    output = "\n".join(numbered)

    if len(output) > MAX_READ_CHARS:
        output = output[:MAX_READ_CHARS] + "\n...read truncated..."

    return output if output else "File is empty."


@mcp.tool()
def search_text(query: str, path: str = ".", max_results: int = 20) -> str:
    """
    Search text inside files.
    Returns only matching lines, not whole files.
    """
    base = safe_path(path)

    if not query.strip():
        return "Empty query."

    results = []

    files = [base] if base.is_file() else base.rglob("*")

    for file in files:
        if len(results) >= min(max_results, MAX_SEARCH_RESULTS):
            break

        if not file.is_file():
            continue

        if any(part in BLOCKED_DIRS for part in file.relative_to(ROOT).parts):
            continue

        if not is_text_file(file):
            continue

        try:
            lines = file.read_text(encoding="utf-8", errors="replace").splitlines()
        except Exception:
            continue

        for line_no, line in enumerate(lines, start=1):
            if query.lower() in line.lower():
                rel = file.relative_to(ROOT)
                results.append(f"{rel}:{line_no}: {line.strip()[:220]}")

                if len(results) >= min(max_results, MAX_SEARCH_RESULTS):
                    break

    return "\n".join(results) if results else "No matches found."


@mcp.tool()
def write_file(path: str, content: str, overwrite: bool = False) -> str:
    """
    Write a text file inside the workspace.
    Refuses to overwrite unless overwrite=true.
    """
    p = safe_path(path)

    if p.exists() and not overwrite:
        return "File already exists. Use overwrite=true to replace it."

    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")

    return f"Written: {p.relative_to(ROOT)}"


@mcp.tool()
def replace_text(path: str, old: str, new: str) -> str:
    """
    Replace exact text in a file.
    Safer than rewriting full files.
    """
    p = safe_path(path)

    if not p.exists():
        return f"File not found: {path}"

    if not p.is_file():
        return f"Not a file: {path}"

    if not is_text_file(p):
        return "Blocked: only text/code files can be modified."

    text = p.read_text(encoding="utf-8", errors="replace")

    if old not in text:
        return "Old text not found. No changes made."

    updated = text.replace(old, new, 1)
    p.write_text(updated, encoding="utf-8")

    return f"Updated: {p.relative_to(ROOT)}"


@mcp.tool()
def move_file(source: str, destination: str, overwrite: bool = False) -> str:
    """
    Move a file or folder inside the workspace.

    Rules:
    1. If destination ends with '/', treat it as a directory and move source inside it.
       Example: move_file("a/file.txt", "b/") -> "b/file.txt"

    2. If destination already exists and is a directory, move source inside it.
       Example: move_file("a/file.txt", "b") where b is folder -> "b/file.txt"

    3. If destination does not end with '/' and does not exist as directory,
       treat destination as the exact final path.
       Example: move_file("a/file.txt", "b/new-name.txt") -> "b/new-name.txt"
    """
    src = safe_path(source)

    if not src.exists():
        return f"Source not found: {source}"

    destination_is_directory = destination.endswith("/") or destination.endswith(os.sep)

    raw_dst = safe_path(destination)

    # Case 1: user explicitly gave directory destination like test/
    if destination_is_directory:
        dst_dir = raw_dst
        dst_dir.mkdir(parents=True, exist_ok=True)
        final_dst = dst_dir / src.name

    # Case 2: destination already exists as directory
    elif raw_dst.exists() and raw_dst.is_dir():
        final_dst = raw_dst / src.name

    # Case 3: exact target path or rename
    else:
        final_dst = raw_dst
        final_dst.parent.mkdir(parents=True, exist_ok=True)

    # Safety: prevent moving a folder into itself
    if src.is_dir():
        try:
            if final_dst == src or src in final_dst.parents:
                return "Blocked: cannot move a folder into itself."
        except Exception:
            pass

    if final_dst.exists() and not overwrite:
        return (
            f"Destination already exists: {final_dst.relative_to(ROOT)}. "
            "Use overwrite=true to replace it."
        )

    if final_dst.exists() and overwrite:
        if final_dst.is_dir():
            shutil.rmtree(final_dst)
        else:
            final_dst.unlink()

    shutil.move(str(src), str(final_dst))

    return f"Moved: {src.relative_to(ROOT)} -> {final_dst.relative_to(ROOT)}"

@mcp.tool()
def delete_file(path: str, confirm: bool = False) -> str:
    """
    Delete a single file inside the workspace.
    Requires confirm=true.
    This does not delete directories.
    """
    p = safe_path(path)

    if not p.exists():
        return f"File not found: {path}"

    if not p.is_file():
        return "Blocked: delete_file only deletes files, not directories."

    if not confirm:
        return (
            f"Delete blocked for safety.\n"
            f"File: {p.relative_to(ROOT)}\n"
            f"Call again with confirm=true to delete this file."
        )

    p.unlink()
    return f"Deleted file: {path}"


@mcp.tool()
def delete_empty_directory(path: str, confirm: bool = False) -> str:
    """
    Delete an empty directory inside the workspace.
    Requires confirm=true.
    Refuses to delete non-empty folders.
    """
    p = safe_path(path)

    if not p.exists():
        return f"Directory not found: {path}"

    if not p.is_dir():
        return "Blocked: path is not a directory."

    if not confirm:
        return (
            f"Delete blocked for safety.\n"
            f"Directory: {p.relative_to(ROOT)}\n"
            f"Call again with confirm=true to delete this empty directory."
        )

    try:
        p.rmdir()
    except OSError:
        return "Blocked: directory is not empty. Use delete_directory_tree only if you really want recursive delete."

    return f"Deleted empty directory: {path}"


@mcp.tool()
def delete_directory_tree(path: str, confirm_text: str = "") -> str:
    """
    Recursively delete a directory inside the workspace.
    Very dangerous. Requires confirm_text='DELETE'.
    Refuses to delete workspace root.
    """
    import shutil

    p = safe_path(path)

    if not p.exists():
        return f"Directory not found: {path}"

    if not p.is_dir():
        return "Blocked: path is not a directory."

    if p == ROOT:
        return "Blocked: cannot delete workspace root."

    if confirm_text != "DELETE":
        return (
            "Recursive delete blocked for safety.\n"
            f"Directory: {p.relative_to(ROOT)}\n"
            "Call again with confirm_text='DELETE' only if you are sure."
        )

    shutil.rmtree(p)
    return f"Deleted directory tree: {path}"

@mcp.tool()
def move_to_trash(path: str) -> str:
    """
    Move a file or folder to .trash inside the workspace instead of permanently deleting it.
    Safer than delete.
    """
    import shutil
    from datetime import datetime

    p = safe_path(path)

    if not p.exists():
        return f"Path not found: {path}"

    if p == ROOT:
        return "Blocked: cannot trash workspace root."

    trash = ROOT / ".trash"
    trash.mkdir(exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    destination = trash / f"{p.name}_{timestamp}"

    shutil.move(str(p), str(destination))

    return f"Moved to trash: {p.relative_to(ROOT)} -> {destination.relative_to(ROOT)}"

@mcp.tool()
def run_safe_shell(command: str, cwd: str = ".", confirm: bool = False) -> str:
    """
    Run a safe shell-like command inside the workspace.
    Dangerous commands are blocked.
    Runs without shell=True, so pipes and shell injection are disabled.
    """
    import shlex
    import subprocess
    import re

    workspace_cwd = safe_path(cwd)

    if not workspace_cwd.exists():
        return f"Working directory not found: {cwd}"

    if not workspace_cwd.is_dir():
        return f"Working path is not a directory: {cwd}"

    blocked_words = {
        "sudo", "su", "rm", "rmdir", "mkfs", "dd", "shutdown", "reboot",
        "poweroff", "chmod", "chown", "mount", "umount", "kill", "pkill",
        "apt", "apt-get", "dnf", "pacman", "snap", "flatpak",
        "curl", "wget", "nc", "netcat", "ssh", "scp", "rsync",
        "docker", "podman"
    }

    blocked_symbols = [
        "&&", "||", ";", "|", "`", "$(", ">", ">>", "<"
    ]

    lower_command = command.lower()

    for symbol in blocked_symbols:
        if symbol in command:
            return f"Blocked unsafe shell operator: {symbol}"

    try:
        parts = shlex.split(command)
    except ValueError as e:
        return f"Command parse failed: {e}"

    if not parts:
        return "Empty command."

    executable = parts[0]

    if executable in blocked_words:
        return f"Blocked unsafe command: {executable}"

    allowed_commands = {
        "pwd", "ls", "find", "grep", "rg", "cat", "head", "tail",
        "wc", "python", "python3", "node", "npm", "pytest",
        "git"
    }

    if executable not in allowed_commands:
        return (
            f"Command not allowed: {executable}\n"
            f"Allowed commands: {', '.join(sorted(allowed_commands))}"
        )

    if executable == "git":
        allowed_git = {"status", "diff", "log", "branch"}
        if len(parts) < 2 or parts[1] not in allowed_git:
            return "Only safe git commands are allowed: git status, git diff, git log, git branch"

    if executable == "npm":
        allowed_npm = {"test", "run", "start"}
        if len(parts) < 2 or parts[1] not in allowed_npm:
            return "Only safe npm commands are allowed: npm test, npm run <script>, npm start"

    if "curl" in lower_command and "bash" in lower_command:
        return "Blocked: never execute unknown curl | bash commands."

    if not confirm and executable in {"python", "python3", "node", "npm", "pytest"}:
        return (
            f"Command requires confirmation before execution:\n"
            f"{command}\n"
            f"Run again with confirm=true if you trust this command."
        )

    try:
        completed = subprocess.run(
            parts,
            cwd=str(workspace_cwd),
            text=True,
            capture_output=True,
            timeout=20,
            shell=False
        )
    except subprocess.TimeoutExpired:
        return "Command timed out after 20 seconds."
    except Exception as e:
        return f"Command failed: {e}"

    output = ""

    if completed.stdout:
        output += completed.stdout

    if completed.stderr:
        output += "\nSTDERR:\n" + completed.stderr

    if not output.strip():
        output = f"Command finished with exit code {completed.returncode}"

    secret_patterns = [
        r"(?i)(api[_-]?key\s*[:=]\s*)[A-Za-z0-9_\-\.]+",
        r"(?i)(token\s*[:=]\s*)[A-Za-z0-9_\-\.]+",
        r"(?i)(password\s*[:=]\s*)\S+",
        r"sk-[A-Za-z0-9]{20,}",
        r"github_pat_[A-Za-z0-9_]+"
    ]

    for pattern in secret_patterns:
        output = re.sub(pattern, r"\1[REDACTED]", output)

    if len(output) > 6000:
        output = output[:6000] + "\n...output truncated..."

    return output


@mcp.tool()
def create_project(
    name: str,
    project_type: str = "python",
    description: str = "",
    overwrite: bool = False
) -> str:
    """
    Create a safe starter project inside the workspace.
    Supported project_type: python, node, web, data.
    """
    safe_name = name.strip().replace(" ", "-")

    if not safe_name:
        return "Project name cannot be empty."

    if safe_name.startswith("."):
        return "Project name cannot start with dot."

    project_path = safe_path(f"projects/{safe_name}")

    if project_path.exists() and not overwrite:
        return f"Project already exists: projects/{safe_name}"

    project_path.mkdir(parents=True, exist_ok=True)

    readme = f"""# {safe_name}

{description or "Local AI generated project."}

## Project Type

{project_type}

## Structure

Generated inside AI-Workspace only.
"""

    (project_path / "README.md").write_text(readme, encoding="utf-8")
    (project_path / ".gitignore").write_text(
        ".venv/\nnode_modules/\n__pycache__/\n.env\n.cache/\ndist/\nbuild/\n",
        encoding="utf-8"
    )

    if project_type.lower() == "python":
        (project_path / "src").mkdir(exist_ok=True)
        (project_path / "tests").mkdir(exist_ok=True)
        (project_path / "src" / "main.py").write_text(
            'def main():\n    print("Hello from local MCP project!")\n\n\nif __name__ == "__main__":\n    main()\n',
            encoding="utf-8"
        )
        (project_path / "requirements.txt").write_text("", encoding="utf-8")

    elif project_type.lower() == "node":
        (project_path / "src").mkdir(exist_ok=True)
        (project_path / "src" / "index.js").write_text(
            'console.log("Hello from local MCP Node project!");\n',
            encoding="utf-8"
        )
        (project_path / "package.json").write_text(
            '{\n  "scripts": {\n    "start": "node src/index.js",\n    "test": "echo \\"No tests yet\\""\n  }\n}\n',
            encoding="utf-8"
        )

    elif project_type.lower() == "web":
        (project_path / "index.html").write_text(
            '<!DOCTYPE html>\n<html>\n<head>\n  <title>Local MCP Web Project</title>\n  <link rel="stylesheet" href="style.css">\n</head>\n<body>\n  <h1>Hello from Local MCP</h1>\n  <script src="script.js"></script>\n</body>\n</html>\n',
            encoding="utf-8"
        )
        (project_path / "style.css").write_text(
            "body {\n  font-family: Arial, sans-serif;\n  margin: 40px;\n}\n",
            encoding="utf-8"
        )
        (project_path / "script.js").write_text(
            'console.log("Local MCP web project loaded");\n',
            encoding="utf-8"
        )

    elif project_type.lower() == "data":
        (project_path / "data").mkdir(exist_ok=True)
        (project_path / "notebooks").mkdir(exist_ok=True)
        (project_path / "src").mkdir(exist_ok=True)
        (project_path / "src" / "analysis.py").write_text(
            'import pandas as pd\n\n\ndef main():\n    print("Data analysis project ready")\n\n\nif __name__ == "__main__":\n    main()\n',
            encoding="utf-8"
        )
        (project_path / "requirements.txt").write_text(
            "pandas\nnumpy\nmatplotlib\n",
            encoding="utf-8"
        )

    else:
        return "Unsupported project_type. Use python, node, web, or data."

    return f"Created project: projects/{safe_name}"


@mcp.tool()
def summarize_folder(path: str = ".", max_files: int = 80) -> str:
    """
    Summarize a folder without reading complete file contents.
    Shows folder structure, file counts, extensions, and important files.
    """
    from collections import Counter

    base = safe_path(path)

    if not base.exists():
        return f"Path not found: {path}"

    if not base.is_dir():
        return f"Not a directory: {path}"

    file_count = 0
    dir_count = 0
    total_size = 0
    extensions = Counter()
    important_files = []
    shown_files = []

    for item in base.rglob("*"):
        if any(part in BLOCKED_DIRS for part in item.relative_to(ROOT).parts):
            continue

        if item.is_dir():
            dir_count += 1
            continue

        if item.is_file():
            file_count += 1
            total_size += item.stat().st_size
            extensions[item.suffix.lower() or "[no extension]"] += 1

            rel = str(item.relative_to(ROOT))

            if item.name.lower() in {
                "readme.md", "package.json", "requirements.txt",
                "pyproject.toml", "dockerfile", "docker-compose.yml",
                ".env", "main.py", "index.js"
            }:
                important_files.append(rel)

            if len(shown_files) < max_files:
                shown_files.append(rel)

    size_kb = round(total_size / 1024, 2)

    output = []
    output.append(f"Folder: {base.relative_to(ROOT)}")
    output.append(f"Directories: {dir_count}")
    output.append(f"Files: {file_count}")
    output.append(f"Total size: {size_kb} KB")
    output.append("")
    output.append("Top extensions:")

    for ext, count in extensions.most_common(10):
        output.append(f"- {ext}: {count}")

    output.append("")
    output.append("Important files:")

    if important_files:
        for f in important_files[:20]:
            output.append(f"- {f}")
    else:
        output.append("- None found")

    output.append("")
    output.append("Sample files:")

    for f in shown_files:
        output.append(f"- {f}")

    if file_count > len(shown_files):
        output.append("...file list truncated...")

    return "\n".join(output)


@mcp.tool()
def generate_resume_bullet(
    project_name: str,
    role_target: str = "Software Engineer",
    tech_stack: str = "",
    work_done: str = "",
    impact: str = "",
    metric: str = ""
) -> str:
    """
    Generate ATS-friendly resume bullets for a project.
    Does not expose secrets or read files.
    """
    project_name = project_name.strip() or "Project"
    role_target = role_target.strip() or "Software Engineer"
    tech_stack = tech_stack.strip() or "Python, SQL, Git"
    work_done = work_done.strip() or "built and improved project features"
    impact = impact.strip() or "improved usability, reliability, and maintainability"
    metric = metric.strip()

    metric_part = f", resulting in {metric}" if metric else ""

    bullets = [
        f"Built {project_name} using {tech_stack}, focusing on {work_done} to support {role_target} workflows.",
        f"Implemented modular features in {project_name} with {tech_stack}, improving {impact}{metric_part}.",
        f"Designed and optimized {project_name} components for cleaner architecture, better debugging, and scalable maintenance.",
        f"Applied {tech_stack} to develop production-style functionality in {project_name}, strengthening problem-solving and software development practices."
    ]

    return "\n".join(f"- {bullet}" for bullet in bullets)


@mcp.tool()
def explain_error_text(error_text: str, context: str = "") -> str:
    """
    Explain a pasted error message in simple words and suggest safe fixes.
    Works with text errors. For screenshots, user should paste OCR/text or use a vision model.
    """
    text = error_text.strip()

    if not text:
        return "No error text provided."

    lower = text.lower()
    output = []

    output.append("Simple explanation:")

    if "taberror" in lower or "inconsistent use of tabs and spaces" in lower:
        output.append("Python found mixed tabs and spaces in indentation.")
        output.append("")
        output.append("Fix:")
        output.append("1. Convert all tabs to 4 spaces.")
        output.append("2. Run: python -m py_compile your_file.py")
        output.append("3. Use only spaces for indentation.")

    elif "modulenotfounderror" in lower:
        output.append("Python cannot find one required package/module.")
        output.append("")
        output.append("Fix:")
        output.append("1. Activate your venv.")
        output.append("2. Install the missing module using pip.")
        output.append("3. Run the script again.")

    elif "filenotfounderror" in lower or "no such file or directory" in lower:
        output.append("The program is trying to access a file/path that does not exist.")
        output.append("")
        output.append("Fix:")
        output.append("1. Check the file path.")
        output.append("2. Use list_dir/tree to confirm the file location.")
        output.append("3. Use relative paths inside AI-Workspace.")

    elif "permission denied" in lower:
        output.append("The program does not have permission to access that file or folder.")
        output.append("")
        output.append("Fix:")
        output.append("1. Make sure the file is inside AI-Workspace.")
        output.append("2. Avoid system folders.")
        output.append("3. Do not use sudo automatically.")

    elif "address already in use" in lower or "port" in lower and "use" in lower:
        output.append("Another process is already using the same port.")
        output.append("")
        output.append("Fix:")
        output.append("1. Stop the old server.")
        output.append("2. Or run on a different port.")
        output.append("3. Check running process safely.")

    elif "context" in lower and "token" in lower:
        output.append("The model request is larger than the available context window.")
        output.append("")
        output.append("Fix:")
        output.append("1. Reduce prompt size.")
        output.append("2. Read smaller file chunks.")
        output.append("3. Avoid sending full workspace content.")
        output.append("4. Increase llama.cpp context only if RAM allows.")

    elif "json" in lower and ("decode" in lower or "expecting" in lower):
        output.append("The model or program returned invalid JSON.")
        output.append("")
        output.append("Fix:")
        output.append("1. Force the model to return only JSON.")
        output.append("2. Lower temperature.")
        output.append("3. Add JSON extraction fallback.")

    else:
        output.append("This error needs more context, but it appears to be a runtime or configuration issue.")
        output.append("")
        output.append("Safe debugging steps:")
        output.append("1. Read the file mentioned in the traceback.")
        output.append("2. Check the exact line number.")
        output.append("3. Avoid destructive commands.")
        output.append("4. Fix one issue at a time.")

    if context:
        output.append("")
        output.append("Extra context considered:")
        output.append(context[:1000])

    output.append("")
    output.append("Original error snippet:")
    output.append(text[:1500])

    return "\n".join(output)

@mcp.tool()
def read_memory(name: str = "rk_profile.md") -> str:
    """
    Read a long-term memory markdown file from .memory.
    Only reads memory inside the workspace.
    """
    memory_path = safe_path(f".memory/{name}")

    if not memory_path.exists():
        return f"Memory file not found: .memory/{name}"

    if not memory_path.is_file():
        return "Memory target is not a file."

    text = memory_path.read_text(encoding="utf-8", errors="replace")

    if len(text) > 4000:
        text = text[:4000] + "\n...memory truncated..."

    return text


@mcp.tool()
def append_memory(name: str, note: str, category: str = "General") -> str:
    """
    Append a safe long-term memory note.
    Never store secrets, API keys, passwords, tokens, or private keys.
    """
    import re
    from datetime import datetime

    if not name.endswith(".md"):
        name = f"{name}.md"

    blocked_patterns = [
        r"(?i)api[_-]?key",
        r"(?i)password",
        r"(?i)token",
        r"(?i)secret",
        r"(?i)private key",
        r"sk-[A-Za-z0-9]{20,}",
        r"github_pat_[A-Za-z0-9_]+"
    ]

    for pattern in blocked_patterns:
        if re.search(pattern, note):
            return "Blocked: memory note may contain secrets/API keys/tokens/passwords."

    memory_dir = safe_path(".memory")
    memory_dir.mkdir(parents=True, exist_ok=True)

    memory_path = safe_path(f".memory/{name}")

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    entry = f"\n\n## {category} - {timestamp}\n\n- {note.strip()}\n"

    with memory_path.open("a", encoding="utf-8") as f:
        f.write(entry)

    return f"Memory updated: .memory/{name}"


@mcp.tool()
def search_memory(query: str) -> str:
    """
    Search all markdown memory files inside .memory.
    Returns only matching lines to keep context low.
    """
    memory_dir = safe_path(".memory")

    if not memory_dir.exists():
        return "No memory folder found."

    if not query.strip():
        return "Empty memory search query."

    results = []

    for file in memory_dir.glob("*.md"):
        try:
            lines = file.read_text(encoding="utf-8", errors="replace").splitlines()
        except Exception:
            continue

        for line_no, line in enumerate(lines, start=1):
            if query.lower() in line.lower():
                rel = file.relative_to(ROOT)
                results.append(f"{rel}:{line_no}: {line.strip()[:220]}")

                if len(results) >= 30:
                    return "\n".join(results)

    return "\n".join(results) if results else "No memory matches found."


@mcp.tool()
def summarize_memory() -> str:
    """
    Show available memory files and a small preview.
    """
    memory_dir = safe_path(".memory")

    if not memory_dir.exists():
        return "No memory folder found."

    output = []

    for file in sorted(memory_dir.glob("*.md")):
        text = file.read_text(encoding="utf-8", errors="replace")
        preview = text.strip().replace("\n", " ")[:300]
        output.append(f"{file.relative_to(ROOT)}: {preview}")

    return "\n\n".join(output) if output else "No memory files found."

# -----------------------------
# Local RAG / Vector Memory Tools
# -----------------------------

RAG_COLLECTION_NAME = "rk_local_knowledge"
RAG_EMBED_MODEL = "/home/rk/AI-Workspace/.models/embeddings/all-MiniLM-L6-v2"
RAG_CHUNK_CHARS = 900
RAG_CHUNK_OVERLAP = 150
RAG_MAX_FILE_CHARS = 200_000
# Device mode:
# auto = use CUDA if available, otherwise CPU
# cuda = force GPU
# cpu = force CPU
RAG_DEVICE = os.getenv("RAG_DEVICE", "auto")

# Batch size:
# CPU: 8 or 16
# GTX 1650 GPU: 16 or 32
RAG_BATCH_SIZE = int(os.getenv("RAG_BATCH_SIZE", "16"))
_RAG_EMBEDDER = None


def _redact_secrets(text: str) -> str:
    import re

    secret_patterns = [
        r"(?i)(api[_-]?key\s*[:=]\s*)[A-Za-z0-9_\-\.]+",
        r"(?i)(token\s*[:=]\s*)[A-Za-z0-9_\-\.]+",
        r"(?i)(password\s*[:=]\s*)\S+",
        r"(?i)(secret\s*[:=]\s*)\S+",
        r"sk-[A-Za-z0-9]{20,}",
        r"github_pat_[A-Za-z0-9_]+",
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----",
    ]

    for pattern in secret_patterns:
        text = re.sub(pattern, r"\1[REDACTED]", text)

    return text


def _is_rag_allowed_file(path: Path) -> bool:
    blocked_names = {
        ".env",
        ".npmrc",
        ".pypirc",
        "id_rsa",
        "id_ed25519",
        "credentials.json",
        "token.json",
    }

    blocked_dirs = set(BLOCKED_DIRS) | {
        ".rag",
        ".memory",
        ".trash",
        ".ssh",
        ".gnupg",
    }

    try:
        rel_parts = set(path.relative_to(ROOT).parts)
    except Exception:
        return False

    if rel_parts.intersection(blocked_dirs):
        return False

    if path.name in blocked_names:
        return False

    allowed_suffixes = {
        ".txt",
        ".md",
        ".pdf",
        ".docx",
        ".py",
        ".sql",
        ".csv",
        ".json",
        ".yaml",
        ".yml",
        ".html",
        ".css",
        ".js",
        ".ts",
        ".ipynb",
    }

    return path.is_file() and path.suffix.lower() in allowed_suffixes


def _extract_text_for_rag(path: Path) -> str:
    suffix = path.suffix.lower()

    if suffix == ".pdf":
        try:
            from pypdf import PdfReader

            reader = PdfReader(str(path))
            pages = []

            for page in reader.pages:
                pages.append(page.extract_text() or "")

            return "\n".join(pages)

        except Exception as e:
            return f"[PDF extraction failed: {e}]"

    if suffix == ".docx":
        try:
            from docx import Document

            doc = Document(str(path))
            return "\n".join(p.text for p in doc.paragraphs)

        except Exception as e:
            return f"[DOCX extraction failed: {e}]"

    if suffix == ".ipynb":
        try:
            import json

            data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
            cells = []

            for cell in data.get("cells", []):
                source = cell.get("source", "")
                if isinstance(source, list):
                    source = "".join(source)
                cells.append(source)

            return "\n\n".join(cells)

        except Exception as e:
            return f"[Notebook extraction failed: {e}]"

    return path.read_text(encoding="utf-8", errors="replace")


def _chunk_text(text: str, chunk_chars: int = RAG_CHUNK_CHARS, overlap: int = RAG_CHUNK_OVERLAP) -> list[str]:
    text = text.strip()

    if not text:
        return []

    chunks = []
    start = 0

    while start < len(text):
        end = min(start + chunk_chars, len(text))
        chunk = text[start:end].strip()

        if chunk:
            chunks.append(chunk)

        if end >= len(text):
            break

        start = max(end - overlap, start + 1)

    return chunks


def _get_rag_device() -> str:
    """
    Choose CPU/GPU for embeddings.
    auto = cuda if available, else cpu.
    """
    if RAG_DEVICE == "cpu":
        return "cpu"

    if RAG_DEVICE == "cuda":
        return "cuda"

    try:
        import torch

        if torch.cuda.is_available():
            return "cuda"
    except Exception:
        pass

    return "cpu"


def _get_rag_embedder():
    global _RAG_EMBEDDER

    if _RAG_EMBEDDER is None:
        from sentence_transformers import SentenceTransformer

        device = _get_rag_device()

        _RAG_EMBEDDER = SentenceTransformer(
            RAG_EMBED_MODEL,
            device=device
        )

    return _RAG_EMBEDDER


def _get_rag_collection(reset: bool = False):
    import chromadb

    rag_path = safe_path(".rag/chroma")
    rag_path.mkdir(parents=True, exist_ok=True)

    client = chromadb.PersistentClient(path=str(rag_path))

    if reset:
        try:
            client.delete_collection(RAG_COLLECTION_NAME)
        except Exception:
            pass

    return client.get_or_create_collection(
        name=RAG_COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"}
    )


@mcp.tool()
def index_rag(path: str = "knowledge", reset: bool = False, max_files: int = 300) -> str:
    """
    Index files into local RAG vector database.
    Only indexes files inside AI-Workspace.
    Blocks secrets, .env, keys, .rag, .memory, .trash, system folders, and huge files.
    """
    import hashlib
    from datetime import datetime

    base = safe_path(path)

    if not base.exists():
        return f"Path not found: {path}"

    if not (base == ROOT or ROOT in base.parents):
        return "Blocked: path outside workspace."

    files = [base] if base.is_file() else list(base.rglob("*"))

    allowed_files = []

    for file in files:
        if len(allowed_files) >= max_files:
            break

        if not _is_rag_allowed_file(file):
            continue

        try:
            if file.stat().st_size > 5_000_000:
                continue
        except Exception:
            continue

        allowed_files.append(file)

    if not allowed_files:
        return "No indexable files found."

    embedder = _get_rag_embedder()
    collection = _get_rag_collection(reset=reset)

    ids = []
    documents = []
    metadatas = []

    indexed_files = 0
    indexed_chunks = 0

    for file in allowed_files:
        try:
            raw_text = _extract_text_for_rag(file)
        except Exception as e:
            raw_text = f"[Extraction failed: {e}]"

        raw_text = _redact_secrets(raw_text)

        if len(raw_text) > RAG_MAX_FILE_CHARS:
            raw_text = raw_text[:RAG_MAX_FILE_CHARS]

        chunks = _chunk_text(raw_text)

        if not chunks:
            continue

        rel = str(file.relative_to(ROOT))
        stat = file.stat()

        for i, chunk in enumerate(chunks):
            raw_id = f"{rel}:{i}:{stat.st_mtime}"
            chunk_id = hashlib.sha1(raw_id.encode("utf-8")).hexdigest()

            ids.append(chunk_id)
            documents.append(chunk)
            metadatas.append({
                "source": rel,
                "chunk": i,
                "file_name": file.name,
                "extension": file.suffix.lower(),
                "indexed_at": datetime.now().isoformat(timespec="seconds"),
            })

        indexed_files += 1
        indexed_chunks += len(chunks)

    if not documents:
        return "No text chunks created."

    embeddings = []

    for start in range(0, len(documents), RAG_BATCH_SIZE):
        batch = documents[start:start + RAG_BATCH_SIZE]

        batch_embeddings = embedder.encode(
            batch,
            normalize_embeddings=True,
            show_progress_bar=False,
            batch_size=RAG_BATCH_SIZE
        ).tolist()

        embeddings.extend(batch_embeddings)

    collection.upsert(
        ids=ids,
        documents=documents,
        metadatas=metadatas,
        embeddings=embeddings
    )

    return (
        f"RAG index updated.\n"
        f"Files indexed: {indexed_files}\n"
        f"Chunks indexed: {indexed_chunks}\n"
        f"Database: .rag/chroma\n"
        f"Collection: {RAG_COLLECTION_NAME}"
    )


@mcp.tool()
def search_rag(query: str, n_results: int = 5, source_filter: str = "") -> str:
    """
    Search local RAG knowledge base and return relevant chunks.
    Use this for resume, projects, docs, notes, interview questions, and job descriptions.
    """
    if not query.strip():
        return "Empty RAG query."

    n_results = max(1, min(n_results, 12))

    embedder = _get_rag_embedder()
    collection = _get_rag_collection(reset=False)

    query_embedding = embedder.encode(
        [query],
        normalize_embeddings=True,
        show_progress_bar=False,
	batch_size=1
    ).tolist()[0]

    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=n_results
    )

    docs = results.get("documents", [[]])[0]
    metas = results.get("metadatas", [[]])[0]
    distances = results.get("distances", [[]])[0]

    output = []

    for idx, doc in enumerate(docs):
        meta = metas[idx] if idx < len(metas) else {}
        distance = distances[idx] if idx < len(distances) else None
        source = meta.get("source", "unknown")

        if source_filter and source_filter.lower() not in source.lower():
            continue

        doc = _redact_secrets(doc)

        if len(doc) > 1200:
            doc = doc[:1200] + "\n...chunk truncated..."

        score_text = f"{distance:.4f}" if isinstance(distance, float) else "n/a"

        output.append(
            f"--- RESULT {idx + 1} ---\n"
            f"Source: {source}\n"
            f"Chunk: {meta.get('chunk', 'n/a')}\n"
            f"Distance: {score_text}\n"
            f"Content:\n{doc}"
        )

    return "\n\n".join(output) if output else "No relevant RAG results found."


@mcp.tool()
def add_job_description_to_rag(
    title: str,
    company: str,
    content: str,
    location: str = "",
    overwrite: bool = False
) -> str:
    """
    Save a job description into knowledge/job_descriptions, then it can be indexed with index_rag.
    """
    import re

    safe_title = re.sub(r"[^a-zA-Z0-9_-]+", "-", title.strip()).strip("-").lower()
    safe_company = re.sub(r"[^a-zA-Z0-9_-]+", "-", company.strip()).strip("-").lower()

    if not safe_title:
        safe_title = "job-description"

    if not safe_company:
        safe_company = "company"

    folder = safe_path("knowledge/job_descriptions")
    folder.mkdir(parents=True, exist_ok=True)

    file_path = safe_path(f"knowledge/job_descriptions/{safe_company}-{safe_title}.md")

    if file_path.exists() and not overwrite:
        return f"Job description already exists: {file_path.relative_to(ROOT)}"

    content = _redact_secrets(content)

    text = f"""# {title}

Company: {company}
Location: {location}

## Job Description

{content}
"""

    file_path.write_text(text, encoding="utf-8")

    return f"Saved job description: {file_path.relative_to(ROOT)}"


@mcp.tool()
def list_rag_sources() -> str:
    """
    List sources currently stored in the RAG vector DB.
    """
    collection = _get_rag_collection(reset=False)

    try:
        data = collection.get(include=["metadatas"])
    except Exception as e:
        return f"Failed to read RAG sources: {e}"

    metadatas = data.get("metadatas", [])

    sources = {}

    for meta in metadatas:
        source = meta.get("source", "unknown")
        sources[source] = sources.get(source, 0) + 1

    if not sources:
        return "No RAG sources found."

    output = ["RAG sources:"]

    for source, count in sorted(sources.items()):
        output.append(f"- {source}: {count} chunks")

    return "\n".join(output)


@mcp.tool()
def clear_rag(confirm_text: str = "") -> str:
    """
    Clear the local RAG vector database.
    Destructive action. Requires confirm_text='CLEAR_RAG'.
    """
    if confirm_text != "CLEAR_RAG":
        return "Clear RAG blocked. Call again with confirm_text='CLEAR_RAG' only if you are sure."

    _get_rag_collection(reset=True)

    return "RAG vector database cleared."


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, help="Allowed workspace root")
    args = parser.parse_args()

    set_root(args.root)
    mcp.run()
