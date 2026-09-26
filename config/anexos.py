"""Anexos protegidos: só abrem para usuários logados com a permissão da pasta."""

import mimetypes
import uuid

from django.conf import settings
from django.contrib.admin.views.decorators import staff_member_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.validators import FileExtensionValidator
from django.http import FileResponse, Http404
from django.utils import timezone
from django.utils._os import safe_join

EXTENSOES_NOTA = ["pdf", "xml", "jpg", "jpeg", "png"]
TAMANHO_MAXIMO = 10 * 1024 * 1024  # 10 MB

# Pasta do anexo -> permissão necessária para abri-lo.
PERMISSOES = {
    "notas": "suprimentos.view_recebimento",
}

validar_extensao_nota = FileExtensionValidator(
    EXTENSOES_NOTA, message="Envie a nota em PDF, XML, JPG ou PNG."
)


def validar_tamanho(arquivo):
    if arquivo.size > TAMANHO_MAXIMO:
        raise ValidationError("Arquivo maior que 10 MB.")


def caminho_nota(instancia, nome):
    """notas/2026/09/1a2b3c4d_nota-12345.pdf (o prefixo evita sobrescrever arquivos de mesmo nome)."""
    return f"notas/{timezone.localdate():%Y/%m}/{uuid.uuid4().hex[:8]}_{nome}"


@staff_member_required
def baixar(request, caminho):
    pasta = caminho.split("/", 1)[0]
    permissao = PERMISSOES.get(pasta)
    if permissao is None:
        raise Http404
    if not request.user.has_perm(permissao):
        raise PermissionDenied
    try:
        arquivo = safe_join(settings.MEDIA_ROOT, caminho)
    except Exception:
        raise Http404 from None
    try:
        resposta = FileResponse(open(arquivo, "rb"))
    except (FileNotFoundError, IsADirectoryError):
        raise Http404 from None
    tipo, _ = mimetypes.guess_type(arquivo)
    resposta["Content-Type"] = tipo or "application/octet-stream"
    resposta["X-Content-Type-Options"] = "nosniff"
    resposta["Content-Security-Policy"] = "sandbox"
    return resposta
