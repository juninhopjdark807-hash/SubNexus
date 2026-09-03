@echo off
setlocal
title SubNexus - Benchmark Passivo CMS
color 0A
cd /d "%~dp0"

echo ============================================================
echo  SubNexus - Benchmark manual passivo do CMS
echo  Sem Playwright, CDP ou polling UI Automation

echo ============================================================
echo.

py --version >nul 2>&1
if errorlevel 1 (
    echo ERRO: Python nao encontrado pelo comando "py".
    pause
    exit /b 1
)

py benchmark_cms_passivo.py
set "EXIT_CODE=%ERRORLEVEL%"

echo.
if "%EXIT_CODE%"=="3" (
    echo Instale primeiro a extensao executando:
    echo Instalar_Benchmark_Passivo.bat
) else if not "%EXIT_CODE%"=="0" (
    echo O benchmark terminou com erro. Codigo: %EXIT_CODE%
)
echo.
pause
exit /b %EXIT_CODE%
