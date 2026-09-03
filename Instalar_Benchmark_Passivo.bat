@echo off
setlocal
title SubNexus - Instalar Observador Passivo
color 0B
cd /d "%~dp0"

echo ============================================================
echo  SubNexus - Instalacao unica do benchmark passivo
echo ============================================================
echo.

py --version >nul 2>&1
if errorlevel 1 (
    echo ERRO: Python nao encontrado pelo comando "py".
    pause
    exit /b 1
)

py benchmark_cms_passivo.py --setup-extension
set "EXIT_CODE=%ERRORLEVEL%"

echo.
if not "%EXIT_CODE%"=="0" echo A configuracao nao foi concluida. Codigo: %EXIT_CODE%
echo Depois de carregar a extensao, feche completamente o Chrome.
echo.
pause
exit /b %EXIT_CODE%
