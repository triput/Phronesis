<!--
# ==============================================================================
# File: USER_GUIDE.md
# Description: User guide explaining application startup, settings, layouts, and V5.2 features
# Component: Documentation
# Version: 5.2 (Gold Master)
# Created: 2026-06-26
# Last Update: 2026-06-28
# ==============================================================================
-->
# LifeOS Django: User Guide (V6.0)

Welcome to **LifeOS Django V6.0**—a stability-first personal operating system built around a unified DRY data model. This guide outlines how to start, navigate, configure, and utilize the application's core systems.

---

## 1. Starting the Application

Since LifeOS Django is designed as a single-user local system, you run the service from your local workstation using the standard Django development server.

### Steps to Run
1. Open a terminal (PowerShell or Command Prompt) and navigate to the project directory:
   ```powershell
   cd "path/to/LifeOS_Django"
   ```
2. Activate the python virtual environment:
   ```powershell
   .venv\Scripts\activate
   ```
3. Run migrations to ensure your schema is up to date:
   ```powershell
   python manage.py migrate
   ```
4. Boot up the server:
   ```powershell
   python manage.py runserver
   ```
   *By default, the server will bind to port `8000` on localhost.*
5. Open your web browser and navigate to:
   [http://127.0.0.1:8000/](http://127.0.0.1:8000/)

---

## 2. Navigation Sidebar Layout

LifeOS V6.0 features a persistent, space-efficient side navigation bar structure:
*   **The Top Command Bar**: Contains quick system actions (owner profile badge, quick brain dump entry field, and standard log out options).
*   **The Left Vertical Sidebar**: Gives you instant access to directories: Dashboard, Kanban (Status), Kanban (Priority), Roadmap, Daily Agenda, Inbox Triage, Backlog Explorer, Planner, Analytics, Academy, Tag Manager, and Settings.
*   **Collapsible Design**: You can collapse the sidebar using the toggle chevron button in the bottom left corner. The collapsed state is persisted in your browser's `localStorage`.

---

## 3. Global Quick Entry ("Brain Dump")

Use the text field in the top bar to capture ideas immediately:
1. Locate the input box labeled **"Brain dump..."** on the right side of the header.
2. Enter the title of your task or container.
3. Select its type:
    *   **Task**: Sent to the Inbox queue as an unfiled execution item.
    *   **Epic / Project / Specialization / Course / Module**: Instantiates a Workspace Container of that type.
4. Press `Enter` or click the `+` button to submit.

---

## 4. Inbox Triage Center

New ideas are placed into the Triage Center for organization. **LifeOS V6.0 supports triaging both Execution Items and Workspace Containers**.

### Processing Items
1. Navigate to **Inbox Triage** from the sidebar.
2. For each card:
    *   **Scope / Parent**: Nest the task under a parent Container, or link it to another Task to establish subtask connections. For new Containers, you can optionally define a parent Container.
    *   **Domain & PARA Category**: Select the target life domain and PARA category.
    *   **Status Target**: Direct it to `Planned` or `Backlog`.
    *   **Default Status Rule**: If you do not assign a start or due date, the item will intelligently default to **Backlog** status when processed to prevent clutter.
3. Click **Process & File** (or **Process Container**) to complete triaging.

---

## 5. Backlog Explorer & Grid Editor (Tree View)

The **Backlog Explorer** provides a collapsible tree showing all of your active folders, projects, tasks, and subtasks.

### Advanced Features in V6.0:
*   **Multi-Tag Filtering**: Use the tag filter checkboxes at the top of the explorer to narrow down items. Filter by single or multiple tags, exclude tags, or view untagged items.
*   **Parent Reassignment**: Open the edit modal (pencil icon) on any Container or Execution Item to reassign the parent container relationship.
*   **Status Override**: Changing a completed task's status back to an active state automatically resets the completion flag in the database.
*   **Backlog Grid Editor**: Navigate to `/explorer/grid/` for a Windows-Explorer style grid editor offering zero-latency folding, debounced auto-saving, inline child row creation, and jewel-tone priority color styling.

---

## 6. Kanban Boards (Status & Priority)

LifeOS V6.0 offers dedicated drag-and-drop boards to organize tasks:
*   **Kanban (Status)**: Columns group tasks by status (*Inbox*, *Planned*, *In Progress*, *Completed*).
*   **Kanban (Priority)**: Columns group tasks by priority (*Critical*, *High*, *Medium*, *Low*).
*   **Workflow Interaction**: Dragging cards between columns instantly updates the task's database records. It also updates their stack order inside the list.

---

## 7. Roadmap & Daily Agenda

*   **Roadmap View (`/roadmap/`)**: Displays all scheduled execution items chronologically based on their due dates. Use this visual timeline to manage projects and verify milestone spreads.
*   **Daily Agenda (`/agenda/`)**: Renders your scheduled task allocations for the current day.
    *   **Print Layout Support**: Click **Print Agenda** to open the browser print dialog. Custom print styles automatically remove sidebars, headers, and backgrounds to render a clean, checklist-style agenda on paper.

---

## 8. Google Calendar OAuth2 Integration

The Planner system scheduler automatically respects your external commitments:
1. **OAuth2 Connection**: Navigate to **Settings**, scroll to **Google Calendar Integrations**, and click **Authorize Google Calendar (OAuth2)** to link your account.
2. **Multi-Calendar Toggle Selection**: After authorization, all retrieved calendars from that Google account are displayed. Check or uncheck the **Sync** checkbox for individual feeds (e.g. Travel, Primary) to control which ones block out tasks.
3. **Respect Busy Status**: The scheduler automatically fetches your upcoming events, marks them as blocking ranges, and schedule tasks around those busy intervals.
4. **Calendar Blocks Toggling**: Click any calendar event on the Planner calendar view to toggle it between blocking (pink/red, schedule around it) and non-blocking (muted gray).

---

## 9. Scoped Tag Manager

The **Tag Manager** (`/settings/tags/`) helps you categorize elements by domain context:
*   **Scoped Domain Tags**: Restrict tags to specific domains (e.g., a "Math" tag restricted to the "Academy" domain) to keep tag selectors uncluttered.
*   **Safe Deletion**: Restricts deletion of tags that are currently in use by any container or task.
*   **Global Re-Tagging**: Shift or clear tag references across all items in bulk before deleting a tag.

