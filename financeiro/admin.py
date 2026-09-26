import datetime

from django.contrib import admin
from django.core.exceptions import ValidationError
from django.forms.models import BaseInlineFormSet
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.utils.html import format_html

from .models import (
    ZERO,
    Apropriacao,
    Baixa,
    CategoriaFinanceira,
    ContaBancaria,
    Parcela,
    ParcelaPagar,
    ParcelaReceber,
    TituloPagar,
    TituloReceber,
)


def moeda(valor):
    texto = f"{valor:,.2f}"
    return texto.replace(",", "_").replace(".", ",").replace("_", ".")


@admin.register(ContaBancaria)
class ContaBancariaAdmin(admin.ModelAdmin):
    list_display = ["descricao", "empresa", "banco", "agencia", "numero", "saldo", "ativa"]
    list_filter = ["ativa", "empresa"]
    search_fields = ["descricao", "banco", "numero"]

    @admin.display(description="saldo atual")
    def saldo(self, obj):
        return moeda(obj.saldo_atual)


@admin.register(CategoriaFinanceira)
class CategoriaFinanceiraAdmin(admin.ModelAdmin):
    list_display = ["codigo", "descricao", "tipo", "ativa"]
    list_filter = ["tipo", "ativa"]
    search_fields = ["codigo", "descricao"]


# ------------------------------------------------------------------- Títulos


class ParcelasFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()
        validas = [
            f for f in self.forms
            if f.cleaned_data and not f.cleaned_data.get("DELETE")
        ]
        if not validas:
            raise ValidationError("Informe pelo menos uma parcela.")


class ParcelaInline(admin.TabularInline):
    model = Parcela
    formset = ParcelasFormSet
    extra = 0
    min_num = 1
    fields = ["numero", "vencimento", "valor", "baixado", "situacao"]
    readonly_fields = ["baixado", "situacao"]

    @admin.display(description="baixado")
    def baixado(self, obj):
        return moeda(obj.baixado) if obj.pk else "-"

    @admin.display(description="situação")
    def situacao(self, obj):
        return obj.situacao if obj.pk else "-"

    def editavel(self, obj):
        # Depois da primeira baixa as parcelas não mudam mais; estorne a baixa antes.
        return obj is None or not obj.tem_baixas()

    def has_add_permission(self, request, obj=None):
        return self.editavel(obj) and super().has_add_permission(request, obj)

    def has_change_permission(self, request, obj=None):
        return self.editavel(obj) and super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        return self.editavel(obj) and super().has_delete_permission(request, obj)


class ApropriacoesFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()
        total = sum(
            (f.cleaned_data.get("percentual") or ZERO
             for f in self.forms if f.cleaned_data and not f.cleaned_data.get("DELETE")),
            ZERO,
        )
        if total > 100:
            raise ValidationError(f"A soma das apropriações passa de 100% ({total:.2f}%).")


class ApropriacaoInline(admin.TabularInline):
    model = Apropriacao
    formset = ApropriacoesFormSet
    extra = 0
    autocomplete_fields = ["etapa"]


class TituloAdminBase(admin.ModelAdmin):
    pessoa_campo = None  # "fornecedor" ou "cliente"
    list_filter = ["empresa", "obra", "categoria"]
    date_hierarchy = "data_emissao"
    autocomplete_fields = ["empresa", "obra", "categoria"]

    def get_list_display(self, request):
        return ["__str__", self.pessoa_campo, "obra", "data_emissao", "total", "saldo"]

    def get_search_fields(self, request):
        return ["documento", "descricao", f"{self.pessoa_campo}__{self.nome_pessoa}"]

    def get_autocomplete_fields(self, request):
        return [*self.autocomplete_fields, self.pessoa_campo]

    def get_fields(self, request, obj=None):
        return [
            "empresa", "obra", self.pessoa_campo, "categoria", "documento", "data_emissao",
            "descricao", *self.campos_extras,
        ]

    @admin.display(description="total")
    def total(self, obj):
        return moeda(obj.total)

    @admin.display(description="saldo")
    def saldo(self, obj):
        return moeda(obj.saldo)


@admin.register(TituloPagar)
class TituloPagarAdmin(TituloAdminBase):
    pessoa_campo = "fornecedor"
    nome_pessoa = "razao_social"
    campos_extras = ["origem"]
    readonly_fields = ["origem"]
    inlines = [ParcelaInline, ApropriacaoInline]

    @admin.display(description="origem")
    def origem(self, obj):
        if not obj.recebimento_id:
            return "Lançamento manual"
        url = reverse("admin:suprimentos_recebimento_change", args=[obj.recebimento_id])
        origem = format_html('<a href="{}">{}</a>', url, obj.recebimento)
        if obj.recebimento.arquivo_nota:
            origem = format_html(
                '{} · <a href="{}" target="_blank">Abrir nota fiscal</a>', origem, obj.recebimento.arquivo_nota.url
            )
        return origem


@admin.register(TituloReceber)
class TituloReceberAdmin(TituloAdminBase):
    pessoa_campo = "cliente"
    nome_pessoa = "nome"
    campos_extras = []
    inlines = [ParcelaInline]


# ----------------------------------------------------------- Parcelas/baixas


class SituacaoFilter(admin.SimpleListFilter):
    title = "situação"
    parameter_name = "situacao"

    def lookups(self, request, model_admin):
        return [
            ("aberto", "Em aberto"),
            ("vencidas", "Vencidas"),
            ("7dias", "Vencem em 7 dias"),
            ("quitadas", "Quitadas"),
        ]

    def queryset(self, request, queryset):
        hoje = datetime.date.today()
        if self.value() == "aberto":
            return queryset.filter(saldo_aberto__gt=0)
        if self.value() == "vencidas":
            return queryset.filter(saldo_aberto__gt=0, vencimento__lt=hoje)
        if self.value() == "7dias":
            return queryset.filter(
                saldo_aberto__gt=0, vencimento__gte=hoje, vencimento__lte=hoje + datetime.timedelta(days=7)
            )
        if self.value() == "quitadas":
            return queryset.filter(saldo_aberto__lte=0)
        return queryset


class BaixasFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()
        novas = sum(
            (f.cleaned_data.get("valor") or ZERO
             for f in self.forms
             if f.cleaned_data and not f.instance.pk and not f.cleaned_data.get("DELETE")),
            ZERO,
        )
        if novas > self.instance.saldo:
            raise ValidationError(
                f"As baixas somam mais que o saldo da parcela (R$ {moeda(self.instance.saldo)})."
            )


class BaixaInline(admin.TabularInline):
    model = Baixa
    formset = BaixasFormSet
    extra = 0
    fields = ["data", "conta", "valor", "juros", "multa", "desconto", "movimentado"]
    readonly_fields = ["movimentado"]
    verbose_name_plural = "baixas (exclua uma baixa para estorná-la)"

    @admin.display(description="valor movimentado")
    def movimentado(self, obj):
        return moeda(obj.valor_movimentado) if obj.pk else "-"

    def has_change_permission(self, request, obj=None):
        # Baixa lançada não se edita: estorne (exclua) e lance de novo.
        return False

    def get_readonly_fields(self, request, obj=None):
        return self.readonly_fields

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "conta":
            parcela_id = request.resolver_match.kwargs.get("object_id")
            parcela = Parcela.objects.filter(pk=parcela_id).select_related("titulo").first()
            contas = ContaBancaria.objects.filter(ativa=True)
            if parcela:
                contas = contas.filter(empresa_id=parcela.titulo.empresa_id)
            kwargs["queryset"] = contas
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


class ParcelaAdminBase(admin.ModelAdmin):
    pessoa_campo = None
    date_hierarchy = "vencimento"
    list_filter = [SituacaoFilter, "titulo__empresa", "titulo__obra"]
    list_select_related = ["titulo__fornecedor", "titulo__cliente", "titulo__obra"]
    fields = ["titulo_link", "numero", "vencimento", "valor", "saldo_atual", "situacao"]
    readonly_fields = fields
    inlines = [BaixaInline]
    actions = ["baixar"]
    ordering = ["vencimento"]

    def get_queryset(self, request):
        return super().get_queryset(request).com_saldo()

    def get_list_display(self, request):
        return ["vencimento", "documento", "pessoa", "obra", "valor_fmt", "saldo_fmt", "situacao_cor"]

    def get_search_fields(self, request):
        return ["titulo__documento", "titulo__descricao", f"titulo__{self.pessoa_campo}__{self.nome_pessoa}"]

    def has_add_permission(self, request):
        return False  # parcelas nascem dos títulos

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description="título")
    def titulo_link(self, obj):
        titulo = obj.titulo
        modelo = "titulopagar" if self.pessoa_campo == "fornecedor" else "tituloreceber"
        url = reverse(f"admin:financeiro_{modelo}_change", args=[titulo.pk])
        return format_html('<a href="{}">{}</a>', url, titulo)

    @admin.display(description="documento")
    def documento(self, obj):
        titulo = obj.titulo
        return f"{titulo.documento or f'Título {titulo.pk}'} - parc. {obj.numero}"

    @admin.display(description="fornecedor / cliente")
    def pessoa(self, obj):
        return obj.titulo.pessoa

    @admin.display(description="obra")
    def obra(self, obj):
        return obj.titulo.obra.codigo if obj.titulo.obra else "-"

    @admin.display(description="valor", ordering="valor")
    def valor_fmt(self, obj):
        return moeda(obj.valor)

    @admin.display(description="saldo", ordering="saldo_aberto")
    def saldo_fmt(self, obj):
        return moeda(obj.saldo_aberto)

    @admin.display(description="saldo")
    def saldo_atual(self, obj):
        return moeda(obj.saldo)

    @admin.display(description="situação")
    def situacao(self, obj):
        return obj.situacao

    @admin.display(description="situação")
    def situacao_cor(self, obj):
        cores = {"Vencida": "#ba2121", "Quitada": "#417505", "Parcial": "#b46d00"}
        situacao = obj.situacao
        return format_html('<span style="color: {}; font-weight: bold">{}</span>', cores.get(situacao, "inherit"), situacao)

    @admin.action(description="Baixar parcelas selecionadas (valor total)")
    def baixar(self, request, queryset):
        ids = ",".join(str(pk) for pk in queryset.values_list("pk", flat=True))
        return HttpResponseRedirect(reverse("financeiro:baixa_lote") + f"?ids={ids}")


@admin.register(ParcelaPagar)
class ParcelaPagarAdmin(ParcelaAdminBase):
    pessoa_campo = "fornecedor"
    nome_pessoa = "razao_social"


@admin.register(ParcelaReceber)
class ParcelaReceberAdmin(ParcelaAdminBase):
    pessoa_campo = "cliente"
    nome_pessoa = "nome"
