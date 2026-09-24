from .versao import VERSAO


def versao(request):
    return {"versao_erp": VERSAO}
