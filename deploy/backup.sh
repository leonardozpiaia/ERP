#!/bin/sh
# Backup diário do banco (formato do pg_dump -Fc), guardando os últimos N dias.
set -e

DIAS="${BACKUP_DIAS:-14}"
sleep 60  # espera o sistema terminar de preparar o banco após uma inicialização
while true; do
    ARQUIVO="/backups/erp-$(date +%Y-%m-%d_%H%M).dump"
    if pg_dump -h db -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc -f "$ARQUIVO.tmp"; then
        mv "$ARQUIVO.tmp" "$ARQUIVO"
        echo "Backup criado: $ARQUIVO"
        find /backups -name 'erp-*.dump' -mtime +"$DIAS" -delete
    else
        rm -f "$ARQUIVO.tmp"
        echo "ERRO: falha no backup" >&2
    fi
    sleep 86400
done
