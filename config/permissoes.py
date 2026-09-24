from functools import wraps

from django.contrib.admin.views.decorators import staff_member_required
from django.core.exceptions import PermissionDenied


def requer(permissao):
    """Tela própria do ERP: exige login no painel e a permissão indicada."""

    def decorador(view):
        @wraps(view)
        def verificada(request, *args, **kwargs):
            if not request.user.has_perm(permissao):
                raise PermissionDenied
            return view(request, *args, **kwargs)

        return staff_member_required(verificada)

    return decorador
