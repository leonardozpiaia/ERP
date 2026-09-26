import io
import shutil
import tempfile

from django.contrib.auth.models import Group, User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import override_settings
from django.urls import reverse

from financeiro.models import Titulo

from . import services
from .models import PedidoCompra, Recebimento
from .tests import Base

PDF = b"%PDF-1.4 nota fiscal de teste"


class AnexoNotaTests(Base):
    def setUp(self):
        super().setUp()
        self.pasta = tempfile.mkdtemp()
        self.ajuste = override_settings(MEDIA_ROOT=self.pasta)
        self.ajuste.enable()
        self.admin = User.objects.create_superuser("admin", "a@a.com", "x")
        self.client.force_login(self.admin)
        sc = self.solicitacao()
        self.pedido = next(
            p for p in services.gerar_pedidos(self.cotacao_com_precos(sc)) if p.fornecedor == self.f1
        )
        services.aprovar_pedido(self.pedido)

    def tearDown(self):
        self.ajuste.disable()
        shutil.rmtree(self.pasta, ignore_errors=True)
        super().tearDown()

    def receber(self, arquivo):
        url = reverse("admin:suprimentos_recebimento_add") + f"?pedido={self.pedido.pk}"
        return self.client.post(url, {
            "pedido": self.pedido.pk, "data": "01/10/2026", "numero_nota": "123", "observacao": "",
            "arquivo_nota": arquivo,
            "itens-TOTAL_FORMS": "1", "itens-INITIAL_FORMS": "0",
            "itens-MIN_NUM_FORMS": "0", "itens-MAX_NUM_FORMS": "1000",
            "itens-0-item_pedido": self.pedido.itens.get().pk, "itens-0-quantidade": "10",
        })

    def test_anexar_e_abrir_nota(self):
        resp = self.receber(SimpleUploadedFile("nota 123.pdf", PDF, content_type="application/pdf"))
        self.assertEqual(resp.status_code, 302)
        receb = Recebimento.objects.get()
        self.assertTrue(receb.arquivo_nota.name.startswith("notas/"))
        self.assertTrue(receb.arquivo_nota.name.endswith("_nota_123.pdf"))
        url = receb.arquivo_nota.url
        self.assertTrue(url.startswith("/anexos/notas/"))

        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(b"".join(resp.streaming_content), PDF)
        self.assertEqual(resp["Content-Type"], "application/pdf")

        # Links no recebimento, na lista e na conta a pagar gerada.
        self.assertContains(self.client.get(reverse("admin:suprimentos_recebimento_change", args=[receb.pk])), url)
        self.assertContains(self.client.get(reverse("admin:suprimentos_recebimento_changelist")), "Abrir nota fiscal")
        titulo = Titulo.objects.get(recebimento=receb)
        self.assertContains(self.client.get(reverse("admin:financeiro_titulopagar_change", args=[titulo.pk])), url)

    def test_nota_pode_ser_anexada_depois(self):
        self.receber("")
        receb = Recebimento.objects.get()
        self.assertFalse(receb.arquivo_nota)
        resp = self.client.post(reverse("admin:suprimentos_recebimento_change", args=[receb.pk]), {
            "data": "01/10/2026", "numero_nota": "123", "observacao": "",
            "arquivo_nota": SimpleUploadedFile("nota.xml", b"<nfe/>", content_type="text/xml"),
            "itens-TOTAL_FORMS": "1", "itens-INITIAL_FORMS": "1",
            "itens-MIN_NUM_FORMS": "0", "itens-MAX_NUM_FORMS": "1000",
            "itens-0-id": receb.itens.get().pk, "itens-0-recebimento": receb.pk,
        })
        self.assertEqual(resp.status_code, 302)
        receb.refresh_from_db()
        self.assertTrue(receb.arquivo_nota.name.endswith(".xml"))

    def test_tipos_de_arquivo_recusados(self):
        for nome in ["nota.html", "nota.exe", "nota.pdf.js"]:
            with self.subTest(nome):
                resp = self.receber(SimpleUploadedFile(nome, b"x"))
                self.assertContains(resp, "Envie a nota em PDF, XML, JPG ou PNG")
        self.assertFalse(Recebimento.objects.exists())

    def test_acesso_protegido(self):
        self.receber(SimpleUploadedFile("nota.pdf", PDF))
        url = Recebimento.objects.get().arquivo_nota.url

        self.client.logout()
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse("admin:login"), resp["Location"])

        call_command("criar_perfis", stdout=io.StringIO())
        comercial = User.objects.create_user("com", is_staff=True)
        comercial.groups.add(Group.objects.get(name="Comercial"))
        self.client.force_login(comercial)
        self.assertEqual(self.client.get(url).status_code, 403)

        financeiro = User.objects.create_user("fin", is_staff=True)
        financeiro.groups.add(Group.objects.get(name="Financeiro"))
        self.client.force_login(financeiro)
        self.assertEqual(self.client.get(url).status_code, 200)

        self.client.force_login(self.admin)
        for caminho in ["/anexos/notas/../../config/settings.py", "/anexos/outra/arquivo.pdf",
                        "/anexos/notas/nao-existe.pdf"]:
            with self.subTest(caminho):
                self.assertEqual(self.client.get(caminho).status_code, 404)
        self.assertTrue(PedidoCompra.objects.exists())
