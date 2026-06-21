#!/usr/bin/env python3

import os
import time
import yaml
import base64
import shlex
import mimetypes
import subprocess
from pathlib import Path

import fitz
from ddgs import DDGS
from openai import OpenAI


BASE_DIR = Path.home() / "local-mcp-agent"
PROMPT_FILE = BASE_DIR / "role_prompts.yaml"
LOG_DIR = BASE_DIR / "logs"

QWEN3_PORT = 8081
VL_PORT = 8082

QWEN3_MODEL = "qwen3-4b-instruct"
VL_MODEL = "qwen25-vl-3b-instruct"

LLAMA_SERVER = str(Path.home() / "llama.cpp/build/bin/llama-server")

LOG_DIR.mkdir(parents=True, exist_ok=True)


DEFAULT_SYSTEM_PROMPT = """
You are a local Qwen3 assistant.
Use normal chat for ordinary questions.
Use provided web search results when available.
Keep answers practical, clear, and useful.
"""


def load_roles():
    if not PROMPT_FILE.exists():
        raise FileNotFoundError(f"Missing role prompt file: {PROMPT_FILE}")

    with open(PROMPT_FILE, "r", encoding="utf-8") as f:
        roles = yaml.safe_load(f) or {}

    command_map = {}

    for role_name, data in roles.items():
        command = data.get("command")
        if command:
            command_map[command] = {
                "role_name": role_name,
                **data
            }

    return roles, command_map


ROLES, COMMAND_MAP = load_roles()


def build_help_text():
    lines = ["Available slash commands:\n"]

    for command, data in sorted(COMMAND_MAP.items()):
        description = data.get("description", "")
        handler = data.get("handler", "llm")

        if handler == "local":
            lines.append(f"{command:<14} {description}  [local]")
        elif data.get("requires_tool"):
            lines.append(f"{command:<14} {description}  [web]")
        else:
            lines.append(f"{command:<14} {description}")

    lines.append("\nVision / upload mode:")
    lines.append("+ /path/to/image.png explain this screenshot")
    lines.append("+ /path/to/file.pdf summarize this PDF")
    lines.append("\nNormal text uses Qwen3 4B.")
    lines.append("+ file mode uses Qwen2.5-VL 3B.")
    lines.append("Only one model runs at a time.")

    return "\n".join(lines)


def run_quiet(cmd):
    return subprocess.run(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )


def is_server_running(port: int) -> bool:
    result = run_quiet(["curl", "-s", f"http://127.0.0.1:{port}/v1/models"])
    return result.returncode == 0


def stop_server(port: int):
    subprocess.run(
        ["pkill", "-f", f"llama-server.*--port {port}"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    time.sleep(1)


def find_model_file(keywords):
    search_dirs = [
        str(Path.home() / ".lmstudio/models"),
        str(Path.home() / "Downloads"),
    ]

    for folder in search_dirs:
        if not os.path.exists(folder):
            continue

        for root, _, files in os.walk(folder):
            for file in files:
                lower = file.lower()
                if not file.endswith(".gguf"):
                    continue

                if all(k.lower() in lower for k in keywords):
                    return os.path.join(root, file)

    return ""


def get_qwen3_model_file():
    return (
        find_model_file(["qwen3", "4b", "q4_k_m"])
        or find_model_file(["qwen3", "4b"])
    )


def get_vl_model_file():
    return (
        find_model_file(["qwen2.5-vl", "3b", "q4"])
        or find_model_file(["qwen2.5", "vl", "3b"])
    )


def get_mmproj_file():
    return (
        find_model_file(["mmproj", "f16"])
        or find_model_file(["mmproj"])
    )


def start_qwen3_server():
    if is_server_running(QWEN3_PORT):
        return True

    if is_server_running(VL_PORT):
        print("Stopping Qwen2.5-VL to free GPU memory...")
        stop_server(VL_PORT)

    model_file = get_qwen3_model_file()

    if not model_file:
        print("Qwen3 4B GGUF model not found.")
        print("Search folders: ~/.lmstudio/models and ~/Downloads")
        return False

    print("Starting Qwen3 4B text model...")

    cmd = [
        LLAMA_SERVER,
        "-m", model_file,
        "--alias", QWEN3_MODEL,
        "-ngl", "999",
        "-c", "8192",
        "-t", "4",
        "-b", "128",
        "-ub", "128",
        "--host", "127.0.0.1",
        "--port", str(QWEN3_PORT),
    ]

    with open(LOG_DIR / "qwen3.log", "w") as log:
        subprocess.Popen(cmd, stdout=log, stderr=log)

    for _ in range(45):
        if is_server_running(QWEN3_PORT):
            print("Qwen3 ready ✅")
            return True
        time.sleep(1)

    print("Qwen3 did not start. Check:")
    print(LOG_DIR / "qwen3.log")
    return False


def start_vl_server():
    if is_server_running(VL_PORT):
        return True

    if is_server_running(QWEN3_PORT):
        print("Stopping Qwen3 to free GPU memory...")
        stop_server(QWEN3_PORT)

    model_file = get_vl_model_file()
    mmproj_file = get_mmproj_file()

    if not model_file:
        print("Qwen2.5-VL 3B GGUF model not found.")
        return False

    if not mmproj_file:
        print("Qwen2.5-VL mmproj file not found.")
        return False

    print("Starting Qwen2.5-VL image model...")

    cmd = [
        LLAMA_SERVER,
        "-m", model_file,
        "--mmproj", mmproj_file,
        "--alias", VL_MODEL,
        "-ngl", "999",
        "-c", "4096",
        "-t", "4",
        "-b", "128",
        "-ub", "128",
        "--host", "127.0.0.1",
        "--port", str(VL_PORT),
    ]

    with open(LOG_DIR / "qwen25_vl.log", "w") as log:
        subprocess.Popen(cmd, stdout=log, stderr=log)

    for _ in range(45):
        if is_server_running(VL_PORT):
            print("Qwen2.5-VL ready ✅")
            return True
        time.sleep(1)

    print("Qwen2.5-VL did not start. Check:")
    print(LOG_DIR / "qwen25_vl.log")
    return False


def qwen3_client():
    return OpenAI(
        base_url=f"http://127.0.0.1:{QWEN3_PORT}/v1",
        api_key="local"
    )


def vl_client():
    return OpenAI(
        base_url=f"http://127.0.0.1:{VL_PORT}/v1",
        api_key="local"
    )


def parse_slash_command(text: str):
    text = text.strip()

    if not text.startswith("/"):
        return None, text

    parts = text.split(maxsplit=1)
    command = parts[0].lower()
    body = parts[1].strip() if len(parts) > 1 else ""

    return command, body


def web_search(query: str, max_results: int = 5):
    results = []

    try:
        for item in DDGS().text(query, max_results=max_results):
            title = item.get("title", "").strip()
            url = item.get("href", "").strip()
            body = item.get("body", "").strip()

            results.append({
                "title": title,
                "url": url,
                "body": body
            })

    except Exception as e:
        return f"Web search failed: {e}"

    if not results:
        return "No web results found."

    formatted = []

    for i, item in enumerate(results, start=1):
        formatted.append(
            f"[{i}] {item['title']}\n"
            f"URL: {item['url']}\n"
            f"Snippet: {item['body']}"
        )

    return "\n\n".join(formatted)


def ask_qwen3(user_text: str, history: list):
    command, body = parse_slash_command(user_text)

    if command == "/help":
        return build_help_text()

    if command == "/clear":
        history.clear()
        return "Chat memory cleared ✅"

    if command in ["/exit", "/quit"]:
        return "__EXIT__"

    if command and command not in COMMAND_MAP:
        return f"Unknown command: {command}\n\nUse /help to see commands."

    if not start_qwen3_server():
        return "Qwen3 server could not start."

    if command:
        role_data = COMMAND_MAP[command]
        system_prompt = role_data.get("system_prompt", DEFAULT_SYSTEM_PROMPT)
        requires_tool = bool(role_data.get("requires_tool", False))
        tool_type = role_data.get("tool_type", "")
        user_query = body
    else:
        system_prompt = ROLES.get("chat", {}).get("system_prompt", DEFAULT_SYSTEM_PROMPT)
        requires_tool = False
        tool_type = ""
        user_query = user_text

    if command == "/jobs" and not user_query:
        user_query = (
            "latest entry level software engineer, data analyst, data engineer, "
            "data scientist fresher jobs for 2025 graduate in India remote, "
            "Bangalore, Chennai, Coimbatore, Hyderabad"
        )

    if requires_tool and tool_type == "web_search":
        if not user_query:
            return f"Use it like this:\n{command} your search query"

        search_results = web_search(user_query)

        user_query = f"""
User query:
{user_query}

Web search results:
{search_results}

Instructions:
Answer using the web search results. Cite using source numbers like [1], [2], [3].
Do not invent details that are not present in the results.
"""

    messages = [
        {
            "role": "system",
            "content": system_prompt
        }
    ]

    messages.extend(history[-8:])
    messages.append({"role": "user", "content": user_query})

    response = qwen3_client().chat.completions.create(
        model=QWEN3_MODEL,
        messages=messages,
        temperature=0.4,
        max_tokens=1500,
    )

    return response.choices[0].message.content.strip()


def encode_image_to_data_url(path: str):
    mime, _ = mimetypes.guess_type(path)

    if not mime:
        mime = "image/png"

    with open(path, "rb") as f:
        data = base64.b64encode(f.read()).decode("utf-8")

    return f"data:{mime};base64,{data}"


def extract_pdf_text(path: str, max_pages: int = 8):
    doc = fitz.open(path)
    pages = []

    for i, page in enumerate(doc):
        if i >= max_pages:
            break

        text = page.get_text().strip()

        if text:
            pages.append(f"--- Page {i + 1} ---\n{text}")

    return "\n\n".join(pages).strip()


def ask_vl(file_path: str, prompt: str):
    if not start_vl_server():
        return "Qwen2.5-VL server could not start."

    ext = Path(file_path).suffix.lower()

    if ext == ".pdf":
        pdf_text = extract_pdf_text(file_path)

        if not pdf_text:
            pdf_text = "No selectable text found. This may be a scanned/image-based PDF."

        user_content = f"""
PDF content:
{pdf_text}

Task:
{prompt}
"""

        response = vl_client().chat.completions.create(
            model=VL_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": "You analyze PDFs and documents clearly."
                },
                {
                    "role": "user",
                    "content": user_content
                },
            ],
            temperature=0.3,
            max_tokens=1500,
        )

        return response.choices[0].message.content.strip()

    image_url = encode_image_to_data_url(file_path)

    response = vl_client().chat.completions.create(
        model=VL_MODEL,
        messages=[
            {
                "role": "system",
                "content": "You analyze images, screenshots, UI errors, charts, and visual documents clearly."
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": prompt or "Analyze this image clearly."
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": image_url
                        }
                    },
                ],
            },
        ],
        temperature=0.3,
        max_tokens=1500,
    )

    return response.choices[0].message.content.strip()


def handle_plus_command(user_text: str):
    text = user_text[1:].strip()

    if not text:
        return "Use it like this:\n+ /path/to/image.png explain this screenshot"

    try:
        parts = shlex.split(text)
    except Exception:
        return "Invalid + command. Use:\n+ /path/to/image.png explain this screenshot"

    if not parts:
        return "Use it like this:\n+ /path/to/image.png explain this screenshot"

    file_path = os.path.expanduser(parts[0])
    prompt = " ".join(parts[1:]).strip() or "Analyze this file clearly."

    if not os.path.exists(file_path):
        return f"File not found:\n{file_path}"

    return ask_vl(file_path, prompt)


def main():
    print("\nQwen3 local assistant ready ✅")
    print("Use /help to see YAML-loaded commands.")
    print("Normal text and /commands use Qwen3.")
    print("+ image/pdf uses Qwen2.5-VL.")
    print("Only one model runs at a time.\n")

    history = []

    while True:
        try:
            user_text = input("qwen3> ").strip()
        except KeyboardInterrupt:
            print("\nBye 👋")
            break

        if not user_text:
            continue

        if user_text.lower() in ["/exit", "exit", "quit", "/quit"]:
            print("Bye 👋")
            break

        try:
            if user_text.startswith("+"):
                answer = handle_plus_command(user_text)
            else:
                answer = ask_qwen3(user_text, history)

                if answer == "__EXIT__":
                    print("Bye 👋")
                    break

                if not user_text.startswith("/help") and not user_text.startswith("/clear"):
                    history.append({"role": "user", "content": user_text})
                    history.append({"role": "assistant", "content": answer})

            print("\n" + answer + "\n")

        except Exception as e:
            print(f"\nError: {e}\n")


if __name__ == "__main__":
    main()
