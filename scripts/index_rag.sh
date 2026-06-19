#!/usr/bin/env bash
set -e

cd ~/local-mcp-agent
source .venv/bin/activate

export RAG_DEVICE=${RAG_DEVICE:-auto}
export RAG_BATCH_SIZE=${RAG_BATCH_SIZE:-16}

echo "Start your agent and ask:"
echo "Use index_rag on knowledge with reset false"
