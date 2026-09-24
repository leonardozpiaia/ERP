@echo off
setlocal
cd /d "%~dp0"
title ERP Obras - teste local
echo ==================================================
echo   ERP Obras - teste no seu computador
echo ==================================================
echo.

set "PY="
py -3 --version >nul 2>&1 && set "PY=py -3"
if not defined PY (python --version >nul 2>&1 && set "PY=python")
if not defined PY goto sem_python
%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" || goto python_antigo

if not exist ".venv\Scripts\python.exe" (
    echo Preparando o ambiente pela primeira vez. Isso pode levar alguns minutos...
    %PY% -m venv .venv || goto erro
)
set "VPY=.venv\Scripts\python.exe"

echo Conferindo os componentes...
"%VPY%" -m pip install --disable-pip-version-check -q -r requirements.txt || goto erro
echo Preparando o banco de dados...
"%VPY%" manage.py migrate --noinput -v 0 || goto erro
if /i "%~1"=="limpo" (
    "%VPY%" manage.py preparar_demo --sem-exemplo || goto erro
) else (
    "%VPY%" manage.py preparar_demo || goto erro
)

echo.
echo O ERP vai abrir no navegador: http://127.0.0.1:8000
echo Para encerrar, feche esta janela.
echo.
start "" cmd /c "timeout /t 4 /nobreak >nul & start http://127.0.0.1:8000/"
"%VPY%" manage.py runserver 127.0.0.1:8000
goto fim

:sem_python
echo Python nao foi encontrado neste computador.
echo.
echo 1. Baixe em https://www.python.org/downloads/ e instale.
echo 2. IMPORTANTE: na primeira tela do instalador, marque "Add python.exe to PATH".
echo 3. Depois feche esta janela e de dois cliques de novo neste arquivo.
goto pausa

:python_antigo
echo A versao do Python instalada e antiga. Instale a 3.12 ou mais nova:
echo https://www.python.org/downloads/
goto pausa

:erro
echo.
echo Algo deu errado. Copie as mensagens acima e envie para quem da suporte ao sistema.

:pausa
echo.
pause

:fim
endlocal
