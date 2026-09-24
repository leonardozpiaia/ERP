import io

from django.conf import settings
from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

USUARIO = "admin"
SENHA = "admin"


class Command(BaseCommand):
    help = "Prepara o ERP para teste no computador: usuário admin, perfis e dados de exemplo."

    def add_arguments(self, parser):
        parser.add_argument(
            "--sem-exemplo", action="store_true", help="Não carrega os dados de exemplo (base limpa)."
        )

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("preparar_demo é só para teste local; não use em produção.")

        call_command("criar_perfis", stdout=io.StringIO())
        if not User.objects.filter(is_superuser=True).exists():
            User.objects.create_superuser(USUARIO, "admin@exemplo.com", SENHA, first_name="Administrador")
        if not options["sem_exemplo"]:
            call_command("carregar_exemplo", stdout=io.StringIO())
        self.stdout.write(self.style.SUCCESS(
            f"Pronto. Entre com usuário '{USUARIO}' e senha '{SENHA}' (se ainda não trocou)."
        ))
