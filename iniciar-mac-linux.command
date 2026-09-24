#!/bin/bash
# ERP Obras - teste no seu computador (Mac e Linux).
# No Mac: dois cliques neste arquivo. No Linux: ./iniciar-mac-linux.command
# Para começar com a base limpa, sem dados de exemplo: ./iniciar-mac-linux.command limpo
cd "$(dirname "$0")" || exit 1

echo "=================================================="
echo "  ERP Obras - teste no seu computador"
echo "=================================================="
echo

falhou() {
    echo
    echo "Algo deu errado. Copie as mensagens acima e envie para quem dá suporte ao sistema."
    read -r -p "Tecle Enter para fechar."
    exit 1
}

if ! command -v python3 >/dev/null 2>&1 || ! python3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)"; then
    echo "É preciso o Python 3.12 ou mais novo."
    echo "Baixe em https://www.python.org/downloads/, instale e rode este arquivo de novo."
    read -r -p "Tecle Enter para fechar."
    exit 1
fi

if [ ! -x .venv/bin/python ]; then
    echo "Preparando o ambiente pela primeira vez. Isso pode levar alguns minutos..."
    python3 -m venv .venv || falhou
fi
VPY=.venv/bin/python

echo "Conferindo os componentes..."
"$VPY" -m pip install --disable-pip-version-check -q -r requirements.txt || falhou
echo "Preparando o banco de dados..."
"$VPY" manage.py migrate --noinput -v 0 || falhou
if [ "$1" = "limpo" ]; then
    "$VPY" manage.py preparar_demo --sem-exemplo || falhou
else
    "$VPY" manage.py preparar_demo || falhou
fi

echo
echo "O ERP vai abrir no navegador: http://127.0.0.1:8000"
echo "Para encerrar, feche esta janela (ou tecle Ctrl+C)."
echo
(
    sleep 4
    if command -v open >/dev/null 2>&1; then open http://127.0.0.1:8000/
    elif command -v xdg-open >/dev/null 2>&1; then xdg-open http://127.0.0.1:8000/ >/dev/null 2>&1
    fi
) &
exec "$VPY" manage.py runserver 127.0.0.1:8000
