@echo off
setlocal
title SubNexus
color 0A

cd /d "%~dp0"

echo ============================================================
echo  SubNexus - Iniciando
echo ============================================================
echo.
echo Pasta do projeto: %cd%
echo.

rem ---------- [1/4] Localizar Python (py ou python) ----------
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
echo [1/4] Python OK:
%PYCMD% --version
echo.

rem ---------- [2/4] Tkinter ----------
%PYCMD% -c "import tkinter" >nul 2>&1
if errorlevel 1 goto :erro_tkinter
echo [2/4] Tkinter OK (interface local).
echo.

rem ---------- [3/4] Arquivos principais ----------
if exist interface_local.py goto :tem_ui
echo ERRO: interface_local.py nao encontrado nesta pasta:
echo %cd%
echo.
echo Copie todos os arquivos do projeto para a mesma pasta.
goto :fim

:tem_ui
echo [3/4] interface_local.py OK.
if exist vtt_auto_editor.py goto :tem_motor
echo AVISO: vtt_auto_editor.py nao encontrado.
echo A interface abrira em modo demonstracao (sem fluxo CMS).
goto :inicio_app

:tem_motor
echo [4/4] vtt_auto_editor.py OK (fluxo CMS ativo).
echo.

:inicio_app
echo Abrindo a janela do SubNexus...
echo.
echo IMPORTANTE: mantenha esta janela de comando aberta enquanto o
echo aplicativo estiver em uso. Se aparecer algum erro, ela ficara
echo visivel com a mensagem completa.
echo.

%PYCMD% interface_local.py
set "CODIGO=%errorlevel%"
echo.
if "%CODIGO%"=="0" goto :fim
echo ERRO: o aplicativo encerrou com o codigo %CODIGO%.
echo Leia a mensagem acima para identificar o problema.

:fim
echo.
pause
endlocal
