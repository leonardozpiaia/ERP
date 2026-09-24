from django.contrib import admin

from .models import Obra


@admin.register(Obra)
class ObraAdmin(admin.ModelAdmin):
    list_display = ["codigo", "nome", "empresa", "cidade", "uf", "status", "data_inicio"]
    list_filter = ["status", "empresa", "uf"]
    search_fields = ["codigo", "nome", "cidade"]
    autocomplete_fields = ["empresa"]
