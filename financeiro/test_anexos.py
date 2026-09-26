import io
import os
import shutil
import tempfile
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import override_settings
from django.urls import reverse

from . import services
from .models import Baixa, Titulo
from .tests import HOJE, Base

PDF = b"%PDF-1.4 teste"
GESTAO_BAIXAS = {
    "baixas-TOTAL_FORMS": "0", "baixas-INITIAL_FORMS": "0",
    "baixas-MIN_NUM_FORMS": "0", "baixas-MAX_NUM_FORMS": "1000",
}


class AnexosFinanceiroTests(Base):
    def setUp(self):
        super().setUp()
        self.pasta = tempfile.mkdtemp()
        self.ajuste = override_settings(MEDIA_ROOT=self.pasta)
        self.ajuste.enable()
        self.admin = User.objects.create_superuser("admin", "a@a.com", "x")
        self.client.force_login(self.admin)
        self.titulo = self.titulo(parcelas=((0, "100"), (30, "200")))
        self.parcela = self.titulo.parcelas.get(numero=1)
        self.url_parcela = reverse("admin:financeiro_parcelapagar_change", args=[self.parcela.pk])

    def tearDown(self):
        self.ajuste.disable()
        shutil.rmtree(self.pasta, ignore_errors=True)
        super().tearDown()

    def test_boleto_e_linha_digitavel_na_parcela(self):
        resp = self.client.post(self.url_parcela, {
            **GESTAO_BAIXAS,
            "arquivo_boleto": SimpleUploadedFile("boleto.pdf", PDF),
            "linha_digitavel": "23790.12345 60000.123456 78901.234567 8 12340000010000",
        })
        self.assertEqual(resp.status_code, 302)
        self.parcela.refresh_from_db()
        self.assertTrue(self.parcela.arquivo_boleto.name.startswith("boletos/"))
        self.assertEqual(self.parcela.linha_digitavel[:5], "23790")
        url = self.parcela.arquivo_boleto.url
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertContains(self.client.get(reverse("admin:financeiro_parcelapagar_changelist")), url)
        self.assertContains(self.client.get(reverse("admin:financeiro_titulopagar_change", args=[self.titulo.pk])), url)

    def test_comprovante_ao_baixar_e_depois(self):
        dados = {
            "baixas-TOTAL_FORMS": "1", "baixas-INITIAL_FORMS": "0",
            "baixas-MIN_NUM_FORMS": "0", "baixas-MAX_NUM_FORMS": "1000",
            "baixas-0-data": HOJE.strftime("%d/%m/%Y"), "baixas-0-conta": self.conta.pk,
            "baixas-0-valor": "100", "baixas-0-juros": "0", "baixas-0-multa": "0", "baixas-0-desconto": "0",
            "baixas-0-arquivo_comprovante": SimpleUploadedFile("ted.pdf", PDF),
        }
        self.assertEqual(self.client.post(self.url_parcela, dados).status_code, 302)
        baixa = Baixa.objects.get()
        self.assertTrue(baixa.arquivo_comprovante.name.startswith("comprovantes/"))

        # Trocar (ou anexar depois) pela tela própria da baixa.
        url = reverse("admin:financeiro_baixa_change", args=[baixa.pk])
        self.assertContains(self.client.get(self.url_parcela), url)
        resp = self.client.post(url, {"arquivo_comprovante": SimpleUploadedFile("ted2.png", b"\x89PNG")})
        self.assertRedirects(resp, self.url_parcela)
        baixa.refresh_from_db()
        self.assertTrue(baixa.arquivo_comprovante.name.endswith("_ted2.png"))
        self.assertEqual(baixa.valor, Decimal("100"))  # valores da baixa não mudam

    def test_comprovante_unico_na_baixa_em_lote(self):
        ids = ",".join(str(p.pk) for p in self.titulo.parcelas.all())
        resp = self.client.post(reverse("financeiro:baixa_lote") + f"?ids={ids}", {
            "data": HOJE.strftime("%d/%m/%Y"), "conta": self.conta.pk,
            "comprovante": SimpleUploadedFile("lote.pdf", PDF),
        })
        self.assertEqual(resp.status_code, 302)
        nomes = set(Baixa.objects.values_list("arquivo_comprovante", flat=True))
        self.assertEqual(len(nomes), 1)
        self.assertEqual(Baixa.objects.count(), 2)
        self.assertEqual(len(os.listdir(os.path.dirname(os.path.join(self.pasta, nomes.pop())))), 1)

    def test_arquivo_invalido_e_permissoes(self):
        resp = self.client.post(self.url_parcela, {**GESTAO_BAIXAS, "arquivo_boleto": SimpleUploadedFile("b.html", b"<x>")})
        self.assertContains(resp, "Envie o arquivo em PDF, JPG ou PNG")

        self.client.post(self.url_parcela, {**GESTAO_BAIXAS, "arquivo_boleto": SimpleUploadedFile("b.pdf", PDF)})
        baixa = services.baixar(self.parcela, self.conta)
        baixa.arquivo_comprovante = SimpleUploadedFile("c.pdf", PDF)
        baixa.save()
        self.parcela.refresh_from_db()
        boleto, comprovante = self.parcela.arquivo_boleto.url, baixa.arquivo_comprovante.url

        call_command("criar_perfis", stdout=io.StringIO())
        for perfil, esperado in [("Financeiro", 200), ("Diretoria", 200), ("Compras", 403), ("Comercial", 403)]:
            usuario = User.objects.create_user(perfil.lower(), is_staff=True)
            usuario.groups.add(Group.objects.get(name=perfil))
            self.client.force_login(usuario)
            with self.subTest(perfil):
                self.assertEqual(self.client.get(boleto).status_code, esperado)
                self.assertEqual(self.client.get(comprovante).status_code, esperado)

    def test_contas_a_receber_nao_tem_boleto(self):
        receber = Titulo.objects.create(tipo="RECEBER", empresa=self.empresa, cliente=self.cliente)
        parcela = receber.parcelas.create(numero=1, vencimento=HOJE, valor=10)
        resp = self.client.get(reverse("admin:financeiro_parcelareceber_change", args=[parcela.pk]))
        self.assertNotContains(resp, "arquivo_boleto")
