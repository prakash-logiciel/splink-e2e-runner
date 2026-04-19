@echo off
:: Splink Test Runner — Launcher
:: Double-click this .bat file or pin it to taskbar.
:: Launches the GUI without keeping a console window open.

cd /d "%~dp0"
start "" pythonw test_runner.py
