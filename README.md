# Hermes — Local Low-Context MCP Agent

Hermes is a local AI assistant/agent setup built for running small and medium local models efficiently on a laptop.

It combines:

* Local LLM using `llama.cpp`
* Custom low-context MCP filesystem server
* Safe file tools
* Long-term Markdown memory
* Local RAG/vector search for resume, projects, notes, and job descriptions
* Safety rules for local automation
* Optional GPU/CPU embedding control

This project is designed for users who want a private, local AI assistant that can work with files, summarize folders, search notes, generate resume bullets, and answer questions using local documents.

---

## Features

### Core File Tools

* List files and folders
* Read file chunks
* Write files
* Search text inside files
* Move files safely
* Move files/folders to trash instead of permanent delete
* Summarize folders
* Create starter projects

### Local AI Agent Tools

* Run safe shell commands
* Explain pasted error text
* Generate resume bullets
* Search project notes
* Search resume/project documents using RAG
* Save and read long-term memory

### RAG Knowledge Search

Use RAG for:

* Resume
* Project reports
* Linux notes
* Python notes
* SQL notes
* Interview questions
* Job descriptions

RAG flow:

```text
Files → chunks → embeddings → vector database → relevant context → local model
```

---

## Recommended Hardware

This project is designed to run on modest local hardware.

Recommended minimum:

```text
RAM: 16GB
Swap: 8GB+
GPU: Optional NVIDIA GPU
Storage: SSD recommended
OS: Linux/Ubuntu recommended
```

Example tested target:

```text
NVIDIA GTX 1650 4GB VRAM
16GB RAM
Ubuntu Linux
llama.cpp
GGUF local models
```

---

## Recommended Local Models

Good local model options:

```text
Hermes 3 Llama 3.1 8B Q4_K_M
Qwen 2.5 Coder 7B Q4_K_M
Qwen 2.5 Coder 3B Q4_K_M
Qwen3 4B Q4_K_M
Qwen2.5-VL for vision tasks
```

Recommended usage:

| Use Case                | Model                 |
| ----------------------- | --------------------- |
| Reliable agent/tool use | Hermes 3 Llama 3.1 8B |
| Coding assistant        | Qwen 2.5 Coder 7B     |
| Faster coding           | Qwen 2.5 Coder 3B     |
| General assistant       | Qwen3 4B              |
| Image/vision tasks      | Qwen2.5-VL            |

---

## Project Structure

```text
Hermes/
├── README.md
├── requirements.txt
├── .gitignore
├── .env.example
├── local_mcp_agent.py
├── lowctx_fs_server.py
├── scripts/
│   ├── run_agent.sh
│   ├── run_hermes_server.sh
│   └── index_rag.sh
├── docs/
│   ├── 01-installation.md
│   ├── 02-mcp-filesystem.md
│   ├── 03-long-term-memory.md
│   ├── 04-rag-setup.md
│   ├── 05-safety-rules.md
│   └── 06-troubleshooting.md
└── examples/
    ├── rk_profile.md
    └── prompts.md
```

---

## Private Files Warning

Do **not** commit these files or folders:

```text
.env
.venv/
models/
*.gguf
*.bin
*.safetensors
.rag/
.memory/
.trash/
AI-Workspace/
```

Your model files, local workspace, memory, and RAG database should stay private.

---

## Installation

Clone the repository:

```bash
git clone https://github.com/YOUR_USERNAME/Hermes.git
cd Hermes
```

Create a Python virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

---

## Requirements

Example `requirements.txt`:

```text
openai
rich
mcp[cli]
chromadb
sentence-transformers
pypdf
python-docx
torch
```

---

## Environment Setup

Copy the example environment file:

```bash
cp .env.example .env
```

Example `.env.example`:

```env
AI_WORKSPACE=/path/to/your/AI-Workspace
LOCAL_MODEL_NAME=hermes
LOCAL_LLM_BASE_URL=http://127.0.0.1:8080/v1
RAG_DEVICE=auto
RAG_BATCH_SIZE=16
```

Important:

```text
.env should stay private.
.env.example can be committed.
```

---

## Workspace Setup

Create your private local workspace outside the GitHub repo:

```bash
mkdir -p ~/AI-Workspace/projects
mkdir -p ~/AI-Workspace/notes
mkdir -p ~/AI-Workspace/knowledge/resume
mkdir -p ~/AI-Workspace/knowledge/projects
mkdir -p ~/AI-Workspace/knowledge/linux
mkdir -p ~/AI-Workspace/knowledge/python
mkdir -p ~/AI-Workspace/knowledge/sql
mkdir -p ~/AI-Workspace/knowledge/interview
mkdir -p ~/AI-Workspace/knowledge/job_descriptions
mkdir -p ~/AI-Workspace/.memory
mkdir -p ~/AI-Workspace/.rag
mkdir -p ~/AI-Workspace/.trash
```

Recommended workspace structure:

```text
AI-Workspace/
├── projects/
├── notes/
├── knowledge/
│   ├── resume/
│   ├── projects/
│   ├── linux/
│   ├── python/
│   ├── sql/
│   ├── interview/
│   └── job_descriptions/
├── .memory/
├── .rag/
└── .trash/
```

---

## Run Local Model Server

Start your local model using `llama.cpp`.

Notes:

* Keep this terminal open.
* Do not commit your model path.
* Use `.env` or local scripts for private paths.

---

## Run Hermes Agent

In another terminal:

```bash
cd Hermes
source .venv/bin/activate

python local_mcp_agent.py \
  --root /path/to/your/AI-Workspace \
  --model hermes3
```

Example prompt:

```text
list files in workspace
```

---

## Long-Term Memory

Small local models forget quickly, so Hermes uses Markdown memory files.

Memory types:

```text
Short-term memory  = current chat
Long-term memory   = Markdown notes
Knowledge memory   = RAG/vector database
Tool memory        = command history and project summaries
```

Recommended memory files:

```text
AI-Workspace/.memory/
├── profile.md
├── active_projects.md
├── command_history.md
└── project_summaries.md
```

Example profile:

```md
# User Profile

- 2025 graduate.
- Looking for software engineer, data analyst, data engineer, and data scientist roles.
- Skills: Python, SQL, Power BI, ETL, Linux, GitHub, data engineering.
- Preferred job locations: remote, Bangalore, Chennai, Coimbatore, Hyderabad.
```

---

## RAG Setup

Hermes supports local RAG using:

```text
ChromaDB + SentenceTransformers
```

Install RAG packages:

```bash
pip install chromadb sentence-transformers pypdf python-docx
```

Add documents into:

```text
AI-Workspace/knowledge/
├── resume/
├── projects/
├── linux/
├── python/
├── sql/
├── interview/
└── job_descriptions/
```

Then ask Hermes:

```text
index my knowledge folder for RAG
```

Or:

```text
Use index_rag on knowledge with reset false
```

Search examples:

```text
search my RAG for ServerLogLake project
what projects in my resume are best for data engineer jobs?
search my interview notes for SQL joins
compare this job description with my resume
generate resume bullets using my project docs
```

---

## RAG Device Control

The embedding model can run on CPU or GPU depending on your PyTorch setup.

Set permanent defaults:

```bash
echo 'export RAG_DEVICE=auto' >> ~/.bashrc
echo 'export RAG_BATCH_SIZE=16' >> ~/.bashrc
source ~/.bashrc
```

Modes:

```text
RAG_DEVICE=auto  → use CUDA if available, otherwise CPU
RAG_DEVICE=cpu   → force CPU embeddings
RAG_DEVICE=cuda  → force GPU embeddings
```

Recommended:

```text
Use auto for normal use.
Use CPU if your local LLM already uses most GPU VRAM.
Use CUDA only when enough GPU memory is available.
```

---

## Safety Rules

Hermes must follow these rules:

```text
- Only work inside the configured AI workspace.
- Never edit system folders.
- Never run rm -rf automatically.
- Never run sudo automatically.
- Never expose secrets, API keys, tokens, passwords, or private keys.
- Never execute unknown curl | bash or wget | bash commands.
- Ask before destructive actions.
- Use move_to_trash by default for delete/remove requests.
- Use permanent delete only when the user clearly asks for permanent deletion.
- Do not use shell commands when an MCP file tool can do the same task.
```

Blocked/private examples:

```text
.env
.ssh/
.gnupg/
API keys
tokens
passwords
private keys
model files
RAG database
memory files
```

---

## Example Prompts

```text
list files in workspace
```

```text
read notes/todo.md
```

```text
create a python project named mcp-demo
```

```text
summarize folder projects/mcp-demo
```

```text
search text TODO in projects
```

```text
move notes/old.txt to trash
```

```text
explain this error: TabError inconsistent use of tabs and spaces in indentation
```

```text
generate resume bullet for ServerLogLake using Python, PostgreSQL, MinIO, Docker, Prefect, and Power BI
```

```text
search my RAG for Python SQL Power BI resume projects
```

```text
what projects in my resume are best for data engineer jobs?
```

---

## Troubleshooting

### MCP Error: Connection closed

Usually the MCP server crashed.

Check syntax:

```bash
python -m py_compile lowctx_fs_server.py
python -m py_compile local_mcp_agent.py
```

---

### Python TabError

Error:

```text
TabError: inconsistent use of tabs and spaces in indentation
```

Fix:

```bash
python - <<'PY'
from pathlib import Path

for file in ["local_mcp_agent.py", "lowctx_fs_server.py"]:
    p = Path(file)
    text = p.read_text()
    text = text.replace("\t", "    ")
    p.write_text(text)

print("Converted tabs to spaces.")
PY
```

Then:

```bash
python -m py_compile local_mcp_agent.py
```

---

### Extra data: line 2 column 1

This happens when the local model returns more than one JSON object.

Fix:

* Force the model to return exactly one JSON object.
* Use a robust JSON extractor.
* Lower temperature.

---

### Context size exceeded

The model received too much text.

Fix:

```text
- Read smaller file chunks.
- Use search_text instead of reading full files.
- Use RAG for documents.
- Avoid sending full workspace context.
- Reduce tool result size.
```

---

### Embedding model is slow

Use:

```bash
export RAG_DEVICE=auto
export RAG_BATCH_SIZE=16
```

If GPU memory is full, use:

```bash
export RAG_DEVICE=cpu
export RAG_BATCH_SIZE=8
```

---

## GitHub Safety

Before pushing:

```bash
git status
```

Check ignored files:

```bash
git check-ignore -v .env
git check-ignore -v models/example.gguf
git check-ignore -v AI-Workspace/
```

Commit safe files only:

```bash
git add README.md requirements.txt .gitignore .env.example local_mcp_agent.py lowctx_fs_server.py scripts docs examples
git commit -m "Initial commit: Hermes local MCP agent"
git push
```

If you accidentally committed secrets:

```text
1. Remove the secret from the repo.
2. Remove it from Git history.
3. Force push.
4. Rotate/change the leaked secret immediately.
```

---

## Roadmap

Planned improvements:

* Better tool-call JSON parser
* SQLite long-term memory
* Better RAG document refresh
* Project-specific memory
* Local web UI
* Optional voice assistant
* Optional vision model support
* GitHub issue/job-description assistant
* Resume/job matching workflow

---

## License

MIT License

---

## Disclaimer

Hermes is a local automation assistant. Always review file edits, shell commands, and delete operations before allowing execution.

Do not use this project to store or expose secrets, credentials, private keys, or sensitive personal data.
