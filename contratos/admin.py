import datetime

from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.forms.models import BaseInlineFormSet
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.utils.html import format_html

from financeiro.admin import moeda
from suprimentos.admin import SomenteLeituraInline, executar
from suprimentos.models import formatar_quantidade

from . import services
from .models import ContratoServico, ItemContrato, ItemMedicao, Medicao


def link_titulo(titulo):
    if titulo is None:
        return "-"
    url = reverse("admin:financeiro_titulopagar_change", args=[titulo.pk])
    return format_html('<a href="{}">{}</a>', url, titulo)


# ------------------------------------------------------------------ Contrato


class ItemContratoInline(admin.TabularInline):
    """Itens editáveis em elaboração; no contrato ativo, só aditivos (incluir ou aumentar)."""

    model = ItemContrato
    extra = 1
    autocomplete_fields = ["unidade", "etapa"]
    fields = ["descricao", "unidade", "quantidade", "preco_unitario", "etapa", "total", "medido", "saldo"]
    readonly_fields = ["total", "medido", "saldo"]

    def has_add_permission(self, request, obj=None):
        return (obj is None or obj.aceita_aditivo()) and super().has_add_permission(request, obj)

    def has_change_permission(self, request, obj=None):
        return (obj is None or obj.aceita_aditivo()) and super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        return (obj is None or obj.editavel()) and super().has_delete_permission(request, obj)

    def get_readonly_fields(self, request, obj=None):
        if obj is not None and not obj.editavel():
            # Em aditivo o preço e a apropriação dos itens já medidos não mudam.
            return [*self.readonly_fields, "preco_unitario", "etapa"]
        return self.readonly_fields

    @admin.display(description="total")
    def total(self, obj):
        return moeda(obj.total) if obj.pk else "-"

    @admin.display(description="medido (aprovado)")
    def medido(self, obj):
        return formatar_quantidade(obj.quantidade_medida()) if obj.pk else "-"

    @admin.display(description="saldo")
    def saldo(self, obj):
        return formatar_quantidade(obj.saldo) if obj.pk else "-"


class MedicaoResumoInline(admin.TabularInline):
    model = Medicao
    extra = 0
    fields = ["numero", "data", "periodo_inicio", "periodo_fim", "status", "bruto", "liquido"]
    readonly_fields = fields
    show_change_link = True
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False

    @admin.display(description="bruto")
    def bruto(self, obj):
        return moeda(obj.valor_bruto)

    @admin.display(description="líquido")
    def liquido(self, obj):
        return moeda(obj.valor_liquido)


@admin.register(ContratoServico)
class ContratoServicoAdmin(admin.ModelAdmin):
    list_display = ["__str__", "obra", "data", "status", "total_fmt", "executado"]
    list_filter = ["status", "obra", "fornecedor"]
    search_fields = ["pk", "objeto", "fornecedor__razao_social", "fornecedor__nome_fantasia"]
    list_select_related = ["fornecedor", "obra"]
    autocomplete_fields = ["obra", "fornecedor"]
    inlines = [ItemContratoInline, MedicaoResumoInline]
    actions = ["ativar", "encerrar", "cancelar"]
    resumo = ["status", "total_fmt", "executado", "caucao", "nova_medicao", "caucao_titulo"]
    fieldsets = [
        (None, {"fields": ["obra", "fornecedor", "objeto", "data", "data_termino", "categoria", "observacao"]}),
        ("Pagamento e retenções", {
            "fields": ["prazo_pagamento_dias", "retencao_caucao", "retencao_inss", "retencao_iss"],
        }),
        ("Andamento", {"fields": resumo}),
    ]

    def get_readonly_fields(self, request, obj=None):
        if obj is not None and not obj.editavel():
            return [
                "obra", "fornecedor", "objeto", "data", "categoria", "prazo_pagamento_dias",
                "retencao_caucao", "retencao_inss", "retencao_iss", *self.resumo,
            ]
        return self.resumo

    def has_delete_permission(self, request, obj=None):
        if obj is not None and not obj.editavel():
            return False
        return super().has_delete_permission(request, obj)

    def delete_queryset(self, request, queryset):
        super().delete_queryset(request, queryset.filter(status=ContratoServico.Status.RASCUNHO))

    @admin.display(description="valor contratado")
    def total_fmt(self, obj):
        return moeda(obj.valor_total) if obj.pk else "-"

    @admin.display(description="executado")
    def executado(self, obj):
        if not obj.pk:
            return "-"
        percentual = f"{obj.percentual_executado:.1f}".replace(".", ",")
        return f"{moeda(obj.valor_medido)} ({percentual}%)"

    @admin.display(description="caução retida")
    def caucao(self, obj):
        return moeda(obj.caucao_retida) if obj.pk else "-"

    @admin.display(description="medição")
    def nova_medicao(self, obj):
        if not obj.pk or obj.status != ContratoServico.Status.ATIVO:
            return "Disponível com o contrato ativo."
        url = reverse("admin:contratos_medicao_add") + f"?contrato={obj.pk}"
        return format_html('<a class="button" href="{}">Nova medição</a>', url)

    @admin.display(description="devolução da caução")
    def caucao_titulo(self, obj):
        return link_titulo(obj.titulo_caucao) if obj.titulo_caucao_id else "Gerada no encerramento."

    @admin.action(description="Ativar contratos selecionados")
    def ativar(self, request, queryset):
        executar(self, request, services.ativar, queryset, "{} contrato(s) ativado(s).")

    @admin.action(description="Encerrar (e gerar a devolução da caução)")
    def encerrar(self, request, queryset):
        executar(self, request, services.encerrar, queryset, "{} contrato(s) encerrado(s).")

    @admin.action(description="Cancelar contratos sem medições")
    def cancelar(self, request, queryset):
        executar(self, request, services.cancelar, queryset, "{} contrato(s) cancelado(s).")


# ------------------------------------------------------------------- Medição


class ItensMedidosFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()
        preenchidos = [
            f for f in self.forms
            if f.has_changed() and f.cleaned_data and not f.cleaned_data.get("DELETE")
        ]
        if not preenchidos and not self.instance.pk:
            raise ValidationError("Informe a quantidade medida de pelo menos um serviço.")


class ItemMedicaoInline(SomenteLeituraInline, admin.TabularInline):
    model = ItemMedicao
    formset = ItensMedidosFormSet
    extra = 0
    fields = ["item_contrato", "quantidade", "total"]
    readonly_fields = ["total"]

    @admin.display(description="valor")
    def total(self, obj):
        return moeda(obj.total) if obj.pk else "-"

    def contrato_em_uso(self, request, obj):
        if obj is not None:
            return obj.contrato_id
        return request.GET.get("contrato") or request.POST.get("contrato")

    def itens_com_saldo(self, request, obj):
        contrato_id = self.contrato_em_uso(request, obj)
        itens = ItemContrato.objects.filter(contrato_id=contrato_id) if contrato_id else []
        return [item for item in itens if item.saldo_a_lancar() > 0]

    def get_formset(self, request, obj=None, **kwargs):
        self._contrato_id = self.contrato_em_uso(request, obj)
        return super().get_formset(request, obj, **kwargs)

    def get_extra(self, request, obj=None, **kwargs):
        if obj is None:
            return len(self.itens_com_saldo(request, obj)) or 1
        return 1 if obj.editavel() else 0

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name != "item_contrato":
            return super().formfield_for_foreignkey(db_field, request, **kwargs)
        kwargs["queryset"] = ItemContrato.objects.filter(
            contrato_id=getattr(self, "_contrato_id", None)
        ).select_related("unidade")
        campo = super().formfield_for_foreignkey(db_field, request, **kwargs)
        campo.label_from_instance = lambda item: (
            f"{item.descricao} - contratado {formatar_quantidade(item.quantidade)}, "
            f"a medir {formatar_quantidade(item.saldo_a_lancar())} {item.unidade}"
        )
        return campo


@admin.register(Medicao)
class MedicaoAdmin(admin.ModelAdmin):
    list_display = ["__str__", "contrato", "data", "periodo", "status", "bruto", "liquido"]
    list_filter = ["status", "contrato__obra", "contrato__fornecedor"]
    search_fields = ["contrato__pk", "contrato__objeto", "contrato__fornecedor__razao_social"]
    list_select_related = ["contrato__fornecedor"]
    inlines = [ItemMedicaoInline]
    actions = ["aprovar", "reabrir"]
    valores = ["status", "bruto", "caucao", "inss", "iss", "liquido", "titulo_link", "boletim"]
    fieldsets = [
        (None, {"fields": ["contrato", "data", "periodo_inicio", "periodo_fim", "observacao"]}),
        ("Valores", {"fields": valores}),
    ]

    def get_readonly_fields(self, request, obj=None):
        if obj is None:
            return self.valores
        if not obj.editavel():
            return ["contrato", "data", "periodo_inicio", "periodo_fim", *self.valores]
        return ["contrato", *self.valores]

    def add_view(self, request, form_url="", extra_context=None):
        if request.method == "GET" and not request.GET.get("contrato"):
            self.message_user(
                request, 'Abra o contrato e use o botão "Nova medição".', messages.INFO
            )
            url = reverse("admin:contratos_contratoservico_changelist")
            return HttpResponseRedirect(f"{url}?status__exact={ContratoServico.Status.ATIVO}")
        return super().add_view(request, form_url, extra_context)

    def get_changeform_initial_data(self, request):
        inicial = super().get_changeform_initial_data(request)
        contrato_id = request.GET.get("contrato")
        ultima = Medicao.objects.filter(contrato_id=contrato_id).order_by("-periodo_fim").first()
        if ultima:
            inicial.setdefault("periodo_inicio", ultima.periodo_fim + datetime.timedelta(days=1))
        return inicial

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "contrato":
            kwargs["queryset"] = ContratoServico.objects.filter(
                status=ContratoServico.Status.ATIVO
            ).select_related("fornecedor")
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def get_formset_kwargs(self, request, obj, inline, prefix):
        kwargs = super().get_formset_kwargs(request, obj, inline, prefix)
        if obj.pk is None and isinstance(inline, ItemMedicaoInline):
            # Já lista os serviços com saldo; linhas deixadas em branco são ignoradas.
            kwargs["initial"] = [
                {"item_contrato": item.pk} for item in inline.itens_com_saldo(request, None)
            ]
        return kwargs

    def has_delete_permission(self, request, obj=None):
        if obj is not None and not obj.editavel():
            return False
        return super().has_delete_permission(request, obj)

    def delete_queryset(self, request, queryset):
        super().delete_queryset(request, queryset.filter(status=Medicao.Status.RASCUNHO))

    @admin.display(description="período")
    def periodo(self, obj):
        return f"{obj.periodo_inicio:%d/%m/%Y} a {obj.periodo_fim:%d/%m/%Y}"

    @admin.display(description="valor bruto")
    def bruto(self, obj):
        return moeda(obj.valor_bruto) if obj.pk else "-"

    @admin.display(description="(-) caução")
    def caucao(self, obj):
        return moeda(obj.valor_caucao) if obj.pk else "-"

    @admin.display(description="(-) INSS retido")
    def inss(self, obj):
        return moeda(obj.valor_inss) if obj.pk else "-"

    @admin.display(description="(-) ISS retido")
    def iss(self, obj):
        return moeda(obj.valor_iss) if obj.pk else "-"

    @admin.display(description="valor líquido a pagar")
    def liquido(self, obj):
        return moeda(obj.valor_liquido) if obj.pk else "-"

    @admin.display(description="título a pagar")
    def titulo_link(self, obj):
        return link_titulo(obj.titulo) if obj.titulo_id else "Gerado na aprovação."

    @admin.display(description="boletim")
    def boletim(self, obj):
        if not obj.pk:
            return "-"
        url = reverse("contratos:boletim", args=[obj.pk])
        return format_html('<a href="{}" target="_blank">Imprimir boletim de medição</a>', url)

    @admin.action(description="Aprovar medições (gera o título a pagar)")
    def aprovar(self, request, queryset):
        executar(self, request, services.aprovar_medicao, queryset, "{} medição(ões) aprovada(s).")

    @admin.action(description="Reabrir medições aprovadas (exclui o título, se não pago)")
    def reabrir(self, request, queryset):
        executar(self, request, services.reabrir_medicao, queryset, "{} medição(ões) reaberta(s).")
