"""Regras de negócio do financeiro."""

import datetime
import re
from collections import defaultdict
from decimal import ROUND_DOWN, Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum

from orcamento.models import arredondar

from .models import ZERO, Apropriacao, Baixa, ContaBancaria, Parcela, Titulo

CENTAVO = Decimal("0.01")


def prazos_da_condicao(condicao):
    """Dias de cada parcela a partir do texto da condição de pagamento.

    "30/60/90 dias" -> [30, 60, 90]; "28 dias" -> [28]; "à vista" ou vazio -> [0].
    """
    dias = [int(n) for n in re.findall(r"\d+", condicao or "")]
    return dias or [0]


def dividir(valor, partes):
    """Divide em parcelas iguais; a diferença de centavos vai para a primeira."""
    base = (valor / partes).quantize(CENTAVO, rounding=ROUND_DOWN)
    valores = [base] * partes
    valores[0] += valor - base * partes
    return valores


@transaction.atomic
def gerar_titulo_do_recebimento(recebimento):
    """Cria o título a pagar da nota recebida, com parcelas e apropriação por etapa.

    O vencimento conta a partir da data do recebimento, conforme a condição de
    pagamento do pedido. Se o título já existe, ele é devolvido sem alterações.
    """
    existente = Titulo.objects.filter(recebimento=recebimento).first()
    if existente:
        return existente

    pedido = recebimento.pedido
    por_etapa = defaultdict(lambda: ZERO)
    total = ZERO
    for item in recebimento.itens.select_related("item_pedido"):
        valor = item.quantidade * item.item_pedido.preco_unitario
        total += valor
        por_etapa[item.item_pedido.etapa_id] += valor
    total = arredondar(total)
    if total <= 0:
        raise ValidationError("O recebimento não tem valor para gerar título.")

    titulo = Titulo.objects.create(
        tipo=Titulo.Tipo.PAGAR,
        empresa_id=pedido.obra.empresa_id,
        obra_id=pedido.obra_id,
        fornecedor_id=pedido.fornecedor_id,
        documento=f"NF {recebimento.numero_nota}" if recebimento.numero_nota else f"Receb. {recebimento.pk}",
        data_emissao=recebimento.data,
        descricao=f"Pedido de compra {pedido.pk}",
        recebimento=recebimento,
    )
    prazos = prazos_da_condicao(pedido.condicao_pagamento)
    for numero, (dias, valor) in enumerate(zip(prazos, dividir(total, len(prazos))), start=1):
        Parcela.objects.create(
            titulo=titulo,
            numero=numero,
            vencimento=recebimento.data + datetime.timedelta(days=dias),
            valor=valor,
        )

    bruto = sum(por_etapa.values(), ZERO)
    for etapa_id, valor in por_etapa.items():
        if etapa_id is not None:
            Apropriacao.objects.create(
                titulo=titulo,
                etapa_id=etapa_id,
                percentual=(valor / bruto * 100).quantize(Decimal("0.000001")),
            )
    return titulo


def validar_apropriacoes(titulo):
    total = titulo.apropriacoes.aggregate(total=Sum("percentual"))["total"] or ZERO
    if total > 100:
        raise ValidationError(f"A soma das apropriações passa de 100% ({total:.2f}%).")


@transaction.atomic
def baixar(parcela, conta, data=None, valor=None, juros=ZERO, multa=ZERO, desconto=ZERO):
    """Registra a baixa. Sem `valor`, quita todo o saldo da parcela."""
    baixa = Baixa(
        parcela=parcela,
        conta=conta,
        data=data or datetime.date.today(),
        valor=parcela.saldo if valor is None else valor,
        juros=juros,
        multa=multa,
        desconto=desconto,
    )
    if baixa.valor <= 0:
        raise ValidationError(f"{parcela}: não há saldo a baixar.")
    baixa.full_clean()
    baixa.save()
    return baixa


def pago_por_etapa(orcamento):
    """{etapa_id: valor pago} dos títulos a pagar apropriados às etapas do orçamento.

    O valor pago de cada título é distribuído pelas etapas conforme o
    percentual apropriado.
    """
    apropriacoes = Apropriacao.objects.filter(
        etapa__orcamento=orcamento, titulo__tipo=Titulo.Tipo.PAGAR
    ).values_list("titulo_id", "etapa_id", "percentual")
    apropriacoes = list(apropriacoes)
    titulos = {titulo_id for titulo_id, _, _ in apropriacoes}
    pago = dict(
        Baixa.objects.filter(parcela__titulo__in=titulos)
        .values_list("parcela__titulo")
        .annotate(total=Sum("valor"))
    )
    resultado = defaultdict(lambda: ZERO)
    for titulo_id, etapa_id, percentual in apropriacoes:
        resultado[etapa_id] += pago.get(titulo_id, ZERO) * percentual / 100
    return dict(resultado)


def inicio_do_periodo(data, agrupamento):
    if agrupamento == "mes":
        return data.replace(day=1)
    if agrupamento == "semana":
        return data - datetime.timedelta(days=data.weekday())
    return data


def fluxo_de_caixa(inicio, fim, agrupamento="mes", empresa=None, obra=None):
    """Previsto (parcelas em aberto) e realizado (baixas) por período.

    O saldo acumulado parte do saldo das contas bancárias no dia anterior ao
    início (ou de zero, quando filtrado por obra), soma as parcelas vencidas
    antes do início e ainda em aberto (`atrasados`) e depois o realizado e o
    previsto de cada período.
    """
    parcelas = Parcela.objects.em_aberto().select_related("titulo")
    baixas = Baixa.objects.select_related("parcela__titulo")
    contas = ContaBancaria.objects.filter(ativa=True)
    if empresa is not None:
        parcelas = parcelas.filter(titulo__empresa=empresa)
        baixas = baixas.filter(parcela__titulo__empresa=empresa)
        contas = contas.filter(empresa=empresa)
    if obra is not None:
        parcelas = parcelas.filter(titulo__obra=obra)
        baixas = baixas.filter(parcela__titulo__obra=obra)

    periodos = {}
    data = inicio_do_periodo(inicio, agrupamento)
    while data <= fim:
        periodos[data] = {
            "periodo": data, "a_receber": ZERO, "a_pagar": ZERO, "recebido": ZERO, "pago": ZERO,
        }
        if agrupamento == "mes":
            data = (data.replace(day=28) + datetime.timedelta(days=4)).replace(day=1)
        else:
            data += datetime.timedelta(days=7 if agrupamento == "semana" else 1)

    atrasados = {"a_receber": ZERO, "a_pagar": ZERO}
    for parcela in parcelas.filter(vencimento__lte=fim):
        chave = "a_receber" if parcela.titulo.tipo == Titulo.Tipo.RECEBER else "a_pagar"
        if parcela.vencimento < inicio:
            atrasados[chave] += parcela.saldo_aberto
        else:
            periodos[inicio_do_periodo(parcela.vencimento, agrupamento)][chave] += parcela.saldo_aberto

    for baixa in baixas.filter(data__gte=inicio, data__lte=fim):
        chave = "recebido" if baixa.parcela.titulo.tipo == Titulo.Tipo.RECEBER else "pago"
        periodos[inicio_do_periodo(baixa.data, agrupamento)][chave] += baixa.valor_movimentado

    # Com filtro de obra, o saldo bancário não é da obra: o acumulado parte de zero.
    vespera = inicio - datetime.timedelta(days=1)
    saldo_inicial = ZERO if obra is not None else sum((c.saldo_em(vespera) for c in contas), ZERO)
    atrasados["previsto"] = atrasados["a_receber"] - atrasados["a_pagar"]
    # Os vencidos em aberto ainda devem acontecer, então entram no acumulado.
    saldo = atrasados["saldo"] = saldo_inicial + atrasados["previsto"]
    linhas = []
    for linha in periodos.values():
        linha["realizado"] = linha["recebido"] - linha["pago"]
        linha["previsto"] = linha["a_receber"] - linha["a_pagar"]
        saldo += linha["realizado"] + linha["previsto"]
        linha["saldo"] = saldo
        linhas.append(linha)
    return {"saldo_inicial": saldo_inicial, "atrasados": atrasados, "linhas": linhas}
