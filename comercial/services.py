"""Regras de negócio do comercial."""

import datetime

from django.core.exceptions import ValidationError
from django.db import transaction

from financeiro.models import Parcela, Titulo
from orcamento.models import arredondar

from .models import (
    ZERO,
    ContratoVenda,
    IndiceEconomico,
    Indice,
    ReajusteContrato,
    ReajusteParcela,
    Unidade,
    fim_do_mes,
)

C = ContratoVenda.Status
U = Unidade.Status


@transaction.atomic
def efetivar(contrato, categoria=None):
    """Gera o título a receber com as parcelas das séries e marca a unidade como vendida."""
    # Trava contrato e unidade para que duas efetivações simultâneas não vendam a mesma unidade.
    ContratoVenda.objects.select_for_update().filter(pk=contrato.pk).exists()
    contrato.refresh_from_db()
    unidade = Unidade.objects.select_for_update().get(pk=contrato.unidade_id)
    if contrato.status != C.RASCUNHO:
        raise ValidationError(f"{contrato}: só contratos em elaboração podem ser efetivados.")
    if unidade.status not in {U.DISPONIVEL, U.RESERVADA}:
        raise ValidationError(f"{contrato}: a unidade está {unidade.get_status_display().lower()}.")
    series = list(contrato.series.all())
    if not series:
        raise ValidationError(f"{contrato}: informe a condição de pagamento.")
    total = sum((s.total for s in series), ZERO)
    if total != contrato.valor_total:
        raise ValidationError(
            f"{contrato}: as parcelas somam R$ {total}, mas o valor do contrato é R$ {contrato.valor_total}."
        )

    titulo = Titulo.objects.create(
        tipo=Titulo.Tipo.RECEBER,
        empresa_id=unidade.obra.empresa_id,
        obra_id=unidade.obra_id,
        cliente_id=contrato.cliente_id,
        categoria=categoria,
        documento=f"Contrato de venda {contrato.pk}",
        descricao=f"Unidade {unidade}",
        data_emissao=contrato.data_contrato,
    )
    vencimentos = sorted(
        (vencimento, serie.valor) for serie in series for vencimento in serie.vencimentos()
    )
    for numero, (vencimento, valor) in enumerate(vencimentos, start=1):
        Parcela.objects.create(titulo=titulo, numero=numero, vencimento=vencimento, valor=valor)

    contrato.titulo = titulo
    contrato.status = C.ATIVO
    contrato.save(update_fields=["titulo", "status"])
    unidade.status = U.VENDIDA
    unidade.save(update_fields=["status"])
    return titulo


@transaction.atomic
def distratar(contrato, data=None):
    """Cancela o contrato: a unidade volta a ficar disponível e o saldo em aberto é cancelado.

    Parcelas sem nenhuma baixa são excluídas; parcelas pagas em parte ficam
    com o valor já recebido. A eventual devolução ao cliente deve ser lançada
    como um título a pagar.
    """
    if contrato.status != C.ATIVO:
        raise ValidationError(f"{contrato}: só contratos ativos podem ser distratados.")
    for parcela in contrato.titulo.parcelas.all():
        baixado = parcela.baixado
        if baixado == 0:
            parcela.delete()
        elif baixado < parcela.valor:
            parcela.valor = baixado
            parcela.save(update_fields=["valor"])
    contrato.status = C.DISTRATADO
    contrato.data_distrato = data or datetime.date.today()
    contrato.save(update_fields=["status", "data_distrato"])
    Unidade.objects.filter(pk=contrato.unidade_id).update(status=U.DISPONIVEL)


@transaction.atomic
def reajustar(contrato):
    """Aplica os índices mensais ainda não aplicados desde a data-base.

    A variação de cada mês corrige o saldo em aberto das parcelas que vencem
    depois daquele mês. Cada índice é aplicado uma única vez por contrato.
    Devolve a quantidade de meses aplicados.
    """
    if contrato.status != C.ATIVO or contrato.indice == Indice.NENHUM:
        return 0
    ja_aplicados = contrato.reajustes.values_list("indice_id", flat=True)
    indices = (
        IndiceEconomico.objects.filter(indice=contrato.indice, mes__gt=contrato.data_base)
        .exclude(pk__in=ja_aplicados)
        .order_by("mes")
    )
    aplicados = 0
    for indice in indices:
        parcelas = Parcela.objects.em_aberto().filter(
            titulo=contrato.titulo, vencimento__gt=fim_do_mes(indice.mes)
        )
        saldo_antes = saldo_depois = ZERO
        reajuste = ReajusteContrato.objects.create(
            contrato=contrato, indice=indice, saldo_antes=ZERO, saldo_depois=ZERO
        )
        for parcela in parcelas:
            corrigido = arredondar(parcela.saldo_aberto * (1 + indice.variacao / 100))
            novo = parcela.total_baixado + corrigido
            ReajusteParcela.objects.create(
                reajuste=reajuste, parcela=parcela, valor_anterior=parcela.valor, valor_novo=novo
            )
            saldo_antes += parcela.saldo_aberto
            saldo_depois += corrigido
            Parcela.objects.filter(pk=parcela.pk).update(valor=novo)
        reajuste.saldo_antes, reajuste.saldo_depois = saldo_antes, saldo_depois
        reajuste.save(update_fields=["saldo_antes", "saldo_depois"])
        aplicados += 1
    return aplicados
