from django.urls import path

from . import views

app_name = "financeiro"

urlpatterns = [
    path("baixa-em-lote/", views.baixa_lote, name="baixa_lote"),
    path("fluxo-de-caixa/", views.fluxo_caixa, name="fluxo_caixa"),
]
