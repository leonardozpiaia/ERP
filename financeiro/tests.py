import datetime
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import IntegrityError
from django.test import TestCase
from django.urls import reverse

from cadastros.models import Cliente, Empresa, Fornecedor, Insumo, UnidadeMedida
from config.datas import somar_meses
from obras.models import Obra
from orcamento.models import Etapa, Orcamento
from suprimentos.models import ItemPedido, ItemRecebimento, PedidoCompra, Recebimento

from . import services
from .models import (
    Apropriacao,
    Baixa,
    CategoriaFinanceira,
    ContaBancaria,
    Parcela,
    Titulo,
    TituloPagar,
)

D = Decimal
HOJE = datetime.date.today()


class Base(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(razao_social="Empresa", cnpj="1")
        self.obra = Obra.objects.create(empresa=self.empresa, codigo="OB1", nome="Obra")
        orc = Orcamento.objects.create(obra=self.obra, descricao="O", data_base=HOJE)
        self.orc = orc
        self.fund = Etapa.objects.create(orcamento=orc, codigo="01", descricao="Fundação")
        self.alv = Etapa.objects.create(orcamento=orc, codigo="02", descricao="Alvenaria")
        self.fornecedor = Fornecedor.objects.create(razao_social="F", cpf_cnpj="1")
        self.cliente = Cliente.objects.create(nome="C", cpf_cnpj="2")
        self.conta = ContaBancaria.objects.create(
            empresa=self.empresa, descricao="Conta", saldo_inicial=D("1000"),
            data_saldo_inicial=HOJE - datetime.timedelta(days=90),
        )

    def titulo(self, tipo=Titulo.Tipo.PAGAR, parcelas=((0, "100"),), obra=None):
        pessoa = {"fornecedor": self.fornecedor} if tipo == Titulo.Tipo.PAGAR else {"cliente": self.cliente}
        titulo = Titulo.objects.create(tipo=tipo, empresa=self.empresa, obra=obra, **pessoa)
        for n, (dias, valor) in enumerate(parcelas, start=1):
            Parcela.objects.create(
                titulo=titulo, numero=n, valor=D(valor), vencimento=HOJE + datetime.timedelta(days=dias)
            )
        return titulo

    def recebimento(self, condicao="30/60 dias"):
        un = UnidadeMedida.objects.create(sigla="un", descricao="un")
        i1 = Insumo.objects.create(codigo="I1", descricao="A", unidade=un, tipo="MAT")
        i2 = Insumo.objects.create(codigo="I2", descricao="B", unidade=un, tipo="MAT")
        i3 = Insumo.objects.create(codigo="I3", descricao="C", unidade=un, tipo="MAT")
        pedido = PedidoCompra.objects.create(
            obra=self.obra, fornecedor=self.fornecedor, condicao_pagamento=condicao,
            status=PedidoCompra.Status.APROVADO,
        )
        itens = [
            ItemPedido.objects.create(pedido=pedido, insumo=i1, etapa=self.fund, quantidade=10, preco_unitario=D("30")),
            ItemPedido.objects.create(pedido=pedido, insumo=i2, etapa=self.alv, quantidade=10, preco_unitario=D("10")),
            ItemPedido.objects.create(pedido=pedido, insumo=i3, etapa=None, quantidade=10, preco_unitario=D("10.01")),
        ]
        receb = Recebimento.objects.create(pedido=pedido, numero_nota="555", data=HOJE)
        for item in itens:
            ItemRecebimento.objects.create(recebimento=receb, item_pedido=item, quantidade=item.quantidade)
        return receb


class RegrasTests(Base):
    def test_dividir_fecha_centavos(self):
        partes = services.dividir(D("100.00"), 3)
        self.assertEqual(partes, [D("33.34"), D("33.33"), D("33.33")])
        self.assertEqual(sum(partes), D("100.00"))

    def test_titulo_gerado_do_recebimento(self):
        receb = self.recebimento()
        titulo = services.gerar_titulo_do_recebimento(receb)

        self.assertEqual(titulo.tipo, Titulo.Tipo.PAGAR)
        self.assertEqual(titulo.fornecedor, self.fornecedor)
        self.assertEqual(titulo.obra, self.obra)
        self.assertEqual(titulo.documento, "NF 555")
        self.assertEqual(titulo.total, D("500.10"))
        parcelas = list(titulo.parcelas.order_by("numero"))
        self.assertEqual([p.vencimento for p in parcelas],
                         [HOJE + datetime.timedelta(days=30), HOJE + datetime.timedelta(days=60)])
        self.assertEqual([p.valor for p in parcelas], [D("250.05"), D("250.05")])
        # 300 de fundação e 100 de alvenaria sobre 500,10; o resto não é apropriado.
        aprop = {a.etapa: a.percentual for a in titulo.apropriacoes.all()}
        self.assertEqual(aprop[self.fund].quantize(D("0.01")), D("59.99"))
        self.assertEqual(aprop[self.alv].quantize(D("0.01")), D("20.00"))
        # Gerar de novo não duplica.
        self.assertEqual(services.gerar_titulo_do_recebimento(receb), titulo)
        self.assertEqual(Titulo.objects.count(), 1)

    def test_primeiro_vencimento_vale_para_a_primeira_nota(self):
        receb = self.recebimento(condicao="3x")
        pedido = receb.pedido
        pedido.primeiro_vencimento = HOJE + datetime.timedelta(days=5)
        pedido.save()
        titulo = services.gerar_titulo_do_recebimento(receb)
        self.assertEqual(
            [p.vencimento for p in titulo.parcelas.order_by("numero")],
            [pedido.primeiro_vencimento] + [somar_meses(pedido.primeiro_vencimento, k) for k in (1, 2)],
        )
        # Segunda nota do mesmo pedido: prazos contados da própria data.
        segunda = Recebimento.objects.create(pedido=pedido, numero_nota="556", data=HOJE)
        item = pedido.itens.first()
        item.quantidade = item.quantidade + 5
        item.save()
        ItemRecebimento.objects.create(recebimento=segunda, item_pedido=item, quantidade=D("5"))
        titulo2 = services.gerar_titulo_do_recebimento(segunda)
        self.assertEqual(titulo2.parcelas.order_by("numero").first().vencimento, HOJE + datetime.timedelta(days=30))

    def test_condicao_invalida_nao_gera_titulo(self):
        receb = self.recebimento(condicao="boleto")
        with self.assertRaises(ValidationError):
            services.gerar_titulo_do_recebimento(receb)

    def test_baixa_parcial_juros_e_saldo_bancario(self):
        titulo = self.titulo(parcelas=((0, "100"),))
        parcela = titulo.parcelas.get()
        services.baixar(parcela, self.conta, valor=D("40"), juros=D("2"))
        self.assertEqual(parcela.saldo, D("60"))
        self.assertEqual(parcela.situacao, "Parcial")
        services.baixar(parcela, self.conta, desconto=D("5"))
        self.assertEqual(parcela.saldo, D("0"))
        self.assertEqual(parcela.situacao, "Quitada")
        # 1000 - (40 + 2) - (60 - 5)
        self.assertEqual(self.conta.saldo_atual, D("903"))

        receber = self.titulo(tipo=Titulo.Tipo.RECEBER, parcelas=((0, "500"),))
        services.baixar(receber.parcelas.get(), self.conta)
        self.assertEqual(self.conta.saldo_atual, D("1403"))
        self.assertEqual(self.conta.saldo_em(HOJE - datetime.timedelta(days=1)), D("1000"))

    def test_baixa_nao_passa_do_saldo_nem_usa_conta_de_outra_empresa(self):
        parcela = self.titulo(parcelas=((0, "100"),)).parcelas.get()
        with self.assertRaises(ValidationError):
            services.baixar(parcela, self.conta, valor=D("100.01"))
        outra = Empresa.objects.create(razao_social="Outra", cnpj="2")
        conta_outra = ContaBancaria.objects.create(empresa=outra, descricao="X")
        with self.assertRaises(ValidationError):
            services.baixar(parcela, conta_outra)
        services.baixar(parcela, self.conta)
        with self.assertRaises(ValidationError):
            services.baixar(parcela, self.conta)  # já quitada

    def test_titulo_exige_pessoa_conforme_tipo(self):
        t = Titulo(tipo=Titulo.Tipo.PAGAR, empresa=self.empresa)
        with self.assertRaises(ValidationError):
            t.full_clean()
        with self.assertRaises(IntegrityError):
            Titulo.objects.create(tipo=Titulo.Tipo.RECEBER, empresa=self.empresa, fornecedor=self.fornecedor)

    def test_categoria_deve_combinar_com_tipo(self):
        receita = CategoriaFinanceira.objects.create(codigo="1", descricao="R", tipo="RECEITA")
        t = TituloPagar(empresa=self.empresa, fornecedor=self.fornecedor, categoria=receita)
        with self.assertRaises(ValidationError):
            t.full_clean()

    def test_pago_por_etapa(self):
        titulo = services.gerar_titulo_do_recebimento(self.recebimento(condicao="30/60"))
        services.baixar(titulo.parcelas.get(numero=1), self.conta)
        pago = services.pago_por_etapa(self.orc)
        # Metade do título (250,05) foi paga: 59,99% em fundação e 20% em alvenaria.
        self.assertAlmostEqual(float(pago[self.fund.pk]), 150.0, places=2)
        self.assertAlmostEqual(float(pago[self.alv.pk]), 50.0, places=2)

    def test_fluxo_de_caixa(self):
        pagar = self.titulo(parcelas=((-5, "100"), (10, "200"), (40, "300")))
        receber = self.titulo(tipo=Titulo.Tipo.RECEBER, parcelas=((1, "1000"),))
        services.baixar(receber.parcelas.get(), self.conta, data=HOJE)

        r = services.fluxo_de_caixa(HOJE, HOJE + datetime.timedelta(days=20), agrupamento="dia")
        self.assertEqual(r["saldo_inicial"], D("1000"))
        self.assertEqual(r["atrasados"]["a_pagar"], D("100"))
        linhas = {l["periodo"]: l for l in r["linhas"]}
        self.assertEqual(len(linhas), 21)
        self.assertEqual(linhas[HOJE]["recebido"], D("1000"))
        self.assertEqual(linhas[HOJE + datetime.timedelta(days=10)]["a_pagar"], D("200"))
        # A parcela de 40 dias está fora do período.
        self.assertEqual(sum(l["a_pagar"] for l in r["linhas"]), D("200"))
        # 1000 inicial - 100 vencido + 1000 recebido - 200 a pagar
        self.assertEqual(r["linhas"][-1]["saldo"], D("1700"))
        self.assertEqual(pagar.saldo, D("600"))

        mensal = services.fluxo_de_caixa(HOJE.replace(day=1), HOJE.replace(day=1) + datetime.timedelta(days=100))
        self.assertTrue(all(l["periodo"].day == 1 for l in mensal["linhas"]))


class TelasTests(Base):
    def setUp(self):
        super().setUp()
        self.client.force_login(User.objects.create_superuser("admin", "a@a.com", "senha"))

    def form_titulo(self, **extra):
        dados = {
            "empresa": self.empresa.pk, "obra": self.obra.pk, "fornecedor": self.fornecedor.pk,
            "categoria": "", "documento": "NF 1", "data_emissao": HOJE.strftime("%d/%m/%Y"), "descricao": "",
            "parcelas-TOTAL_FORMS": "2", "parcelas-INITIAL_FORMS": "0",
            "parcelas-MIN_NUM_FORMS": "1", "parcelas-MAX_NUM_FORMS": "1000",
            "parcelas-0-numero": "1", "parcelas-0-vencimento": HOJE.strftime("%d/%m/%Y"), "parcelas-0-valor": "100",
            "parcelas-1-numero": "2", "parcelas-1-vencimento": HOJE.strftime("%d/%m/%Y"), "parcelas-1-valor": "50",
            "apropriacoes-TOTAL_FORMS": "1", "apropriacoes-INITIAL_FORMS": "0",
            "apropriacoes-MIN_NUM_FORMS": "0", "apropriacoes-MAX_NUM_FORMS": "1000",
            "apropriacoes-0-etapa": self.fund.pk, "apropriacoes-0-percentual": "100",
        }
        dados.update(extra)
        return dados

    def test_lancar_titulo_a_pagar_pelo_admin(self):
        url = reverse("admin:financeiro_titulopagar_add")
        resp = self.client.post(url, self.form_titulo(**{"apropriacoes-0-percentual": "120"}))
        self.assertEqual(resp.status_code, 200)  # recusado: passa de 100%
        resp = self.client.post(url, self.form_titulo(**{"parcelas-1-numero": "1"}))
        self.assertEqual(resp.status_code, 200)  # recusado: número de parcela repetido
        self.assertFalse(Titulo.objects.exists())
        resp = self.client.post(url, self.form_titulo())
        self.assertEqual(resp.status_code, 302)
        titulo = Titulo.objects.get()
        self.assertEqual(titulo.tipo, Titulo.Tipo.PAGAR)
        self.assertEqual(titulo.total, D("150"))
        self.assertEqual(Apropriacao.objects.get().percentual, D("100"))

    def test_baixa_na_tela_da_parcela(self):
        parcela = self.titulo(parcelas=((0, "100"),)).parcelas.get()
        url = reverse("admin:financeiro_parcelapagar_change", args=[parcela.pk])
        self.assertEqual(self.client.get(url).status_code, 200)
        base = {
            "baixas-TOTAL_FORMS": "2", "baixas-INITIAL_FORMS": "0",
            "baixas-MIN_NUM_FORMS": "0", "baixas-MAX_NUM_FORMS": "1000",
        }
        linha = lambda n, valor: {
            f"baixas-{n}-data": HOJE.strftime("%d/%m/%Y"), f"baixas-{n}-conta": self.conta.pk,
            f"baixas-{n}-valor": valor, f"baixas-{n}-juros": "0", f"baixas-{n}-multa": "0",
            f"baixas-{n}-desconto": "0",
        }
        # Duas baixas que juntas passam do saldo são recusadas.
        resp = self.client.post(url, {**base, **linha(0, "60"), **linha(1, "60")})
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Baixa.objects.exists())
        resp = self.client.post(url, {**base, **linha(0, "60"), **linha(1, "40")})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(parcela.saldo, D("0"))
        # Com baixa, as parcelas do título ficam travadas.
        resp = self.client.get(reverse("admin:financeiro_titulopagar_change", args=[parcela.titulo_id]))
        self.assertNotContains(resp, 'name="parcelas-0-valor"')

    def test_baixa_em_lote(self):
        titulo = self.titulo(parcelas=((0, "100"), (30, "200")))
        ids = ",".join(str(p.pk) for p in titulo.parcelas.all())
        url = reverse("financeiro:baixa_lote") + f"?ids={ids}"
        resp = self.client.get(url)
        self.assertContains(resp, "300,00")
        resp = self.client.post(url, {"data": HOJE.strftime("%d/%m/%Y"), "conta": self.conta.pk})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(titulo.saldo, D("0"))
        self.assertEqual(self.conta.saldo_atual, D("700"))

    def test_filtros_de_parcelas(self):
        self.titulo(parcelas=((-3, "100"), (3, "200"), (30, "300")))
        url = reverse("admin:financeiro_parcelapagar_changelist")
        for situacao, qtd in [("vencidas", 1), ("7dias", 1), ("aberto", 3), ("quitadas", 0)]:
            with self.subTest(situacao=situacao):
                resp = self.client.get(url, {"situacao": situacao})
                self.assertEqual(resp.context["cl"].result_count, qtd)

    def test_telas_com_dados_de_exemplo(self):
        call_command("carregar_exemplo", stdout=open("/dev/null", "w"))
        titulo = Titulo.objects.filter(tipo="PAGAR", recebimento__isnull=False).first()
        receber = Titulo.objects.filter(tipo="RECEBER").first()
        urls = [
            reverse("admin:index"),
            reverse("admin:financeiro_titulopagar_changelist"),
            reverse("admin:financeiro_titulopagar_change", args=[titulo.pk]),
            reverse("admin:financeiro_titulopagar_add"),
            reverse("admin:financeiro_tituloreceber_changelist"),
            reverse("admin:financeiro_tituloreceber_change", args=[receber.pk]),
            reverse("admin:financeiro_tituloreceber_add"),
            reverse("admin:financeiro_parcelapagar_changelist"),
            reverse("admin:financeiro_parcelareceber_changelist"),
            reverse("admin:financeiro_parcelareceber_change", args=[receber.parcelas.first().pk]),
            reverse("admin:financeiro_contabancaria_changelist"),
            reverse("admin:financeiro_categoriafinanceira_changelist"),
            reverse("financeiro:fluxo_caixa"),
            reverse("financeiro:fluxo_caixa") + "?inicio=2026-01-01&fim=2026-02-01&agrupamento=semana",
            reverse("suprimentos:orcado_comprado", args=[Orcamento.objects.get(obra__codigo="OB-001").pk]),
        ]
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_recebimento_pelo_admin_gera_titulo(self):
        receb = self.recebimento()
        pedido = receb.pedido
        item = pedido.itens.first()
        receb.itens.all().delete()
        receb.delete()
        url = reverse("admin:suprimentos_recebimento_add") + f"?pedido={pedido.pk}"
        resp = self.client.post(url, {
            "pedido": pedido.pk, "data": HOJE.strftime("%d/%m/%Y"), "numero_nota": "9", "observacao": "",
            "itens-TOTAL_FORMS": "1", "itens-INITIAL_FORMS": "0",
            "itens-MIN_NUM_FORMS": "0", "itens-MAX_NUM_FORMS": "1000",
            "itens-0-item_pedido": item.pk, "itens-0-quantidade": "4",
        })
        self.assertEqual(resp.status_code, 302)
        titulo = Titulo.objects.get()
        self.assertEqual(titulo.documento, "NF 9")
        self.assertEqual(titulo.total, D("120.00"))
        # O recebimento não pode mais ser alterado.
        resp = self.client.get(reverse("admin:suprimentos_recebimento_change", args=[titulo.recebimento_id]))
        self.assertNotContains(resp, 'name="itens-0-quantidade"')
