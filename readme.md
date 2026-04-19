# Splink Test Runner

A powerful, high-performance GUI manager for local development and E2E testing of the Splink platform. Built with Python and `CustomTkinter`, this tool provides a centralized dashboard to manage backend and frontend services, track Git status, and automate Playwright test sequences.

## 🚀 Key Features

- **Service Management**: Start, Stop, and Rebuild Frontend (FE) and Backend (BE) services with a single click.
- **Port Automation**: Automatically detects and handles process collisions on ports `3001` and `4001`, ensuring a clean environment on startup and shutdown.
- **Git Integration**: Live tracking of current branches and origin status (ahead/behind/dirty) for both BE and FE repositories.
- **E2E Test Suite**: Specialized Playwright runner with user-role filtering. Select specific users and tests to run sequentially.
- **Tabbed Log System**: Real-time log routing to dedicated panels for Backend, Frontend, and E2E processes.
- **Advanced Results History**: 
  - Grouped by Date and User Role.
  - Collapsible accordion view for a cleaner interface.
  - Filtering by status (Passed/Failed).
  - Quick access to Playwright HTML reports and raw logs.

## 🛠️ Prerequisites

- **Python**: 3.10 or higher.
- **Node.js**: Required to run the FE/BE services.
- **Playwright**: Installed and configured within the `E2E` directory.

## 📦 Installation & Setup

1. **Clone the repository**:
   ```powershell
   git clone <your-repo-url>
   cd "Test runner"
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

To launch the dashboard, run the following command from the root directory:

```powershell
python test_runner.py
```

## 📂 Directory Structure

- **/BE**: Backend Node.js service.
- **/FE**: Frontend Next.js/React service.
- **/E2E**: Playwright test suite and user maps.
- **/test_results_history**: Auto-generated storage for all test runs (HTML reports, screenshots, and logs).

---
*Developed by Antigravity for Splink Development Team*
