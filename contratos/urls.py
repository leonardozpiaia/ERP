from django.urls import path

from . import views

app_name = "contratos"

urlpatterns = [
    path("medicoes/<int:pk>/boletim/", views.boletim, name="boletim"),
    path("retencoes/", views.retencoes, name="retencoes"),
]
