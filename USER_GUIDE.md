<!--
# ==============================================================================
# File: USER_GUIDE.md
# Description: User guide explaining application startup, authentication, structure, and focus features
# Component: Documentation
# Version: 3.0 (Gold Master)
# Created: 2026-06-26
# Last Update: 2026-06-27
# ==============================================================================
-->
# LifeOS Django: User Guide (V3.0)

Welcome to **LifeOS Django V3.0**—a stability-first personal operating system built around a unified DRY data model. This guide outlines how to manage, navigate, and utilize the core modules of the system.

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
3. Boot up the server:
   ```powershell
   python manage.py runserver
   ```
   *By default, the server will bind to port `8000` on localhost.*
4. Open your web browser and navigate to:
   [http://127.0.0.1:8000/](http://127.0.0.1:8000/)

---

## 2. Authentication & Security
Access to the LifeOS Django interface is strictly limited to the system owner.

### Logging In
1. Navigate to the application URL (by default, `http://localhost:8000/login/` or `http://127.0.0.1:8000/login/`).
2. Input the owner credentials you created during system setup (superuser account).
3. If an unauthorized user attempts to access any page on the system, they will be blocked and redirected back to the login page.

---

## 3. Global Quick Entry ("Brain Dump")
The header navigation bar features a persistent Quick Entry form to capture tasks or structural containers instantly without interrupting your current workflow.

### Creating a Dump
1. Go to the input field on the right side of the top navbar labeled **"Brain dump..."**.
2. Type the title, and select the dump type from the dropdown:
   *   **Task**: Placed as an unassigned task in the Inbox queue.
   *   **Epic / Project / Specialization / Course / Module**: Instantly instantiates a Workspace Container of that type.
3. Click the `+` button. The form submits via HTMX and flashes a success toast.

---

## 4. Inbox Triage Center
Unassigned tasks (brain dumps) sit in the **Inbox** stage. To classify and organize them, you use the Triage Center.

### Triaging Tasks
1. Navigate to **Inbox Triage** in the top navigation bar.
2. For each card, fill in the following:
    *   **Scope / Parent**: Nest the task under a Workspace Container (Epic, Project, Course, Module) OR select another Task to establish subtask relations.
    *   **Domain & PARA Category**: Mark the life domain (dynamic Domain categories) and PARA class.
    *   **Item Type & Priority**: Specify if it is a Task, LearningTask, or LifeActivity, and set its priority.
    *   **Estimate**: Set a duration estimate (accepts human formats, e.g. `1h 30m` or `45`).
    *   **Status Target**: Shift it into `Planned` or `Backlog`.
3. Click **Process & File** to process.

---

## 5. Backlog Explorer (Tree View) & Editing Scopes
The **Backlog Explorer** provides a visual, collapsible tree hierarchy of your workspace.

### Action Triggers in the Explorer
*   **Add Child**: Type a title next to any container/task to nest a child task or subtask inline.
*   **Move To**: Move a project or task to a new parent container.
*   **Edit (Pencil)**: Opens the edit form to configure metadata:
    *   **Human-readable time estimate** (e.g. `1.5h` or `45m`).
    *   **Manual focus log**: Add time spent directly to the extra actual focus time bucket.
    *   **Target dates**: Configure start, end, and due datetimes.
    *   **Fuzzy calendar bucket**: Assign to `Today`, `Tomorrow`, `Weekend`, `Week`, `Month`.
    *   **Recurrence schedules**: Configure frequency (Daily, Weekly, Monthly, Quarterly, Annually, Custom) for automatic cloning.
    *   **Notion link**: Link a Notion document page.

---

## 6. Consolidated Focus Engine & Scheduled Agendas
The Focus Engine handles real-time timer tracking for all execution tasks.

### Today's Focus Agenda
*   Pin tasks using the **Pin (thumbtack)** icon on any task card.
*   They display at the top of the Dashboard. Pinned tasks allow you to quickly run focus sessions without distractions.

### Scheduled & Upcoming Agenda
*   Displays tasks scheduled with explicit start/due dates or fuzzy timeframe buckets (`Today`, `Tomorrow`, `Weekend`, etc.).
*   Keep track of future tasks and quickly toggle pins directly from the calendar feed.

---

## 7. Academy Hub & Certifications HUD
A dedicated view (`/academy/`) to manage academic curriculum and track certifications.

### Core Features
*   **Certifications HUD**: Record professional achievements (e.g. PMP, CSM) with achieved/renewal dates and interactive PDU progress bars.
*   **Curriculum Scope**: View coursework folders (Specializations, Courses, Modules) and total accumulated time spent.
*   **Coursework Assignments**: Dedicated dashboard cards showing all active `LearningTask` elements.

---

## 8. User Settings & Integrations
Manage configuration parameters directly in the settings view `/settings/`.

### Configuration Options
*   **User Preferences**: Focus duration, work day start hour, metric/imperial toggle, timezone dropdown, and 12h/24h time formats.
*   **Browser Geolocation**: Enable auto-detection or input manual latitude and longitude.
*   **Dashboard HUD Renaming**: Custom title labels for dashboard HUD metrics.
*   **Dynamic Domain Manager**: Add and delete custom domain categories with distinct colors, icons, and academic flags.
*   **Google Calendar**: Integrate multiple Google Calendar feeds to import external events.
