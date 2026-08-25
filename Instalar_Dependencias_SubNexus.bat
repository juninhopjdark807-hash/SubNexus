@echo off
title SubNexus - Instalador de Dependencias
color 0B

echo ============================================================
echo  SubNexus - Instalador de Dependencias Python
echo ============================================================
echo.
echo Este instalador vai:
echo  1. Verificar se o Python esta disponivel
echo  2. Atualizar o pip
echo  3. Instalar o Playwright (fluxo CMS: download + upload)
echo  4. Instalar o navegador Chromium do Playwright
echo.
echo A interface local (interface_local.py) usa SOMENTE a biblioteca
echo padrao do Python (Tkinter) - nao precisa de pip install.
echo.
echo Execute este arquivo dentro da pasta do SubNexus.
echo.
pause

cd /d "%~dp0"

echo.
echo ============================================================
echo  Verificando Python...
echo ============================================================
py --version
if errorlevel 1 (
    echo.
    echo ERRO: Python nao encontrado pelo comando "py".
    echo Instale o Python em https://www.python.org/downloads/
    echo.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo  Verificando Tkinter (interface local)...
echo ============================================================
py -c "import tkinter"
if errorlevel 1 (
    echo.
    echo ERRO: Tkinter nao encontrado neste Python.
    echo Instale o Python oficial (python.org) - o tcl/tk vem por padrao.
    echo.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo  Atualizando o pip...
echo ============================================================
py -m pip install --upgrade pip

echo.
echo ============================================================
echo  Instalando o Playwright (fluxo CMS)...
echo ============================================================
py -m pip install playwright

if errorlevel 1 (
    echo.
    echo AVISO: nao foi possivel instalar o Playwright.
    echo A interface local funciona, mas o fluxo CMS (download/upload) nao.
    echo Verifique a conexao com a internet e permissoes da maquina.
    echo.
)

echo.
echo ============================================================
echo  Instalando o Chromium do Playwright...
echo ============================================================
py -m playwright install chromium

if errorlevel 1 (
    echo.
    echo AVISO: nao foi possivel baixar o Chromium.
    echo Em ambiente corporativo, pode haver bloqueio de download.
    echo.
)

echo.
echo ============================================================
echo  Instalacao concluida.
echo ============================================================
echo.
echo Agora voce pode iniciar o SubNexus pelo arquivo:
echo Iniciar_SubNexus.bat
echo.
pause
