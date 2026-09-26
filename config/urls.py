from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

from .anexos import baixar
from .views import saude

urlpatterns = [
    path("", RedirectView.as_view(url="/admin/", permanent=False)),
    path("admin/", admin.site.urls),
    path("saude/", saude, name="saude"),
    path("anexos/<path:caminho>", baixar, name="anexo"),
    path("orcamentos/", include("orcamento.urls")),
    path("suprimentos/", include("suprimentos.urls")),
    path("financeiro/", include("financeiro.urls")),
    path("comercial/", include("comercial.urls")),
    path("contratos/", include("contratos.urls")),
]
