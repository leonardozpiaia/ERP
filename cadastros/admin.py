from django.contrib import admin

from .models import Composicao, ComposicaoItem, Empresa, Insumo, UnidadeMedida

admin.site.site_header = "ERP Obras"
admin.site.site_title = "ERP Obras"
admin.site.index_title = "Painel"


@admin.register(Empresa)
class EmpresaAdmin(admin.ModelAdmin):
    list_display = ["razao_social", "nome_fantasia", "cnpj", "ativa"]
    list_filter = ["ativa"]
    search_fields = ["razao_social", "nome_fantasia", "cnpj"]


@admin.register(UnidadeMedida)
class UnidadeMedidaAdmin(admin.ModelAdmin):
    list_display = ["sigla", "descricao"]
    search_fields = ["sigla", "descricao"]


@admin.register(Insumo)
class InsumoAdmin(admin.ModelAdmin):
    list_display = ["codigo", "descricao", "tipo", "unidade", "preco_unitario", "ativo"]
    list_filter = ["tipo", "ativo"]
    search_fields = ["codigo", "descricao"]
    autocomplete_fields = ["unidade"]


class ComposicaoItemInline(admin.TabularInline):
    model = ComposicaoItem
    extra = 1
    autocomplete_fields = ["insumo"]
    readonly_fields = ["custo"]

    @admin.display(description="custo")
    def custo(self, obj):
        return obj.custo if obj.pk else "-"


@admin.register(Composicao)
class ComposicaoAdmin(admin.ModelAdmin):
    list_display = ["codigo", "descricao", "unidade", "custo_unitario", "ativa"]
    list_filter = ["ativa"]
    search_fields = ["codigo", "descricao"]
    autocomplete_fields = ["unidade"]
    readonly_fields = ["custo_unitario"]
    inlines = [ComposicaoItemInline]

    @admin.display(description="custo unitário")
    def custo_unitario(self, obj):
        return obj.custo_unitario if obj.pk else "-"
