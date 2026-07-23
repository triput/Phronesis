# Workspace Rules

## Code Quality & Engineering Standards

- Always write comprehensive module/function docstrings and strategic inline business-logic comments.
- Never push incomplete code loops; run local test passes before declaring a task finished.

## File Header Automation

- For all core or "Gold Master" files, always prepend this exact file header format:

# ==============================================================================

# File: [File Path]

# Description: [Brief description of functionality]

# Component: [Architecture layer]

# Version: 1.0 (Gold Master)

# Created: [YYYY-MM-DD]



# Last Update: [YYYY-MM-DD]



# ==============================================================================



## Documentation sync

- **Phase gate:** Documentation is mandatory before Delivery — Renee test delta → Page sync → Steve land. See [docs/DOC_SYNC.md](docs/DOC_SYNC.md) (triggers, checklist) and [docs/MULTI_AGENT_SYSTEM_PROMPT.md](docs/MULTI_AGENT_SYSTEM_PROMPT.md) (agent roster, gates).
- Page owns markdown truth, inventory regen (`tool/generate_test_inventory.py`), Gold Master headers, and DEFECTS hygiene — not drive-by doc marathons on every commit.
- **Never push secrets / local runtime:** see [docs/DO_NOT_COMMIT.md](docs/DO_NOT_COMMIT.md).



## Execution Policy

- Terminal: Request human review before running any mutating shell commands or script executions.
- File Management: Always present a clear implementation plan before performing multi-file refactors or destructive deletions.
- Sandbox Init: Whenever initializing a new cloud container, run `python3 validate_sandbox.py` first and resolve any critical environment failures before beginning development.

