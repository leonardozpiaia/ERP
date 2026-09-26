from django.contrib import admin
from django.utils import timezone

from . import marca
from .painel import indicadores, saudacao


class ErpAdminSite(admin.AdminSite):
    site_header = f"{marca.NOME} · {marca.SISTEMA}"
    site_title = f"{marca.SISTEMA} {marca.NOME}"
    index_title = "Painel"

    def index(self, request, extra_context=None):
        contexto = {
            "indicadores": indicadores(request.user),
            "saudacao": saudacao(timezone.localtime()),
            "hoje": timezone.localdate(),
            **(extra_context or {}),
        }
        return super().index(request, contexto)
