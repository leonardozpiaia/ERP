import datetime
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from cadastros.models import Empresa, Fornecedor, Insumo, UnidadeMedida
from obras.models import Obra
from orcamento.models import Etapa, ItemOrcamento, Orcamento

from . import services
from .models import (
    ItemRecebimento,
    ItemSolicitacao,
    PedidoCompra,
    PrecoCotado,
    PropostaFornecedor,
    Recebimento,
    SolicitacaoCompra,
)
from .views import ler_decimal


class Base(TestCase):
    def setUp(self):
        un = UnidadeMedida.objects.create(sigla="un", descricao="unidade")
        self.bloco = Insumo.objects.create(
            codigo="I1", descricao="Bloco", unidade=un, tipo=Insumo.Tipo.MATERIAL,
            preco_unitario=Decimal("2"),
        )
        self.cimento = Insumo.objects.create(
            codigo="I2", descricao="Cimento", unidade=un, tipo=Insumo.Tipo.MATERIAL,
            preco_unitario=Decimal("40"),
        )
        empresa = Empresa.objects.create(razao_social="Empresa", cnpj="1")
        self.obra = Obra.objects.create(empresa=empresa, codigo="OB1", nome="Obra")
        self.orc = Orcamento.objects.create(
            obra=self.obra, descricao="Orç", data_base=datetime.date(2026, 1, 1)
        )
        self.etapa = Etapa.objects.create(orcamento=self.orc, codigo="01", descricao="Alvenaria")
        self.f1 = Fornecedor.objects.create(razao_social="F1", cpf_cnpj="1")
        self.f2 = Fornecedor.objects.create(razao_social="F2", cpf_cnpj="2")

    def solicitacao(self, aprovada=True):
        sc = SolicitacaoCompra.objects.create(obra=self.obra)
        ItemSolicitacao.objects.create(
            solicitacao=sc, insumo=self.bloco, quantidade=Decimal("1000"), etapa=self.etapa
        )
        ItemSolicitacao.objects.create(solicitacao=sc, insumo=self.cimento, quantidade=Decimal("10"))
        if aprovada:
            services.aprovar_solicitacao(sc)
        return sc

    def cotacao_com_precos(self, sc):
        cotacao = services.gerar_cotacao([sc])
        bloco, cimento = cotacao.itens.order_by("pk")
        p1 = PropostaFornecedor.objects.create(cotacao=cotacao, fornecedor=self.f1, prazo_entrega_dias=5)
        p2 = PropostaFornecedor.objects.create(cotacao=cotacao, fornecedor=self.f2)
        # F1 ganha o bloco, F2 ganha o cimento.
        PrecoCotado.objects.create(proposta=p1, item=bloco, preco_unitario=Decimal("1.90"))
        PrecoCotado.objects.create(proposta=p2, item=bloco, preco_unitario=Decimal("2.10"))
        PrecoCotado.objects.create(proposta=p1, item=cimento, preco_unitario=Decimal("41"))
        PrecoCotado.objects.create(proposta=p2, item=cimento, preco_unitario=Decimal("39"))
        return cotacao


class FluxoTests(Base):
    def test_cotacao_exige_solicitacao_aprovada(self):
        with self.assertRaises(ValidationError):
            services.gerar_cotacao([self.solicitacao(aprovada=False)])

    def test_pedidos_pelo_menor_preco(self):
        sc = self.solicitacao()
        cotacao = self.cotacao_com_precos(sc)
        pedidos = services.gerar_pedidos(cotacao)

        self.assertEqual(len(pedidos), 2)
        por_fornecedor = {p.fornecedor: p for p in pedidos}
        item_bloco = por_fornecedor[self.f1].itens.get()
        self.assertEqual(item_bloco.insumo, self.bloco)
        self.assertEqual(item_bloco.preco_unitario, Decimal("1.90"))
        self.assertEqual(item_bloco.etapa, self.etapa)
        self.assertEqual(por_fornecedor[self.f2].itens.get().preco_unitario, Decimal("39"))
        self.assertEqual(por_fornecedor[self.f1].total, Decimal("1900.00"))
        self.assertIsNotNone(por_fornecedor[self.f1].previsao_entrega)

        cotacao.refresh_from_db()
        sc.refresh_from_db()
        self.assertEqual(cotacao.status, cotacao.Status.CONCLUIDA)
        self.assertEqual(sc.status, SolicitacaoCompra.Status.ATENDIDA)

    def test_item_sem_preco_continua_com_saldo(self):
        sc = self.solicitacao()
        cotacao = services.gerar_cotacao([sc])
        bloco = cotacao.itens.order_by("pk").first()
        proposta = PropostaFornecedor.objects.create(cotacao=cotacao, fornecedor=self.f1)
        PrecoCotado.objects.create(proposta=proposta, item=bloco, preco_unitario=Decimal("2"))
        services.gerar_pedidos(cotacao)

        sc.refresh_from_db()
        self.assertEqual(sc.status, SolicitacaoCompra.Status.APROVADA)
        cimento = sc.itens.get(insumo=self.cimento)
        self.assertEqual(cimento.saldo, Decimal("10"))
        # O saldo pode ir para uma nova cotação, só com o que falta.
        nova = services.gerar_cotacao([sc])
        self.assertEqual([i.item_solicitacao for i in nova.itens.all()], [cimento])

    def test_cancelar_pedido_devolve_saldo(self):
        sc = self.solicitacao()
        pedidos = services.gerar_pedidos(self.cotacao_com_precos(sc))
        services.cancelar_pedido(pedidos[0])
        sc.refresh_from_db()
        self.assertEqual(sc.status, SolicitacaoCompra.Status.APROVADA)

    def test_recebimento_atualiza_status_e_bloqueia_excesso(self):
        sc = self.solicitacao()
        pedido = services.gerar_pedidos(self.cotacao_com_precos(sc))[0]
        item = pedido.itens.get()

        with self.assertRaises(ValidationError):
            Recebimento(pedido=pedido).clean()  # ainda em rascunho
        services.aprovar_pedido(pedido)

        receb = Recebimento.objects.create(pedido=pedido)
        parcial = ItemRecebimento(recebimento=receb, item_pedido=item, quantidade=Decimal("400"))
        parcial.full_clean()
        parcial.save()
        services.atualizar_status_pedido(pedido)
        self.assertEqual(pedido.status, PedidoCompra.Status.PARCIAL)

        excesso = ItemRecebimento(recebimento=receb, item_pedido=item, quantidade=Decimal("601"))
        with self.assertRaises(ValidationError):
            excesso.full_clean()

        ItemRecebimento.objects.create(recebimento=receb, item_pedido=item, quantidade=Decimal("600"))
        services.atualizar_status_pedido(pedido)
        self.assertEqual(pedido.status, PedidoCompra.Status.ENTREGUE)
        with self.assertRaises(ValidationError):
            services.cancelar_pedido(pedido)

    def test_etapa_deve_ser_da_mesma_obra(self):
        outra = Obra.objects.create(empresa=self.obra.empresa, codigo="OB2", nome="Outra")
        sc = SolicitacaoCompra.objects.create(obra=outra)
        item = ItemSolicitacao(solicitacao=sc, insumo=self.bloco, quantidade=1, etapa=self.etapa)
        with self.assertRaises(ValidationError):
            item.full_clean()

    def test_ler_decimal(self):
        self.assertEqual(ler_decimal("1.234,56"), Decimal("1234.56"))
        self.assertEqual(ler_decimal("38,9"), Decimal("38.9"))
        self.assertEqual(ler_decimal("38.90"), Decimal("38.90"))
        self.assertIsNone(ler_decimal("  "))
        with self.assertRaises(ValidationError):
            ler_decimal("abc")


class TelasTests(Base):
    def setUp(self):
        super().setUp()
        self.client.force_login(User.objects.create_superuser("admin", "a@a.com", "senha"))

    def test_mapa_salva_precos_e_gera_pedidos(self):
        sc = self.solicitacao()
        cotacao = services.gerar_cotacao([sc])
        p1 = PropostaFornecedor.objects.create(cotacao=cotacao, fornecedor=self.f1)
        p2 = PropostaFornecedor.objects.create(cotacao=cotacao, fornecedor=self.f2)
        bloco, cimento = cotacao.itens.order_by("pk")
        url = reverse("suprimentos:mapa_cotacao", args=[cotacao.pk])

        self.assertEqual(self.client.get(url).status_code, 200)
        dados = {
            f"preco_{p1.pk}_{bloco.pk}": "1,95",
            f"preco_{p2.pk}_{bloco.pk}": "2,00",
            f"preco_{p1.pk}_{cimento.pk}": "",
            f"preco_{p2.pk}_{cimento.pk}": "39,50",
        }
        self.client.post(url, {**dados, "salvar": "1"})
        self.assertEqual(PrecoCotado.objects.count(), 3)
        resp = self.client.get(url)
        self.assertContains(resp, "melhor")

        self.client.post(url, {**dados, "gerar_pedidos": "1"})
        self.assertEqual(PedidoCompra.objects.count(), 2)
        self.assertEqual(
            PedidoCompra.objects.get(fornecedor=self.f1).itens.get().preco_unitario, Decimal("1.95")
        )

    def test_recebimento_pelo_admin(self):
        sc = self.solicitacao()
        pedido = next(
            p for p in services.gerar_pedidos(self.cotacao_com_precos(sc)) if p.fornecedor == self.f1
        )
        services.aprovar_pedido(pedido)
        item = pedido.itens.get()
        url = reverse("admin:suprimentos_recebimento_add")

        resp = self.client.get(url, {"pedido": pedido.pk})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, f'<option value="{item.pk}" selected>I1 - Bloco - pedido 1.000, a receber 1.000 un</option>')

        form = {
            "pedido": pedido.pk, "data": "01/02/2026", "numero_nota": "999", "observacao": "",
            "itens-TOTAL_FORMS": "1", "itens-INITIAL_FORMS": "0",
            "itens-MIN_NUM_FORMS": "0", "itens-MAX_NUM_FORMS": "1000",
            "itens-0-item_pedido": item.pk,
        }
        # Quantidade acima do pedido é recusada.
        resp = self.client.post(url + f"?pedido={pedido.pk}", {**form, "itens-0-quantidade": "5000"})
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Recebimento.objects.exists())
        # Sem nenhuma quantidade também.
        resp = self.client.post(url + f"?pedido={pedido.pk}", form)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "pelo menos um item")

        resp = self.client.post(url + f"?pedido={pedido.pk}", {**form, "itens-0-quantidade": "1000"})
        self.assertEqual(resp.status_code, 302)
        pedido.refresh_from_db()
        self.assertEqual(pedido.status, PedidoCompra.Status.ENTREGUE)

    def test_recebimento_ignora_linhas_em_branco(self):
        sc = self.solicitacao()
        cotacao = services.gerar_cotacao([sc])
        proposta = PropostaFornecedor.objects.create(cotacao=cotacao, fornecedor=self.f1)
        for item in cotacao.itens.all():
            PrecoCotado.objects.create(proposta=proposta, item=item, preco_unitario=Decimal("1"))
        pedido = services.gerar_pedidos(cotacao)[0]
        services.aprovar_pedido(pedido)
        bloco, cimento = pedido.itens.order_by("pk")
        url = reverse("admin:suprimentos_recebimento_add") + f"?pedido={pedido.pk}"

        resp = self.client.get(url)
        self.assertEqual(resp.context["inline_admin_formsets"][0].formset.total_form_count(), 2)
        resp = self.client.post(url, {
            "pedido": pedido.pk, "data": "01/02/2026", "numero_nota": "", "observacao": "",
            "itens-TOTAL_FORMS": "2", "itens-INITIAL_FORMS": "0",
            "itens-MIN_NUM_FORMS": "0", "itens-MAX_NUM_FORMS": "1000",
            "itens-0-item_pedido": bloco.pk, "itens-0-quantidade": "300",
            "itens-1-item_pedido": cimento.pk, "itens-1-quantidade": "",
        })
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(ItemRecebimento.objects.get().item_pedido, bloco)
        pedido.refresh_from_db()
        self.assertEqual(pedido.status, PedidoCompra.Status.PARCIAL)

    def test_orcado_comprado(self):
        ItemOrcamento.objects.create(etapa=self.etapa, insumo=self.bloco, quantidade=Decimal("1000"))
        sc = self.solicitacao()
        for pedido in services.gerar_pedidos(self.cotacao_com_precos(sc)):
            services.aprovar_pedido(pedido)
        resp = self.client.get(reverse("suprimentos:orcado_comprado", args=[self.orc.pk]))
        self.assertEqual(resp.status_code, 200)
        linha = resp.context["linhas"][0]
        self.assertEqual(linha["orcado"], Decimal("2000.00"))
        self.assertEqual(linha["comprado"], Decimal("1900.00"))
        self.assertEqual(resp.context["sem_etapa"], Decimal("390.00"))  # cimento sem etapa

    def test_telas_com_dados_de_exemplo(self):
        call_command("carregar_exemplo", stdout=open("/dev/null", "w"))
        pedido = PedidoCompra.objects.filter(status=PedidoCompra.Status.PARCIAL).first()
        urls = [
            reverse("admin:suprimentos_solicitacaocompra_changelist"),
            reverse("admin:suprimentos_solicitacaocompra_add"),
            reverse("admin:suprimentos_solicitacaocompra_change", args=[SolicitacaoCompra.objects.first().pk]),
            reverse("admin:suprimentos_cotacao_changelist"),
            reverse("admin:suprimentos_pedidocompra_changelist"),
            reverse("admin:suprimentos_pedidocompra_change", args=[pedido.pk]),
            reverse("admin:suprimentos_recebimento_changelist"),
            reverse("admin:suprimentos_recebimento_change", args=[Recebimento.objects.first().pk]),
            reverse("admin:cadastros_fornecedor_changelist"),
        ]
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)
        # Sem pedido, o cadastro de recebimento manda escolher o pedido primeiro.
        self.assertEqual(self.client.get(reverse("admin:suprimentos_recebimento_add")).status_code, 302)
