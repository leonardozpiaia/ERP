from django.contrib import admin, messages
from django.urls import reverse
from django.utils.html import format_html

from .models import Etapa, ItemOrcamento, Orcamento


class EtapaInline(admin.TabularInline):
    model = Etapa
    extra = 1
    fields = ["codigo", "descricao", "pai", "editar_itens"]
    readonly_fields = ["editar_itens"]
    show_change_link = True

    @admin.display(description="itens")
    def editar_itens(self, obj):
        if not obj.pk:
            return "-"
        url = reverse("admin:orcamento_etapa_change", args=[obj.pk])
        return format_html('<a href="{}">Editar itens</a>', url)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        # Só oferece como "etapa pai" as etapas do próprio orçamento.
        if db_field.name == "pai":
            orcamento_id = request.resolver_match.kwargs.get("object_id")
            kwargs["queryset"] = Etapa.objects.filter(orcamento_id=orcamento_id)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


@admin.register(Orcamento)
class OrcamentoAdmin(admin.ModelAdmin):
    list_display = [
        "obra", "descricao", "versao", "data_base", "status",
        "custo_direto", "bdi_percentual", "preco_total", "ver_eap",
    ]
    list_filter = ["status", "obra"]
    search_fields = ["descricao", "obra__codigo", "obra__nome"]
    autocomplete_fields = ["obra"]
    readonly_fields = ["custo_direto", "valor_bdi", "preco_total", "ver_eap"]
    inlines = [EtapaInline]
    actions = ["atualizar_precos"]

    @admin.display(description="custo direto")
    def custo_direto(self, obj):
        return obj.custo_direto

    @admin.display(description="valor do BDI")
    def valor_bdi(self, obj):
        return obj.valor_bdi

    @admin.display(description="preço total")
    def preco_total(self, obj):
        return obj.preco_total

    @admin.display(description="EAP")
    def ver_eap(self, obj):
        if not obj.pk:
            return "-"
        url = reverse("orcamento:eap", args=[obj.pk])
        return format_html('<a href="{}">Ver EAP</a>', url)

    @admin.action(description="Atualizar preços dos itens com os valores atuais dos cadastros")
    def atualizar_precos(self, request, queryset):
        bloqueados = queryset.exclude(status=Orcamento.Status.RASCUNHO)
        if bloqueados.exists():
            self.message_user(
                request,
                "Só é possível atualizar preços de orçamentos em rascunho.",
                messages.ERROR,
            )
            return
        itens = ItemOrcamento.objects.filter(etapa__orcamento__in=queryset).select_related(
            "composicao", "insumo"
        )
        for item in itens:
            item.preco_unitario = item.preco_atual()
            item.save(update_fields=["preco_unitario"])
        self.message_user(request, f"{itens.count()} item(ns) atualizado(s).")


class ItemOrcamentoInline(admin.TabularInline):
    model = ItemOrcamento
    extra = 1
    autocomplete_fields = ["composicao", "insumo"]
    fields = ["composicao", "insumo", "quantidade", "preco_unitario", "unidade", "total"]
    readonly_fields = ["unidade", "total"]

    @admin.display(description="unidade")
    def unidade(self, obj):
        return obj.unidade if obj.pk else "-"

    @admin.display(description="total")
    def total(self, obj):
        return obj.total if obj.pk else "-"


@admin.register(Etapa)
class EtapaAdmin(admin.ModelAdmin):
    list_display = ["codigo", "descricao", "orcamento", "pai"]
    list_filter = ["orcamento"]
    search_fields = ["codigo", "descricao"]
    autocomplete_fields = ["orcamento", "pai"]
    inlines = [ItemOrcamentoInline]
