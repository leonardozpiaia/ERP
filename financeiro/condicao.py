"""Condição de pagamento: do texto digitado às datas de vencimento.

Formatos aceitos (maiúsculas, acentos e a palavra "dias" são indiferentes):

- "à vista" ou em branco ........ 1 parcela no dia da nota
- "30", "28 dias", "28 ddl" ..... 1 parcela N dias depois da nota
- "30/60/90", "0/30/60" ......... uma parcela para cada prazo, em dias
- "3x", "3 vezes", "3 parcelas" . 3 parcelas a cada 30 dias (30/60/90)
- "dia 10" ...................... 1 parcela no próximo dia 10
- "3x dia 10" ................... 3 parcelas mensais, todo dia 10

Com o "1º vencimento" preenchido, a primeira parcela vence nessa data e as
demais mantêm os intervalos da condição (mensais para "3x" e "dia 10").
"""

import datetime
import re
import unicodedata

from config.datas import dia_do_mes, somar_meses

MAXIMO_PARCELAS = 120
MAXIMO_DIAS = 3650


class CondicaoInvalida(ValueError):
    pass


def _normalizar(texto):
    texto = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode().lower()
    return " ".join(texto.split())


def interpretar(condicao):
    """Descrição estruturada da condição: ("dias", [0, 30]) ou ("mensal", (n, dia ou None))."""
    texto = _normalizar(condicao)
    if texto in {"", "a vista", "avista", "vista", "a vista.", "antecipado", "pagamento a vista"}:
        return ("dias", [0])

    vezes = re.search(r"\b(\d+)\s*(x|vezes|parcelas?)\b", texto)
    dia = re.search(r"\bdia\s*(\d{1,2})\b", texto)
    if vezes or dia:
        n = int(vezes.group(1)) if vezes else 1
        dia_fixo = int(dia.group(1)) if dia else None
        if not 1 <= n <= MAXIMO_PARCELAS:
            raise CondicaoInvalida(f"Número de parcelas fora do limite (1 a {MAXIMO_PARCELAS}).")
        if dia_fixo is not None and not 1 <= dia_fixo <= 31:
            raise CondicaoInvalida("O dia do vencimento deve estar entre 1 e 31.")
        restante = re.sub(r"\b\d+\s*(x|vezes|parcelas?)\b|\bdia\s*\d{1,2}\b", " ", texto)
        if re.search(r"\d", restante):
            raise CondicaoInvalida(
                "Não misture prazos em dias com parcelas (\"3x\") ou dia fixo (\"dia 10\"). "
                "Ex.: \"30/60/90\", \"3x\" ou \"3x dia 10\"."
            )
        return ("mensal", (n, dia_fixo))

    numeros = [int(n) for n in re.findall(r"\d+", texto)]
    if not numeros:
        raise CondicaoInvalida(
            "Não entendi a condição de pagamento. Use prazos em dias (\"30/60/90\"), "
            "parcelas (\"3x\"), dia fixo (\"dia 10\") ou \"à vista\"."
        )
    if len(numeros) > MAXIMO_PARCELAS:
        raise CondicaoInvalida(f"Parcelas demais (máximo {MAXIMO_PARCELAS}).")
    if any(n > MAXIMO_DIAS for n in numeros):
        raise CondicaoInvalida(f"Prazo maior que {MAXIMO_DIAS} dias.")
    if numeros != sorted(numeros):
        raise CondicaoInvalida("Os prazos devem estar em ordem crescente (ex.: 30/60/90).")
    return ("dias", numeros)


def proximo_dia(data, dia):
    """Próxima data com o dia do mês pedido, depois de `data`."""
    candidato = dia_do_mes(data.year, data.month, dia)
    return candidato if candidato > data else somar_meses(data.replace(day=1), 1, dia)


def vencimentos(condicao, data_base, primeiro_vencimento=None):
    """Datas de vencimento das parcelas. `data_base` é a data da nota (recebimento)."""
    tipo, valor = interpretar(condicao)
    if tipo == "dias":
        if primeiro_vencimento:
            return [primeiro_vencimento + datetime.timedelta(days=d - valor[0]) for d in valor]
        return [data_base + datetime.timedelta(days=d) for d in valor]

    n, dia = valor
    if primeiro_vencimento:
        return [somar_meses(primeiro_vencimento, k) for k in range(n)]
    if dia:
        primeira = proximo_dia(data_base, dia)
        return [somar_meses(primeira, k, dia) for k in range(n)]
    return [data_base + datetime.timedelta(days=30 * (k + 1)) for k in range(n)]


def descrever(datas):
    """'3 parcelas: 09/11/2026, 09/12/2026 e 08/01/2027'"""
    textos = [d.strftime("%d/%m/%Y") for d in datas]
    if len(textos) == 1:
        return f"1 parcela: {textos[0]}"
    if len(textos) > 6:
        return f"{len(textos)} parcelas: {textos[0]}, {textos[1]} ... {textos[-1]}"
    return f"{len(textos)} parcelas: {', '.join(textos[:-1])} e {textos[-1]}"


def previa(condicao, data_base, primeiro_vencimento=None):
    """(True, 'se a nota chegar em ...: 3 parcelas: ...') ou (False, mensagem de erro)."""
    try:
        datas = vencimentos(condicao, data_base, primeiro_vencimento)
    except CondicaoInvalida as erro:
        return False, str(erro)
    return True, f"Se a nota chegar em {data_base:%d/%m/%Y}: {descrever(datas)}."
