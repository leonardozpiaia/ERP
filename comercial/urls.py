from django.urls import path

from . import views

app_name = "comercial"

urlpatterns = [
    path("espelho-de-vendas/", views.espelho, name="espelho"),
]
