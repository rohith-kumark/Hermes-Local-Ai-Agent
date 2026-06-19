#!/usr/bin/env bash
set -e

cd ~/local-mcp-agent
source .venv/bin/activate

export RAG_DEVICE=${RAG_DEVICE:-auto}
export RAG_BATCH_SIZE=${RAG_BATCH_SIZE:-16}

python local_mcp_agent.py \
  --root /home/rk/AI-Workspace \
  --model hermes
