@echo off
pwsh -ExecutionPolicy RemoteSigned -NoExit -File "%~dp0stop-app.ps1"
