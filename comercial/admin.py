from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.forms.models import BaseInlineFormSet
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.html import format_html

from financeiro.admin import moeda
from suprimentos.admin import SomenteLeituraInline, executar

from . import services
from .models import (
    ZERO,
    ContratoVenda,
    IndiceEconomico,
    ReajusteContrato,
    SerieParcelas,
    Unidade,
)


@admin.register(Unidade)
class UnidadeAdmin(admin.ModelAdmin):
    list_display = [
        "__str__", "bloco", "andar", "tipo", "area_privativa", "quartos", "preco_fmt", "status", "contrato",
    ]
    list_filter = ["obra", "status", "tipo", "bloco"]
    search_fields = ["identificador", "bloco", "obra__codigo", "obra__nome"]
    list_select_related = ["obra"]
    actions = ["liberar", "reservar", "bloquear"]

    def get_readonly_fields(self, request, obj=None):
        # A situação "vendida" só muda pelo contrato (efetivação ou distrato).
        if obj and obj.status == Unidade.Status.VENDIDA:
            return ["obra", "status"]
        return []

    def formfield_for_choice_field(self, db_field, request, **kwargs):
        if db_field.name == "status":
            kwargs["choices"] = [c for c in Unidade.Status.choices if c[0] != Unidade.Status.VENDIDA]
        return super().formfield_for_choice_field(db_field, request, **kwargs)

    @admin.display(description="preço de tabela", ordering="preco_tabela")
    def preco_fmt(self, obj):
        return moeda(obj.preco_tabela)

    @admin.display(description="contrato")
    def contrato(self, obj):
        contrato = obj.contrato_vigente
        if not contrato:
            return "-"
        url = reverse("admin:comercial_contratovenda_change", args=[contrato.pk])
        return format_html('<a href="{}">CV {}</a>', url, contrato.pk)

    def mudar_status(self, request, queryset, status):
        alteradas = queryset.exclude(status=Unidade.Status.VENDIDA).update(status=status)
        ignoradas = queryset.count() - alteradas
        self.message_user(request, f"{alteradas} unidade(s) alterada(s).")
        if ignoradas:
            self.message_user(
                request, f"{ignoradas} unidade(s) vendida(s) não foram alteradas.", messages.WARNING
            )

    @admin.action(description="Marcar como disponíveis")
    def liberar(self, request, queryset):
        self.mudar_status(request, queryset, Unidade.Status.DISPONIVEL)

    @admin.action(description="Marcar como reservadas")
    def reservar(self, request, queryset):
        self.mudar_status(request, queryset, Unidade.Status.RESERVADA)

    @admin.action(description="Bloquear para venda")
    def bloquear(self, request, queryset):
        self.mudar_status(request, queryset, Unidade.Status.BLOQUEADA)


@admin.register(IndiceEconomico)
class IndiceEconomicoAdmin(admin.ModelAdmin):
    list_display = ["indice", "mes_fmt", "variacao"]
    list_filter = ["indice"]
    date_hierarchy = "mes"

    @admin.display(description="mês", ordering="mes")
    def mes_fmt(self, obj):
        return obj.mes.strftime("%m/%Y")


class SeriesFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()
        if any(self.errors):
            return
        series = [
            f.cleaned_data for f in self.forms
            if f.cleaned_data and not f.cleaned_data.get("DELETE")
        ]
        total = sum((s["quantidade"] * s["valor"] for s in series), ZERO)
        valor = self.instance.valor_total
        if series and valor is not None and total != valor:
            raise ValidationError(
                f"As parcelas somam R$ {moeda(total)}, mas o valor do contrato é R$ {moeda(valor)} "
                f"(diferença de R$ {moeda(valor - total)})."
            )


class SerieParcelasInline(SomenteLeituraInline, admin.TabularInline):
    model = SerieParcelas
    formset = SeriesFormSet
    extra = 1
    fields = ["tipo", "quantidade", "valor", "primeiro_vencimento", "intervalo_meses", "total"]
    readonly_fields = ["total"]

    @admin.display(description="total da série")
    def total(self, obj):
        return moeda(obj.total) if obj.pk else "-"


class ReajusteInline(admin.TabularInline):
    model = ReajusteContrato
    extra = 0
    fields = ["indice", "aplicado_em", "saldo_antes", "saldo_depois"]
    readonly_fields = fields
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(ContratoVenda)
class ContratoVendaAdmin(admin.ModelAdmin):
    list_display = [
        "__str__", "data_contrato", "valor_fmt", "indice", "status", "recebido_fmt", "saldo_fmt",
    ]
    list_filter = ["status", "indice", "unidade__obra"]
    search_fields = ["pk", "cliente__nome", "cliente__cpf_cnpj", "unidade__identificador"]
    list_select_related = ["unidade__obra", "cliente"]
    autocomplete_fields = ["cliente"]
    readonly_fields = ["status", "data_distrato", "titulo_link", "recebido_fmt", "saldo_fmt"]
    fields = [
        "unidade", "cliente", "data_contrato", "valor_total", "indice", "data_base", "observacao",
        "status", "data_distrato", "titulo_link", "recebido_fmt", "saldo_fmt",
    ]
    inlines = [SerieParcelasInline, ReajusteInline]
    actions = ["efetivar", "reajustar", "distratar"]

    def get_readonly_fields(self, request, obj=None):
        if obj and not obj.editavel():
            return [f for f in self.fields]
        return self.readonly_fields

    def has_delete_permission(self, request, obj=None):
        # Contrato efetivado não se exclui: use o distrato.
        if obj is not None and not obj.editavel():
            return False
        return super().has_delete_permission(request, obj)

    def delete_queryset(self, request, queryset):
        super().delete_queryset(request, queryset.filter(status=ContratoVenda.Status.RASCUNHO))

    def get_changeform_initial_data(self, request):
        inicial = super().get_changeform_initial_data(request)
        unidade = Unidade.objects.filter(pk=request.GET.get("unidade")).first()
        if unidade:
            inicial.setdefault("valor_total", unidade.preco_tabela)
        return inicial

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "unidade":
            # Só unidades que podem ser vendidas (e a do próprio contrato, ao editar).
            livres = Unidade.objects.filter(
                status__in=[Unidade.Status.DISPONIVEL, Unidade.Status.RESERVADA]
            )
            contrato_id = request.resolver_match.kwargs.get("object_id")
            if contrato_id:
                livres = livres | Unidade.objects.filter(contratos__pk=contrato_id)
            kwargs["queryset"] = livres.select_related("obra").distinct()
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    @admin.display(description="valor", ordering="valor_total")
    def valor_fmt(self, obj):
        return moeda(obj.valor_total)

    @admin.display(description="recebido")
    def recebido_fmt(self, obj):
        return moeda(obj.recebido) if obj.pk else "-"

    @admin.display(description="saldo a receber")
    def saldo_fmt(self, obj):
        return moeda(obj.saldo) if obj.pk else "-"

    @admin.display(description="parcelas no financeiro")
    def titulo_link(self, obj):
        if not obj.titulo_id:
            return "Geradas ao efetivar o contrato."
        url = reverse("admin:financeiro_tituloreceber_change", args=[obj.titulo_id])
        return format_html('<a href="{}">{}</a>', url, obj.titulo)

    @admin.action(description="Efetivar (gerar parcelas a receber e marcar unidade como vendida)")
    def efetivar(self, request, queryset):
        executar(self, request, services.efetivar, queryset, "{} contrato(s) efetivado(s).")

    @admin.action(description="Aplicar reajustes pendentes")
    def reajustar(self, request, queryset):
        meses = sum(services.reajustar(c) for c in queryset)
        self.message_user(request, f"{meses} reajuste(s) mensal(is) aplicado(s).")

    @admin.action(description="Distratar contratos selecionados")
    def distratar(self, request, queryset):
        if request.POST.get("confirmar") != "sim":
            contexto = {
                **self.admin_site.each_context(request),
                "title": "Confirmar distrato",
                "contratos": queryset,
                "opts": self.model._meta,
                "action_checkbox_name": admin.helpers.ACTION_CHECKBOX_NAME,
            }
            return TemplateResponse(request, "comercial/confirmar_distrato.html", contexto)
        executar(self, request, services.distratar, queryset, "{} contrato(s) distratado(s).")
        return None
