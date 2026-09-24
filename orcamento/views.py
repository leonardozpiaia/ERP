from django.contrib import admin
from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import get_object_or_404, render

from .models import ItemOrcamento, Orcamento


@staff_member_required
def eap(request, pk):
    orcamento = get_object_or_404(Orcamento.objects.select_related("obra"), pk=pk)
    itens_por_etapa = {}
    itens = ItemOrcamento.objects.filter(etapa__orcamento=orcamento).select_related(
        "composicao__unidade", "insumo__unidade"
    )
    for item in itens:
        itens_por_etapa.setdefault(item.etapa_id, []).append(item)
    linhas = [
        {"etapa": etapa, "nivel": nivel, "total": total, "itens": itens_por_etapa.get(etapa.pk, [])}
        for etapa, nivel, total in orcamento.arvore()
    ]
    contexto = {**admin.site.each_context(request), "orcamento": orcamento, "linhas": linhas}
    return render(request, "orcamento/eap.html", contexto)
