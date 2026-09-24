import datetime
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import IntegrityError
from django.test import TestCase
from django.urls import reverse

from cadastros.models import Composicao, ComposicaoItem, Empresa, Insumo, UnidadeMedida
from obras.models import Obra

from .models import Etapa, ItemOrcamento, Orcamento


class OrcamentoTests(TestCase):
    def setUp(self):
        un = UnidadeMedida.objects.create(sigla="un", descricao="unidade")
        self.insumo = Insumo.objects.create(
            codigo="I1", descricao="Bloco", unidade=un, tipo=Insumo.Tipo.MATERIAL,
            preco_unitario=Decimal("2.00"),
        )
        self.comp = Composicao.objects.create(codigo="C1", descricao="Parede", unidade=un)
        ComposicaoItem.objects.create(composicao=self.comp, insumo=self.insumo, coeficiente=Decimal("10"))
        empresa = Empresa.objects.create(razao_social="Empresa", cnpj="1")
        obra = Obra.objects.create(empresa=empresa, codigo="OB1", nome="Obra")
        self.orc = Orcamento.objects.create(
            obra=obra, descricao="Orç", data_base=datetime.date(2026, 1, 1),
            bdi_percentual=Decimal("20"),
        )

    def test_item_copia_preco_atual_ao_ser_criado(self):
        etapa = Etapa.objects.create(orcamento=self.orc, codigo="01", descricao="E")
        item = ItemOrcamento.objects.create(etapa=etapa, composicao=self.comp, quantidade=Decimal("3"))
        self.assertEqual(item.preco_unitario, Decimal("20.0000"))

        # Mudança de preço no cadastro não altera o item já orçado.
        self.insumo.preco_unitario = Decimal("5.00")
        self.insumo.save()
        item.refresh_from_db()
        self.assertEqual(item.preco_unitario, Decimal("20.0000"))

    def test_totais_com_bdi(self):
        etapa = Etapa.objects.create(orcamento=self.orc, codigo="01", descricao="E")
        ItemOrcamento.objects.create(etapa=etapa, composicao=self.comp, quantidade=Decimal("3"))
        ItemOrcamento.objects.create(etapa=etapa, insumo=self.insumo, quantidade=Decimal("5"))
        self.assertEqual(self.orc.custo_direto, Decimal("70.00"))
        self.assertEqual(self.orc.valor_bdi, Decimal("14.00"))
        self.assertEqual(self.orc.preco_total, Decimal("84.00"))

    def test_arvore_soma_subetapas(self):
        e1 = Etapa.objects.create(orcamento=self.orc, codigo="01", descricao="Pai")
        e11 = Etapa.objects.create(orcamento=self.orc, pai=e1, codigo="01.01", descricao="Filho")
        e2 = Etapa.objects.create(orcamento=self.orc, codigo="02", descricao="Outra")
        ItemOrcamento.objects.create(etapa=e1, insumo=self.insumo, quantidade=Decimal("1"))
        ItemOrcamento.objects.create(etapa=e11, insumo=self.insumo, quantidade=Decimal("4"))
        ItemOrcamento.objects.create(etapa=e2, insumo=self.insumo, quantidade=Decimal("10"))

        arvore = [(e.codigo, nivel, total) for e, nivel, total in self.orc.arvore()]
        self.assertEqual(
            arvore,
            [("01", 0, Decimal("10.00")), ("01.01", 1, Decimal("8.00")), ("02", 0, Decimal("20.00"))],
        )

    def test_item_exige_composicao_ou_insumo(self):
        etapa = Etapa.objects.create(orcamento=self.orc, codigo="01", descricao="E")
        item = ItemOrcamento(etapa=etapa, composicao=self.comp, insumo=self.insumo,
                             quantidade=Decimal("1"), preco_unitario=Decimal("1"))
        with self.assertRaises(ValidationError):
            item.clean()
        with self.assertRaises(IntegrityError):
            item.save()

    def test_etapa_nao_pode_ser_pai_de_si_mesma(self):
        e1 = Etapa.objects.create(orcamento=self.orc, codigo="01", descricao="A")
        e2 = Etapa.objects.create(orcamento=self.orc, pai=e1, codigo="01.01", descricao="B")
        e1.pai = e2
        with self.assertRaises(ValidationError):
            e1.clean()


class TelasTests(TestCase):
    def setUp(self):
        call_command("carregar_exemplo", stdout=open("/dev/null", "w"))
        self.user = User.objects.create_superuser("admin", "a@a.com", "senha")
        self.client.force_login(self.user)

    def test_eap_renderiza(self):
        orc = Orcamento.objects.get()
        resp = self.client.get(reverse("orcamento:eap", args=[orc.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Fundações")
        self.assertContains(resp, "ERP Obras")

    def test_telas_do_admin_abrem(self):
        orc = Orcamento.objects.get()
        etapa = orc.etapas.first()
        for url in [
            reverse("admin:index"),
            reverse("admin:orcamento_orcamento_changelist"),
            reverse("admin:orcamento_orcamento_change", args=[orc.pk]),
            reverse("admin:orcamento_etapa_change", args=[etapa.pk]),
            reverse("admin:cadastros_composicao_changelist"),
            reverse("admin:obras_obra_changelist"),
        ]:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_eap_exige_login(self):
        self.client.logout()
        orc = Orcamento.objects.get()
        resp = self.client.get(reverse("orcamento:eap", args=[orc.pk]))
        self.assertEqual(resp.status_code, 302)
