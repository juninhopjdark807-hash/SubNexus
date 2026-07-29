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
echo Verificando Streamlit...
py -m streamlit --version
if errorlevel 1 (
    echo.
    echo ERRO: Streamlit nao encontrado neste Python.
    echo.
    echo Execute primeiro:
    echo Instalar_Dependencias_SubNexus.bat
    echo.
    echo Se mesmo assim falhar, rode manualmente:
    echo py -m pip install streamlit pandas playwright watchdog
    echo py -m playwright install chromium
    echo.
    pause
    exit /b 1
)

echo.
echo Abrindo SubNexus...
echo.
py -m streamlit run interface_legendas_dark_progress_clean.py

pause
