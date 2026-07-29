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
echo  3. Instalar bibliotecas necessarias
echo  4. Instalar o navegador Chromium do Playwright
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
    echo Instale o Python ou verifique se ele esta no PATH.
    echo.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo  Atualizando pip...
echo ============================================================
py -m pip install --upgrade pip

echo.
echo ============================================================
echo  Instalando bibliotecas Python...
echo ============================================================
py -m pip install ^
streamlit ^
pandas ^
playwright ^
beautifulsoup4 ^
lxml ^
requests ^
python-dateutil ^
chardet ^
charset-normalizer

if errorlevel 1 (
    echo.
    echo ERRO: Falha ao instalar uma ou mais bibliotecas.
    echo Verifique a conexao com a internet e permissoes da maquina.
    echo.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo  Instalando Chromium do Playwright...
echo ============================================================
py -m playwright install chromium

if errorlevel 1 (
    echo.
    echo ERRO: Falha ao instalar o Chromium do Playwright.
    echo Em ambiente corporativo, pode haver bloqueio de download.
    echo.
    pause
    exit /b 1
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
