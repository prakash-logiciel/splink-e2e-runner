"""
Splink Test Runner — Windowless Launcher
=========================================
This .pyw file runs with pythonw.exe, so no console window appears.
Double-click this file to launch the Test Runner GUI directly.
The app will only close when you click the X button.
"""
import runpy
import sys
from pathlib import Path

# Ensure we're running from the correct directory
script_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(script_dir))

# Run the main test_runner module
runpy.run_path(str(script_dir / "test_runner.py"), run_name="__main__")
