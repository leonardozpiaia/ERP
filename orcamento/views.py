import datetime
from decimal import Decimal

from django.contrib import admin, messages
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from config.permissoes import requer
from obras.models import Obra

from . import importacao
from .forms import ImportarPlanilhaForm
from .models import ItemOrcamento, Orcamento, arredondar


@requer("orcamento.view_orcamento")
def eap(request, pk):
    orcamento = get_object_or_404(Orcamento.objects.select_related("obra"), pk=pk)
    itens_por_etapa = {}
    itens = ItemOrcamento.objects.filter(etapa__orcamento=orcamento).select_related(
        "composicao__unidade", "insumo__unidade", "unidade_medida"
    )
    for item in itens:
        itens_por_etapa.setdefault(item.etapa_id, []).append(item)
    linhas = [
        {"etapa": etapa, "nivel": nivel, "total": total, "itens": itens_por_etapa.get(etapa.pk, [])}
        for etapa, nivel, total in orcamento.arvore()
    ]
    contexto = {**admin.site.each_context(request), "orcamento": orcamento, "linhas": linhas}
    return render(request, "orcamento/eap.html", contexto)


CHAVE_SESSAO = "importacao_orcamento"


@requer("orcamento.add_orcamento")
def importar_planilha(request):
    """Importação em duas etapas: envio da planilha com prévia, depois confirmação."""
    if request.method == "POST" and "confirmar" in request.POST:
        pendente = request.session.get(CHAVE_SESSAO)
        if not pendente:
            messages.error(request, "A prévia expirou. Envie a planilha de novo.")
            return redirect("orcamento:importar")
        dados = pendente["dados"]
        obra = get_object_or_404(Obra, pk=dados["obra"])
        orcamento = importacao.importar(
            importacao.Leitura.da_sessao(pendente["leitura"]),
            obra=obra,
            descricao=dados["descricao"],
            data_base=datetime.date.fromisoformat(dados["data_base"]),
            bdi_percentual=Decimal(dados["bdi_percentual"]),
        )
        del request.session[CHAVE_SESSAO]
        messages.success(request, f"Orçamento importado: {orcamento}.")
        return redirect("orcamento:eap", orcamento.pk)

    leitura = None
    if request.method == "POST":
        form = ImportarPlanilhaForm(request.POST, request.FILES)
        if form.is_valid():
            d = form.cleaned_data
            leitura = importacao.ler_planilha(d["arquivo"])
            if not leitura.erros:
                importacao.conferir_cadastros(leitura)
            if leitura.ok:
                request.session[CHAVE_SESSAO] = {
                    "leitura": leitura.para_sessao(),
                    "dados": {
                        "obra": d["obra"].pk,
                        "descricao": d["descricao"],
                        "data_base": d["data_base"].isoformat(),
                        "bdi_percentual": str(d["bdi_percentual"]),
                        "arquivo": d["arquivo"].name,
                    },
                }
            else:
                request.session.pop(CHAVE_SESSAO, None)
    else:
        form = ImportarPlanilhaForm()

    contexto = {
        **admin.site.each_context(request),
        "title": "Importar orçamento de planilha",
        "form": form,
        "leitura": leitura,
    }
    if leitura is not None and leitura.ok:
        bdi = form.cleaned_data["bdi_percentual"]
        contexto.update({
            "resumo": leitura.resumo(),
            "total": leitura.total,
            "total_com_bdi": arredondar(leitura.total * (1 + bdi / 100)),
            "amostra": leitura.itens[:15],
            "obra": form.cleaned_data["obra"],
            "bdi": bdi,
        })
    return render(request, "orcamento/importar.html", contexto)


@requer("orcamento.add_orcamento")
def modelo_planilha(request):
    resposta = HttpResponse(
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    resposta["Content-Disposition"] = 'attachment; filename="modelo-orcamento.xlsx"'
    importacao.gerar_modelo(resposta)
    return resposta
