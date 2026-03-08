# AGENTS.md

## Purpose
- This repository is for controlling a fan through Nature Remo using both the Cloud API and the Local API.
- Treat the repository as a mix of operational scripts and IR-analysis notes, not as a reusable library.

## Repo Map
- `cloud_send_signal.py`: send a registered Nature Remo cloud signal by name or id.
- `dump_local_message.py`: poll the Nature Remo Local API and print received IR messages.
- `analyze_ir_dump.py`: decode captured IR payloads and compare message groups.
- `send_bruteforce_cmd.py`: send generated IR frames across a byte range for command exploration.
- `docs/`: working notes and analysis reports, especially `docs/ir-analysis.md`.
- `dump-results.txt` and `tmp/`: scratch data; inspect before changing anything that depends on them.

## Environment
- Use Python 3.12+.
- Prefer `uv run python ...` for script execution.
- Load configuration from `.env`.
- Relevant variables:
  - `NATURE_REMO_TOKEN`
  - `NATURE_REMO_API_TOKEN`
  - `NATURE_REMO_LOCAL_IP_ADDRESS`
  - `REMO_IP`

## Safety Rules
- Start with read-only inspection of scripts and docs before changing behavior.
- Do not run scripts that send IR commands, poll live devices for long periods, or brute-force command ranges unless the user explicitly asks.
- Treat `cloud_send_signal.py`, `send_bruteforce_cmd.py`, and Local API send flows as device-affecting operations.
- Avoid changing `.env`, captured data files, or scratch outputs unless the task is specifically about them.

## Change Conventions
- Keep edits narrow and aligned with the existing simple script style.
- Prefer small script-level changes over broad refactors.
- Preserve Japanese domain terminology already used in docs and comments when it improves continuity.
- Do not add `memo.txt` to commits unless the user asks for it.
- Do not touch unrelated generated, captured, or temporary files just to keep the tree tidy.

## Verification
- For doc-only changes, review the file, then check `git diff --stat` and `git status --short`.
- For code changes, prefer narrow checks that match the touched script rather than running every script.
- If a verification step would talk to Nature Remo hardware or external APIs, ask first.
