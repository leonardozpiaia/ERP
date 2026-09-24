import datetime
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from cadastros.models import (
    Cliente,
    Composicao,
    ComposicaoItem,
    Empresa,
    Fornecedor,
    Insumo,
    UnidadeMedida,
)
from financeiro import services as financeiro
from financeiro.models import CategoriaFinanceira, ContaBancaria, Parcela, Titulo
from obras.models import Obra
from orcamento.models import Etapa, ItemOrcamento, Orcamento
from suprimentos import services
from suprimentos.models import (
    ItemRecebimento,
    ItemSolicitacao,
    PrecoCotado,
    PropostaFornecedor,
    Recebimento,
    SolicitacaoCompra,
)

CNPJ_EXEMPLO = "11.111.111/0001-11"
CONTA_EXEMPLO = "Banco Exemplo - conta movimento"


class Command(BaseCommand):
    help = "Carrega dados de exemplo: obra, orçamento e um ciclo de compras."

    @transaction.atomic
    def handle(self, *args, **options):
        if Obra.objects.filter(codigo="OB-001").exists():
            self.stdout.write("Orçamento de exemplo já carregado.")
        else:
            self.carregar_orcamento()
        if Fornecedor.objects.filter(cpf_cnpj=CNPJ_EXEMPLO).exists():
            self.stdout.write("Compras de exemplo já carregadas.")
        else:
            self.carregar_suprimentos()
        if ContaBancaria.objects.filter(descricao=CONTA_EXEMPLO).exists():
            self.stdout.write("Financeiro de exemplo já carregado.")
        else:
            self.carregar_financeiro()

    def carregar_orcamento(self):
        un = {
            sigla: UnidadeMedida.objects.get_or_create(sigla=sigla, defaults={"descricao": desc})[0]
            for sigla, desc in [
                ("m2", "metro quadrado"), ("m3", "metro cúbico"), ("kg", "quilograma"),
                ("h", "hora"), ("un", "unidade"), ("sc", "saco"),
            ]
        }
        T = Insumo.Tipo
        insumos = {}
        for codigo, desc, sigla, tipo, preco in [
            ("I-001", "Cimento Portland CP II-32 (50 kg)", "sc", T.MATERIAL, "38.90"),
            ("I-002", "Areia média", "m3", T.MATERIAL, "120.00"),
            ("I-003", "Brita 1", "m3", T.MATERIAL, "135.00"),
            ("I-004", "Pedreiro", "h", T.MAO_DE_OBRA, "28.50"),
            ("I-005", "Servente", "h", T.MAO_DE_OBRA, "21.00"),
            ("I-006", "Bloco cerâmico 9x19x19", "un", T.MATERIAL, "1.35"),
            ("I-007", "Aço CA-50", "kg", T.MATERIAL, "7.80"),
        ]:
            insumos[codigo] = Insumo.objects.create(
                codigo=codigo, descricao=desc, unidade=un[sigla], tipo=tipo,
                preco_unitario=Decimal(preco),
            )

        concreto = Composicao.objects.create(
            codigo="C-001", descricao="Concreto fck 25 MPa, preparo em betoneira", unidade=un["m3"]
        )
        alvenaria = Composicao.objects.create(
            codigo="C-002", descricao="Alvenaria de vedação com bloco cerâmico 9 cm", unidade=un["m2"]
        )
        for comp, codigo, coef in [
            (concreto, "I-001", "7.0"), (concreto, "I-002", "0.60"), (concreto, "I-003", "0.75"),
            (concreto, "I-005", "6.0"),
            (alvenaria, "I-006", "26.0"), (alvenaria, "I-001", "0.15"),
            (alvenaria, "I-004", "0.80"), (alvenaria, "I-005", "0.40"),
        ]:
            ComposicaoItem.objects.create(
                composicao=comp, insumo=insumos[codigo], coeficiente=Decimal(coef)
            )

        empresa = Empresa.objects.create(
            razao_social="Construtora Exemplo Ltda", nome_fantasia="Construtora Exemplo",
            cnpj="00.000.000/0001-00",
        )
        obra = Obra.objects.create(
            empresa=empresa, codigo="OB-001", nome="Residencial Exemplo",
            cidade="Porto Alegre", uf="RS", area_construida=Decimal("1200"),
            data_inicio=datetime.date.today(),
        )
        orc = Orcamento.objects.create(
            obra=obra, descricao="Orçamento executivo", data_base=datetime.date.today(),
            bdi_percentual=Decimal("25"),
        )
        infra = Etapa.objects.create(orcamento=orc, codigo="01", descricao="Infraestrutura")
        fund = Etapa.objects.create(orcamento=orc, pai=infra, codigo="01.01", descricao="Fundações")
        supra = Etapa.objects.create(orcamento=orc, codigo="02", descricao="Supraestrutura")
        alv = Etapa.objects.create(orcamento=orc, codigo="03", descricao="Alvenaria")
        ItemOrcamento.objects.create(etapa=fund, composicao=concreto, quantidade=Decimal("45"))
        ItemOrcamento.objects.create(etapa=fund, insumo=insumos["I-007"], quantidade=Decimal("3500"))
        ItemOrcamento.objects.create(etapa=supra, composicao=concreto, quantidade=Decimal("110"))
        ItemOrcamento.objects.create(etapa=alv, composicao=alvenaria, quantidade=Decimal("1850"))

        self.stdout.write(self.style.SUCCESS(f"Exemplo carregado: {orc} — total R$ {orc.preco_total}"))

    def carregar_suprimentos(self):
        obra = Obra.objects.get(codigo="OB-001")
        orc = obra.orcamentos.first()
        etapa = {e.codigo: e for e in orc.etapas.all()}
        insumo = {i.codigo: i for i in Insumo.objects.all()}

        fornecedores = [
            Fornecedor.objects.create(
                razao_social=razao, nome_fantasia=fantasia, cpf_cnpj=cnpj, cidade="Porto Alegre", uf="RS"
            )
            for razao, fantasia, cnpj in [
                ("Depósito Central Materiais Ltda", "Depósito Central", CNPJ_EXEMPLO),
                ("Casa do Construtor Sul Ltda", "Construtor Sul", "22.222.222/0001-22"),
                ("Aços Gaúchos S.A.", "Aços Gaúchos", "33.333.333/0001-33"),
            ]
        ]

        sc = SolicitacaoCompra.objects.create(obra=obra, observacao="Material para fundações e alvenaria")
        for codigo, qtd, cod_etapa in [
            ("I-001", "315", "01.01"),   # cimento
            ("I-002", "27", "01.01"),    # areia
            ("I-007", "3500", "01.01"),  # aço
            ("I-006", "48100", "03"),    # blocos
        ]:
            ItemSolicitacao.objects.create(
                solicitacao=sc, insumo=insumo[codigo], quantidade=Decimal(qtd), etapa=etapa[cod_etapa]
            )
        services.aprovar_solicitacao(sc)
        cotacao = services.gerar_cotacao([sc])

        # Preços por fornecedor, na ordem: cimento, areia, aço, bloco (None = não cotou).
        tabela = {
            fornecedores[0]: (("36.50", "118.00", None, "1.29"), 7, "30 dias"),
            fornecedores[1]: (("37.90", "112.00", "8.10", "1.35"), 5, "30/60 dias"),
            fornecedores[2]: ((None, None, "7.45", None), 10, "28 dias"),
        }
        itens = list(cotacao.itens.order_by("pk"))
        for fornecedor, (precos, prazo, condicao) in tabela.items():
            proposta = PropostaFornecedor.objects.create(
                cotacao=cotacao, fornecedor=fornecedor, prazo_entrega_dias=prazo,
                condicao_pagamento=condicao,
            )
            for item, preco in zip(itens, precos):
                if preco is not None:
                    PrecoCotado.objects.create(proposta=proposta, item=item, preco_unitario=Decimal(preco))

        pedidos = services.gerar_pedidos(cotacao)
        for pedido in pedidos:
            services.aprovar_pedido(pedido)

        # Metade do aço já chegou na obra.
        pedido_aco = next(p for p in pedidos if p.fornecedor == fornecedores[2])
        item_aco = pedido_aco.itens.get()
        receb = Recebimento.objects.create(pedido=pedido_aco, numero_nota="12345")
        ItemRecebimento.objects.create(recebimento=receb, item_pedido=item_aco, quantidade=Decimal("1750"))
        services.atualizar_status_pedido(pedido_aco)

        self.stdout.write(self.style.SUCCESS(
            f"Compras de exemplo: {sc}, {cotacao} e {len(pedidos)} pedido(s) aprovados."
        ))

    def carregar_financeiro(self):
        hoje = datetime.date.today()
        obra = Obra.objects.get(codigo="OB-001")
        empresa = obra.empresa
        conta = ContaBancaria.objects.create(
            empresa=empresa, descricao=CONTA_EXEMPLO, banco="Banco Exemplo", agencia="0001",
            numero="12345-6", saldo_inicial=Decimal("150000"),
            data_saldo_inicial=hoje - datetime.timedelta(days=60),
        )
        cat = {}
        for codigo, desc, tipo in [
            ("1.01", "Venda de unidades", CategoriaFinanceira.Tipo.RECEITA),
            ("2.01", "Materiais de construção", CategoriaFinanceira.Tipo.DESPESA),
            ("2.02", "Mão de obra terceirizada", CategoriaFinanceira.Tipo.DESPESA),
            ("3.01", "Despesas administrativas", CategoriaFinanceira.Tipo.DESPESA),
        ]:
            cat[codigo] = CategoriaFinanceira.objects.create(codigo=codigo, descricao=desc, tipo=tipo)

        # Nota do aço recebida em Suprimentos vira conta a pagar.
        for recebimento in Recebimento.objects.filter(titulo__isnull=True):
            titulo = financeiro.gerar_titulo_do_recebimento(recebimento)
            titulo.categoria = cat["2.01"]
            titulo.save(update_fields=["categoria"])
            financeiro.baixar(titulo.parcelas.first(), conta)

        # Aluguel do escritório: despesa administrativa, sem obra, com uma parcela vencida.
        aluguel = Titulo.objects.create(
            tipo=Titulo.Tipo.PAGAR, empresa=empresa, fornecedor=Fornecedor.objects.create(
                razao_social="Imobiliária Centro Ltda", cpf_cnpj="44.444.444/0001-44"
            ),
            categoria=cat["3.01"], documento="Contrato 77", descricao="Aluguel do escritório",
            data_emissao=hoje - datetime.timedelta(days=40),
        )
        for n in range(4):
            Parcela.objects.create(
                titulo=aluguel, numero=n + 1, valor=Decimal("4500"),
                vencimento=hoje - datetime.timedelta(days=10) + datetime.timedelta(days=30 * n),
            )

        # Venda de uma unidade: entrada paga + 12 parcelas mensais.
        cliente = Cliente.objects.create(nome="Maria Exemplo", cpf_cnpj="000.000.000-00", cidade="Porto Alegre", uf="RS")
        venda = Titulo.objects.create(
            tipo=Titulo.Tipo.RECEBER, empresa=empresa, obra=obra, cliente=cliente,
            categoria=cat["1.01"], documento="Contrato de venda 101",
            descricao="Apto 101 - Residencial Exemplo", data_emissao=hoje - datetime.timedelta(days=20),
        )
        entrada = Parcela.objects.create(
            titulo=venda, numero=1, valor=Decimal("60000"), vencimento=hoje - datetime.timedelta(days=20)
        )
        for n in range(1, 13):
            Parcela.objects.create(
                titulo=venda, numero=n + 1, valor=Decimal("8500"),
                vencimento=hoje + datetime.timedelta(days=30 * n - 20),
            )
        financeiro.baixar(entrada, conta, data=hoje - datetime.timedelta(days=20))

        self.stdout.write(self.style.SUCCESS(
            f"Financeiro de exemplo: saldo em conta R$ {conta.saldo_atual}."
        ))
