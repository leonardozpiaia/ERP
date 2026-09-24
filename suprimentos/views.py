from decimal import Decimal, InvalidOperation

from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.db.models import F, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from config.permissoes import requer
from contratos.services import medido_por_etapa, medido_sem_etapa
from financeiro.services import pago_por_etapa
from orcamento.models import Orcamento, arredondar

from . import services
from .models import Cotacao, ItemPedido, PedidoCompra, PrecoCotado

STATUS_COMPRADO = [
    PedidoCompra.Status.APROVADO,
    PedidoCompra.Status.PARCIAL,
    PedidoCompra.Status.ENTREGUE,
]


def ler_decimal(texto):
    """Aceita "1.234,56" (padrão brasileiro) e "1234.56". Vazio vira None."""
    texto = (texto or "").strip()
    if not texto:
        return None
    if "," in texto:
        texto = texto.replace(".", "").replace(",", ".")
    try:
        return Decimal(texto)
    except InvalidOperation:
        raise ValidationError(f"Valor inválido: {texto}") from None


@requer("suprimentos.view_cotacao")
def mapa_cotacao(request, pk):
    cotacao = get_object_or_404(Cotacao, pk=pk)
    propostas = list(cotacao.propostas.select_related("fornecedor").order_by("pk"))
    itens = list(
        cotacao.itens.select_related(
            "item_solicitacao__insumo__unidade",
            "item_solicitacao__etapa",
            "item_solicitacao__solicitacao__obra",
        ).order_by("pk")
    )

    if request.method == "POST":
        if not request.user.has_perm("suprimentos.change_cotacao"):
            messages.error(request, "Você não tem permissão para alterar cotações.")
            return redirect(request.path)
        try:
            precos = {
                (p.pk, i.pk): ler_decimal(request.POST.get(f"preco_{p.pk}_{i.pk}"))
                for p in propostas
                for i in itens
            }
            services.salvar_precos(cotacao, precos)
            if "gerar_pedidos" in request.POST:
                pedidos = services.gerar_pedidos(cotacao)
                messages.success(request, f"{len(pedidos)} pedido(s) gerado(s) em rascunho.")
                return redirect(
                    reverse("admin:suprimentos_pedidocompra_changelist")
                    + f"?cotacao__id__exact={cotacao.pk}"
                )
            messages.success(request, "Preços salvos.")
        except ValidationError as erro:
            messages.error(request, "; ".join(erro.messages))
        return redirect(request.path)

    precos = {
        (p.proposta_id, p.item_id): p.preco_unitario
        for p in PrecoCotado.objects.filter(item__cotacao=cotacao)
    }
    melhores = services.vencedores(cotacao)
    linhas = []
    for item in itens:
        celulas = []
        for proposta in propostas:
            preco = precos.get((proposta.pk, item.pk))
            vencedor = melhores.get(item.pk)
            celulas.append({
                "nome": f"preco_{proposta.pk}_{item.pk}",
                "preco": preco,
                "total": arredondar(preco * item.quantidade) if preco is not None else None,
                "melhor": vencedor is not None and vencedor.proposta_id == proposta.pk,
            })
        linhas.append({"item": item, "celulas": celulas})

    totais = [
        arredondar(sum(
            (precos[(p.pk, i.pk)] * i.quantidade for i in itens if (p.pk, i.pk) in precos),
            Decimal("0"),
        ))
        for p in propostas
    ]
    melhor_total = arredondar(sum(
        (v.preco_unitario * i.quantidade for i in itens if (v := melhores.get(i.pk))),
        Decimal("0"),
    ))
    contexto = {
        **admin.site.each_context(request),
        "cotacao": cotacao,
        "propostas": propostas,
        "linhas": linhas,
        "rodape": list(zip(propostas, totais)),
        "melhor_total": melhor_total,
        "editavel": cotacao.editavel(),
    }
    return render(request, "suprimentos/mapa_cotacao.html", contexto)


@requer("orcamento.view_orcamento")
def orcado_comprado(request, pk):
    """Orçado x realizado por etapa: compras (pedidos), medições de empreiteiros e pago."""
    orcamento = get_object_or_404(Orcamento.objects.select_related("obra"), pk=pk)
    comprados = ItemPedido.objects.filter(pedido__status__in=STATUS_COMPRADO)

    por_etapa = dict(
        comprados.filter(etapa__orcamento=orcamento)
        .values_list("etapa_id")
        .annotate(total=Sum(F("quantidade") * F("preco_unitario")))
    )
    medido = medido_por_etapa(orcamento)
    pago = pago_por_etapa(orcamento)
    linhas = []
    arvore = orcamento.arvore(por_etapa, medido, pago)
    for etapa, nivel, orcado, comprado, medido_etapa, pago_etapa in arvore:
        realizado = comprado + medido_etapa
        linhas.append({
            "etapa": etapa,
            "nivel": nivel,
            "orcado": orcado,
            "comprado": comprado,
            "medido": medido_etapa,
            "realizado": realizado,
            "pago": pago_etapa,
            "saldo": orcado - realizado,
            "percentual": (realizado / orcado * 100) if orcado else None,
        })

    sem_etapa = arredondar(
        (
            comprados.filter(pedido__obra=orcamento.obra, etapa__isnull=True).aggregate(
                total=Sum(F("quantidade") * F("preco_unitario"))
            )["total"]
            or Decimal("0")
        )
        + medido_sem_etapa(orcamento.obra)
    )
    total_orcado = orcamento.custo_direto
    total_comprado = arredondar(sum(por_etapa.values(), Decimal("0")))
    total_medido = arredondar(sum(medido.values(), Decimal("0")))
    total_realizado = total_comprado + total_medido
    total_pago = arredondar(sum(pago.values(), Decimal("0")))
    contexto = {
        **admin.site.each_context(request),
        "orcamento": orcamento,
        "linhas": linhas,
        "sem_etapa": sem_etapa,
        "total_orcado": total_orcado,
        "total_comprado": total_comprado,
        "total_medido": total_medido,
        "total_realizado": total_realizado,
        "total_pago": total_pago,
        "total_saldo": total_orcado - total_realizado,
        "total_percentual": (total_realizado / total_orcado * 100) if total_orcado else None,
    }
    return render(request, "suprimentos/orcado_comprado.html", contexto)
