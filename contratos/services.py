"""Regras de negócio de contratos e medições."""

import datetime
from collections import defaultdict
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F, Sum

from financeiro.models import Apropriacao, Parcela, Titulo

from .models import ZERO, ContratoServico, ItemMedicao, Medicao

C = ContratoServico.Status
M = Medicao.Status


@transaction.atomic
def ativar(contrato):
    if contrato.status != C.RASCUNHO:
        raise ValidationError(f"{contrato}: só contratos em elaboração podem ser ativados.")
    if not contrato.itens.exists():
        raise ValidationError(f"{contrato}: o contrato não tem itens.")
    contrato.status = C.ATIVO
    contrato.save(update_fields=["status"])


def _titulo(contrato, valor, data, documento, descricao):
    titulo = Titulo.objects.create(
        tipo=Titulo.Tipo.PAGAR,
        empresa_id=contrato.obra.empresa_id,
        obra_id=contrato.obra_id,
        fornecedor_id=contrato.fornecedor_id,
        categoria=contrato.categoria,
        documento=documento,
        descricao=descricao,
        data_emissao=data,
    )
    Parcela.objects.create(
        titulo=titulo,
        numero=1,
        vencimento=data + datetime.timedelta(days=contrato.prazo_pagamento_dias),
        valor=valor,
    )
    return titulo


@transaction.atomic
def aprovar_medicao(medicao):
    """Aprova a medição e gera o título a pagar ao empreiteiro pelo valor líquido."""
    # Trava a medição para que duas aprovações simultâneas não gerem dois títulos.
    Medicao.objects.select_for_update().filter(pk=medicao.pk).exists()
    medicao.refresh_from_db()
    contrato = medicao.contrato
    if medicao.status != M.RASCUNHO:
        raise ValidationError(f"{medicao}: já está aprovada.")
    if contrato.status != C.ATIVO:
        raise ValidationError(f"{medicao}: o contrato não está ativo.")
    itens = list(medicao.itens.select_related("item_contrato"))
    if not itens:
        raise ValidationError(f"{medicao}: a medição não tem itens.")
    for item in itens:
        # Confere contra o que já foi aprovado: entre duas medições em elaboração
        # que juntas passam do contratado, a primeira a ser aprovada vale.
        servico = item.item_contrato
        saldo = servico.quantidade - servico.quantidade_medida(excluir_medicao=medicao)
        if item.quantidade > saldo:
            raise ValidationError(
                f"{medicao}: {servico.descricao} tem saldo de {saldo:f} {servico.unidade}, "
                f"menor que o medido ({item.quantidade:f})."
            )
    liquido = medicao.valor_liquido
    if liquido <= 0:
        raise ValidationError(f"{medicao}: o valor líquido precisa ser positivo.")

    titulo = _titulo(
        contrato,
        liquido,
        medicao.data,
        documento=f"Medição {medicao.numero} - CT {contrato.pk}",
        descricao=f"{contrato.objeto} ({medicao.periodo_inicio:%d/%m/%Y} a {medicao.periodo_fim:%d/%m/%Y})",
    )
    por_etapa = defaultdict(lambda: ZERO)
    for item in itens:
        por_etapa[item.item_contrato.etapa_id] += item.quantidade * item.item_contrato.preco_unitario
    bruto = sum(por_etapa.values(), ZERO)
    for etapa_id, valor in por_etapa.items():
        if etapa_id is not None and bruto:
            Apropriacao.objects.create(
                titulo=titulo, etapa_id=etapa_id,
                percentual=(valor / bruto * 100).quantize(Decimal("0.000001")),
            )

    medicao.titulo = titulo
    medicao.status = M.APROVADA
    medicao.save(update_fields=["titulo", "status"])
    return titulo


@transaction.atomic
def reabrir_medicao(medicao):
    """Desfaz a aprovação, excluindo o título gerado (só se ele não tem baixas)."""
    if medicao.status != M.APROVADA:
        raise ValidationError(f"{medicao}: não está aprovada.")
    if medicao.contrato.status != C.ATIVO:
        raise ValidationError(f"{medicao}: o contrato não está mais ativo.")
    titulo = medicao.titulo
    if titulo.tem_baixas():
        raise ValidationError(f"{medicao}: o título já tem pagamentos; estorne-os antes.")
    medicao.titulo = None
    medicao.status = M.RASCUNHO
    medicao.save(update_fields=["titulo", "status"])
    titulo.delete()


@transaction.atomic
def encerrar(contrato, data=None):
    """Encerra o contrato e gera o título de devolução da caução retida, se houver."""
    if contrato.status != C.ATIVO:
        raise ValidationError(f"{contrato}: só contratos ativos podem ser encerrados.")
    if contrato.medicoes.filter(status=M.RASCUNHO).exists():
        raise ValidationError(f"{contrato}: há medições em elaboração; aprove ou exclua antes.")
    data = data or datetime.date.today()
    caucao = contrato.caucao_retida
    if caucao > 0:
        contrato.titulo_caucao = _titulo(
            contrato, caucao, data,
            documento=f"Caução CT {contrato.pk}",
            descricao=f"Devolução da caução - {contrato.objeto}",
        )
    contrato.status = C.ENCERRADO
    contrato.save(update_fields=["status", "titulo_caucao"])


@transaction.atomic
def cancelar(contrato):
    if contrato.status not in {C.RASCUNHO, C.ATIVO}:
        raise ValidationError(f"{contrato}: não pode ser cancelado.")
    if contrato.medicoes.exists():
        raise ValidationError(f"{contrato}: já tem medições; encerre o contrato em vez de cancelar.")
    contrato.status = C.CANCELADO
    contrato.save(update_fields=["status"])


def medido_por_etapa(orcamento):
    """{etapa_id: valor bruto medido} das medições aprovadas nas etapas do orçamento."""
    return dict(
        ItemMedicao.objects.filter(
            medicao__status=M.APROVADA, item_contrato__etapa__orcamento=orcamento
        )
        .values_list("item_contrato__etapa")
        .annotate(total=Sum(F("quantidade") * F("item_contrato__preco_unitario")))
    )


def medido_sem_etapa(obra):
    return (
        ItemMedicao.objects.filter(
            medicao__status=M.APROVADA,
            medicao__contrato__obra=obra,
            item_contrato__etapa__isnull=True,
        ).aggregate(total=Sum(F("quantidade") * F("item_contrato__preco_unitario")))["total"]
        or ZERO
    )


def retencoes(inicio, fim, obra=None):
    """Medições aprovadas no período, com o INSS e o ISS retidos a recolher."""
    medicoes = (
        Medicao.objects.filter(status=M.APROVADA, data__gte=inicio, data__lte=fim)
        .select_related("contrato__fornecedor", "contrato__obra")
        .order_by("data", "pk")
    )
    if obra is not None:
        medicoes = medicoes.filter(contrato__obra=obra)
    linhas = [
        {
            "medicao": m,
            "bruto": m.valor_bruto,
            "inss": m.valor_inss,
            "iss": m.valor_iss,
            "caucao": m.valor_caucao,
            "liquido": m.valor_liquido,
        }
        for m in medicoes
    ]
    totais = {
        chave: sum((linha[chave] for linha in linhas), ZERO)
        for chave in ("bruto", "inss", "iss", "caucao", "liquido")
    }
    return linhas, totais
