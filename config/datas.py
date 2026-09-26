import calendar
import datetime


def dia_do_mes(ano, mes, dia):
    """Data com o dia pedido; se o mês não tem esse dia (31 em abril), usa o último dia."""
    return datetime.date(ano, mes, min(dia, calendar.monthrange(ano, mes)[1]))


def somar_meses(data, meses, dia=None):
    """Mesma data `meses` depois (ou no `dia` indicado), respeitando o fim do mês."""
    total = data.month - 1 + meses
    return dia_do_mes(data.year + total // 12, total % 12 + 1, dia or data.day)


def fim_do_mes(data):
    return data.replace(day=calendar.monthrange(data.year, data.month)[1])
