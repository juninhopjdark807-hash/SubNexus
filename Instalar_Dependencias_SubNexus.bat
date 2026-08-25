@echo off
setlocal
title SubNexus - Instalador de Dependencias
color 0B

cd /d "%~dp0"

echo ============================================================
echo  SubNexus - Instalador de Dependencias Python
echo ============================================================
echo.
echo O que sera feito:
echo  1. Verificar o Python (comandos py ou python)
echo  2. Verificar o Tkinter (interface local - ja vem com o Python)
echo  3. Atualizar o pip
echo  4. Instalar o Playwright (fluxo CMS: download + upload)
echo  5. Baixar o navegador Chromium do Playwright
echo.
echo A interface local (interface_local.py) usa SOMENTE a biblioteca
echo padrao do Python (Tkinter) - nao precisa de pip install.
echo.
echo Execute este arquivo dentro da pasta do SubNexus.
echo.
pause
echo.

rem ---------- [1/5] Python ----------
set "PYCMD="
py --version >nul 2>&1
if errorlevel 1 goto :provar_python
set "PYCMD=py"
goto :python_ok

:provar_python
python --version >nul 2>&1
if errorlevel 1 goto :erro_python
set "PYCMD=python"

:python_ok
echo [1/5] Python OK:
%PYCMD% --version
echo.

rem ---------- [2/5] Tkinter ----------
%PYCMD% -c "import tkinter" >nul 2>&1
if errorlevel 1 goto :erro_tkinter
echo [2/5] Tkinter OK (interface local).
echo.

rem ---------- [3/5] pip ----------
echo [3/5] Atualizando o pip...
%PYCMD% -m pip install --upgrade pip
echo.

rem ---------- [4/5] Playwright ----------
echo [4/5] Instalando o Playwright (fluxo CMS)...
%PYCMD% -m pip install playwright
if errorlevel 1 goto :aviso_playwright
echo.

rem ---------- [5/5] Chromium ----------
echo [5/5] Baixando o Chromium do Playwright...
%PYCMD% -m playwright install chromium
if errorlevel 1 goto :aviso_chromium
goto :fim

:erro_python
echo.
echo ERRO: Python nao encontrado (comandos "py" e "python" falharam).
echo Instale o Python em https://www.python.org/downloads/
echo e marque a opcao "Add Python to PATH" durante a instalacao.
goto :fim

:erro_tkinter
echo.
echo ERRO: Tkinter nao encontrado neste Python.
echo Reinstale o Python oficial (python.org) - o tcl/tk vem por padrao.
goto :fim

:aviso_playwright
echo.
echo AVISO: nao foi possivel instalar o Playwright.
echo A interface local funciona, mas o fluxo CMS (download/upload) nao.
echo Verifique a conexao com a internet e as permissoes da maquina.
echo Depois, execute este arquivo novamente.
goto :fim

:aviso_chromium
echo.
echo AVISO: nao foi possivel baixar o Chromium.
echo Em ambiente corporativo pode haver bloqueio de download.
echo A interface local funciona; o fluxo CMS funciona apos o
echo Chromium ser baixado (execute este arquivo novamente).
goto :fim

:fim
echo.
echo ============================================================
echo  Instalacao concluida.
echo ============================================================
echo.
echo Agora voce pode iniciar o SubNexus pelo arquivo:
echo   Iniciar_SubNexus.bat
echo.
pause
endlocal
