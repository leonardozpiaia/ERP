from django.urls import path

from . import views

app_name = "orcamento"

urlpatterns = [
    path("<int:pk>/eap/", views.eap, name="eap"),
    path("importar/", views.importar_planilha, name="importar"),
    path("importar/modelo.xlsx", views.modelo_planilha, name="modelo_planilha"),
]
