from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand
from django.db import transaction

from config.perfis import PERFIS


def permissoes(itens, acoes):
    encontradas = Permission.objects.none()
    for item in itens:
        app, _, modelo = item.partition(".")
        filtro = {"content_type__app_label": app}
        if modelo:
            filtro["content_type__model"] = modelo
        qs = Permission.objects.filter(**filtro, codename__regex=rf"^({'|'.join(acoes)})_")
        if not qs.exists():
            raise ValueError(f"Nenhuma permissão encontrada para '{item}'. Confira config/perfis.py.")
        encontradas |= qs
    return encontradas


class Command(BaseCommand):
    help = "Cria ou atualiza os grupos de acesso (Diretoria, Engenharia, Compras, Financeiro, Comercial)."

    @transaction.atomic
    def handle(self, *args, **options):
        for nome, regra in PERFIS.items():
            grupo, criado = Group.objects.get_or_create(name=nome)
            perms = permissoes(regra["alterar"], ["view", "add", "change", "delete"]) | permissoes(
                regra["consultar"], ["view"]
            )
            grupo.permissions.set(perms.distinct())
            acao = "criado" if criado else "atualizado"
            self.stdout.write(f"Perfil {nome} {acao}: {grupo.permissions.count()} permissões.")
