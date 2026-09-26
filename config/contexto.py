from . import marca
from .versao import VERSAO


def versao(request):
    return {"versao_erp": VERSAO, "marca": marca}
