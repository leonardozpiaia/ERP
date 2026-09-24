#!/bin/sh
# Restaura um backup no banco do ERP, substituindo os dados atuais.
# Uso (na pasta do projeto, no servidor):  sh deploy/restaurar.sh backups/erp-AAAA-MM-DD_HHMM.dump
set -e

ARQUIVO="$1"
if [ -z "$ARQUIVO" ] || [ ! -f "$ARQUIVO" ]; then
    echo "Informe o arquivo de backup. Disponíveis:"; ls -1 backups/ 2>/dev/null
    exit 1
fi
printf "Isto SUBSTITUI todos os dados atuais pelo backup %s. Digite RESTAURAR para confirmar: " "$ARQUIVO"
read -r CONFIRMA
[ "$CONFIRMA" = "RESTAURAR" ] || { echo "Cancelado."; exit 1; }

docker compose stop web
docker compose exec -T db sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner' < "$ARQUIVO"
docker compose start web
echo "Backup restaurado."
