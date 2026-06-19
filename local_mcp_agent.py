import argparse
import asyncio
import json
import sys
from typing import Any, Dict, List

from openai import OpenAI
from rich.console import Console

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

console = Console()

MAX_MODEL_STEPS = 3
MAX_TOOL_RESULT_CHARS = 5000
MAX_HISTORY_MESSAGES = 8

AUTO_FINAL_TOOLS = {
    "list_dir",
    "tree",
    "read_file",
    "search_text",
    "write_file",
    "replace_text",
    "move_file",
    "move_to_trash",
    "delete_file",
    "delete_empty_directory",
    "delete_directory_tree",
    "run_safe_shell",
    "create_project",
    "summarize_folder",
    "generate_resume_bullet",
    "explain_error_text",
    "read_memory",
    "append_memory",
    "search_memory",
    "summarize_memory",
    "index_rag",
    "add_job_description_to_rag",
    "list_rag_sources",
    "clear_rag",
}

SYSTEM_PROMPT = """
You are a low-context local AI coding/filesystem assistant.

You must be efficient because the local model has limited context.

Rules:
1. Never ask for the full workspace.
2. Use tree or list_dir first.
3. Use search_text to find exact files/content.
4. Use read_file with small line ranges only.
5. Use replace_text for small edits.
6. Use write_file for new files.
7. Return ONLY valid JSON. No markdown.
8. Use only available MCP tool names. Never invent shell commands like mv, cp, rm, cat, ls.

Tool calling rules:
9. To move files, use move_file.
10. When moving to a folder, use destination like "test/" only. Do not append the filename yourself. The move_file tool will handle that.
11. For delete operations, first list or inspect the target path.
12. Never delete workspace root.
13. For delete_file, use confirm=true only when user clearly asks to delete.
14. For delete_directory_tree, use confirm_text="DELETE" only when user clearly asks recursive delete.
15. When the user asks to delete, remove, clear, or get rid of a file/folder, do NOT permanently delete it by default.
16. Use move_to_trash for normal delete/remove requests.
17. Before moving anything to trash, inspect the target using list_dir or get_file_info if available.
18. Never move the workspace root to trash.
19. Never move important hidden folders like .git, .venv, node_modules, or .trash unless the user explicitly gives the exact path.
20. After moving to trash, tell the user the original path and trash destination.
21. For any delete/remove request, always prefer move_to_trash instead of delete_file or delete_directory_tree.
22. Use permanent delete tools only when the user clearly says: "delete permanently", "remove forever", or "recursive delete permanently".
23. After receiving TOOL_RESULT, do not call the same tool again with the same args.
24. If the tool result answers the user request, immediately return {"final":"answer here"}.
25. For simple list/show requests, call list_dir once, then return final using the TOOL_RESULT.

Memory rules:
26. Use long-term memory only when relevant to the user's request.
27. Never store secrets, API keys, passwords, tokens, private keys, or credentials in memory.
28. If the user says remember/save/note this, use append_memory.
29. For job/profile/preferences memory, save to rk_profile.md.
30. For project progress, save to active_projects.md or project_summaries.md.
31. For useful command history, save to command_history.md.
32. Do not expose full memory unless the user asks to read memory.

RAG rules:
33. Use search_rag before answering questions about resume, projects, reports, notes, interview questions, job descriptions, Linux notes, Python notes, SQL notes, or saved documents.
34. Use index_rag only when the user asks to index, refresh, update, or rebuild knowledge.
35. Never index system folders.
36. Never index secrets, API keys, passwords, tokens, private keys, .env files, .ssh files, or credentials.
37. Use add_job_description_to_rag when the user pastes a job description and asks to save/analyze it.
38. Use list_rag_sources to check what is indexed.
39. Use clear_rag only when the user clearly asks to clear/delete the RAG database.
40. For resume/project matching, search RAG for both the user profile/project and the job description before generating final advice.
41. Do not expose full retrieved chunks unless the user asks. Summarize relevant parts.
42. Return exactly ONE JSON object per response.
43. Never return two JSON objects.
44. Never return a tool call and final answer together.
45. First call the tool, wait for TOOL_RESULT, then return final.
46. If you need RAG, call search_rag first. After TOOL_RESULT, return final.
47. Do not call search_rag again with the same query.
48. For index_rag, list_rag_sources, clear_rag, create_project, summarize_folder, write_file, move_file, and move_to_trash, return the tool call only.
49. Never put raw multiline text directly inside JSON strings. If giving a final answer, keep it short.

Core safety rules:
- Only work inside /home/rk/AI-Workspace.
- You should not do anything outside the AI-Workspace.
- Never edit system folders.
- Never access or modify /, /etc, /usr, /bin, /boot, /var, /root, ~/.ssh, ~/.gnupg, or ~/.config.
- Never run rm -rf automatically.
- Never run sudo automatically.
- Never expose secrets, API keys, tokens, passwords, .env values, private keys, or credentials.
- If tool output contains secrets, summarize and redact them.
- Never execute unknown curl | bash, wget | bash, remote install scripts, or piped network commands.
- Ask before destructive actions.
- For delete/remove requests, use move_to_trash by default.
- Use permanent delete only when the user clearly says delete permanently/remove forever.
- Use run_safe_shell only for safe read/test commands.
- For commands like python, node, npm, pytest, use confirm=true only after the user clearly approves.
- Do not use shell commands when an MCP file tool can do the same task.
- For screenshots, ask the user to paste the error text unless a vision model is connected.

Available response formats:

To call a tool:
{
  "tool": "tool_name",
  "args": {
    "key": "value"
  }
}

To answer the user:
{
  "final": "your final answer"
}

Good examples:
{"tool":"list_dir","args":{"path":"."}}
{"tool":"tree","args":{"path":"projects","max_depth":2}}
{"tool":"read_file","args":{"path":"notes/todo.md","start_line":1,"max_lines":80}}
{"tool":"search_text","args":{"query":"TODO","path":"."}}
{"tool":"write_file","args":{"path":"notes/test.txt","content":"hello","overwrite":false}}
{"tool":"replace_text","args":{"path":"notes/todo.md","old":"old text","new":"new text"}}
{"tool":"move_file","args":{"source":"test/sample-test.txt","destination":"projects/"}}
{"tool":"delete_file","args":{"path":"notes/old.txt","confirm":true}}
{"tool":"delete_empty_directory","args":{"path":"old_folder","confirm":true}}
{"tool":"delete_directory_tree","args":{"path":"old_project","confirm_text":"DELETE"}}
{"tool":"move_to_trash","args":{"path":"notes/old.txt"}}
{"tool":"move_to_trash","args":{"path":"projects/test-folder"}}
{"tool":"run_safe_shell","args":{"command":"ls -la","cwd":".","confirm":false}}
{"tool":"run_safe_shell","args":{"command":"pytest","cwd":"projects/my-python-app","confirm":true}}
{"tool":"create_project","args":{"name":"portfolio-api","project_type":"python","description":"Flask API project","overwrite":false}}
{"tool":"summarize_folder","args":{"path":"projects/portfolio-api","max_files":80}}
{"tool":"generate_resume_bullet","args":{"project_name":"ServerLogLake","role_target":"Data Engineer","tech_stack":"Python, PostgreSQL, MinIO, Docker, Prefect, Power BI","work_done":"built an ETL pipeline and dashboard","impact":"data monitoring and reporting","metric":"processed 200+ server logs"}}
{"tool":"explain_error_text","args":{"error_text":"TabError: inconsistent use of tabs and spaces in indentation","context":"Python MCP agent"}}
{"tool":"read_memory","args":{"name":"rk_profile.md"}}
{"tool":"append_memory","args":{"name":"rk_profile.md","category":"Profile","note":"User prefers remote, Bangalore, Chennai, Coimbatore, and Hyderabad jobs."}}
{"tool":"search_memory","args":{"query":"Python"}}
{"tool":"summarize_memory","args":{}}
{"tool":"index_rag","args":{"path":"knowledge","reset":false,"max_files":300}}
{"tool":"search_rag","args":{"query":"ServerLogLake ETL pipeline Power BI dashboard","n_results":5}}
{"tool":"search_rag","args":{"query":"Python SQL Power BI resume projects","n_results":5,"source_filter":"resume"}}
{"tool":"add_job_description_to_rag","args":{"title":"Data Analyst Fresher","company":"Example Company","content":"Job description text here","location":"Bangalore","overwrite":false}}
{"tool":"list_rag_sources","args":{}}
{"tool":"clear_rag","args":{"confirm_text":"CLEAR_RAG"}}
{"final":"Done."}
"""


def extract_json(text: str) -> Dict[str, Any]:
    """
    Extract the first valid JSON object from model output.
    Handles markdown fences, extra text, and multiple JSON objects.
    """
    text = text.strip()

    if text.startswith("```"):
        text = text.replace("```json", "").replace("```", "").strip()

    decoder = json.JSONDecoder()

    try:
        obj, _ = decoder.raw_decode(text)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass

    first_brace = text.find("{")

    if first_brace == -1:
        raise ValueError(f"Model did not return JSON:\n{text}")

    text_from_json = text[first_brace:]

    try:
        obj, _ = decoder.raw_decode(text_from_json)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError as e:
        raise ValueError(f"Model did not return valid JSON:\n{text}\n\nError: {e}")

    raise ValueError(f"JSON found but it was not an object:\n{text}")


def tool_result_to_text(result: Any) -> str:
    parts = []

    for item in getattr(result, "content", []):
        text = getattr(item, "text", None)
        if text:
            parts.append(text)

    output = "\n".join(parts)

    if len(output) > MAX_TOOL_RESULT_CHARS:
        output = output[:MAX_TOOL_RESULT_CHARS] + "\n...tool result truncated..."

    return output


def trim_messages(messages: List[Dict[str, str]]) -> List[Dict[str, str]]:
    system = messages[0]
    rest = messages[1:]

    trimmed = rest[-MAX_HISTORY_MESSAGES:]

    for msg in trimmed:
        if len(msg["content"]) > 3500:
            msg["content"] = msg["content"][:3500] + "\n...message truncated..."

    return [system] + trimmed


def load_long_term_memory(root: str) -> str:
    """
    Load small long-term memory summary from AI-Workspace/.memory.
    Keeps memory short so local models do not exceed context.
    """
    from pathlib import Path

    memory_dir = Path(root).expanduser().resolve() / ".memory"

    if not memory_dir.exists():
        return "No long-term memory found."

    memory_files = [
        memory_dir / "rk_profile.md",
        memory_dir / "active_projects.md",
        memory_dir / "command_history.md",
        memory_dir / "project_summaries.md",
    ]

    chunks = []

    for file in memory_files:
        if file.exists() and file.is_file():
            text = file.read_text(encoding="utf-8", errors="replace").strip()

            if len(text) > 1500:
                text = text[:1500] + "\n...memory file truncated..."

            chunks.append(f"## {file.name}\n{text}")

    if not chunks:
        return "No long-term memory found."

    memory_text = "\n\n".join(chunks)

    if len(memory_text) > 4000:
        memory_text = memory_text[:4000] + "\n...long-term memory truncated..."

    return memory_text


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/home/rk/AI-Workspace")
    parser.add_argument("--base-url", default="http://127.0.0.1:8080/v1")
    parser.add_argument("--model", default="hermes3")
    args = parser.parse_args()

    llm = OpenAI(
        base_url=args.base_url,
        api_key="local",
    )

    server_params = StdioServerParameters(
        command=sys.executable,
        args=[
            "lowctx_fs_server.py",
            "--root",
            args.root,
        ],
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = await session.list_tools()
            tool_names = [tool.name for tool in tools.tools]

            console.print("[green]Low-context MCP agent ready.[/green]")
            console.print(f"[cyan]Workspace:[/cyan] {args.root}")
            console.print(f"[cyan]Model:[/cyan] {args.model}")
            console.print(f"[cyan]Tools:[/cyan] {', '.join(tool_names)}")
            console.print("Type [bold]exit[/bold] to quit.\n")

            while True:
                user_input = input("you> ").strip()

                if user_input.lower() in {"exit", "quit"}:
                    break

                long_term_memory = load_long_term_memory(args.root)

                memory_prompt = (
                    SYSTEM_PROMPT
                    + "\n\nLong-term memory:\n"
                    + long_term_memory
                    + "\n\nUse long-term memory only when relevant. "
                    + "Do not expose secrets. "
                    + "Do not store sensitive data unless the user clearly asks."
                )

                messages = [
                    {"role": "system", "content": memory_prompt},
                    {"role": "user", "content": user_input},
                ]

                seen_actions = set()
                last_tool_result = ""

                for step in range(MAX_MODEL_STEPS):
                    messages = trim_messages(messages)

                    response = llm.chat.completions.create(
                        model=args.model,
                        messages=messages,
                        temperature=0.1,
                        max_tokens=600,
                    )

                    raw = response.choices[0].message.content or ""

                    try:
                        action = extract_json(raw)
                    except Exception as e:
                        console.print("[red]Model returned invalid JSON.[/red]")

                        if last_tool_result:
                            console.print("\n[bold green]assistant>[/bold green]")
                            console.print(last_tool_result)
                            console.print()
                        else:
                            console.print(f"[red]{e}[/red]")

                        break

                    if "final" in action:
                        console.print(f"\n[bold green]assistant>[/bold green] {action['final']}\n")
                        break

                    tool_name = action.get("tool")
                    tool_args = action.get("args", {})

                    action_key = json.dumps(
                        {
                            "tool": tool_name,
                            "args": tool_args,
                        },
                        sort_keys=True,
                    )

                    if action_key in seen_actions:
                        console.print("\n[bold green]assistant>[/bold green]")
                        console.print(
                            last_tool_result
                            if last_tool_result
                            else "The tool already ran, but no result was captured."
                        )
                        console.print()
                        break

                    seen_actions.add(action_key)

                    if tool_name not in tool_names:
                        console.print(f"[red]Unknown tool:[/red] {tool_name}")
                        break

                    console.print(f"[yellow]tool>[/yellow] {tool_name} {tool_args}")

                    result = await session.call_tool(tool_name, tool_args)
                    result_text = tool_result_to_text(result)
                    last_tool_result = result_text

                    if tool_name in AUTO_FINAL_TOOLS:
                        console.print("\n[bold green]assistant>[/bold green]")
                        console.print(result_text if result_text else "Done.")
                        console.print()
                        break

                    messages.append(
                        {
                            "role": "assistant",
                            "content": json.dumps(action),
                        }
                    )

                    messages.append(
                        {
                            "role": "user",
                            "content": (
                                f"TOOL_RESULT from {tool_name}:\n"
                                f"{result_text}\n\n"
                                "Continue. Return ONLY JSON."
                            ),
                        }
                    )
                else:
                    console.print("[red]Stopped: too many tool steps.[/red]")


if __name__ == "__main__":
    asyncio.run(main())
