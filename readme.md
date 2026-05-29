# Splink Test Runner

A powerful, high-performance GUI manager for local development and E2E testing of the Splink platform. Built with Python and `CustomTkinter`, this tool provides a centralized dashboard to manage backend and frontend services, track Git status, and automate Playwright test sequences.

## 🚀 Key Features

- **Service Management**: Start, Stop, and Rebuild Frontend (FE) and Backend (BE) services with a single click.
  - Contains a powerful **Rebuild All** action that automatically pulls the latest changes (`git pull`) from active branches before rebuilding.
- **Dynamic Port Automation**: No more hardcoded ports! Automatically detects active ports straight from `BE/.env` and `FE/package.json`, handling process collisions gracefully on startup/shutdown.
- **Git & DB Integrations**: Live tracking of current branches and origin status (ahead/behind/dirty).
  - Modify the **Backend Database Name (DB)** directly from the dashboard UI with a single click—no need to dive into config files.
- **E2E Test Suite**: Specialized Playwright runner with user-role filtering. Select specific users and tests to run sequentially.
  - **Fault-Tolerant execution:** Tests correctly move on rather than hard-halting the test suite upon unexpected spec failure.
  - **Smart Resume Manager**: Remembers previously passed manufacturers to optimize time. Explicit selections cleverly override completed states to let you laser-focus on specific targets.
- **Tabbed Log System**: Real-time log routing to dedicated panels for Backend, Frontend, and E2E processes.
- **Advanced Results History**: 
  - Grouped by Date and User Role.
  - Collapsible accordion view for a cleaner interface.
  - Filtering by status (Passed/Failed).
  - Quick access to Playwright HTML reports and raw logs.
  - **Run Isolation**: Pre-emptively purges stale artifacts (`playwright-report` and `test-results`) so reports are guaranteed clean, eliminating any cross-contamination from previous user executions.

## 🛠️ Prerequisites

- **Python**: 3.10 or higher.
- **Node.js**: Required to run the FE/BE services.
- **Playwright**: Installed and configured within the `E2E` directory.

## 📦 Installation & Setup

1. **Clone the repository (with submodules)**:
   The `BE`, `FE`, and `E2E` folders are wired up as Git submodules, so the dependent repos are fetched automatically:
   ```powershell
   # Fresh clone (gets the runner + BE/FE/E2E in one step)
   git clone --recurse-submodules <your-repo-url>
   cd "Test runner"

   # If you already cloned without --recurse-submodules:
   git submodule update --init --recursive
   ```
   Submodule mapping:
   - `BE/`  → `splink-rebate-api`
   - `FE/`  → `splink-rebate-app`
   - `E2E/` → `e2e_testing` (branch: `feature/test_runner-support`)

   To later pull the latest commits for all submodules:
   ```powershell
   git submodule update --remote --merge
   ```

2. **Set up a Virtual Environment**:
   ```powershell
   python -m venv .venv
   .\.venv\Scripts\activate
   ```

3. **Install Dependencies**:
   ```powershell
   pip install -r requirements.txt
   ```

4. **Environment Configuration**:
   Ensure your `.env` files are correctly set up in the `BE`, `FE`, and `E2E` subdirectories as they are used by the services and for test credentials.

## 🏃 Running the Application

To launch the dashboard, run the backend GUI module directly or use the windowless launcher:

**Windowless Mode (Recommended)**: Double-click `test_runner.pyw` to launch the GUI seamlessly without a persistent terminal window.

**CLI Mode**: Run from the root directory:
```powershell
python test_runner.py
```

## ✨ Deep Dive: `test_runner.py` GUI Features

The `test_runner.py` script represents a massive leap in developer experience, acting as a fully multithreaded, interactive local orchestrator. Key developments implemented directly in the runner include:

- **Intelligent Port Sniffing & Collision Handling**: Instead of hard-coded values, the runner dynamically parses `BE/.env` to find the Backend port and parses `FE/package.json` scripts to extract the Frontend port. If ghost node processes occupy these ports at launch, it automatically kills them.
- **Git Branch Management via Modal**: Click "Branch" to open a searchable, filterable modal displaying all local Git branches. Switch branches for BE/FE directly through the UI without dropping into a terminal.
- **Live Database Configuration**: Click the edit (pencil) icon next to the Backend Database name to mutate `DB_NAME` within your local `.env`. The UI updates instantly and injects the new target DB on the next start.
- **"Rebuild All" with Auto-Pull**: Automatically performs a `git pull origin <current-branch>` for both BE and FE repositories, subsequently building and serving them in a single click.
- **Dynamic User & Manufacturer Checkboxes**: Populates lists of Users seamlessly from `userMap.js`. Allows launching "nested modals" to explicitly check/uncheck specific manufacturers to bypass or forcefully test isolated flows.
- **Zero-Contamination Execution Flow**: Before spawning Playwright, the runner aggressively clears stale `playwright-report` and `test-results` directories. This ensures that HTML reports mapped to users (like `NCD`) are 100% pristine and never cross-contaminated with previous artifacts (like `Andrew Butler`).
- **Fault-Tolerant Test Queuing**: Runs `npx playwright test` under the hood dynamically passing spec files and configuring environment bindings via `test_config.json`. Playwright crashes are successfully compartmentalized; the runner absorbs the failure, reports it to the UI, and moves on without locking the E2E queue.
- **Multithreaded Tabbed Logging Output**: Real-time console hooking. ANSI color codes are stripped/parsed smoothly and output dynamically to three separated streaming tabs (Backend, Frontend, and E2E) so you never miss a stack trace.
- **Interactive Results Dashboard**: Programmatically maps the `test_results_history` directory into collapsible UI accordions grouped by Date and Role. Opens HTML reports and raw logs right in your browser or default text editor.
- **Windows Notifier**: Integrates with `plyer` to fire a native Windows push notification when an E2E suite completes, so you can test in the background and alt-tab back when ready.

### `test_runner.pyw` Integration
The workspace includes a `test_runner.pyw` launcher which utilizes Python's `runpy` module. Running this file instead of `.py` correctly suppresses the persistent Windows shell console while piping application output silently. It provides a clean, native desktop application experience.

## 📂 Directory Structure

- **/BE**: Backend Node.js service.
- **/FE**: Frontend Next.js/React service.
- **/E2E**: Playwright test suite and user maps.
- **/test_results_history**: Auto-generated storage for all test runs (HTML reports, screenshots, and logs).

---
*Developed by Antigravity for Splink Development Team*
