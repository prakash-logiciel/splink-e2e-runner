# Test Runner GUI — Implementation Plan

A Python GUI application to manage local FE/BE services, Git operations, and E2E Playwright tests from a single dashboard with Windows notifications.

## User Review Required

> [!IMPORTANT]
> **Technology Choice**: I'll use **CustomTkinter** (modern-looking tkinter wrapper) for the GUI. It gives a sleek dark-mode interface out of the box, is lightweight, and doesn't require complex setup. Alternative would be PyQt — let me know if you prefer that.

> [!IMPORTANT]
> **BE Build & Start**: The BE `package.json` shows `"build": "yarn lint && tsc"` and `"start": "node dist/index.js"`. The rebuild flow will be: stop process → `yarn build` → `yarn start`. Is this correct, or do you sometimes use `yarn dev` instead?

> [!IMPORTANT]
> **E2E Test Execution**: Tests use `playwright test -g "username"` pattern to run per-user. I see test files use maps like `salesRepMap`, `distributorMap`, `salesRepManagerMap`, `manufacturerMap`, `distributorExecMap`, `distributorGeneralManagerMap`. Each user role has different test files. The GUI will:
> 1. Parse `userMap.js` to extract all user maps and users
> 2. List each test spec file from `playwright.config.js` `testMatch` 
> 3. Let you pick which tests + which users to run
>
> **Question**: When you run a test for a specific user (e.g., "RUSTY JEWETT"), do you use `playwright test -g "RUSTY JEWETT"` or do you run specific spec files? I see both patterns in `package.json`.

## Proposed Changes

### Architecture Overview

```
Test runner/
├── BE/                          # Backend repo
├── FE/                          # Frontend repo
├── E2E/                         # Playwright repo
├── test_results_history/        # Saved test results (by date/time/user)
├── .venv/                       # Python virtual environment
└── test_runner.py               # Main GUI application (single file)
```

The app will be a **single Python file** (`test_runner.py`) using CustomTkinter with threading for non-blocking operations.

---

### GUI Layout (3 Panels)

#### Panel 1: Services Dashboard
| Feature | Details |
|---|---|
| **BE Status** | Running/Stopped indicator, Port (4001), DB name from `.env` (`DB_NAME`), Git branch + sync status |
| **FE Status** | Running/Stopped indicator, Port (3001), Git branch + sync status |
| **Git Pull** | Button per service to `git pull origin main` |
| **Rebuild** | Button per service: Stop → `yarn build` → `yarn start` |
| **Rebuild All** | Single button to rebuild both FE and BE sequentially |

#### Panel 2: E2E Test Runner
| Feature | Details |
|---|---|
| **User List** | All users from `userMap.js` grouped by role (Distributor Admin, Sales Rep, Sales Rep Manager, Manufacturer, etc.) |
| **Test Selection** | Checkboxes for each test file per user role |
| **Run per User** | Button next to each user to run selected tests for that user |
| **Run All** | Button to run tests for all users sequentially (one by one) |
| **Live Output** | Scrollable log panel showing real-time test output |

#### Panel 3: Test Results History
| Feature | Details |
|---|---|
| **Results Browser** | Tree view of past results organized by date → time → user |
| **View Report** | Open the Playwright HTML report for any past run |

---

### [NEW] [test_runner.py](file:///e:/Logiciel/Test%20runner/test_runner.py)

Single-file Python application with these major components:

**1. Service Manager (BE/FE)**
- Parse `.env` files to extract `DB_NAME`, `PORT`, `FRONTEND_URL`
- Check if ports 4001/3001 are in use (using `psutil`)
- Start/stop services via `subprocess.Popen` with proper process group handling on Windows
- Git operations: `git status`, `git fetch`, `git pull` via subprocess
- Rebuild: terminate process → `yarn build` → `yarn start`

**2. User Map Parser**
- Read `E2E/utils/userMap.js` using regex to extract all Maps and their entries
- Return structured data: `{ mapName: { userName: { email, name, jsonPath } } }`

**3. Test Spec Discovery**
- Parse `E2E/playwright.config.js` to extract `testMatch` array
- Also scan `E2E/tests/` directory for all `.spec.js` and `.spec.ts` files

**4. E2E Test Runner**
- Run tests per user with: `npx playwright test -g "username"` (filtered by selected test files using `--grep`)
- Run sequentially for multiple users
- Capture output in real-time and display in log panel
- Save results to `test_results_history/{date}/{time}_{user}/` with:
  - `output.log` — terminal output
  - Copy of Playwright HTML report (from `E2E/playwright-report/`)

**5. Windows Notifications**
- Use `win10toast` or `plyer` for native Windows toast notifications
- Notify on: test complete, test failure, idle state (FE+BE running, no test)

**6. Idle Detection**
- Background thread checks if FE+BE are running but no test is active
- After configurable timeout (e.g., 5 minutes), sends notification

---

### Dependencies

```
customtkinter      # Modern GUI
psutil             # Process management
plyer              # Windows notifications
```

All available via pip. The `.venv` already exists.

## Open Questions

1. **BE start command**: Should I use `yarn start` (production mode, requires build first) or `yarn dev` (development mode, no build needed)? The rebuild flow you described (`yarn build` → `yarn start`) suggests production mode.

2. **Test grep pattern**: When running tests for a user like "Sandstrom", should I use `-g "Sandstrom"` or `-g "sandstrom"` (case-insensitive)? Playwright's `-g` flag uses regex matching.

3. **Specific test files**: When selecting tests for a user, should I filter by running only the spec files that use that user's map? For example, `distributorMap` users should only see `distributor-admin/*.spec.js` tests. Or should all tests be available for all users?

4. **Idle notification interval**: How often should the "idle" notification appear? Every 5 minutes? Or just once?

## Verification Plan

### Manual Testing
- Launch the GUI and verify all panels render correctly
- Test service start/stop for FE and BE
- Verify Git status detection and pull functionality
- Run E2E tests for a single user and verify results are saved
- Check Windows notification appears on test completion
