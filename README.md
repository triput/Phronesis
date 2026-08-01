<!--
# ==============================================================================
# File: README.md
# Description: Bootstrap and documentation index for Phronesis V3
# Component: Documentation
# Version: 3.1 (Gold Master)
# Created: 2026-06-26
# Last Update: 2026-07-22
# ==============================================================================
-->

# Phronesis V3 — Personal Cockpit

**Todoist+ for people who need a little more** — calm capture → organize → today → focus, offline on your device. Power surfaces are optional. Sync without an author-run cloud (cable/LAN when shipped, or geek self-host).

**Phronesis — Organon by LiveBytes.** Email sibling: Synesis (`livebytes.net/synesis/`).

**Authoritative product docs:** [docs/PHRONESIS_V3_PRODUCT_BRIEF.md](docs/PHRONESIS_V3_PRODUCT_BRIEF.md) — **V-Now closed**; current wave **V3.1** (V-Next Marvin).

---

## Who hosts what (VN-E03)

| Path | Who runs it |
| :--- | :--- |
| **Windows standalone** (default) | You, on your PC — [Start-Phronesis](packaging/windows/Start-Phronesis.cmd) |
| **Geek self-host** | You, on infrastructure you control — [Geeks ’R Us](docs/PHRONESIS_V3_GEEK_SELF_HOST.md) |
| **Geek Docker/Compose** | Operator-only appendix — [§D](docs/PHRONESIS_V3_GEEK_SELF_HOST.md#d-docker--compose-operator-only-appendix); not author-supported |
| **Author-hosted cloud for friends/family** | **Does not exist.** Not a product, not a support offering. |

The author does **not** host Phronesis for other people, does **not** operate a sync SaaS for third parties, and does **not** provide remote hands for your relatives’ servers. Standalone is the default; self-host only if you like that sort of thing.

---

## Documentation

| Doc | Audience |
| :--- | :--- |
| [Product brief](docs/PHRONESIS_V3_PRODUCT_BRIEF.md) | Why V3 / V-Now exists |
| [SRS](docs/PHRONESIS_V3_SRS.md) | Requirements |
| [Modules](docs/PHRONESIS_V3_MODULES.md) | Simple vs Full cockpit |
| [User Guide](docs/PHRONESIS_V3_USER_GUIDE.md) | Daily operation |
| [Technical Documentation](docs/PHRONESIS_V3_TECHNICAL_DOCS.md) | Architecture, packaging, sync |
| [Geeks ’R Us (self-host)](docs/PHRONESIS_V3_GEEK_SELF_HOST.md) | Operator web + SQLite/Postgres (VN-E01); Docker appendix (VN-E02) |
| [Android architecture](docs/PHRONESIS_V3_ANDROID_ARCHITECTURE.md) | Kotlin/Compose/Room client lock (VN-C01) |
| [Sync-pack v0](docs/PHRONESIS_V3_SYNC_PACK.md) | Pair sync schema (VN-D01) |
| [Backlog](docs/PHRONESIS_V3_BACKLOG.md) | V-Now / V-Next |
| [Do not commit](docs/DO_NOT_COMMIT.md) | Local-only / secrets checklist (never push) |
| [V2 carryover](docs/V2_CARRYOVER.md) | What unfinished V2 work Carry / Park / Drop |
| [Defects](docs/DEFECTS.md) | Standing defect log |
| [Cmd grammar](docs/PHRONESIS_V3_CMD_GRAMMAR.md) | Capture / go / do notes |
| [Offline demo checklist](docs/V3_OFFLINE_DEMO_CHECKLIST.md) | Spine without network (VN-B03) |
| [Test plan](docs/PHRONESIS_V3_TEST_PLAN.md) | V3 strategy, pyramid, gates |
| [Test inventory](docs/TEST_INVENTORY.md) | Automated catalog ritual + column defs |
| [Automated inventory CSV](docs/V3_AUTOMATED_TEST_INVENTORY.csv) | Canonical `AT-*` test case list (regenerate via `tool/generate_test_inventory.py`) |
| [Manual E2E matrix](docs/V3_MANUAL_E2E_MATRIX.csv) | Operator spine / security / perf smoke |
| [Security test checklist](docs/V3_SECURITY_TEST_CHECKLIST.md) | Authz, OAuth, secrets |
| [Performance test checklist](docs/V3_PERFORMANCE_TEST_CHECKLIST.md) | Load and job timing hypotheses |
| [AGENTS.md](AGENTS.md) | Agent / engineering rules |
| [Doc sync runbook](docs/DOC_SYNC.md) | When/how Page keeps docs current (phase gate) |
| [Multi-agent playbook](docs/MULTI_AGENT_SYSTEM_PROMPT.md) | Steve / Jules / Renee / Page / Tesla gates |

**Historical (pre-V3):** `docs/TECHNICAL_DOCS.md` (V6), June 2026 assessments, older backlog wishlists — archaeology only. Triage: [docs/V2_CARRYOVER.md](docs/V2_CARRYOVER.md). Current docs are `PHRONESIS_V3_*`.

---

## Windows one-step (VN-B01)

Double-click [`packaging/windows/Start-Phronesis.cmd`](packaging/windows/Start-Phronesis.cmd) after installing Python 3.11+ on PATH.

- SQLite + `.env` live in `%LOCALAPPDATA%\Phronesis\`
- App opens at [http://127.0.0.1:8765/](http://127.0.0.1:8765/) (Waitress)
- Cleanup: [`packaging/windows/Uninstall-Phronesis.cmd`](packaging/windows/Uninstall-Phronesis.cmd) — removes AppData data; optional `.venv`
- Details: [packaging/windows/README.md](packaging/windows/README.md)

---

## Quick start (dev / geek)

```powershell
python validate_sandbox.py
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
python manage.py migrate
python manage.py create_owner --username owner --password "your-password"
python manage.py seed_data
python manage.py runserver
```

Open [http://127.0.0.1:8000/](http://127.0.0.1:8000/).

**Database:** SQLite by default (`./db.sqlite3`, or AppData under the Windows launcher). Set `DATABASE_URL` only if you want Postgres — it is never required for the product. Google/Microsoft OAuth clients can be entered in Settings → Calendars (preferred over env).

Civilian **Windows** path: [`packaging/windows/Start-Phronesis.cmd`](packaging/windows/Start-Phronesis.cmd) (VN-B01). Android: open [`android/`](android/) in Android Studio ([ADR](docs/PHRONESIS_V3_ANDROID_ARCHITECTURE.md)). Dev `runserver` + SQLite remains fine for geeks.

---

## Tests

```powershell
python manage.py test phronesis_app.tests -v 1
python tool/generate_test_inventory.py   # refresh docs/V3_AUTOMATED_TEST_INVENTORY.csv
```

See [docs/PHRONESIS_V3_TEST_PLAN.md](docs/PHRONESIS_V3_TEST_PLAN.md) and [docs/TEST_INVENTORY.md](docs/TEST_INVENTORY.md).

---

## Background jobs (Celery Beat)

**Preferred** (Redis + worker with embedded Beat):

```powershell
celery -A phronesis_django worker -B -l info
```

Schedule: reminders every **2 min**, telemetry cache warm every **15 min**, stability daily **12:05 UTC**.

**Fallback** without Redis (cron / Task Scheduler):

```powershell
python manage.py sweep_reminders
python manage.py run_beat_jobs
python manage.py run_beat_jobs --stability
python manage.py sync_calendar
python manage.py compute_stability
```
