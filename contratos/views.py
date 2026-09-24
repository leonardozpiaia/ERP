import datetime

from django import forms
from django.contrib import admin
from django.db.models import Sum
from django.shortcuts import get_object_or_404, render

from config.permissoes import requer
from obras.models import Obra
from orcamento.models import arredondar

from . import services
from .models import ZERO, ItemMedicao, Medicao


@requer("contratos.view_medicao")
def boletim(request, pk):
    """Boletim de medição para impressão: contratado, anterior, atual, acumulado e saldo."""
    medicao = get_object_or_404(
        Medicao.objects.select_related("contrato__fornecedor", "contrato__obra__empresa"), pk=pk
    )
    contrato = medicao.contrato
    anteriores = dict(
        ItemMedicao.objects.filter(
            medicao__contrato=contrato,
            medicao__numero__lt=medicao.numero,
            medicao__status=Medicao.Status.APROVADA,
        ).values_list("item_contrato").annotate(total=Sum("quantidade"))
    )
    atuais = dict(medicao.itens.values_list("item_contrato", "quantidade"))

    linhas = []
    for item in contrato.itens.select_related("unidade", "etapa"):
        anterior = anteriores.get(item.pk, ZERO)
        atual = atuais.get(item.pk, ZERO)
        acumulado = anterior + atual
        linhas.append({
            "item": item,
            "anterior": anterior,
            "atual": atual,
            "acumulado": acumulado,
            "saldo": item.quantidade - acumulado,
            "valor_atual": arredondar(atual * item.preco_unitario),
            "valor_acumulado": arredondar(acumulado * item.preco_unitario),
            "percentual": acumulado / item.quantidade * 100 if item.quantidade else ZERO,
        })
    total_contrato = contrato.valor_total
    total_acumulado = sum((linha["valor_acumulado"] for linha in linhas), ZERO)
    return render(request, "contratos/boletim.html", {
        "medicao": medicao,
        "contrato": contrato,
        "linhas": linhas,
        "total_contrato": total_contrato,
        "total_acumulado": total_acumulado,
        "percentual": total_acumulado / total_contrato * 100 if total_contrato else ZERO,
    })


class RetencoesForm(forms.Form):
    inicio = forms.DateField(label="De")
    fim = forms.DateField(label="Até")
    obra = forms.ModelChoiceField(label="Obra", queryset=Obra.objects.all(), required=False)


@requer("contratos.view_medicao")
def retencoes(request):
    hoje = datetime.date.today()
    inicio = hoje.replace(day=1)
    fim = (inicio + datetime.timedelta(days=32)).replace(day=1) - datetime.timedelta(days=1)
    form = RetencoesForm(request.GET or {"inicio": inicio, "fim": fim})
    linhas, totais = [], {}
    if form.is_valid():
        d = form.cleaned_data
        linhas, totais = services.retencoes(d["inicio"], d["fim"], d["obra"])
    return render(request, "contratos/retencoes.html", {
        **admin.site.each_context(request),
        "title": "Retenções de medições",
        "form": form,
        "linhas": linhas,
        "totais": totais,
    })
