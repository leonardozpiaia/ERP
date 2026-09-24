from django.urls import path

from . import views

app_name = "orcamento"

urlpatterns = [
    path("<int:pk>/eap/", views.eap, name="eap"),
]
