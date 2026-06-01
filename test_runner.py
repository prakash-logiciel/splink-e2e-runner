"""
Splink Test Runner — Local Development Environment Manager
===========================================================
A Python/CustomTkinter GUI to manage FE/BE services, Git operations,
and E2E Playwright tests from a single dashboard with Windows notifications.
"""

import os
import re
import sys
import json
import shutil
import signal
import socket
import subprocess
import threading
import time
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import customtkinter as ctk
import psutil
import tkinter as tk

try:
    from plyer import notification as plyer_notification
    _ = plyer_notification.notify  # force backend load (macOS needs pyobjus)
    HAS_NOTIFICATIONS = True
except ImportError:
    HAS_NOTIFICATIONS = False

# ════════════════════════════════════════════════════════════
# Constants
# ════════════════════════════════════════════════════════════

BASE_DIR = Path(__file__).parent.resolve()
BE_DIR = BASE_DIR / "BE"
FE_DIR = BASE_DIR / "FE"
E2E_DIR = BASE_DIR / "E2E"
RESULTS_DIR = BASE_DIR / "test_results_history"
RESUME_STATE_FILE = E2E_DIR / "resume_state.json"
TEST_CONFIG_FILE = E2E_DIR / "test_config.json"

# Spec files that support resume functionality
RESUMABLE_SPECS = {
    "tests/distributor-admin/store-program-detail-common.spec.js",
    "tests/distributor-admin/store-breakdown-common.spec.ts",
    "tests/sales-rep-manager/store-program-detail-common.spec.js",
    "tests/sales-rep-manager/store-breakdown-common.spec.ts",
    "tests/sales-rep/store-program-detail-common.spec.js",
    "tests/sales-rep/store-breakdown-common.spec.ts",
}

def get_be_port() -> int:
    env_file = BE_DIR / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("PORT"):
                try:
                    return int(line.split("=")[1].strip())
                except ValueError:
                    pass
    return 4002

def get_fe_port() -> int:
    pkg_file = FE_DIR / "package.json"
    if pkg_file.exists():
        try:
            data = json.loads(pkg_file.read_text(encoding="utf-8"))
            dev_script = data.get("scripts", {}).get("dev", "")
            m = re.search(r'-p\s+(\d+)', dev_script)
            if m:
                return int(m.group(1))
        except Exception:
            pass
    return 3002

BE_PORT = get_be_port()
FE_PORT = get_fe_port()

# Suppress console flash for all subprocess calls (critical for pythonw / .pyw)
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

_IS_WIN = sys.platform == "win32"


def _proc_group_kwargs() -> dict:
    """Popen kwargs that start a child in its own process group, so we can later
    signal the whole tree (Ctrl-Break on Windows, SIGINT to the group on POSIX)."""
    if _IS_WIN:
        return {"creationflags": _NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def _interrupt_process_group(proc):
    """Send a graceful interrupt to a child started via _proc_group_kwargs()."""
    if _IS_WIN:
        os.kill(proc.pid, signal.CTRL_BREAK_EVENT)
    else:
        os.killpg(os.getpgid(proc.pid), signal.SIGINT)


def _open_path(path):
    """Open a file or folder with the OS default handler (cross-platform)."""
    target = str(path)
    try:
        if _IS_WIN:
            os.startfile(target)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.run(["open", target])
        else:
            subprocess.run(["xdg-open", target])
    except Exception:
        webbrowser.open(target)

ROLE_FOLDER_MAP = {
    "distributorMap": "distributor-admin",
    "distributorExecMap": "distributor-admin",
    "distributorGeneralManagerMap": "distributor-admin",
    "salesRepManagerMap": "sales-rep-manager",
    "salesRepMap": "sales-rep",
    "manufacturerMap": "manufacturer-admin",
}

ROLE_LABELS = {
    "distributorMap": "🏢  Distributor Admin",
    "distributorExecMap": "👔  Distributor Executive",
    "distributorGeneralManagerMap": "🎩  Distributor General Mgr",
    "salesRepManagerMap": "📊  Sales Rep Manager",
    "salesRepMap": "💼  Sales Rep",
    "manufacturerMap": "🏭  Manufacturer Admin",
}

# Colors
CLR_GREEN = "#2ecc71"
CLR_RED = "#e74c3c"
CLR_ORANGE = "#f39c12"
CLR_BLUE = "#3498db"
CLR_CARD = "#1e293b"
CLR_CARD_BORDER = "#334155"
CLR_HEADER = "#0f172a"
CLR_PURPLE = "#7c3aed"
CLR_CYAN = "#06b6d4"

# ════════════════════════════════════════════════════════════
# Utility helpers
# ════════════════════════════════════════════════════════════

def parse_env_file(filepath: Path) -> dict:
    env = {}
    if not filepath.exists():
        return env
    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                key = key.strip()
                if key.startswith("#"):
                    continue
                value = value.split("#")[0].strip().strip('"').strip("'")
                env[key] = value
    return env


def update_env_value(filepath: Path, key: str, new_value: str):
    if not filepath.exists():
        return
    text = filepath.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    found = False
    new_lines = []
    for line in lines:
        if line.strip().startswith(f"{key}="):
            new_lines.append(f"{key}={new_value}")
            found = True
        else:
            new_lines.append(line)
    if not found:
        new_lines.append(f"{key}={new_value}")
    filepath.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


def parse_user_map(filepath: Path) -> dict:
    if not filepath.exists():
        return {}
    content = filepath.read_text(encoding="utf-8", errors="replace")
    maps: Dict[str, Dict] = {}

    # Remove block comments
    clean = re.sub(r"/\*.*?\*/", "", content, flags=re.DOTALL)

    # Remove fully commented-out map blocks  (// export const …)
    # Keep only lines that are NOT entirely commented
    lines = []
    for ln in clean.split("\n"):
        stripped = ln.strip()
        if stripped.startswith("//"):
            continue
        lines.append(ln)
    clean = "\n".join(lines)

    map_pat = re.compile(
        r"export\s+const\s+(\w+)\s*=\s*new\s+Map\(\s*Object\.entries\(\{(.*?)\}\)\s*\)",
        re.DOTALL,
    )
    entry_pat = re.compile(
        r"""(?:['"]([^'"]+)['"]|(\w+))\s*:\s*\{[^}]*?email\s*:\s*['"]([^'"]+)['"][^}]*?name\s*:\s*['"]([^'"]+)['"]""",
        re.DOTALL,
    )

    for m in map_pat.finditer(clean):
        map_name = m.group(1)
        body = m.group(2)
        users = {}
        for e in entry_pat.finditer(body):
            key = e.group(1) or e.group(2)
            users[key] = {"email": e.group(3), "name": e.group(4)}
        if users:
            maps[map_name] = users
    return maps


def parse_playwright_config(filepath: Path) -> List[str]:
    if not filepath.exists():
        return []
    content = filepath.read_text(encoding="utf-8", errors="replace")
    tests = []
    m = re.search(r"testMatch:\s*\[(.*?)\]", content, re.DOTALL)
    if m:
        for line in m.group(1).split("\n"):
            line = line.strip()
            if line.startswith("//"):
                continue
            sm = re.search(r"'([^']+)'", line)
            if sm:
                tests.append(sm.group(1))
    return tests


def get_all_test_files(e2e_dir: Path) -> Dict[str, List[str]]:
    tests_dir = e2e_dir / "tests"
    result: Dict[str, List[str]] = {}
    if not tests_dir.exists():
        return result
    for item in sorted(tests_dir.iterdir()):
        if item.is_dir() and not item.name.startswith(".") and item.name != "shared":
            folder_tests = sorted(
                f"tests/{item.name}/{f.name}"
                for f in item.iterdir()
                if f.is_file() and ".spec." in f.name and f.suffix in (".js", ".ts")
            )
            if folder_tests:
                result[item.name] = folder_tests
    root_tests = sorted(
        f"tests/{f.name}"
        for f in tests_dir.iterdir()
        if f.is_file() and ".spec." in f.name and f.suffix in (".js", ".ts")
    )
    if root_tests:
        result["root"] = root_tests
    return result


def is_port_in_use(port: int) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            return s.connect_ex(("127.0.0.1", port)) == 0
    except Exception:
        return False


def get_pid_on_port(port: int) -> Optional[int]:
    # On macOS psutil.net_connections requires elevated privileges and returns
    # nothing without sudo. Use lsof as the primary method on POSIX.
    if not _IS_WIN:
        try:
            r = subprocess.run(
                ["lsof", "-nP", "-iTCP:" + str(port), "-sTCP:LISTEN"],
                capture_output=True, text=True, timeout=5,
            )
            for line in r.stdout.splitlines()[1:]:  # skip header
                parts = line.split()
                if len(parts) >= 2:
                    try:
                        return int(parts[1])
                    except ValueError:
                        pass
        except Exception:
            pass
    # Windows or lsof unavailable: fall back to psutil
    try:
        for conn in psutil.net_connections(kind="inet"):
            if conn.laddr.port == port and conn.status == "LISTEN":
                return conn.pid
    except (psutil.AccessDenied, PermissionError):
        pass
    return None


def kill_process_tree(pid: int):
    if _IS_WIN:
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True,
                timeout=15,
                creationflags=_NO_WINDOW,
            )
        except Exception:
            pass
        return
    # POSIX: kill the whole process group (works because we launched with
    # start_new_session=True, which places the child in its own session/pgroup).
    try:
        pgid = os.getpgid(pid)
        os.killpg(pgid, signal.SIGKILL)
        return
    except (ProcessLookupError, OSError):
        pass
    # Fallback: walk the psutil tree
    try:
        p = psutil.Process(pid)
        for ch in p.children(recursive=True):
            ch.kill()
        p.kill()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass


def get_git_info(repo_dir: Path) -> dict:
    info = {"branch": "—", "behind": 0, "ahead": 0, "dirty": False, "error": None, "no_git": False}
    try:
        # Check if this is a git repo first
        r = subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            cwd=str(repo_dir), capture_output=True, text=True, timeout=5,
            creationflags=_NO_WINDOW,
        )
        if r.returncode != 0:
            info["no_git"] = True
            return info

        r = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=str(repo_dir), capture_output=True, text=True, timeout=10,
            creationflags=_NO_WINDOW,
        )
        if r.returncode == 0:
            info["branch"] = r.stdout.strip()

        subprocess.run(
            ["git", "fetch", "origin"],
            cwd=str(repo_dir), capture_output=True, text=True, timeout=30,
            creationflags=_NO_WINDOW,
        )

        r = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(repo_dir), capture_output=True, text=True, timeout=10,
            creationflags=_NO_WINDOW,
        )
        info["dirty"] = bool(r.stdout.strip()) if r.returncode == 0 else False

        branch = info["branch"]
        r = subprocess.run(
            ["git", "rev-list", "--count", f"HEAD..origin/{branch}"],
            cwd=str(repo_dir), capture_output=True, text=True, timeout=10,
            creationflags=_NO_WINDOW,
        )
        if r.returncode == 0:
            info["behind"] = int(r.stdout.strip())

        r = subprocess.run(
            ["git", "rev-list", "--count", f"origin/{branch}..HEAD"],
            cwd=str(repo_dir), capture_output=True, text=True, timeout=10,
            creationflags=_NO_WINDOW,
        )
        if r.returncode == 0:
            info["ahead"] = int(r.stdout.strip())
    except Exception as exc:
        info["error"] = str(exc)
    return info


def get_git_branches(repo_dir: Path) -> List[str]:
    """Return a sorted list of all local + remote branch names for the repo."""
    branches: List[str] = []
    try:
        # Fetch latest remote info
        subprocess.run(
            ["git", "fetch", "--all", "--prune"],
            cwd=str(repo_dir), capture_output=True, text=True, timeout=30,
            creationflags=_NO_WINDOW,
        )
        # Get all branches (local + remote tracking)
        r = subprocess.run(
            ["git", "branch", "-a", "--format=%(refname:short)"],
            cwd=str(repo_dir), capture_output=True, text=True, timeout=10,
            creationflags=_NO_WINDOW,
        )
        if r.returncode == 0:
            seen = set()
            for line in r.stdout.strip().splitlines():
                name = line.strip()
                if not name or "HEAD" in name:
                    continue
                # Normalize remote branches: origin/foo -> foo
                if name.startswith("origin/"):
                    name = name.removeprefix("origin/")
                if name not in seen:
                    seen.add(name)
                    branches.append(name)
    except Exception:
        pass
    return sorted(branches, key=str.lower)


_ANSI_RE = re.compile(
    r"\x1b\[[0-9;]*[A-Za-z]"
    r"|\x1b\][^\x07]*\x07"
    r"|\x1b[^\[]"
    r"|\[\d+[;\d]*[mABCDEFGHJKSTfn]"
)

def strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences (including orphaned ones on Windows)."""
    return _ANSI_RE.sub("", text)


def _nocolor_env() -> dict:
    """Return a copy of os.environ with color-output suppressed."""
    env = os.environ.copy()
    env["NO_COLOR"] = "1"
    env["FORCE_COLOR"] = "0"
    return env


def notify(title: str, message: str):
    if not HAS_NOTIFICATIONS:
        return
    try:
        plyer_notification.notify(
            title=title, message=message, app_name="Splink Test Runner", timeout=10,
        )
    except Exception:
        pass


class CTkToolTip:
    """A simple tooltip implementation for CustomTkinter widgets."""
    def __init__(self, widget, text, delay=500):
        self.widget = widget
        self.text = text
        self.delay = delay
        self.tip_window = None
        self.id = None
        self.widget.bind("<Enter>", self._on_enter)
        self.widget.bind("<Leave>", self._on_leave)

    def _on_enter(self, event=None):
        self._schedule()

    def _on_leave(self, event=None):
        self._unschedule()
        self._hide()

    def _schedule(self):
        self._unschedule()
        self.id = self.widget.after(self.delay, self._show)

    def _unschedule(self):
        if self.id:
            self.widget.after_cancel(self.id)
            self.id = None

    def _show(self):
        if self.tip_window or not self.text:
            return
        x = self.widget.winfo_rootx() + (self.widget.winfo_width() // 2)
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 10
        self.tip_window = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        tw.attributes("-topmost", True)
        label = tk.Label(tw, text=self.text, justify="left",
                        background="#1e293b", foreground="#f8fafc",
                        relief="solid", borderwidth=1, padx=8, pady=4,
                        font=("Segoe UI", 9))
        label.pack()

    def _hide(self):
        tw = self.tip_window
        self.tip_window = None
        if tw:
            tw.destroy()


# ════════════════════════════════════════════════════════════
# Main Application
# ════════════════════════════════════════════════════════════

class TestRunnerApp(ctk.CTk):
    """Main GUI window."""

    def __init__(self):
        super().__init__()
        self.title("🚀 Splink Test Runner")
        self.geometry("1280x860")
        self.minsize(1060, 700)
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        # ── state ──
        self.be_process: Optional[subprocess.Popen] = None
        self.fe_process: Optional[subprocess.Popen] = None
        self.test_process: Optional[subprocess.Popen] = None
        self.is_testing = False
        self._stop_tests_flag = False
        self._idle_notified = False
        self.idle_start_time = None
        self.last_idle_notify_time = None
        self._monitor_running = True

        # ── parsed data ──
        self.be_env = parse_env_file(BE_DIR / ".env")
        self.fe_env = parse_env_file(FE_DIR / ".env")
        self.user_maps = parse_user_map(E2E_DIR / "utils" / "userMap.js")
        self.config_tests = parse_playwright_config(E2E_DIR / "playwright.config.js")
        self.all_tests = get_all_test_files(E2E_DIR)

        # ── test selections per role-folder  { folder: {path: BooleanVar} } ──
        self.role_test_vars: Dict[str, Dict[str, ctk.BooleanVar]] = {}
        self._init_test_vars()

        # ── user checkboxes  { "mapName::key": BooleanVar } ──
        self.user_vars: Dict[str, ctk.BooleanVar] = {}

        # currently-displayed role in right panel
        self._active_role_folder: Optional[str] = None

        # ── resume state ──
        self.resume_data: dict = self._load_resume_state()
        # { "mapName::key": {manufacturer_name: BooleanVar} }  for selection
        self.manufacturer_selections: Dict[str, Dict[str, ctk.BooleanVar]] = {}
        # resume toggle per user: { "mapName::key": BooleanVar }
        self.resume_toggles: Dict[str, ctk.BooleanVar] = {}
        # resume indicator widgets per user for refreshing
        self._resume_widgets: Dict[str, dict] = {}

        # ── kill stale ports so we start fresh ──
        self._kill_stale_ports()

        # ── build UI ──
        self._build_ui()

        # ── background monitor ──
        self._start_monitor()

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _kill_stale_ports(self):
        """Kill any process lingering on managed ports at startup."""
        for port in (BE_PORT, FE_PORT):
            pid = get_pid_on_port(port)
            if pid:
                try:
                    kill_process_tree(pid)
                except Exception:
                    pass

    # ────────────────────────────────────────────────────────
    # Init helpers
    # ────────────────────────────────────────────────────────

    def _init_test_vars(self):
        """Create BooleanVars for every test file per role folder,
        pre-selecting those that appear in playwright.config testMatch."""
        config_set = set(self.config_tests)
        for folder, files in self.all_tests.items():
            self.role_test_vars[folder] = {}
            for fpath in files:
                pre = fpath in config_set
                self.role_test_vars[folder][fpath] = ctk.BooleanVar(value=pre)

    # ────────────────────────────────────────────────────────
    # Resume state helpers
    # ────────────────────────────────────────────────────────

    def _load_resume_state(self) -> dict:
        """Load resume_state.json from E2E dir."""
        if RESUME_STATE_FILE.exists():
            try:
                return json.loads(RESUME_STATE_FILE.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {}

    def _save_test_config(self, user_name: str, resume_mode: bool = True):
        """Write test_config.json for Playwright tests to read."""
        # Gather manufacturer selections for all users
        selected = {}
        for uid, mfr_vars in self.manufacturer_selections.items():
            # Find user name from uid
            map_name, ukey = uid.split("::", 1)
            udata = self.user_maps.get(map_name, {}).get(ukey, {})
            uname = udata.get("name", ukey)
            sel_list = [m for m, v in mfr_vars.items() if v.get()]
            if sel_list:
                selected[uname] = sel_list

        config = {
            "selectedManufacturers": selected,
            "resumeMode": resume_mode,
        }
        try:
            TEST_CONFIG_FILE.write_text(json.dumps(config, indent=2), encoding="utf-8")
        except Exception as exc:
            self._log(f"Failed to write test config: {exc}", "err", "e2e")

    def _get_user_resume_info(self, user_name: str) -> Optional[dict]:
        """Get resume info for a user across all specs. Returns combined info or None."""
        if not self.resume_data:
            return None
        info = {"specs": {}, "has_resume": False}
        for spec_name, users in self.resume_data.items():
            if user_name in users:
                u_state = users[user_name]
                status = u_state.get("status", "")
                if status == "failed":
                    info["has_resume"] = True
                    completed_mfrs = len(u_state.get("completedManufacturers", []))
                    total_mfrs = u_state.get("totalManufacturers", "?")
                    completed_stores = len(u_state.get("completedStores", []))
                    total_stores = u_state.get("totalStores", "?")
                    last_failed = u_state.get("lastFailedManufacturer") or u_state.get("lastFailedStore", "")
                    info["specs"][spec_name] = {
                        "completed_mfrs": completed_mfrs,
                        "total_mfrs": total_mfrs,
                        "completed_stores": completed_stores,
                        "total_stores": total_stores,
                        "last_failed": last_failed,
                        "status": status,
                    }
        return info if info["has_resume"] else None

    def _get_discovered_manufacturers(self, user_name: str) -> List[str]:
        """Get all discovered manufacturers for a user from resume state."""
        mfrs = set()
        for spec_name, users in self.resume_data.items():
            if user_name in users:
                discovered = users[user_name].get("discoveredManufacturers", {})
                for _, mfr_list in discovered.items():
                    mfrs.update(mfr_list)
        return sorted(mfrs)

    def _clear_resume_for_user(self, user_name: str):
        """Clear resume state for a specific user across all specs."""
        changed = False
        for spec_name in list(self.resume_data.keys()):
            if user_name in self.resume_data[spec_name]:
                # Keep discoveredManufacturers but clear progress
                discovered = self.resume_data[spec_name][user_name].get("discoveredManufacturers", {})
                self.resume_data[spec_name][user_name] = {
                    "completedManufacturers": [],
                    "completedStores": [],
                    "discoveredManufacturers": discovered,
                    "status": "completed",
                }
                changed = True
        if changed:
            try:
                RESUME_STATE_FILE.write_text(
                    json.dumps(self.resume_data, indent=2), encoding="utf-8")
            except Exception:
                pass
        self._log(f"Cleared resume state for {user_name}", "ok", "e2e")
        self.after(0, self._refresh_resume_indicators)

    def _refresh_resume_indicators(self):
        """Refresh all resume indicator badges in the UI."""
        self.resume_data = self._load_resume_state()
        for uid, widgets in self._resume_widgets.items():
            map_name, ukey = uid.split("::", 1)
            udata = self.user_maps.get(map_name, {}).get(ukey, {})
            uname = udata.get("name", ukey)
            info = self._get_user_resume_info(uname)
            badge = widgets.get("badge")
            clear_btn = widgets.get("clear_btn")
            info_frame = widgets.get("frame")
            if info and info["has_resume"]:
                # Build tooltip-style text
                parts = []
                for spec, s_info in info["specs"].items():
                    short_spec = spec.replace("-common", "").replace("store-", "")
                    if s_info["completed_mfrs"]:
                        parts.append(f"{short_spec}: {s_info['completed_mfrs']}/{s_info['total_mfrs']} mfrs")
                    if s_info["completed_stores"]:
                        parts.append(f"{short_spec}: {s_info['completed_stores']}/{s_info['total_stores']} stores")
                badge_text = "🔄 " + " | ".join(parts) if parts else "🔄 Resume"
                if badge:
                    badge.configure(text=badge_text, text_color=CLR_ORANGE)
                    badge.grid()
                if clear_btn:
                    clear_btn.grid()
                if info_frame:
                    info_frame.grid()
            else:
                if badge:
                    badge.grid_remove()
                if clear_btn:
                    clear_btn.grid_remove()
                if info_frame:
                    info_frame.grid_remove()

    def _open_manufacturer_dialog(self, uid: str, user_name: str):
        """Open a dialog to select manufacturers for a specific user."""
        discovered = self._get_discovered_manufacturers(user_name)

        dialog = ctk.CTkToplevel(self)
        dialog.title(f"🏭 Select Manufacturers — {user_name}")
        dialog.geometry("460x500")
        dialog.transient(self)
        dialog.grab_set()
        dialog.configure(fg_color="#0f172a")

        # Header
        hdr = ctk.CTkLabel(dialog, text=f"Manufacturers for {user_name}",
                           font=("Segoe UI Semibold", 15))
        hdr.pack(pady=(16, 4))

        if not discovered:
            ctk.CTkLabel(dialog,
                         text="No manufacturers discovered yet.\nRun the test once to discover manufacturers.",
                         font=("Segoe UI", 12), text_color="#94a3b8",
                         justify="center").pack(pady=30)

            # Free-text entry for manual input
            ctk.CTkLabel(dialog, text="Or enter manufacturer names (comma-separated):",
                         font=("Segoe UI", 12), text_color="#94a3b8").pack(pady=(10, 4))
            manual_entry = ctk.CTkEntry(dialog, width=380, placeholder_text="e.g. Quest, Old Trapper")
            manual_entry.pack(pady=4)

            def _save_manual():
                text = manual_entry.get().strip()
                if text:
                    mfrs = [m.strip() for m in text.split(",") if m.strip()]
                    if uid not in self.manufacturer_selections:
                        self.manufacturer_selections[uid] = {}
                    for m in mfrs:
                        self.manufacturer_selections[uid][m] = ctk.BooleanVar(value=True)
                dialog.destroy()

            ctk.CTkButton(dialog, text="💾  Save", width=120,
                          fg_color=CLR_GREEN, hover_color="#27ae60", text_color="black",
                          command=_save_manual).pack(pady=12)
            return

        # Info label
        ctk.CTkLabel(dialog,
                     text="Select manufacturers to test (leave all unchecked = test all):",
                     font=("Segoe UI", 11), text_color="#94a3b8").pack(pady=(4, 8))

        # Select all / deselect all bar
        bar = ctk.CTkFrame(dialog, fg_color="transparent")
        bar.pack(fill="x", padx=16)

        # Initialize manufacturer BooleanVars if not already done
        if uid not in self.manufacturer_selections:
            self.manufacturer_selections[uid] = {}
        for m in discovered:
            if m not in self.manufacturer_selections[uid]:
                self.manufacturer_selections[uid][m] = ctk.BooleanVar(value=False)

        mfr_vars = self.manufacturer_selections[uid]

        def _select_all():
            for v in mfr_vars.values():
                v.set(True)

        def _deselect_all():
            for v in mfr_vars.values():
                v.set(False)

        ctk.CTkButton(bar, text="Select All", width=90, height=26,
                      fg_color="#475569", hover_color="#64748b",
                      command=_select_all).pack(side="left", padx=3)
        ctk.CTkButton(bar, text="Deselect All", width=100, height=26,
                      fg_color="#475569", hover_color="#64748b",
                      command=_deselect_all).pack(side="left", padx=3)

        # Scrollable list of manufacturers
        scroll = ctk.CTkScrollableFrame(dialog, fg_color=CLR_CARD, corner_radius=8)
        scroll.pack(fill="both", expand=True, padx=16, pady=8)

        for mfr_name in discovered:
            ctk.CTkCheckBox(
                scroll, text=mfr_name, variable=mfr_vars[mfr_name],
                font=("Segoe UI", 12), checkbox_width=18, checkbox_height=18,
            ).pack(anchor="w", padx=8, pady=2)

        # Save & close
        ctk.CTkButton(dialog, text="✓  Done", width=120,
                      fg_color=CLR_GREEN, hover_color="#27ae60", text_color="black",
                      command=dialog.destroy).pack(pady=12)

    # ────────────────────────────────────────────────────────
    # UI building
    # ────────────────────────────────────────────────────────

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=5)
        self.grid_rowconfigure(1, weight=2)

        # tabs
        self.tabs = ctk.CTkTabview(self, corner_radius=10)
        self.tabs.grid(row=0, column=0, sticky="nsew", padx=12, pady=(12, 4))
        self.tab_svc = self.tabs.add("⚙️  Services")
        self.tab_e2e = self.tabs.add("🧪  E2E Tests")
        self.tab_res = self.tabs.add("📋  Results")

        self._build_services_tab()
        self._build_e2e_tab()
        self._build_results_tab()

        # log panel
        self._build_log_panel()

        # refresh resume badges on startup
        self.after(1000, self._refresh_resume_indicators)

    # ═══════════════════  SERVICES TAB  ═══════════════════

    def _build_services_tab(self):
        self.tab_svc.grid_columnconfigure((0, 1), weight=1)
        self.tab_svc.grid_rowconfigure(0, weight=1)
        self.tab_svc.grid_rowconfigure(1, weight=0)

        self._be_card = self._make_service_card(
            self.tab_svc, "Backend (BE)", BE_PORT,
            self.be_env.get("DB_NAME", "—"), BE_DIR, col=0,
        )
        self._fe_card = self._make_service_card(
            self.tab_svc, "Frontend (FE)", FE_PORT,
            None, FE_DIR, col=1,
            api_url=self.fe_env.get("NEXT_PUBLIC_API_BASE_URL", None),
        )

        # bottom bar
        bar = ctk.CTkFrame(self.tab_svc, fg_color="transparent")
        bar.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        self._btn_rebuild_all = ctk.CTkButton(
            bar, text="🔄  Rebuild All", width=180,
            fg_color="#7c3aed", hover_color="#6d28d9",
            command=self._rebuild_all)
        self._btn_rebuild_all.pack(side="left", padx=6)
        CTkToolTip(self._btn_rebuild_all, "Pulls latest code from current branches and rebuilds both services")
        self._btn_stop_all = ctk.CTkButton(
            bar, text="⏹  Stop All", width=160,
            fg_color=CLR_RED, hover_color="#c0392b",
            command=self._stop_all, state="disabled")
        self._btn_stop_all.pack(side="left", padx=6)
        ctk.CTkButton(bar, text="🔃  Refresh Status", width=160,
                      fg_color="#475569", hover_color="#64748b",
                      command=self._refresh_services).pack(side="left", padx=6)

    def _make_service_card(self, parent, title, port, db_name, repo_dir, col, api_url=None):
        card = ctk.CTkFrame(parent, corner_radius=12, fg_color=CLR_CARD,
                            border_width=1, border_color=CLR_CARD_BORDER)
        card.grid(row=0, column=col, sticky="nsew", padx=8, pady=4)
        card.grid_columnconfigure(1, weight=1)

        w = {}  # widgets dict

        # title row
        hdr = ctk.CTkFrame(card, fg_color=CLR_HEADER, corner_radius=8)
        hdr.grid(row=0, column=0, columnspan=3, sticky="ew", padx=8, pady=(8, 4))
        w["status_dot"] = ctk.CTkLabel(hdr, text="●", font=("Segoe UI", 22),
                                       text_color=CLR_RED)
        w["status_dot"].pack(side="left", padx=(10, 4))
        ctk.CTkLabel(hdr, text=title, font=("Segoe UI Semibold", 16)).pack(
            side="left", padx=4
        )
        w["status_text"] = ctk.CTkLabel(hdr, text="Stopped",
                                        font=("Segoe UI", 13), text_color="#94a3b8")
        w["status_text"].pack(side="right", padx=10)

        # info rows
        r = 1
        ctk.CTkLabel(card, text=f"Port:", font=("Segoe UI", 13),
                     text_color="#94a3b8").grid(row=r, column=0, sticky="w", padx=14, pady=2)
        ctk.CTkLabel(card, text=str(port), font=("Segoe UI Semibold", 13)).grid(
            row=r, column=1, sticky="w", padx=4, pady=2
        )
        r += 1

        if db_name:
            ctk.CTkLabel(card, text="DB:", font=("Segoe UI", 13),
                         text_color="#94a3b8").grid(row=r, column=0, sticky="w", padx=14, pady=2)
            db_frame = ctk.CTkFrame(card, fg_color="transparent")
            db_frame.grid(row=r, column=1, sticky="w", padx=4, pady=2)
            w["db_label"] = ctk.CTkLabel(db_frame, text=db_name,
                                         font=("Segoe UI Semibold", 13),
                                         text_color=CLR_BLUE)
            w["db_label"].pack(side="left")

            def _edit_db():
                dialog = ctk.CTkInputDialog(text="Enter new DB name:", title="Change DB Name")
                new_db = dialog.get_input()
                if new_db and new_db.strip():
                    new_db = new_db.strip()
                    update_env_value(repo_dir / ".env", "DB_NAME", new_db)
                    w["db_label"].configure(text=new_db)
                    self.be_env = parse_env_file(BE_DIR / ".env")
                    self._log(f"Backend DB changed to: {new_db}", "ok", "be")
            
            w["btn_edit_db"] = ctk.CTkButton(db_frame, text="✏️", width=24, height=24,
                                             fg_color="transparent", hover_color="#334155",
                                             command=_edit_db)
            w["btn_edit_db"].pack(side="left", padx=(6, 0))
            CTkToolTip(w["btn_edit_db"], "Change Database Name")
            r += 1

        if api_url:
            ctk.CTkLabel(card, text="API:", font=("Segoe UI", 13),
                         text_color="#94a3b8").grid(row=r, column=0, sticky="w", padx=14, pady=2)
            w["api_label"] = ctk.CTkLabel(card, text=api_url,
                                          font=("Segoe UI Semibold", 11),
                                          text_color=CLR_CYAN)
            w["api_label"].grid(row=r, column=1, sticky="w", padx=4, pady=2)
            r += 1

        # git info
        ctk.CTkLabel(card, text="Branch:", font=("Segoe UI", 13),
                     text_color="#94a3b8").grid(row=r, column=0, sticky="w", padx=14, pady=2)
        w["branch"] = ctk.CTkLabel(card, text="…", font=("Segoe UI Semibold", 13))
        w["branch"].grid(row=r, column=1, sticky="w", padx=4, pady=2)
        r += 1

        ctk.CTkLabel(card, text="Origin:", font=("Segoe UI", 13),
                     text_color="#94a3b8").grid(row=r, column=0, sticky="w", padx=14, pady=2)
        w["git_status"] = ctk.CTkLabel(card, text="…", font=("Segoe UI", 13))
        w["git_status"].grid(row=r, column=1, sticky="w", padx=4, pady=2)
        r += 1

        # buttons
        btn_frame = ctk.CTkFrame(card, fg_color="transparent")
        btn_frame.grid(row=r, column=0, columnspan=3, sticky="ew", padx=8, pady=(10, 4))
        r += 1

        w["btn_start"] = ctk.CTkButton(
            btn_frame, text="▶  Start", width=90,
            fg_color=CLR_GREEN, hover_color="#27ae60", text_color="black",
            command=lambda: self._start_service(title, port, repo_dir, w),
        )
        w["btn_start"].pack(side="left", padx=3)

        w["btn_stop"] = ctk.CTkButton(
            btn_frame, text="⬛  Stop", width=90,
            fg_color=CLR_RED, hover_color="#c0392b",
            command=lambda: self._stop_service(title, port, w),
        )
        w["btn_stop"].pack(side="left", padx=3)

        w["btn_rebuild"] = ctk.CTkButton(
            btn_frame, text="🔨  Rebuild", width=100,
            fg_color="#7c3aed", hover_color="#6d28d9",
            command=lambda: self._rebuild_service(title, port, repo_dir, w),
        )
        w["btn_rebuild"].pack(side="left", padx=3)

        btn_frame2 = ctk.CTkFrame(card, fg_color="transparent")
        btn_frame2.grid(row=r, column=0, columnspan=3, sticky="ew", padx=8, pady=(2, 4))
        r += 1

        w["btn_pull"] = ctk.CTkButton(
            btn_frame2, text="⬇  Git Pull", width=100,
            fg_color="#475569", hover_color="#64748b",
            command=lambda: self._git_pull(title, repo_dir, w),
        )
        w["btn_pull"].pack(side="left", padx=3)

        w["btn_dev"] = ctk.CTkButton(
            btn_frame2, text="🔧  Dev Mode", width=110,
            fg_color="#0e7490", hover_color="#155e75",
            command=lambda: self._start_service(title, port, repo_dir, w, dev=True),
        )
        w["btn_dev"].pack(side="left", padx=3)

        w["btn_branch"] = ctk.CTkButton(
            btn_frame2, text="🔀  Branch", width=100,
            fg_color="#1d4ed8", hover_color="#1e40af",
            command=lambda: self._open_branch_dialog(title, repo_dir, w),
        )
        w["btn_branch"].pack(side="left", padx=3)

        w["port"] = port
        w["repo_dir"] = repo_dir
        w["title"] = title
        return w

    # ── service actions ──

    def _set_svc_status(self, w, running: bool, text: str = ""):
        dot_color = CLR_GREEN if running else CLR_RED
        label = text or ("Running" if running else "Stopped")
        w["status_dot"].configure(text_color=dot_color)
        w["status_text"].configure(text=label)
        # Toggle buttons based on state
        if running:
            w["btn_start"].configure(state="disabled")
            w["btn_stop"].configure(state="normal")
            w["btn_rebuild"].configure(state="disabled")
            w["btn_dev"].configure(state="disabled")
            w["btn_branch"].configure(state="disabled")
        else:
            w["btn_start"].configure(state="normal")
            w["btn_stop"].configure(state="disabled")
            w["btn_rebuild"].configure(state="normal")
            w["btn_dev"].configure(state="normal")
            w["btn_branch"].configure(state="normal")
        # Re-enable pull button (unless git UI update disables it)
        w["btn_pull"].configure(state="normal")

    def _set_svc_busy(self, w, text="Working…"):
        w["status_dot"].configure(text_color=CLR_ORANGE)
        w["status_text"].configure(text=text)
        # Disable all action buttons while busy
        for k in ("btn_start", "btn_stop", "btn_rebuild", "btn_dev", "btn_pull", "btn_branch"):
            w[k].configure(state="disabled")

    def _update_git_ui(self, w, info):
        w["branch"].configure(text=info["branch"])
        if info.get("no_git"):
            w["branch"].configure(text="—")
            w["git_status"].configure(text="No Git Repo", text_color="#64748b")
            w["btn_pull"].configure(state="disabled")
        elif info["error"]:
            w["git_status"].configure(text="⚠ Error", text_color=CLR_ORANGE)
            w["btn_pull"].configure(state="normal")
        elif info["behind"] > 0:
            w["git_status"].configure(
                text=f"↓ {info['behind']} behind", text_color=CLR_ORANGE
            )
            w["btn_pull"].configure(state="normal")
        elif info.get("dirty"):
            w["git_status"].configure(text="✓ Up to date (uncommitted changes)", text_color=CLR_ORANGE)
            w["btn_pull"].configure(state="normal")
        else:
            w["git_status"].configure(text="✓ Up to date", text_color=CLR_GREEN)
            w["btn_pull"].configure(state="normal")

    @staticmethod
    def _svc_target(title: str) -> str:
        return "be" if "BE" in title or "Backend" in title else "fe"

    # ── branch switching ──

    def _open_branch_dialog(self, title, repo_dir, w):
        """Open a searchable branch-picker dialog for a service."""
        tgt = self._svc_target(title)

        # Show loading state
        dialog = ctk.CTkToplevel(self)
        dialog.title(f"🔀 Switch Branch — {title}")
        dialog.geometry("480x560")
        dialog.transient(self)
        dialog.grab_set()
        dialog.configure(fg_color="#0f172a")

        # Header
        hdr = ctk.CTkLabel(dialog, text=f"Switch Branch for {title}",
                           font=("Segoe UI Semibold", 16))
        hdr.pack(pady=(16, 4))

        loading_label = ctk.CTkLabel(dialog, text="⏳ Fetching branches…",
                                     font=("Segoe UI", 13), text_color="#94a3b8")
        loading_label.pack(pady=20)

        # Fetch branches in background
        def _load():
            branches = get_git_branches(repo_dir)
            # Get current branch
            try:
                r = subprocess.run(
                    ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                    cwd=str(repo_dir), capture_output=True, text=True, timeout=5,
                    creationflags=_NO_WINDOW,
                )
                current_branch = r.stdout.strip() if r.returncode == 0 else ""
            except Exception:
                current_branch = ""
            self.after(0, lambda: _build_list(branches, current_branch))

        def _build_list(branches, current_branch):
            loading_label.destroy()

            if not branches:
                ctk.CTkLabel(dialog, text="No branches found.",
                             font=("Segoe UI", 13), text_color="#94a3b8").pack(pady=30)
                ctk.CTkButton(dialog, text="Close", width=100,
                              fg_color="#475569", hover_color="#64748b",
                              command=dialog.destroy).pack(pady=10)
                return

            # Current branch info
            ctk.CTkLabel(dialog, text=f"Current: {current_branch}",
                         font=("Segoe UI Semibold", 13),
                         text_color=CLR_GREEN).pack(pady=(4, 8))

            # Search bar
            search_var = ctk.StringVar()
            search_entry = ctk.CTkEntry(
                dialog, width=420, height=36,
                placeholder_text="🔍  Search branches…",
                font=("Segoe UI", 13),
                textvariable=search_var,
            )
            search_entry.pack(padx=20, pady=(0, 8))
            search_entry.focus_set()

            # Scrollable list
            scroll = ctk.CTkScrollableFrame(dialog, fg_color=CLR_CARD, corner_radius=8)
            scroll.pack(fill="both", expand=True, padx=16, pady=(0, 8))
            scroll.grid_columnconfigure(0, weight=1)

            # Keep track of branch buttons for filtering
            branch_widgets = []

            def _on_select(branch_name):
                dialog.destroy()
                self._switch_branch(title, repo_dir, w, branch_name)

            def _render_branches(filter_text=""):
                # Clear existing
                for bw in branch_widgets:
                    bw.destroy()
                branch_widgets.clear()

                ft = filter_text.strip().lower()
                for bname in branches:
                    if ft and ft not in bname.lower():
                        continue
                    is_current = (bname == current_branch)
                    btn_fg = "#166534" if is_current else "#1e293b"
                    btn_hover = "#15803d" if is_current else "#334155"
                    icon = "  ✓" if is_current else ""
                    btn = ctk.CTkButton(
                        scroll, text=f"  {bname}{icon}",
                        anchor="w", height=32,
                        font=("Segoe UI", 12),
                        fg_color=btn_fg, hover_color=btn_hover,
                        corner_radius=6,
                        command=lambda b=bname: _on_select(b),
                    )
                    btn.pack(fill="x", padx=4, pady=1)
                    branch_widgets.append(btn)

                if not branch_widgets:
                    no_match = ctk.CTkLabel(
                        scroll, text="No matching branches.",
                        font=("Segoe UI", 12), text_color="#64748b",
                    )
                    no_match.pack(pady=10)
                    branch_widgets.append(no_match)

            # Initial render
            _render_branches()

            # Re-render on search
            def _on_search(*_):
                _render_branches(search_var.get())

            search_var.trace_add("write", _on_search)

            # Close button
            ctk.CTkButton(dialog, text="Cancel", width=100,
                          fg_color="#475569", hover_color="#64748b",
                          command=dialog.destroy).pack(pady=(4, 12))

        threading.Thread(target=_load, daemon=True).start()

    def _switch_branch(self, title, repo_dir, w, branch_name):
        """Checkout a git branch for a service (stops service first if running)."""
        tgt = self._svc_target(title)
        port = w["port"]

        def _run():
            self._log(f"═══ Switching to branch: {branch_name} ═══", target=tgt)

            # Stop service if running
            if is_port_in_use(port):
                self._log(f"Stopping {title} before branch switch…", "warn", tgt)
                self.after(0, self._set_svc_busy, w, "Stopping…")
                proc = self.be_process if tgt == "be" else self.fe_process
                if proc and proc.poll() is None:
                    kill_process_tree(proc.pid)
                else:
                    pid = get_pid_on_port(port)
                    if pid:
                        kill_process_tree(pid)
                if tgt == "be":
                    self.be_process = None
                else:
                    self.fe_process = None
                time.sleep(2)

            self.after(0, self._set_svc_busy, w, f"Switching to {branch_name}…")

            # Checkout
            r = subprocess.run(
                ["git", "checkout", branch_name],
                cwd=str(repo_dir), capture_output=True, text=True, timeout=30,
                creationflags=_NO_WINDOW,
            )
            if r.returncode != 0:
                err = r.stderr.strip() or r.stdout.strip()
                self._log(f"Branch switch FAILED: {err}", "err", tgt)
                notify(f"{title} Branch Switch Failed", f"Could not switch to {branch_name}")
                self.after(0, self._refresh_services)
                return

            self._log(f"Switched to branch: {branch_name}", "ok", tgt)

            # Pull latest
            self._log(f"Pulling latest for {branch_name}…", target=tgt)
            self.after(0, self._set_svc_busy, w, "Pulling…")
            r = subprocess.run(
                ["git", "pull", "origin", branch_name],
                cwd=str(repo_dir), capture_output=True, text=True, timeout=60,
                creationflags=_NO_WINDOW,
            )
            if r.returncode == 0:
                self._log(f"Pull: {r.stdout.strip()}", "ok", tgt)
            else:
                self._log(f"Pull warning: {r.stderr.strip()}", "warn", tgt)

            notify(f"{title} Branch Switched", f"Now on branch: {branch_name}")
            self.after(0, self._refresh_services)

        threading.Thread(target=_run, daemon=True).start()

    def _start_service(self, title, port, repo_dir, w, dev=False):
        tgt = self._svc_target(title)
        def _run():
            if is_port_in_use(port):
                self._log(f"Port {port} in use — killing existing process…", "warn", tgt)
                pid = get_pid_on_port(port)
                if pid:
                    kill_process_tree(pid)
                    time.sleep(2)
                if is_port_in_use(port):
                    self._log(f"Could not free port {port}.", "err", tgt)
                    return
                self._log(f"Port {port} freed.", "ok", tgt)
            self.after(0, self._set_svc_busy, w, "Starting…")
            cmd = "yarn dev" if dev else "yarn start"
            self._log(f"Running: {cmd}", target=tgt)
            try:
                proc = subprocess.Popen(
                    cmd, cwd=str(repo_dir), shell=True,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    **_proc_group_kwargs(),
                )
                if tgt == "be":
                    self.be_process = proc
                else:
                    self.fe_process = proc
                threading.Thread(target=self._stream_output, args=(proc, tgt),
                                 daemon=True).start()
                # wait for port
                for _ in range(60):
                    if is_port_in_use(port):
                        self.after(0, self._set_svc_status, w, True)
                        self._log(f"Started on port {port}.", "ok", tgt)
                        return
                    time.sleep(1)
                self._log(f"Timeout waiting for port {port}.", "err", tgt)
            except Exception as exc:
                self._log(f"Start failed: {exc}", "err", tgt)
            self.after(0, self._refresh_services)
        threading.Thread(target=_run, daemon=True).start()

    def _stop_service(self, title, port, w):
        tgt = self._svc_target(title)
        def _run():
            self.after(0, self._set_svc_busy, w, "Stopping…")
            pid = get_pid_on_port(port)
            proc = self.be_process if tgt == "be" else self.fe_process
            if proc and proc.poll() is None:
                kill_process_tree(proc.pid)
                if tgt == "be":
                    self.be_process = None
                else:
                    self.fe_process = None
            elif pid:
                kill_process_tree(pid)
            else:
                self._log("Not running.", "warn", tgt)
                self.after(0, self._set_svc_status, w, False)
                return
            time.sleep(1)
            running = is_port_in_use(port)
            self.after(0, self._set_svc_status, w, running)
            self._log(f"{'Still running!' if running else 'Stopped.'}", target=tgt)
        threading.Thread(target=_run, daemon=True).start()

    def _rebuild_service(self, title, port, repo_dir, w):
        tgt = self._svc_target(title)
        def _run():
            self._log("═══ Rebuild starting ═══", target=tgt)
            # stop
            self.after(0, self._set_svc_busy, w, "Stopping…")
            pid = get_pid_on_port(port)
            proc = self.be_process if tgt == "be" else self.fe_process
            if proc and proc.poll() is None:
                kill_process_tree(proc.pid)
            elif pid:
                kill_process_tree(pid)
            if tgt == "be":
                self.be_process = None
            else:
                self.fe_process = None
            time.sleep(2)

            # build
            self.after(0, self._set_svc_busy, w, "Building…")
            self._log("Running yarn build …", target=tgt)
            r = subprocess.run(
                "yarn build", cwd=str(repo_dir), shell=True,
                capture_output=True, text=True, timeout=600,
                creationflags=_NO_WINDOW,
            )
            if r.returncode != 0:
                self._log(f"Build FAILED:\n{r.stdout}\n{r.stderr}", "err", tgt)
                notify(f"{title} Build Failed", "yarn build returned an error")
                self.after(0, self._set_svc_status, w, False, "Build failed")
                return
            self._log("Build succeeded.", "ok", tgt)

            # start
            self._start_service(title, port, repo_dir, w)
            notify(f"{title} Rebuilt", "Build + start completed successfully")
        threading.Thread(target=_run, daemon=True).start()

    def _rebuild_all(self):
        def _run():
            self.after(0, lambda: self._btn_rebuild_all.configure(state="disabled"))
            self.after(0, lambda: self._btn_stop_all.configure(state="disabled"))
            self._log("═══════ REBUILD ALL ═══════", target="be")
            self._log("═══════ REBUILD ALL ═══════", target="fe")
            # ── Rebuild BE first ──
            self._log("Starting Backend rebuild…", target="be")
            self.after(0, self._set_svc_busy, self._be_card, "Stopping…")
            pid = get_pid_on_port(BE_PORT)
            if self.be_process and self.be_process.poll() is None:
                kill_process_tree(self.be_process.pid)
            elif pid:
                kill_process_tree(pid)
            self.be_process = None
            time.sleep(2)

            self.after(0, self._set_svc_busy, self._be_card, "Pulling…")
            self._log("Pulling latest code from current branch…", target="be")
            rb_branch = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=str(BE_DIR), capture_output=True, text=True, creationflags=_NO_WINDOW)
            if rb_branch.returncode == 0:
                br_be = rb_branch.stdout.strip()
                rb_pull = subprocess.run(["git", "pull", "origin", br_be], cwd=str(BE_DIR), capture_output=True, text=True, timeout=60, creationflags=_NO_WINDOW)
                if rb_pull.returncode == 0:
                    self._log("Pull successful.", "ok", "be")
                else:
                    self._log(f"Pull warning:\n{rb_pull.stderr.strip()}", "warn", "be")

            self.after(0, self._set_svc_busy, self._be_card, "Building…")
            self._log("Running yarn build …", target="be")
            r = subprocess.run("yarn build", cwd=str(BE_DIR), shell=True,
                               capture_output=True, text=True, timeout=600, creationflags=_NO_WINDOW)
            be_ok = False
            if r.returncode != 0:
                self._log(f"Build FAILED:\n{r.stdout}\n{r.stderr}", "err", "be")
                self.after(0, self._set_svc_status, self._be_card, False, "Build failed")
            else:
                self._log("Build succeeded. Starting…", "ok", "be")
                self._start_service("Backend (BE)", BE_PORT, BE_DIR, self._be_card)
                # Wait for BE to actually be running before proceeding to FE
                self._log("Waiting for Backend to be ready…", "info", "be")
                for _ in range(90):
                    if is_port_in_use(BE_PORT):
                        be_ok = True
                        break
                    time.sleep(1)
                if be_ok:
                    self._log("Backend is up and running.", "ok", "be")
                else:
                    self._log("Backend did not start in time.", "warn", "be")

            # ── Then rebuild FE (only after BE is up or timed out) ──
            self._log("Starting Frontend rebuild…", target="fe")
            if be_ok:
                self._log("Backend is running — proceeding with FE rebuild.", "ok", "fe")
            else:
                self._log("⚠ Backend is NOT running — proceeding with FE rebuild anyway.", "warn", "fe")
            self.after(0, self._set_svc_busy, self._fe_card, "Stopping…")
            pid = get_pid_on_port(FE_PORT)
            if self.fe_process and self.fe_process.poll() is None:
                kill_process_tree(self.fe_process.pid)
            elif pid:
                kill_process_tree(pid)
            self.fe_process = None
            time.sleep(2)

            self.after(0, self._set_svc_busy, self._fe_card, "Pulling…")
            self._log("Pulling latest code from current branch…", target="fe")
            rf_branch = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=str(FE_DIR), capture_output=True, text=True, creationflags=_NO_WINDOW)
            if rf_branch.returncode == 0:
                br_fe = rf_branch.stdout.strip()
                rf_pull = subprocess.run(["git", "pull", "origin", br_fe], cwd=str(FE_DIR), capture_output=True, text=True, timeout=60, creationflags=_NO_WINDOW)
                if rf_pull.returncode == 0:
                    self._log("Pull successful.", "ok", "fe")
                else:
                    self._log(f"Pull warning:\n{rf_pull.stderr.strip()}", "warn", "fe")

            self.after(0, self._set_svc_busy, self._fe_card, "Building…")
            self._log("Running yarn build …", target="fe")
            r = subprocess.run("yarn build", cwd=str(FE_DIR), shell=True,
                               capture_output=True, text=True, timeout=600, creationflags=_NO_WINDOW)
            if r.returncode != 0:
                self._log(f"Build FAILED:\n{r.stdout}\n{r.stderr}", "err", "fe")
                self.after(0, self._set_svc_status, self._fe_card, False, "Build failed")
            else:
                self._log("Build succeeded. Starting…", "ok", "fe")
                self._start_service("Frontend (FE)", FE_PORT, FE_DIR, self._fe_card)

            self._log("═══════ REBUILD ALL COMPLETE ═══════", "ok", "be")
            self._log("═══════ REBUILD ALL COMPLETE ═══════", "ok", "fe")
            notify("Rebuild All Complete", "Both FE and BE have been rebuilt")
            self.after(0, self._refresh_services)
        threading.Thread(target=_run, daemon=True).start()

    def _stop_all(self):
        """Stop both BE and FE services."""
        def _run():
            self.after(0, lambda: self._btn_stop_all.configure(state="disabled"))
            self._log("═══════ STOPPING ALL SERVICES ═══════", target="be")
            self._log("═══════ STOPPING ALL SERVICES ═══════", target="fe")

            # Stop BE
            self.after(0, self._set_svc_busy, self._be_card, "Stopping…")
            pid = get_pid_on_port(BE_PORT)
            if self.be_process and self.be_process.poll() is None:
                kill_process_tree(self.be_process.pid)
                self.be_process = None
            elif pid:
                kill_process_tree(pid)
            time.sleep(1)
            be_stopped = not is_port_in_use(BE_PORT)
            self.after(0, self._set_svc_status, self._be_card, not be_stopped)
            self._log(f"Backend: {'Stopped' if be_stopped else 'Still running!'}", target="be")

            # Stop FE
            self.after(0, self._set_svc_busy, self._fe_card, "Stopping…")
            pid = get_pid_on_port(FE_PORT)
            if self.fe_process and self.fe_process.poll() is None:
                kill_process_tree(self.fe_process.pid)
                self.fe_process = None
            elif pid:
                kill_process_tree(pid)
            time.sleep(1)
            fe_stopped = not is_port_in_use(FE_PORT)
            self.after(0, self._set_svc_status, self._fe_card, not fe_stopped)
            self._log(f"Frontend: {'Stopped' if fe_stopped else 'Still running!'}", target="fe")

            self._log("═══════ STOP ALL COMPLETE ═══════", "ok", "be")
            self._log("═══════ STOP ALL COMPLETE ═══════", "ok", "fe")
            notify("All Services Stopped", "Both BE and FE have been stopped")
            self.after(0, self._refresh_services)
        threading.Thread(target=_run, daemon=True).start()

    def _git_pull(self, title, repo_dir, w):
        tgt = self._svc_target(title)
        def _run():
            self.after(0, self._set_svc_busy, w, "Pulling…")
            # Get current branch name
            br_result = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=str(repo_dir), capture_output=True, text=True, timeout=10,
                creationflags=_NO_WINDOW,
            )
            if br_result.returncode != 0:
                self._log("Failed to determine current branch", "err", tgt)
                self.after(0, self._refresh_services)
                return
            branch = br_result.stdout.strip()
            self._log(f"git pull origin {branch} …", target=tgt)
            r = subprocess.run(
                ["git", "pull", "origin", branch],
                cwd=str(repo_dir), capture_output=True, text=True, timeout=60,
                creationflags=_NO_WINDOW,
            )
            if r.stdout.strip():
                self._log(f"{r.stdout.strip()}", target=tgt)
            if r.returncode != 0 and r.stderr.strip():
                self._log(f"{r.stderr.strip()}", "err", tgt)
            self.after(0, self._refresh_services)
        threading.Thread(target=_run, daemon=True).start()

    def _refresh_services(self):
        def _run():
            be_running = is_port_in_use(BE_PORT)
            fe_running = is_port_in_use(FE_PORT)
            be_git = get_git_info(BE_DIR)
            fe_git = get_git_info(FE_DIR)
            # re-read env in case values changed
            self.be_env = parse_env_file(BE_DIR / ".env")
            self.fe_env = parse_env_file(FE_DIR / ".env")
            db_name = self.be_env.get("DB_NAME", "—")
            api_url = self.fe_env.get("NEXT_PUBLIC_API_BASE_URL", "—")
            self.after(0, self._apply_svc_refresh, be_running, fe_running,
                       be_git, fe_git, db_name, api_url)
        threading.Thread(target=_run, daemon=True).start()

    def _apply_svc_refresh(self, be_run, fe_run, be_git, fe_git, db_name, api_url="—"):
        self._set_svc_status(self._be_card, be_run)
        self._set_svc_status(self._fe_card, fe_run)
        self._update_git_ui(self._be_card, be_git)
        self._update_git_ui(self._fe_card, fe_git)
        if "db_label" in self._be_card:
            self._be_card["db_label"].configure(text=db_name)
        if "api_label" in self._fe_card:
            self._fe_card["api_label"].configure(text=api_url)
        # Update Stop All button: enabled only when at least one service is running
        any_running = be_run or fe_run
        self._btn_stop_all.configure(state="normal" if any_running else "disabled")
        # Update Rebuild All button: disabled when any service is running
        self._btn_rebuild_all.configure(state="disabled" if any_running else "normal")

    # ═══════════════════  E2E TESTS TAB  ═══════════════════

    def _build_e2e_tab(self):
        self.tab_e2e.grid_columnconfigure(0, weight=3)
        self.tab_e2e.grid_columnconfigure(1, weight=2)
        self.tab_e2e.grid_rowconfigure(0, weight=0)
        self.tab_e2e.grid_rowconfigure(1, weight=1)

        # ── action bar ──
        action_bar = ctk.CTkFrame(self.tab_e2e, fg_color=CLR_HEADER, corner_radius=8)
        action_bar.grid(row=0, column=0, columnspan=2, sticky="ew", padx=4, pady=(4, 6))

        ctk.CTkButton(action_bar, text="▶  Run Selected", width=140,
                      fg_color=CLR_GREEN, hover_color="#27ae60", text_color="black",
                      command=self._run_selected_users).pack(side="left", padx=6, pady=6)
        ctk.CTkButton(action_bar, text="▶▶  Run All Users", width=150,
                      fg_color="#2563eb", hover_color="#1d4ed8",
                      command=self._run_all_users).pack(side="left", padx=6, pady=6)
        
        self._run_last_failed_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(action_bar, text="Only Failed", variable=self._run_last_failed_var,
                        font=("Segoe UI", 12), checkbox_width=18, checkbox_height=18
                        ).pack(side="left", padx=(10, 6), pady=6)

        ctk.CTkButton(action_bar, text="⏭  Skip Current", width=120,
                      fg_color="#ea580c", hover_color="#c2410c", text_color="white",
                      command=self._skip_current_test).pack(side="left", padx=6, pady=6)

        ctk.CTkButton(action_bar, text="⬛  Stop Tests", width=120,
                      fg_color=CLR_RED, hover_color="#c0392b",
                      command=self._stop_tests).pack(side="left", padx=6, pady=6)

        self._test_status_label = ctk.CTkLabel(
            action_bar, text="Status: Idle", font=("Segoe UI", 13),
            text_color="#94a3b8",
        )
        self._test_status_label.pack(side="right", padx=12)

        # ── left: users ──
        left = ctk.CTkScrollableFrame(self.tab_e2e, corner_radius=10,
                                      fg_color=CLR_CARD, label_text="👥 Users",
                                      label_font=("Segoe UI Semibold", 14))
        left.grid(row=1, column=0, sticky="nsew", padx=(4, 3), pady=4)
        left.grid_columnconfigure(0, weight=1)

        row = 0
        for map_name in ROLE_LABELS:
            users = self.user_maps.get(map_name, {})
            if not users:
                continue
            folder = ROLE_FOLDER_MAP.get(map_name, "")
            label = ROLE_LABELS.get(map_name, map_name)

            # role header (clickable)
            hdr = ctk.CTkButton(
                left, text=label, anchor="w",
                font=("Segoe UI Semibold", 13),
                fg_color="#334155", hover_color="#475569",
                corner_radius=6, height=32,
                command=lambda f=folder: self._show_role_tests(f),
            )
            hdr.grid(row=row, column=0, sticky="ew", padx=4, pady=(8, 2))
            row += 1

            for ukey, udata in users.items():
                uframe = ctk.CTkFrame(left, fg_color="transparent")
                uframe.grid(row=row, column=0, sticky="ew", padx=16, pady=2)
                uframe.grid_columnconfigure(1, weight=1)

                var = ctk.BooleanVar(value=False)
                uid = f"{map_name}::{ukey}"
                self.user_vars[uid] = var

                # Clicking the row (uframe or labels) shows tests for that role
                def _on_row_click(event=None, f=folder):
                    self._show_role_tests(f)

                uframe.bind("<Button-1>", _on_row_click)
                uframe.bind("<Enter>", lambda e, f=uframe: f.configure(fg_color="#334155"))
                uframe.bind("<Leave>", lambda e, f=uframe: f.configure(fg_color="transparent"))

                checkbox = ctk.CTkCheckBox(
                    uframe, text=f"{udata['name']}",
                    font=("Segoe UI", 12), variable=var,
                    checkbox_width=18, checkbox_height=18,
                )
                checkbox.grid(row=0, column=0, sticky="w")

                email_label = ctk.CTkLabel(
                    uframe, text=udata["email"],
                    font=("Segoe UI", 11), text_color="#64748b",
                )
                email_label.grid(row=0, column=1, sticky="e", padx=(8, 10))
                email_label.bind("<Button-1>", _on_row_click)

                # Manufacturer selection button
                mfr_btn = ctk.CTkButton(
                    uframe, text="🏭", width=28, height=26,
                    fg_color=CLR_PURPLE, hover_color="#6d28d9",
                    command=lambda u=uid, n=udata['name']: self._open_manufacturer_dialog(u, n),
                )
                mfr_btn.grid(row=0, column=2, padx=(4, 0))
                CTkToolTip(mfr_btn, f"Select Manufacturers for {udata['name']}")

                play_btn = ctk.CTkButton(
                    uframe, text="▶", width=32, height=26,
                    fg_color=CLR_GREEN, hover_color="#27ae60", text_color="black",
                    command=lambda mn=map_name, uk=ukey, ud=udata: self._run_single_user(mn, uk, ud),
                )
                play_btn.grid(row=0, column=3, padx=(4, 0))
                CTkToolTip(play_btn, f"Run All selected tests for {udata['name']}")

                # Resume indicator (same user row, row 1 of uframe)
                res_info_frame = ctk.CTkFrame(uframe, fg_color="transparent")
                res_info_frame.grid(row=1, column=0, columnspan=4, sticky="ew", padx=(24, 0), pady=(0, 2))
                res_info_frame.grid_columnconfigure(0, weight=1)
                res_info_frame.bind("<Button-1>", _on_row_click)

                resume_badge = ctk.CTkLabel(
                    res_info_frame, text="",
                    font=("Segoe UI", 10), text_color=CLR_ORANGE,
                    anchor="w",
                )
                resume_badge.grid(row=0, column=0, sticky="w")
                resume_badge.grid_remove()
                resume_badge.bind("<Button-1>", _on_row_click)

                clear_btn = ctk.CTkButton(
                    res_info_frame, text="✕ Clear", width=60, height=18,
                    fg_color="#475569", hover_color="#64748b",
                    font=("Segoe UI", 9),
                    command=lambda n=udata['name']: self._clear_resume_for_user(n),
                )
                clear_btn.grid(row=0, column=1, padx=(4, 0))
                clear_btn.grid_remove()

                self._resume_widgets[uid] = {
                    "frame": res_info_frame,
                    "badge": resume_badge,
                    "clear_btn": clear_btn,
                }
                row += 1

        # ── right: test files ──
        self._test_panel = ctk.CTkScrollableFrame(
            self.tab_e2e, corner_radius=10, fg_color=CLR_CARD,
            label_text="📝 Test Files (click a role header)",
            label_font=("Segoe UI Semibold", 14),
        )
        self._test_panel.grid(row=1, column=1, sticky="nsew", padx=(3, 4), pady=4)
        self._test_panel.grid_columnconfigure(0, weight=1)

    def _show_role_tests(self, folder: str):
        """Rebuild right panel with test checkboxes for the given role folder."""
        self._active_role_folder = folder
        # clear
        for child in self._test_panel.winfo_children():
            child.destroy()

        self._test_panel.configure(label_text=f"📝 Tests — {folder}")

        vars_dict = self.role_test_vars.get(folder, {})
        if not vars_dict:
            ctk.CTkLabel(self._test_panel, text="No test files found.",
                         text_color="#94a3b8").grid(row=0, column=0, pady=10)
            return

        # select all / deselect all
        bar = ctk.CTkFrame(self._test_panel, fg_color="transparent")
        bar.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        ctk.CTkButton(bar, text="Select All", width=90, height=26,
                      fg_color="#475569", hover_color="#64748b",
                      command=lambda: self._toggle_all_tests(folder, True)).pack(side="left", padx=3)
        ctk.CTkButton(bar, text="Deselect All", width=100, height=26,
                      fg_color="#475569", hover_color="#64748b",
                      command=lambda: self._toggle_all_tests(folder, False)).pack(side="left", padx=3)

        r = 1
        for fpath, var in vars_dict.items():
            display = fpath.split("/")[-1]
            ctk.CTkCheckBox(
                self._test_panel, text=display, variable=var,
                font=("Segoe UI", 12), checkbox_width=18, checkbox_height=18,
            ).grid(row=r, column=0, sticky="w", padx=8, pady=2)
            r += 1

    def _toggle_all_tests(self, folder, state: bool):
        for var in self.role_test_vars.get(folder, {}).values():
            var.set(state)

    # ── E2E execution ──

    def _get_selected_tests_for_role(self, map_name: str) -> List[str]:
        folder = ROLE_FOLDER_MAP.get(map_name, "")
        return [p for p, v in self.role_test_vars.get(folder, {}).items() if v.get()]

    def _run_single_user(self, map_name, user_key, user_data):
        if self.is_testing:
            self._log("Tests already running. Stop first.", "warn", "e2e")
            return
        tests = self._get_selected_tests_for_role(map_name)
        if not tests:
            self._log("No test files selected for role. Click role header to configure.", "warn", "e2e")
            return
        self._stop_tests_flag = False
        threading.Thread(target=self._execute_tests,
                         args=([(map_name, user_key, user_data, tests)],),
                         daemon=True).start()

    def _run_selected_users(self):
        if self.is_testing:
            self._log("Tests already running.", "warn", "e2e")
            return
        queue = []
        for uid, var in self.user_vars.items():
            if not var.get():
                continue
            map_name, user_key = uid.split("::", 1)
            user_data = self.user_maps.get(map_name, {}).get(user_key, {})
            tests = self._get_selected_tests_for_role(map_name)
            if tests:
                queue.append((map_name, user_key, user_data, tests))
        if not queue:
            self._log("No users selected or no tests for selected roles.", "warn", "e2e")
            return
        self._stop_tests_flag = False
        threading.Thread(target=self._execute_tests, args=(queue,), daemon=True).start()

    def _run_all_users(self):
        if self.is_testing:
            self._log("Tests already running.", "warn", "e2e")
            return
        queue = []
        for map_name, users in self.user_maps.items():
            tests = self._get_selected_tests_for_role(map_name)
            if not tests:
                continue
            for ukey, udata in users.items():
                queue.append((map_name, ukey, udata, tests))
        if not queue:
            self._log("No tests configured. Click role headers to select tests.", "warn", "e2e")
            return
        self._stop_tests_flag = False
        threading.Thread(target=self._execute_tests, args=(queue,), daemon=True).start()

    def _execute_tests(self, queue: list):
        """Run playwright tests for each user in queue, sequentially."""
        self.is_testing = True
        self._idle_notified = False
        total = len(queue)
        self.after(0, lambda: self._test_status_label.configure(
            text=f"Running: 0/{total}", text_color=CLR_ORANGE))

        for idx, (map_name, user_key, user_data, test_files) in enumerate(queue):
            if self._stop_tests_flag:
                self._log("⬛ Tests stopped by user.", target="e2e")
                break

            name = user_data.get("name", user_key)
            self.after(0, lambda n=name, i=idx: self._test_status_label.configure(
                text=f"Running: {i + 1}/{total}  —  {n}",
                text_color=CLR_ORANGE))

            self._log(f"\n{'═' * 60}", target="e2e")
            self._log(f"▶ Running tests for: {name}  ({map_name})", target="e2e")
            self._log(f"  Test files: {len(test_files)}", target="e2e")

            # Check if any selected tests are resumable
            has_resumable = any(t in RESUMABLE_SPECS for t in test_files)
            if has_resumable:
                uid = f"{map_name}::{user_key}"
                resume_enabled = True  # Always enable resume mode
                self._save_test_config(name, resume_mode=resume_enabled)
                self._log(f"  Resume mode: {'ON' if resume_enabled else 'OFF'}", "info", "e2e")
                # Log manufacturer selections if any
                if uid in self.manufacturer_selections:
                    selected = [m for m, v in self.manufacturer_selections[uid].items() if v.get()]
                    if selected:
                        self._log(f"  Selected manufacturers: {', '.join(selected)}", "info", "e2e")

            self._log(f"{'═' * 60}", target="e2e")

            # Build command
            files_str = " ".join(test_files)
            cmd = f'npx playwright test -g "{name}" {files_str}'
            if getattr(self, "_run_last_failed_var", None) and self._run_last_failed_var.get():
                cmd += " --last-failed"
            self._log(f"$ {cmd}", target="e2e")

            # Prepare results dir
            now = datetime.now()
            day_dir = RESULTS_DIR / now.strftime("%Y-%m-%d")
            run_dir = day_dir / f"{now.strftime('%H-%M-%S')}_{name.replace(' ', '_')}"
            run_dir.mkdir(parents=True, exist_ok=True)

            # Clear old playwright-report and test-results to prevent stale artifacts
            pw_report_dir = E2E_DIR / "playwright-report"
            if pw_report_dir.exists():
                try:
                    shutil.rmtree(pw_report_dir)
                except Exception as e:
                    self._log(f"Warning: Could not clear {pw_report_dir}: {e}", "warn", "e2e")

            pw_results_dir = E2E_DIR / "test-results"
            if pw_results_dir.exists():
                try:
                    shutil.rmtree(pw_results_dir)
                except Exception:
                    pass

            log_lines = []
            self._stop_signal_sent = False
            try:
                self.test_process = subprocess.Popen(
                    cmd, cwd=str(E2E_DIR), shell=True,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    **_proc_group_kwargs(),
                    env=_nocolor_env(),
                )
                for raw in iter(self.test_process.stdout.readline, b""):
                    if not raw:
                        break
                    line = strip_ansi(raw.decode("utf-8", errors="replace")).rstrip()
                    if not line:
                        continue  # skip empty lines (progress-indicator junk)
                    log_lines.append(line)
                    self.after(0, self._log, line, "", "e2e")
                self.test_process.wait(timeout=7200)
                rc = self.test_process.returncode
            except Exception as exc:
                rc = -1
                self._log(f"Error: {exc}", "err", "e2e")
                log_lines.append(f"Error: {exc}")

            # Save results — clean UTF-8 text
            (run_dir / "output.log").write_text("\n".join(log_lines), encoding="utf-8")
            (run_dir / "meta.json").write_text(json.dumps({
                "user": name, "email": user_data.get("email", ""),
                "role": map_name, "tests": test_files,
                "exit_code": rc, "timestamp": now.isoformat(),
            }, indent=2), encoding="utf-8")

            # Copy playwright report
            pw_report = E2E_DIR / "playwright-report"
            dest_report = run_dir / "playwright-report"
            if pw_report.exists():
                try:
                    if dest_report.exists():
                        shutil.rmtree(dest_report)
                    shutil.copytree(str(pw_report), str(dest_report))
                except Exception:
                    pass

            status = "PASSED" if rc == 0 else "FAILED"
            self._log(f"Result: {status}  (exit code {rc})", target="e2e")
            self._log(f"Saved to: {run_dir}", target="e2e")
            notify(f"Test {status}: {name}", f"E2E tests for {name} {status.lower()}")

            # Refresh results and resume indicators immediately after each user completes
            self.after(0, self._refresh_results)
            self.after(500, self._refresh_resume_indicators)

        self.is_testing = False
        self.test_process = None
        self.after(0, lambda: self._test_status_label.configure(
            text="Status: Idle", text_color="#94a3b8"))
        notify("All Tests Complete", f"Finished {total} user(s)")

    def _stop_tests(self):
        self._stop_tests_flag = True
        if self.test_process and self.test_process.poll() is None:
            if not getattr(self, "_stop_signal_sent", False):
                self._log("⬛ Sending stop signal. Waiting for Playwright to compile report…", "warn", "e2e")
                self._log("   (Click 'Stop Tests' again to force kill)", "warn", "e2e")
                self._stop_signal_sent = True
                try:
                    _interrupt_process_group(self.test_process)
                except Exception as e:
                    self._log(f"Failed to send stop signal: {e}. Force killing…", "err", "e2e")
                    kill_process_tree(self.test_process.pid)
            else:
                self._log("⬛ Force killing current test process…", "err", "e2e")
                kill_process_tree(self.test_process.pid)

    def _skip_current_test(self):
        if self.test_process and self.test_process.poll() is None:
            self._log("⏭ Skipping current test process…", "warn", "e2e")
            kill_process_tree(self.test_process.pid)
        else:
            self._log("No test process is currently running to skip.", "warn", "e2e")

    # ═══════════════════  RESULTS TAB  ═══════════════════

    def _build_results_tab(self):
        self.tab_res.grid_columnconfigure(0, weight=1)
        self.tab_res.grid_rowconfigure(0, weight=0)
        self.tab_res.grid_rowconfigure(1, weight=1)

        bar = ctk.CTkFrame(self.tab_res, fg_color="transparent")
        bar.grid(row=0, column=0, sticky="ew", pady=(4, 6))
        ctk.CTkButton(bar, text="🔃 Refresh", width=100, fg_color="#475569",
                      hover_color="#64748b",
                      command=self._refresh_results).pack(side="left", padx=6)
        ctk.CTkButton(bar, text="📂 Open Folder", width=120, fg_color="#475569",
                      hover_color="#64748b",
                      command=lambda: _open_path(str(RESULTS_DIR))).pack(side="left", padx=6)

        # Filter dropdown
        ctk.CTkLabel(bar, text="Filter:", font=("Segoe UI", 12),
                     text_color="#94a3b8").pack(side="left", padx=(20, 4))
        self._results_filter = ctk.StringVar(value="All")
        ctk.CTkOptionMenu(
            bar, variable=self._results_filter,
            values=["All", "Passed", "Failed"],
            width=120, height=28,
            fg_color="#475569", button_color="#334155", button_hover_color="#64748b",
            font=("Segoe UI", 12),
            command=lambda _: self._refresh_results(),
        ).pack(side="left", padx=4)

        self._results_frame = ctk.CTkScrollableFrame(
            self.tab_res, corner_radius=10, fg_color=CLR_CARD,
            label_text="📋 Test Results History",
            label_font=("Segoe UI Semibold", 14),
        )
        self._results_frame.grid(row=1, column=0, sticky="nsew", padx=4, pady=4)
        self._results_frame.grid_columnconfigure(0, weight=1)

        self.after(500, self._refresh_results)

    def _refresh_results(self):
        for child in self._results_frame.winfo_children():
            child.destroy()

        if not RESULTS_DIR.exists():
            ctk.CTkLabel(self._results_frame, text="No results yet.",
                         text_color="#94a3b8").grid(row=0, column=0, pady=20)
            return

        # Read filter
        filt = self._results_filter.get()

        # Collect entries:  { date: { role_label: [ (time, user, rc, run_dir) ] } }
        grouped: Dict[str, Dict[str, list]] = {}
        for day_dir in sorted(RESULTS_DIR.iterdir(), reverse=True):
            if not day_dir.is_dir():
                continue
            date_str = day_dir.name
            for run_dir in sorted(day_dir.iterdir(), reverse=True):
                if not run_dir.is_dir():
                    continue
                meta_file = run_dir / "meta.json"
                meta = {}
                if meta_file.exists():
                    try:
                        meta = json.loads(meta_file.read_text(encoding="utf-8"))
                    except Exception:
                        pass
                role_key = meta.get("role", "")
                role_label = ROLE_LABELS.get(role_key, "📁  Other")
                user = meta.get("user", run_dir.name)
                rc = meta.get("exit_code", "?")
                time_str = run_dir.name[:8].replace("-", ":")

                # Apply filter
                if filt == "Passed" and rc != 0:
                    continue
                if filt == "Failed" and rc == 0:
                    continue

                grouped.setdefault(date_str, {}).setdefault(role_label, []).append(
                    (time_str, user, rc, run_dir)
                )

        if not grouped:
            msg = "No results match the filter." if filt != "All" else "No results yet."
            ctk.CTkLabel(self._results_frame, text=msg,
                         text_color="#94a3b8").grid(row=0, column=0, pady=20)
            return

        row = 0
        for date_str in sorted(grouped.keys(), reverse=True):
            roles = grouped[date_str]
            total_pass = sum(1 for rl in roles.values() for e in rl if e[2] == 0)
            total_fail = sum(1 for rl in roles.values() for e in rl if e[2] != 0 and e[2] != "?")
            total_users = sum(len(rl) for rl in roles.values())

            txt_open = f"  ▼  📅  {date_str}        {total_users} runs  •  ✓ {total_pass}  •  ✗ {total_fail}"
            txt_closed = f"  ▶  📅  {date_str}        {total_users} runs  •  ✓ {total_pass}  •  ✗ {total_fail}"

            date_btn = ctk.CTkButton(
                self._results_frame, fg_color="#0f172a", hover_color="#1e293b",
                corner_radius=8, anchor="w", height=36,
                text=txt_open, font=("Segoe UI Semibold", 14),
            )
            date_btn.grid(row=row, column=0, sticky="ew", padx=2, pady=(10, 2))
            row += 1

            date_children = []

            for role_label in sorted(roles.keys()):
                entries = roles[role_label]
                rp = sum(1 for e in entries if e[2] == 0)
                rf = sum(1 for e in entries if e[2] != 0 and e[2] != "?")

                r_open = f"    ▼  {role_label}        {len(entries)} users  |  ✓ {rp}  ✗ {rf}"
                r_closed = f"    ▶  {role_label}        {len(entries)} users  |  ✓ {rp}  ✗ {rf}"

                role_btn = ctk.CTkButton(
                    self._results_frame, fg_color="#1a2332", hover_color="#243044",
                    corner_radius=6, anchor="w", height=30,
                    text=r_open, font=("Segoe UI Semibold", 12),
                )
                role_btn.grid(row=row, column=0, sticky="ew", padx=(16, 2), pady=(4, 1))
                date_children.append(role_btn)
                row += 1

                role_children = []
                for time_str, user, rc, run_dir in entries:
                    urow = ctk.CTkFrame(self._results_frame, fg_color="#1e293b",
                                         corner_radius=4)
                    urow.grid(row=row, column=0, sticky="ew", padx=(36, 2), pady=1)
                    urow.grid_columnconfigure(2, weight=1)

                    s_clr = CLR_GREEN if rc == 0 else CLR_RED
                    s_txt = "✓" if rc == 0 else "✗"

                    ctk.CTkLabel(urow, text=s_txt, font=("Segoe UI Semibold", 13),
                                 text_color=s_clr, width=24).grid(
                        row=0, column=0, padx=(8, 2))
                    ctk.CTkLabel(urow, text=time_str, font=("Consolas", 11),
                                 text_color="#64748b", width=65).grid(
                        row=0, column=1, padx=(2, 6))
                    ctk.CTkLabel(urow, text=user, font=("Segoe UI", 12),
                                 anchor="w").grid(
                        row=0, column=2, sticky="w", padx=2)

                    report_path = run_dir / "playwright-report" / "index.html"
                    if report_path.exists():
                        ctk.CTkButton(
                            urow, text="📊 Report", width=80, height=24,
                            fg_color="#475569", hover_color="#64748b",
                            command=lambda p=str(report_path): _open_path(p),
                        ).grid(row=0, column=3, padx=3, pady=2)

                    log_file = run_dir / "output.log"
                    if log_file.exists():
                        ctk.CTkButton(
                            urow, text="📄 Log", width=60, height=24,
                            fg_color="#475569", hover_color="#64748b",
                            command=lambda p=str(log_file): _open_path(p),
                        ).grid(row=0, column=4, padx=(0, 6), pady=2)

                    role_children.append(urow)
                    date_children.append(urow)
                    row += 1

                # Wire role accordion
                role_btn.configure(command=lambda b=role_btn, c=list(role_children),
                                   o=r_open, cl=r_closed:
                                   self._toggle_accordion(b, c, o, cl))

            # Wire date accordion
            date_btn.configure(command=lambda b=date_btn, c=list(date_children),
                               o=txt_open, cl=txt_closed:
                               self._toggle_accordion(b, c, o, cl))

    def _toggle_accordion(self, btn, children, text_open, text_closed):
        """Toggle visibility of child widgets and update button arrow."""
        if children and children[0].winfo_viewable():
            for w in children:
                w.grid_remove()
            btn.configure(text=text_closed)
        else:
            for w in children:
                w.grid()
            btn.configure(text=text_open)

    # ═══════════════════  LOG PANEL  ═══════════════════

    def _build_log_panel(self):
        log_frame = ctk.CTkFrame(self, corner_radius=10, fg_color=CLR_CARD,
                                 border_width=1, border_color=CLR_CARD_BORDER)
        log_frame.grid(row=1, column=0, sticky="nsew", padx=12, pady=(4, 12))
        log_frame.grid_columnconfigure(0, weight=1)
        log_frame.grid_rowconfigure(0, weight=1)

        # Tabbed log panels
        self._log_tabs = ctk.CTkTabview(log_frame, corner_radius=8,
                                        fg_color=CLR_CARD, height=10)
        self._log_tabs.grid(row=0, column=0, sticky="nsew", padx=4, pady=4)

        tab_e2e = self._log_tabs.add("🧪 E2E Tests")
        tab_be = self._log_tabs.add("🔧 Backend")
        tab_fe = self._log_tabs.add("🌐 Frontend")
        self._log_tabs.set("🧪 E2E Tests")

        # Create textboxes and clear buttons for each tab
        self._log_boxes = {}
        for key, tab in [("e2e", tab_e2e), ("be", tab_be), ("fe", tab_fe)]:
            tab.grid_columnconfigure(0, weight=1)
            tab.grid_rowconfigure(1, weight=1)

            hdr = ctk.CTkFrame(tab, fg_color="transparent")
            hdr.grid(row=0, column=0, sticky="ew")
            ctk.CTkButton(hdr, text="Clear", width=60, height=22,
                          fg_color="#475569", hover_color="#64748b",
                          command=lambda k=key: self._clear_log(k)).pack(
                side="right", padx=4, pady=2)

            tb = ctk.CTkTextbox(tab, font=("Consolas", 12),
                                fg_color="#0f172a", corner_radius=6,
                                wrap="word", state="disabled")
            tb.grid(row=1, column=0, sticky="nsew", padx=2, pady=(2, 4))
            tb.tag_config("err", foreground=CLR_RED)
            tb.tag_config("warn", foreground=CLR_ORANGE)
            tb.tag_config("ok", foreground=CLR_GREEN)
            tb.tag_config("info", foreground=CLR_BLUE)
            self._log_boxes[key] = tb

    def _log(self, text: str, tag: str = "", target: str = "e2e"):
        text = strip_ansi(text)
        box = self._log_boxes.get(target, self._log_boxes["e2e"])
        def _insert():
            box.configure(state="normal")
            ts = datetime.now().strftime("%H:%M:%S")
            box.insert("end", f"[{ts}] {text}\n", tag or "")
            box.see("end")
            box.configure(state="disabled")
        if threading.current_thread() is threading.main_thread():
            _insert()
        else:
            self.after(0, _insert)

    def _clear_log(self, target: str = "e2e"):
        box = self._log_boxes.get(target, self._log_boxes["e2e"])
        box.configure(state="normal")
        box.delete("1.0", "end")
        box.configure(state="disabled")

    def _stream_output(self, proc: subprocess.Popen, target: str):
        """Stream process output to the appropriate log panel."""
        try:
            for raw in iter(proc.stdout.readline, b""):
                if not raw:
                    break
                line = raw.decode("utf-8", errors="replace").rstrip()
                self.after(0, self._log, line, "", target)
        except Exception:
            pass

    # ═══════════════════  MONITORING  ═══════════════════

    def _start_monitor(self):
        def _loop():
            # initial refresh
            time.sleep(1)
            self.after(0, self._refresh_services)

            while self._monitor_running:
                time.sleep(15)
                if not self._monitor_running:
                    break
                be_up = is_port_in_use(BE_PORT)
                fe_up = is_port_in_use(FE_PORT)
                self.after(0, self._set_svc_status, self._be_card, be_up)
                self.after(0, self._set_svc_status, self._fe_card, fe_up)

                # idle detection — triggers when ANY service is running
                any_svc_up = be_up or fe_up
                if any_svc_up and not self.is_testing:
                    # Build a descriptive label for the notification
                    if be_up and fe_up:
                        svc_label = "Both BE and FE services are"
                    elif be_up:
                        svc_label = "Backend (BE) service is"
                    else:
                        svc_label = "Frontend (FE) service is"

                    if self.idle_start_time is None:
                        self.idle_start_time = time.time()
                    
                    elapsed_total = time.time() - self.idle_start_time
                    
                    # First notification after 5 minutes (300 sec)
                    if elapsed_total >= 300 and not self._idle_notified:
                        self._idle_notified = True
                        self.last_idle_notify_time = time.time()
                        notify("Idle Reminder", f"{svc_label} running for 5+ mins without tests. Consider stopping if not needed.")
                    
                    # Repeat notification every 10 minutes (600 sec)
                    elif self._idle_notified:
                        elapsed_since_last = time.time() - self.last_idle_notify_time
                        if elapsed_since_last >= 600:
                            self.last_idle_notify_time = time.time()
                            notify("Idle Reminder", f"{svc_label} still running idle! Please check if they should be stopped.")
                else:
                    self.idle_start_time = None
                    self._idle_notified = False
                    self.last_idle_notify_time = None

        t = threading.Thread(target=_loop, daemon=True)
        t.start()

    # ═══════════════════  CLEANUP  ═══════════════════

    def _on_close(self):
        """Graceful shutdown: stop monitor, kill all processes, free ports."""
        # Confirmation if E2E tests are running
        if self.is_testing:
            from tkinter import messagebox
            if not messagebox.askyesno(
                "E2E Tests Running",
                "E2E tests are currently running.\n\n"
                "Closing the app will stop all running tests and services.\n\n"
                "Are you sure you want to close?",
                icon="warning",
            ):
                return  # User cancelled
        self._monitor_running = False
        # Kill any running test process
        try:
            if self.test_process and self.test_process.poll() is None:
                kill_process_tree(self.test_process.pid)
        except Exception:
            pass
        # Kill managed service processes
        for proc in (self.be_process, self.fe_process):
            try:
                if proc and proc.poll() is None:
                    kill_process_tree(proc.pid)
            except Exception:
                pass
        # Kill anything still on managed ports
        for port in (BE_PORT, FE_PORT):
            try:
                pid = get_pid_on_port(port)
                if pid:
                    kill_process_tree(pid)
            except Exception:
                pass
        self.destroy()


# ════════════════════════════════════════════════════════════
# Entry point
# ════════════════════════════════════════════════════════════

if __name__ == "__main__":
    RESULTS_DIR.mkdir(exist_ok=True)
    app = TestRunnerApp()
    app.mainloop()
