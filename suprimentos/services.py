"""Regras de negócio do fluxo de compras.

Cada função executa uma etapa do fluxo dentro de uma transação e levanta
ValidationError com uma mensagem para o usuário quando a etapa não é possível.
"""

import datetime
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction

from .models import (
    Cotacao,
    ItemCotacao,
    ItemPedido,
    PedidoCompra,
    PrecoCotado,
    SolicitacaoCompra,
)

S = SolicitacaoCompra.Status
P = PedidoCompra.Status


@transaction.atomic
def aprovar_solicitacao(solicitacao):
    if solicitacao.status != S.ABERTA:
        raise ValidationError(f"{solicitacao}: só solicitações abertas podem ser aprovadas.")
    if not solicitacao.itens.exists():
        raise ValidationError(f"{solicitacao}: a solicitação não tem itens.")
    solicitacao.status = S.APROVADA
    solicitacao.save(update_fields=["status"])


@transaction.atomic
def gerar_cotacao(solicitacoes):
    """Cria uma cotação com o saldo ainda não comprado das solicitações aprovadas."""
    solicitacoes = list(solicitacoes)
    nao_aprovadas = [s for s in solicitacoes if s.status != S.APROVADA]
    if nao_aprovadas:
        raise ValidationError(
            "Só solicitações aprovadas podem ir para cotação: "
            + ", ".join(str(s) for s in nao_aprovadas)
        )
    cotacao = Cotacao.objects.create()
    for solicitacao in solicitacoes:
        for item in solicitacao.itens.all():
            saldo = item.saldo
            if saldo > 0:
                ItemCotacao.objects.create(cotacao=cotacao, item_solicitacao=item, quantidade=saldo)
    if not cotacao.itens.exists():
        raise ValidationError("Não há saldo a comprar nas solicitações selecionadas.")
    return cotacao


@transaction.atomic
def salvar_precos(cotacao, precos):
    """Grava os preços do mapa. `precos` é {(proposta_id, item_id): Decimal ou None}.

    None apaga o preço (o fornecedor não cotou aquele item).
    """
    if cotacao.status != Cotacao.Status.ABERTA:
        raise ValidationError("Só é possível alterar preços de cotações abertas.")
    propostas = set(cotacao.propostas.values_list("pk", flat=True))
    itens = set(cotacao.itens.values_list("pk", flat=True))
    for (proposta_id, item_id), valor in precos.items():
        if proposta_id not in propostas or item_id not in itens:
            raise ValidationError("Preço informado para item ou fornecedor de outra cotação.")
        if valor is None:
            PrecoCotado.objects.filter(proposta_id=proposta_id, item_id=item_id).delete()
        elif valor < 0:
            raise ValidationError("Preço não pode ser negativo.")
        else:
            PrecoCotado.objects.update_or_create(
                proposta_id=proposta_id, item_id=item_id, defaults={"preco_unitario": valor}
            )


def vencedores(cotacao):
    """{item_cotacao_id: PrecoCotado de menor preço}. Empate: o primeiro cadastrado."""
    melhores = {}
    precos = PrecoCotado.objects.filter(item__cotacao=cotacao).order_by("preco_unitario", "pk")
    for preco in precos.select_related("proposta__fornecedor"):
        melhores.setdefault(preco.item_id, preco)
    return melhores


@transaction.atomic
def gerar_pedidos(cotacao):
    """Gera um pedido por fornecedor e obra com os itens de menor preço.

    Itens sem nenhum preço ficam de fora e continuam com saldo na solicitação.
    Os pedidos nascem em rascunho, para revisão antes da aprovação.
    """
    if cotacao.status != Cotacao.Status.ABERTA:
        raise ValidationError("Esta cotação não está aberta.")
    melhores = vencedores(cotacao)
    if not melhores:
        raise ValidationError("Nenhum preço foi informado nesta cotação.")

    pedidos = {}
    itens = cotacao.itens.select_related(
        "item_solicitacao__solicitacao", "item_solicitacao__insumo"
    )
    for item in itens:
        preco = melhores.get(item.pk)
        if preco is None:
            continue
        item_sc = item.item_solicitacao
        quantidade = min(item.quantidade, item_sc.saldo)
        if quantidade <= 0:
            continue
        proposta = preco.proposta
        chave = (proposta.pk, item_sc.solicitacao.obra_id)
        if chave not in pedidos:
            prazo = proposta.prazo_entrega_dias
            pedidos[chave] = PedidoCompra.objects.create(
                obra_id=item_sc.solicitacao.obra_id,
                fornecedor=proposta.fornecedor,
                cotacao=cotacao,
                condicao_pagamento=proposta.condicao_pagamento,
                previsao_entrega=(
                    datetime.date.today() + datetime.timedelta(days=prazo) if prazo else None
                ),
            )
        ItemPedido.objects.create(
            pedido=pedidos[chave],
            insumo=item_sc.insumo,
            etapa=item_sc.etapa,
            item_solicitacao=item_sc,
            quantidade=quantidade,
            preco_unitario=preco.preco_unitario,
        )

    if not pedidos:
        raise ValidationError("Não há saldo a comprar nos itens cotados.")
    cotacao.status = Cotacao.Status.CONCLUIDA
    cotacao.save(update_fields=["status"])
    atualizar_solicitacoes(
        SolicitacaoCompra.objects.filter(itens__itens_cotacao__cotacao=cotacao).distinct()
    )
    return list(pedidos.values())


@transaction.atomic
def aprovar_pedido(pedido):
    if pedido.status != P.RASCUNHO:
        raise ValidationError(f"{pedido}: só pedidos em rascunho podem ser aprovados.")
    if not pedido.itens.exists():
        raise ValidationError(f"{pedido}: o pedido não tem itens.")
    pedido.status = P.APROVADO
    pedido.save(update_fields=["status"])


@transaction.atomic
def cancelar_pedido(pedido):
    if pedido.status not in {P.RASCUNHO, P.APROVADO}:
        raise ValidationError(f"{pedido}: pedidos com entregas não podem ser cancelados.")
    pedido.status = P.CANCELADO
    pedido.save(update_fields=["status"])
    # O saldo volta para a solicitação, que pode ser cotada de novo.
    atualizar_solicitacoes(
        SolicitacaoCompra.objects.filter(itens__itens_pedido__pedido=pedido).distinct()
    )


def atualizar_status_pedido(pedido):
    """Recalcula o status de entrega a partir das quantidades recebidas."""
    if pedido.status not in {P.APROVADO, P.PARCIAL, P.ENTREGUE}:
        return
    itens = list(pedido.itens.all())
    recebido = sum((i.quantidade_recebida for i in itens), Decimal("0"))
    if itens and all(i.saldo == 0 for i in itens):
        novo = P.ENTREGUE
    elif recebido > 0:
        novo = P.PARCIAL
    else:
        novo = P.APROVADO
    if novo != pedido.status:
        pedido.status = novo
        pedido.save(update_fields=["status"])


def atualizar_solicitacoes(solicitacoes):
    """Marca como atendidas as solicitações sem saldo, e reabre as que voltaram a ter."""
    for solicitacao in solicitacoes:
        if solicitacao.status not in {S.APROVADA, S.ATENDIDA}:
            continue
        atendida = all(item.saldo == 0 for item in solicitacao.itens.all())
        novo = S.ATENDIDA if atendida else S.APROVADA
        if novo != solicitacao.status:
            solicitacao.status = novo
            solicitacao.save(update_fields=["status"])
