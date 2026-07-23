<!--
# ==============================================================================
# File: packaging/windows/README.md
# Description: Windows one-step launcher notes (VN-B01)
# Component: Packaging / Windows
# Version: 1.0 (Gold Master)
# Created: 2026-07-21
# Last Update: 2026-07-21
# ==============================================================================
-->

# Phronesis — Windows launcher (VN-B01)

## One-step start

1. Install [Python 3.11+](https://www.python.org/downloads/) (enable **Add python.exe to PATH**).
2. Double-click [`Start-Phronesis.cmd`](Start-Phronesis.cmd) from this folder (or from a shortcut).

The script will:

- Create/use the repo `.venv` and install `requirements.txt`
- Store SQLite + `.env` under `%LOCALAPPDATA%\Phronesis\`
- Run migrations
- Create a default owner (`owner` / `owner`) on first run if none exists in AppData
- Serve with Waitress at [http://127.0.0.1:8765/](http://127.0.0.1:8765/) and open your browser

**Login:** first-run defaults are `owner` / `owner`. That account lives in `%LOCALAPPDATA%\Phronesis\db.sqlite3` — not your repo Postgres/`DATABASE_URL`. If login fails after an older launcher build, wipe AppData via Uninstall (or delete that folder) and start again, or reset with:

```powershell
$env:PHRONESIS_DATA_DIR = "$env:LOCALAPPDATA\Phronesis"
Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue
.\.venv\Scripts\python.exe manage.py create_owner --username owner --password owner --force
```

Stop with **Ctrl+C** in the console window.

## One-step cleanup

Double-click [`Uninstall-Phronesis.cmd`](Uninstall-Phronesis.cmd) (or run the `.ps1`).

- Type **UNINSTALL** to confirm
- Stops whatever is listening on port **8765** (best-effort)
- Deletes `%LOCALAPPDATA%\Phronesis\` (SQLite, `.env`, logs)
- Optionally removes the repo `.venv` (prompt, or `-RemoveVenv`)
- **Does not** delete the source checkout or touch Postgres/`DATABASE_URL` installs

```powershell
# Non-interactive (CI / re-test loops)
powershell -NoProfile -ExecutionPolicy Bypass -File .\Uninstall-Phronesis.ps1 -Force -RemoveVenv
```

Export from Settings → Backup before cleanup if you want the data back.

## Runtime decision (locked for this wave)

| Item | Choice |
| :--- | :--- |
| Python | Local 3.11+ / repo `.venv` (not embeddable CPython yet) |
| Server | Waitress on loopback `:8765` |
| Database | SQLite in AppData when `PHRONESIS_DATA_DIR` is set |
| Installer | Deferred — this CMD/PS1 is the FR-RUN-03 equivalent |

## Dev / geek path

From the repo root you can still use `manage.py runserver` (port 8000). For the same Waitress stack as the launcher:

```powershell
$env:PHRONESIS_DATA_DIR = "$env:LOCALAPPDATA\Phronesis"
.\.venv\Scripts\python.exe manage.py run_local
```
