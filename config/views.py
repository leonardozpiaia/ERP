from django.db import connection
from django.http import JsonResponse


def saude(request):
    """Verificação de funcionamento para o servidor e o monitoramento: app e banco respondem."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except Exception:
        return JsonResponse({"status": "erro", "banco": "indisponível"}, status=503)
    return JsonResponse({"status": "ok"})
