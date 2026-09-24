#!/bin/sh
# Inicia o ERP: atualiza o banco, os perfis de acesso e sobe o servidor.
set -e

python manage.py migrate --noinput
python manage.py criar_perfis

exec gunicorn config.wsgi:application \
    --bind 0.0.0.0:8000 \
    --workers "${GUNICORN_WORKERS:-3}" \
    --timeout 60 \
    --access-logfile - \
    --forwarded-allow-ips "*"
