@echo off
title SubNexus
color 0A

echo ============================================================
echo  Iniciando SubNexus
echo ============================================================
echo.

cd /d "%~dp0"

echo Verificando Python...
py --version
if errorlevel 1 (
    echo.
    echo ERRO: Python nao encontrado.
    echo Verifique se o Python esta instalado e se o comando "py" funciona.
    echo.
    pause
    exit /b 1
)

echo.
echo Verificando interface local (Tkinter)...
py -c "import tkinter"
if errorlevel 1 (
    echo.
    echo ERRO: Tkinter nao encontrado neste Python.
    echo Instale o Python oficial (python.org) com a opcao tcl/tk, que vem por padrao.
    echo.
    pause
    exit /b 1
)

echo.
echo Abrindo SubNexus...
echo.
py interface_local.py

pause
