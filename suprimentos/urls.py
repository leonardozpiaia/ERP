from django.urls import path

from . import views

app_name = "suprimentos"

urlpatterns = [
    path("cotacoes/<int:pk>/mapa/", views.mapa_cotacao, name="mapa_cotacao"),
    path("orcamentos/<int:pk>/orcado-comprado/", views.orcado_comprado, name="orcado_comprado"),
]
