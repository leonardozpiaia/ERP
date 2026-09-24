import datetime
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from cadastros.models import Empresa, Fornecedor, UnidadeMedida
from financeiro import services as financeiro
from financeiro.models import ContaBancaria, Titulo
from obras.models import Obra
from orcamento.models import Etapa, Orcamento

from . import services
from .models import ContratoServico, ItemContrato, ItemMedicao, Medicao

D = Decimal
HOJE = datetime.date.today()


class Base(TestCase):
    def setUp(self):
        empresa = Empresa.objects.create(razao_social="E", cnpj="1")
        self.obra = Obra.objects.create(empresa=empresa, codigo="OB1", nome="Obra")
        self.orc = Orcamento.objects.create(obra=self.obra, descricao="O", data_base=HOJE)
        self.alv = Etapa.objects.create(orcamento=self.orc, codigo="01", descricao="Alvenaria")
        self.rev = Etapa.objects.create(orcamento=self.orc, codigo="02", descricao="Revestimento")
        self.m2 = UnidadeMedida.objects.create(sigla="m2", descricao="m2")
        self.empreiteiro = Fornecedor.objects.create(razao_social="Empreiteiro", cpf_cnpj="9")
        self.conta = ContaBancaria.objects.create(empresa=empresa, descricao="Conta")
        self.contrato = ContratoServico.objects.create(
            obra=self.obra, fornecedor=self.empreiteiro, objeto="Alvenaria", retencao_caucao=D("5"),
            retencao_inss=D("11"), retencao_iss=D("2"), prazo_pagamento_dias=10,
        )
        self.alvenaria = ItemContrato.objects.create(
            contrato=self.contrato, descricao="Alvenaria", unidade=self.m2,
            quantidade=D("100"), preco_unitario=D("30"), etapa=self.alv,
        )
        self.reboco = ItemContrato.objects.create(
            contrato=self.contrato, descricao="Reboco", unidade=self.m2,
            quantidade=D("200"), preco_unitario=D("20"), etapa=self.rev,
        )

    def medicao(self, alvenaria="0", reboco="0", aprovar=False):
        medicao = Medicao.objects.create(
            contrato=self.contrato, data=HOJE, periodo_inicio=HOJE, periodo_fim=HOJE
        )
        for item, qtd in [(self.alvenaria, alvenaria), (self.reboco, reboco)]:
            if D(qtd) > 0:
                ItemMedicao.objects.create(medicao=medicao, item_contrato=item, quantidade=D(qtd))
        if aprovar:
            services.aprovar_medicao(medicao)
        return medicao


class RegrasTests(Base):
    def test_so_mede_contrato_ativo(self):
        m = Medicao(contrato=self.contrato, periodo_inicio=HOJE, periodo_fim=HOJE)
        with self.assertRaises(ValidationError):
            m.full_clean()
        services.ativar(self.contrato)
        m.full_clean()

    def test_valores_e_titulo_da_medicao(self):
        services.ativar(self.contrato)
        medicao = self.medicao(alvenaria="50", reboco="75")  # 1500 + 1500
        self.assertEqual(medicao.numero, 1)
        self.assertEqual(medicao.valor_bruto, D("3000.00"))
        self.assertEqual(medicao.valor_caucao, D("150.00"))
        self.assertEqual(medicao.valor_inss, D("330.00"))
        self.assertEqual(medicao.valor_iss, D("60.00"))
        self.assertEqual(medicao.valor_liquido, D("2460.00"))

        titulo = services.aprovar_medicao(medicao)
        self.assertEqual(medicao.status, Medicao.Status.APROVADA)
        self.assertEqual(titulo.tipo, Titulo.Tipo.PAGAR)
        self.assertEqual(titulo.fornecedor, self.empreiteiro)
        self.assertEqual(titulo.total, D("2460.00"))
        self.assertEqual(titulo.parcelas.get().vencimento, HOJE + datetime.timedelta(days=10))
        aprop = {a.etapa: a.percentual for a in titulo.apropriacoes.all()}
        self.assertEqual(aprop, {self.alv: D("50"), self.rev: D("50")})
        self.assertEqual(self.medicao().numero, 2)

    def test_nao_mede_alem_do_contratado(self):
        services.ativar(self.contrato)
        self.medicao(alvenaria="80", aprovar=True)
        medicao = self.medicao()
        item = ItemMedicao(medicao=medicao, item_contrato=self.alvenaria, quantidade=D("20.0001"))
        with self.assertRaises(ValidationError):
            item.full_clean()
        ItemMedicao(medicao=medicao, item_contrato=self.alvenaria, quantidade=D("20")).full_clean()

    def test_medicao_em_elaboracao_reserva_saldo_no_lancamento(self):
        services.ativar(self.contrato)
        self.medicao(alvenaria="80")  # ainda não aprovada
        nova = self.medicao()
        with self.assertRaises(ValidationError):
            ItemMedicao(medicao=nova, item_contrato=self.alvenaria, quantidade=D("21")).full_clean()
        self.assertEqual(self.alvenaria.saldo, D("100"))  # aprovado: nada ainda
        self.assertEqual(self.alvenaria.saldo_a_lancar(), D("20"))

    def test_aprovacao_reconfere_saldo(self):
        # Duas medições em elaboração que, juntas, passam do contratado.
        services.ativar(self.contrato)
        m1 = self.medicao(alvenaria="70")
        m2 = self.medicao(alvenaria="70")
        services.aprovar_medicao(m1)
        with self.assertRaises(ValidationError):
            services.aprovar_medicao(m2)

    def test_aditivo_nao_reduz_abaixo_do_medido(self):
        services.ativar(self.contrato)
        self.medicao(alvenaria="60", aprovar=True)
        self.alvenaria.quantidade = D("59")
        with self.assertRaises(ValidationError):
            self.alvenaria.full_clean()
        self.alvenaria.quantidade = D("150")
        self.alvenaria.full_clean()

    def test_reabrir_medicao(self):
        services.ativar(self.contrato)
        medicao = self.medicao(alvenaria="10", aprovar=True)
        titulo_id = medicao.titulo_id
        services.reabrir_medicao(medicao)
        self.assertEqual(medicao.status, Medicao.Status.RASCUNHO)
        self.assertFalse(Titulo.objects.filter(pk=titulo_id).exists())

        titulo = services.aprovar_medicao(medicao)
        financeiro.baixar(titulo.parcelas.get(), self.conta)
        with self.assertRaises(ValidationError):
            services.reabrir_medicao(medicao)  # já paga

    def test_encerrar_devolve_caucao(self):
        services.ativar(self.contrato)
        self.medicao(alvenaria="100", aprovar=True)
        self.medicao(reboco="100", aprovar=True)
        rascunho = self.medicao(reboco="10")
        with self.assertRaises(ValidationError):
            services.encerrar(self.contrato)
        rascunho.delete()
        services.encerrar(self.contrato)
        self.assertEqual(self.contrato.status, ContratoServico.Status.ENCERRADO)
        # 5% de (3000 + 2000)
        self.assertEqual(self.contrato.titulo_caucao.total, D("250.00"))

    def test_cancelar_so_sem_medicoes(self):
        services.ativar(self.contrato)
        self.medicao(alvenaria="1")
        with self.assertRaises(ValidationError):
            services.cancelar(self.contrato)

    def test_retencoes_e_medido_por_etapa(self):
        services.ativar(self.contrato)
        self.medicao(alvenaria="50", reboco="75", aprovar=True)
        self.medicao(alvenaria="10")  # em elaboração não conta
        linhas, totais = services.retencoes(HOJE, HOJE)
        self.assertEqual(len(linhas), 1)
        self.assertEqual((totais["inss"], totais["iss"], totais["caucao"]), (D("330.00"), D("60.00"), D("150.00")))
        medido = services.medido_por_etapa(self.orc)
        self.assertEqual((medido[self.alv.pk], medido[self.rev.pk]), (D("1500"), D("1500")))


class TelasTests(Base):
    def setUp(self):
        super().setUp()
        self.client.force_login(User.objects.create_superuser("admin", "a@a.com", "senha"))
        services.ativar(self.contrato)

    def test_medicao_pelo_admin(self):
        url = reverse("admin:contratos_medicao_add") + f"?contrato={self.contrato.pk}"
        resp = self.client.get(url)
        self.assertContains(resp, "Alvenaria - contratado 100, a medir 100 m2")
        dados = {
            "contrato": self.contrato.pk, "data": HOJE.strftime("%d/%m/%Y"),
            "periodo_inicio": HOJE.strftime("%d/%m/%Y"), "periodo_fim": HOJE.strftime("%d/%m/%Y"),
            "observacao": "",
            "itens-TOTAL_FORMS": "2", "itens-INITIAL_FORMS": "0",
            "itens-MIN_NUM_FORMS": "0", "itens-MAX_NUM_FORMS": "1000",
            "itens-0-item_contrato": self.alvenaria.pk, "itens-0-quantidade": "",
            "itens-1-item_contrato": self.reboco.pk, "itens-1-quantidade": "",
        }
        resp = self.client.post(url, dados)
        self.assertContains(resp, "pelo menos um serviço")
        resp = self.client.post(url, {**dados, "itens-0-quantidade": "101"})
        self.assertContains(resp, "Maior que o saldo")
        resp = self.client.post(url, {**dados, "itens-0-quantidade": "40"})
        self.assertEqual(resp.status_code, 302)
        medicao = Medicao.objects.get()
        self.assertEqual(medicao.valor_bruto, D("1200.00"))

        changelist = reverse("admin:contratos_medicao_changelist")
        self.client.post(changelist, {"action": "aprovar", "_selected_action": [medicao.pk]})
        medicao.refresh_from_db()
        self.assertEqual(medicao.status, Medicao.Status.APROVADA)
        resp = self.client.get(reverse("admin:contratos_medicao_change", args=[medicao.pk]))
        self.assertNotContains(resp, 'name="itens-0-quantidade"')
        self.assertEqual(
            self.client.get(reverse("admin:contratos_medicao_delete", args=[medicao.pk])).status_code, 403
        )

    def test_boletim(self):
        self.medicao(alvenaria="30", aprovar=True)
        m2 = self.medicao(alvenaria="20", reboco="10")
        resp = self.client.get(reverse("contratos:boletim", args=[m2.pk]))
        self.assertEqual(resp.status_code, 200)
        linha = resp.context["linhas"][0]
        self.assertEqual((linha["anterior"], linha["atual"], linha["acumulado"], linha["saldo"]),
                         (D("30"), D("20"), D("50"), D("50")))
        self.assertContains(resp, "Boletim de medição nº 2")

    def test_orcado_realizado_inclui_medicoes(self):
        self.medicao(alvenaria="50", aprovar=True)
        resp = self.client.get(reverse("suprimentos:orcado_comprado", args=[self.orc.pk]))
        linha = next(l for l in resp.context["linhas"] if l["etapa"] == self.alv)
        self.assertEqual(linha["medido"], D("1500.00"))
        self.assertEqual(linha["realizado"], D("1500.00"))

    def test_telas_com_dados_de_exemplo(self):
        call_command("carregar_exemplo", stdout=open("/dev/null", "w"))
        contrato = ContratoServico.objects.get(obra__codigo="OB-001")
        medicao = contrato.medicoes.first()
        urls = [
            reverse("admin:contratos_contratoservico_changelist"),
            reverse("admin:contratos_contratoservico_change", args=[contrato.pk]),
            reverse("admin:contratos_contratoservico_add"),
            reverse("admin:contratos_medicao_changelist"),
            reverse("admin:contratos_medicao_change", args=[medicao.pk]),
            reverse("contratos:boletim", args=[medicao.pk]),
            reverse("contratos:retencoes"),
            reverse("contratos:retencoes") + "?inicio=2020-01-01&fim=2030-12-31",
            reverse("suprimentos:orcado_comprado", args=[Orcamento.objects.get(obra__codigo="OB-001").pk]),
            reverse("admin:index"),
        ]
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(self.client.get(reverse("admin:contratos_medicao_add")).status_code, 302)
