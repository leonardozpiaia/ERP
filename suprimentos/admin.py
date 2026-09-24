from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.forms.models import BaseInlineFormSet
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.utils.html import format_html

from financeiro.admin import moeda
from financeiro.services import gerar_titulo_do_recebimento

from . import services
from .models import (
    Cotacao,
    ItemCotacao,
    ItemPedido,
    ItemRecebimento,
    ItemSolicitacao,
    PedidoCompra,
    PropostaFornecedor,
    Recebimento,
    SolicitacaoCompra,
    formatar_quantidade,
)


def executar(modeladmin, request, funcao, objetos, sucesso):
    """Aplica `funcao` a cada objeto e mostra o resultado como mensagem."""
    feitos = 0
    for obj in objetos:
        try:
            funcao(obj)
            feitos += 1
        except ValidationError as erro:
            modeladmin.message_user(request, "; ".join(erro.messages), messages.ERROR)
    if feitos:
        modeladmin.message_user(request, sucesso.format(feitos))


class SomenteLeituraInline:
    """Inline que só pode ser editado enquanto o documento pai está editável."""

    def pai_editavel(self, obj):
        return obj is None or obj.editavel()

    def has_add_permission(self, request, obj=None):
        return self.pai_editavel(obj) and super().has_add_permission(request, obj)

    def has_change_permission(self, request, obj=None):
        return self.pai_editavel(obj) and super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        return self.pai_editavel(obj) and super().has_delete_permission(request, obj)


# ---------------------------------------------------------------- Solicitação


class ItemSolicitacaoInline(SomenteLeituraInline, admin.TabularInline):
    model = ItemSolicitacao
    extra = 1
    autocomplete_fields = ["insumo", "etapa"]
    fields = ["insumo", "quantidade", "etapa", "data_necessidade", "pedido", "saldo"]
    readonly_fields = ["pedido", "saldo"]

    @admin.display(description="já pedido")
    def pedido(self, obj):
        return formatar_quantidade(obj.quantidade_pedida) if obj.pk else "-"

    @admin.display(description="saldo")
    def saldo(self, obj):
        return formatar_quantidade(obj.saldo) if obj.pk else "-"


@admin.register(SolicitacaoCompra)
class SolicitacaoCompraAdmin(admin.ModelAdmin):
    list_display = ["__str__", "obra", "data", "solicitante", "status"]
    list_filter = ["status", "obra"]
    search_fields = ["pk", "obra__codigo", "obra__nome"]
    autocomplete_fields = ["obra"]
    readonly_fields = ["solicitante", "status"]
    inlines = [ItemSolicitacaoInline]
    actions = ["aprovar", "gerar_cotacao"]

    def get_readonly_fields(self, request, obj=None):
        if obj and not obj.editavel():
            return ["obra", "data", "solicitante", "status", "observacao"]
        return self.readonly_fields

    def save_model(self, request, obj, form, change):
        if not change:
            obj.solicitante = request.user
        super().save_model(request, obj, form, change)

    @admin.action(description="Aprovar solicitações selecionadas")
    def aprovar(self, request, queryset):
        executar(self, request, services.aprovar_solicitacao, queryset, "{} solicitação(ões) aprovada(s).")

    @admin.action(description="Gerar cotação com as solicitações selecionadas")
    def gerar_cotacao(self, request, queryset):
        try:
            cotacao = services.gerar_cotacao(queryset)
        except ValidationError as erro:
            self.message_user(request, "; ".join(erro.messages), messages.ERROR)
            return None
        self.message_user(
            request,
            f"{cotacao} criada. Adicione os fornecedores e depois preencha o mapa de cotação.",
        )
        return HttpResponseRedirect(reverse("admin:suprimentos_cotacao_change", args=[cotacao.pk]))


# -------------------------------------------------------------------- Cotação


class ItemCotacaoInline(admin.TabularInline):
    model = ItemCotacao
    extra = 0
    fields = ["item_solicitacao", "obra", "quantidade"]
    readonly_fields = ["item_solicitacao", "obra", "quantidade"]
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False

    @admin.display(description="obra")
    def obra(self, obj):
        return obj.item_solicitacao.solicitacao.obra


class PropostaFornecedorInline(SomenteLeituraInline, admin.TabularInline):
    model = PropostaFornecedor
    extra = 1
    autocomplete_fields = ["fornecedor"]
    fields = ["fornecedor", "prazo_entrega_dias", "condicao_pagamento"]


@admin.register(Cotacao)
class CotacaoAdmin(admin.ModelAdmin):
    list_display = ["__str__", "data", "prazo_resposta", "status", "mapa"]
    list_filter = ["status"]
    readonly_fields = ["status", "mapa"]
    fields = ["data", "prazo_resposta", "status", "observacao", "mapa"]
    inlines = [ItemCotacaoInline, PropostaFornecedorInline]
    actions = ["cancelar"]

    def has_add_permission(self, request):
        # Cotações nascem das solicitações aprovadas (ação "Gerar cotação").
        return False

    @admin.display(description="mapa de cotação")
    def mapa(self, obj):
        if not obj.pk:
            return "-"
        url = reverse("suprimentos:mapa_cotacao", args=[obj.pk])
        return format_html('<a href="{}">Abrir mapa de cotação</a>', url)

    @admin.action(description="Cancelar cotações selecionadas")
    def cancelar(self, request, queryset):
        abertas = queryset.filter(status=Cotacao.Status.ABERTA)
        feitas = abertas.update(status=Cotacao.Status.CANCELADA)
        self.message_user(request, f"{feitas} cotação(ões) cancelada(s).")


# --------------------------------------------------------------------- Pedido


class ItemPedidoInline(SomenteLeituraInline, admin.TabularInline):
    model = ItemPedido
    extra = 1
    autocomplete_fields = ["insumo", "etapa"]
    fields = ["insumo", "etapa", "quantidade", "preco_unitario", "total", "recebido"]
    readonly_fields = ["total", "recebido"]

    @admin.display(description="total")
    def total(self, obj):
        return moeda(obj.total) if obj.pk else "-"

    @admin.display(description="recebido")
    def recebido(self, obj):
        return formatar_quantidade(obj.quantidade_recebida) if obj.pk else "-"


class RecebimentoInline(admin.TabularInline):
    model = Recebimento
    extra = 0
    fields = ["data", "numero_nota", "observacao"]
    readonly_fields = fields
    show_change_link = True
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(PedidoCompra)
class PedidoCompraAdmin(admin.ModelAdmin):
    list_display = ["__str__", "obra", "data", "previsao_entrega", "status", "total"]
    list_filter = ["status", "obra", "fornecedor"]
    search_fields = ["pk", "fornecedor__razao_social", "fornecedor__nome_fantasia", "obra__codigo"]
    autocomplete_fields = ["obra", "fornecedor"]
    readonly_fields = ["status", "cotacao", "total", "receber"]
    inlines = [ItemPedidoInline, RecebimentoInline]
    actions = ["aprovar", "cancelar"]

    def get_readonly_fields(self, request, obj=None):
        if obj and not obj.editavel():
            return [
                "obra", "fornecedor", "data", "previsao_entrega", "condicao_pagamento",
                "observacao", *self.readonly_fields,
            ]
        return self.readonly_fields

    @admin.display(description="total")
    def total(self, obj):
        return moeda(obj.total) if obj.pk else "-"

    @admin.display(description="recebimento")
    def receber(self, obj):
        if not obj.pk or not obj.pode_receber:
            return "-"
        url = reverse("admin:suprimentos_recebimento_add") + f"?pedido={obj.pk}"
        return format_html('<a class="button" href="{}">Registrar recebimento</a>', url)

    @admin.action(description="Aprovar pedidos selecionados")
    def aprovar(self, request, queryset):
        executar(self, request, services.aprovar_pedido, queryset, "{} pedido(s) aprovado(s).")

    @admin.action(description="Cancelar pedidos selecionados")
    def cancelar(self, request, queryset):
        executar(self, request, services.cancelar_pedido, queryset, "{} pedido(s) cancelado(s).")


# ---------------------------------------------------------------- Recebimento


class ItensRecebidosFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()
        preenchidos = [
            f for f in self.forms
            if f.has_changed() and f.cleaned_data and not f.cleaned_data.get("DELETE")
        ]
        if not preenchidos and not self.instance.pk:
            raise ValidationError("Informe a quantidade recebida de pelo menos um item.")


class ItemRecebimentoInline(admin.TabularInline):
    model = ItemRecebimento
    formset = ItensRecebidosFormSet
    extra = 0

    # Depois de salvo, o recebimento já gerou o título a pagar e não muda mais.
    def has_add_permission(self, request, obj=None):
        return obj is None and super().has_add_permission(request, obj)

    def has_change_permission(self, request, obj=None):
        return obj is None and super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        return obj is None and super().has_delete_permission(request, obj)

    def pedido_em_uso(self, request, obj):
        if obj is not None:
            return obj.pedido_id
        return request.GET.get("pedido") or request.POST.get("pedido")

    def get_formset(self, request, obj=None, **kwargs):
        self._pedido_id = self.pedido_em_uso(request, obj)
        return super().get_formset(request, obj, **kwargs)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name != "item_pedido":
            return super().formfield_for_foreignkey(db_field, request, **kwargs)
        kwargs["queryset"] = ItemPedido.objects.filter(
            pedido_id=getattr(self, "_pedido_id", None)
        ).select_related("insumo__unidade")
        campo = super().formfield_for_foreignkey(db_field, request, **kwargs)
        campo.label_from_instance = lambda item: (
            f"{item.insumo} - pedido {formatar_quantidade(item.quantidade)}, "
            f"a receber {formatar_quantidade(item.saldo)} {item.insumo.unidade}"
        )
        return campo

    def get_extra(self, request, obj=None, **kwargs):
        if obj is None and self.pedido_em_uso(request, obj):
            return len(self._itens_com_saldo(request, obj)) or 1
        return 1 if obj is None else 0

    def _itens_com_saldo(self, request, obj):
        pedido_id = self.pedido_em_uso(request, obj)
        itens = ItemPedido.objects.filter(pedido_id=pedido_id) if pedido_id else []
        return [item for item in itens if item.saldo > 0]


@admin.register(Recebimento)
class RecebimentoAdmin(admin.ModelAdmin):
    list_display = ["__str__", "pedido", "data", "numero_nota"]
    list_filter = ["pedido__obra"]
    search_fields = ["numero_nota", "pedido__pk"]
    inlines = [ItemRecebimentoInline]

    def get_readonly_fields(self, request, obj=None):
        return ["pedido"] if obj else []

    def add_view(self, request, form_url="", extra_context=None):
        if request.method == "GET" and not request.GET.get("pedido"):
            self.message_user(
                request,
                "Abra o pedido de compra e use o botão \"Registrar recebimento\".",
                messages.INFO,
            )
            url = reverse("admin:suprimentos_pedidocompra_changelist")
            return HttpResponseRedirect(f"{url}?status__exact={PedidoCompra.Status.APROVADO}")
        return super().add_view(request, form_url, extra_context)

    def get_changeform_initial_data(self, request):
        return {"pedido": request.GET.get("pedido")}

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "pedido":
            kwargs["queryset"] = PedidoCompra.objects.filter(
                status__in=[PedidoCompra.Status.APROVADO, PedidoCompra.Status.PARCIAL]
            ).select_related("fornecedor")
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def get_formset_kwargs(self, request, obj, inline, prefix):
        kwargs = super().get_formset_kwargs(request, obj, inline, prefix)
        if obj.pk is None and isinstance(inline, ItemRecebimentoInline):
            # Já lista os itens com saldo; basta digitar as quantidades recebidas.
            # Também no POST, para que as linhas deixadas em branco sejam ignoradas.
            kwargs["initial"] = [
                {"item_pedido": item.pk} for item in inline._itens_com_saldo(request, None)
            ]
        return kwargs

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        services.atualizar_status_pedido(form.instance.pedido)
        if not change:
            titulo = gerar_titulo_do_recebimento(form.instance)
            url = reverse("admin:financeiro_titulopagar_change", args=[titulo.pk])
            self.message_user(
                request,
                format_html('Título a pagar gerado: <a href="{}">{}</a>', url, titulo),
            )

    def delete_model(self, request, obj):
        pedido = obj.pedido
        super().delete_model(request, obj)
        services.atualizar_status_pedido(pedido)

    def delete_queryset(self, request, queryset):
        pedidos = {r.pedido for r in queryset.select_related("pedido")}
        super().delete_queryset(request, queryset)
        for pedido in pedidos:
            services.atualizar_status_pedido(pedido)
