#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
TREE_SITTER_DIR=$(dirname "$SCRIPT_DIR")
GRAMMAR_DIR="$TREE_SITTER_DIR/tree-sitter-c"

if [ ! -d "$GRAMMAR_DIR" ]; then
    git clone --depth 1 --branch v0.20.8 \
        https://github.com/tree-sitter/tree-sitter-c.git "$GRAMMAR_DIR"
fi

cd "$TREE_SITTER_DIR"
python3 parser/build.py
