from collections import defaultdict

from django.contrib import admin
from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Sum
from django.shortcuts import render

from financeiro.models import Baixa
from obras.models import Obra

from .models import ZERO, ContratoVenda, Unidade


@staff_member_required
def espelho(request):
    obras = Obra.objects.filter(unidades__isnull=False).distinct()
    obra = obras.filter(pk=request.GET.get("obra")).first() or obras.first()
    contexto = {**admin.site.each_context(request), "title": "Espelho de vendas", "obras": obras, "obra": obra}
    if obra is None:
        return render(request, "comercial/espelho.html", contexto)

    unidades = list(Unidade.objects.filter(obra=obra))
    contratos = {
        c.unidade_id: c
        for c in ContratoVenda.objects.filter(unidade__obra=obra)
        .exclude(status=ContratoVenda.Status.DISTRATADO)
        .select_related("cliente")
    }

    # Blocos -> andares (do mais alto para o mais baixo) -> unidades.
    blocos = defaultdict(lambda: defaultdict(list))
    for unidade in unidades:
        unidade.contrato = contratos.get(unidade.pk)
        blocos[unidade.bloco or ""][unidade.andar].append(unidade)
    grade = [
        {
            "nome": nome,
            "andares": [
                {"andar": andar, "unidades": andares[andar]}
                for andar in sorted(andares, key=lambda a: (a is None, -(a or 0)))
            ],
        }
        for nome, andares in sorted(blocos.items())
    ]

    por_status = {s: {"rotulo": r, "qtd": 0, "valor": ZERO} for s, r in Unidade.Status.choices}
    for unidade in unidades:
        linha = por_status[unidade.status]
        linha["qtd"] += 1
        contrato = unidade.contrato
        linha["valor"] += contrato.valor_total if contrato and contrato.status == ContratoVenda.Status.ATIVO else unidade.preco_tabela

    ativos = [c for c in contratos.values() if c.status == ContratoVenda.Status.ATIVO]
    vendido = sum((c.valor_total for c in ativos), ZERO)
    recebido = Baixa.objects.filter(
        parcela__titulo__contrato_venda__in=ativos
    ).aggregate(total=Sum("valor"))["total"] or ZERO
    contexto.update({
        "grade": grade,
        "por_status": por_status.items(),
        "total_unidades": len(unidades),
        "vgv": sum((u["valor"] for u in por_status.values()), ZERO),
        "vendido": vendido,
        "recebido": recebido,
        "percentual_vendido": (
            100 * por_status[Unidade.Status.VENDIDA]["qtd"] / len(unidades) if unidades else 0
        ),
    })
    return render(request, "comercial/espelho.html", contexto)
