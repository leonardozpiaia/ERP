from django.contrib.auth.models import Group, User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.urls import reverse

from config.perfis import PERFIS


class SaudeTests(TestCase):
    def test_saude_responde_sem_login(self):
        resp = self.client.get(reverse("saude"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"status": "ok"})


class PerfisTests(TestCase):
    def setUp(self):
        call_command("criar_perfis", stdout=open("/dev/null", "w"))

    def usuario(self, perfil):
        user = User.objects.create_user(perfil.lower(), password="x", is_staff=True)
        user.groups.add(Group.objects.get(name=perfil))
        self.client.force_login(user)
        return user

    def test_cria_todos_os_perfis_e_e_idempotente(self):
        call_command("criar_perfis", stdout=open("/dev/null", "w"))
        self.assertEqual(set(Group.objects.values_list("name", flat=True)), set(PERFIS))

    def test_diretoria_so_consulta(self):
        user = self.usuario("Diretoria")
        self.assertTrue(user.has_perm("financeiro.view_titulopagar"))
        self.assertTrue(user.has_perm("orcamento.view_orcamento"))
        self.assertFalse(user.has_perm("financeiro.add_baixa"))
        self.assertFalse(user.has_perm("suprimentos.change_pedidocompra"))

    def test_permissoes_por_perfil(self):
        casos = {
            "Engenharia": (["contratos.add_medicao", "suprimentos.add_solicitacaocompra"],
                           ["suprimentos.change_pedidocompra", "financeiro.view_titulopagar"]),
            "Compras": (["suprimentos.change_pedidocompra", "cadastros.add_fornecedor"],
                        ["financeiro.add_baixa", "comercial.view_contratovenda"]),
            "Financeiro": (["financeiro.add_baixa", "financeiro.change_titulopagar"],
                           ["comercial.change_contratovenda", "suprimentos.change_pedidocompra"]),
            "Comercial": (["comercial.change_contratovenda", "financeiro.view_parcelareceber"],
                          ["financeiro.view_titulopagar", "financeiro.add_baixa"]),
        }
        for perfil, (pode, nao_pode) in casos.items():
            with self.subTest(perfil=perfil):
                user = User.objects.create_user(f"u_{perfil}", is_staff=True)
                user.groups.add(Group.objects.get(name=perfil))
                for perm in pode:
                    self.assertTrue(user.has_perm(perm), perm)
                for perm in nao_pode:
                    self.assertFalse(user.has_perm(perm), perm)

    def test_telas_proprias_respeitam_permissao(self):
        self.usuario("Comercial")
        self.assertEqual(self.client.get(reverse("comercial:espelho")).status_code, 200)
        self.assertEqual(self.client.get(reverse("financeiro:fluxo_caixa")).status_code, 403)
        self.assertEqual(self.client.get(reverse("contratos:retencoes")).status_code, 403)
        resp = self.client.get(reverse("admin:index"))
        self.assertContains(resp, "Espelho de vendas")
        self.assertNotContains(resp, "Fluxo de caixa")

    def test_sem_login_vai_para_o_login(self):
        resp = self.client.get(reverse("financeiro:fluxo_caixa"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse("admin:login"), resp["Location"])


class PrepararDemoTests(TestCase):
    # O Django roda os testes com DEBUG=False; o uso normal do comando é em modo de teste local.
    @override_settings(DEBUG=True)
    def test_prepara_usuario_perfis_e_exemplo(self):
        call_command("preparar_demo", stdout=open("/dev/null", "w"))
        call_command("preparar_demo", stdout=open("/dev/null", "w"))  # rodar de novo não duplica
        self.assertEqual(User.objects.filter(is_superuser=True).count(), 1)
        self.assertTrue(User.objects.get(username="admin").check_password("admin"))
        self.assertEqual(Group.objects.count(), len(PERFIS))
        from obras.models import Obra
        self.assertTrue(Obra.objects.filter(codigo="OB-001").exists())

    @override_settings(DEBUG=True)
    def test_sem_exemplo(self):
        call_command("preparar_demo", "--sem-exemplo", stdout=open("/dev/null", "w"))
        from obras.models import Obra
        self.assertFalse(Obra.objects.exists())

    @override_settings(DEBUG=False)
    def test_recusa_em_producao(self):
        with self.assertRaises(CommandError):
            call_command("preparar_demo", stdout=open("/dev/null", "w"))
        self.assertFalse(User.objects.exists())
