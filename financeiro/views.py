import datetime

from django import forms
from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import redirect, render
from django.urls import reverse

from cadastros.models import Empresa
from config import anexos
from config.permissoes import requer
from obras.models import Obra

from . import services
from .models import Baixa, ContaBancaria, Parcela, Titulo


class BaixaLoteForm(forms.Form):
    data = forms.DateField(label="Data da baixa", initial=datetime.date.today)
    conta = forms.ModelChoiceField(label="Conta bancária", queryset=ContaBancaria.objects.none())
    comprovante = forms.FileField(
        label="Comprovante (opcional)", required=False,
        validators=[anexos.validar_extensao_documento, anexos.validar_tamanho],
        help_text="Um único comprovante para todas as parcelas desta baixa (ex.: a TED que pagou tudo).",
    )

    def __init__(self, *args, empresas, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["conta"].queryset = ContaBancaria.objects.filter(ativa=True, empresa__in=empresas)


@requer("financeiro.add_baixa")
def baixa_lote(request):
    ids = [int(i) for i in request.GET.get("ids", "").split(",") if i.isdigit()]
    parcelas = list(Parcela.objects.em_aberto().filter(pk__in=ids).select_related("titulo__empresa"))
    tipos = {p.titulo.tipo for p in parcelas}
    modelo = "parcelareceber" if tipos == {Titulo.Tipo.RECEBER} else "parcelapagar"
    voltar = reverse(f"admin:financeiro_{modelo}_changelist")

    if not parcelas:
        messages.warning(request, "Nenhuma das parcelas selecionadas tem saldo em aberto.")
        return redirect(voltar)
    empresas = {p.titulo.empresa_id for p in parcelas}
    if len(empresas) > 1 or len(tipos) > 1:
        messages.error(request, "Selecione parcelas de uma só empresa e de um só tipo (pagar ou receber).")
        return redirect(voltar)
    if not request.user.has_perm("financeiro.add_baixa"):
        messages.error(request, "Você não tem permissão para registrar baixas.")
        return redirect(voltar)

    form = BaixaLoteForm(request.POST or None, request.FILES or None, empresas=empresas)
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                baixas = [
                    services.baixar(parcela, form.cleaned_data["conta"], form.cleaned_data["data"])
                    for parcela in parcelas
                ]
                arquivo = form.cleaned_data["comprovante"]
                if arquivo:
                    # O arquivo é gravado uma vez e compartilhado por todas as baixas do lote.
                    primeira = baixas[0]
                    primeira.arquivo_comprovante = arquivo
                    primeira.save(update_fields=["arquivo_comprovante"])
                    Baixa.objects.filter(pk__in=[b.pk for b in baixas[1:]]).update(
                        arquivo_comprovante=primeira.arquivo_comprovante.name
                    )
        except ValidationError as erro:
            messages.error(request, "; ".join(erro.messages))
        else:
            messages.success(request, f"{len(parcelas)} parcela(s) baixada(s).")
            return redirect(voltar)

    contexto = {
        **admin.site.each_context(request),
        "form": form,
        "parcelas": parcelas,
        "total": sum(p.saldo_aberto for p in parcelas),
        "voltar": voltar,
        "pagar": modelo == "parcelapagar",
    }
    return render(request, "financeiro/baixa_lote.html", contexto)


class FluxoForm(forms.Form):
    AGRUPAMENTOS = [("dia", "Dia"), ("semana", "Semana"), ("mes", "Mês")]
    inicio = forms.DateField(label="De")
    fim = forms.DateField(label="Até")
    agrupamento = forms.ChoiceField(label="Agrupar por", choices=AGRUPAMENTOS, initial="mes")
    empresa = forms.ModelChoiceField(label="Empresa", queryset=Empresa.objects.all(), required=False)
    obra = forms.ModelChoiceField(label="Obra", queryset=Obra.objects.all(), required=False)

    def clean(self):
        dados = super().clean()
        inicio, fim = dados.get("inicio"), dados.get("fim")
        if inicio and fim:
            if fim < inicio:
                raise ValidationError("A data final deve ser depois da inicial.")
            limite = {"dia": 93, "semana": 366, "mes": 3660}[dados.get("agrupamento", "mes")]
            if (fim - inicio).days > limite:
                raise ValidationError("Período longo demais para esse agrupamento.")
        return dados


@requer("financeiro.view_titulopagar")
def fluxo_caixa(request):
    hoje = datetime.date.today()
    padrao = {
        "inicio": hoje.replace(day=1),
        "fim": (hoje.replace(day=1) + datetime.timedelta(days=190)).replace(day=1) - datetime.timedelta(days=1),
        "agrupamento": "mes",
    }
    form = FluxoForm(request.GET or padrao)
    resultado = None
    if form.is_valid():
        d = form.cleaned_data
        resultado = services.fluxo_de_caixa(
            d["inicio"], d["fim"], d["agrupamento"], empresa=d["empresa"], obra=d["obra"]
        )
    contexto = {
        **admin.site.each_context(request),
        "title": "Fluxo de caixa",
        "form": form,
        "r": resultado,
        "agrupamento": form.cleaned_data.get("agrupamento") if form.is_valid() else "mes",
        "por_obra": form.is_valid() and form.cleaned_data.get("obra") is not None,
    }
    return render(request, "financeiro/fluxo_caixa.html", contexto)
