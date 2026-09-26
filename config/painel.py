"""Indicadores da página inicial. Cada um só aparece para quem tem a permissão."""

import datetime

from django.db.models import Count, Q
from django.urls import reverse


def _card(titulo, valor, detalhe, url, estado="neutro"):
    return {"titulo": titulo, "valor": valor, "detalhe": detalhe, "url": url, "estado": estado}


def indicadores(user):
    from comercial.models import Unidade
    from financeiro.admin import moeda
    from contratos.models import Medicao
    from financeiro.models import ContaBancaria, ParcelaPagar, ParcelaReceber
    from suprimentos.models import PedidoCompra, SolicitacaoCompra

    hoje = datetime.date.today()
    cards = []

    def soma(parcelas):
        total = sum((p.saldo_aberto for p in parcelas), 0)
        return total, len(parcelas)

    if user.has_perm("financeiro.view_parcelapagar"):
        abertas = ParcelaPagar.objects.em_aberto()
        vencidas, n = soma(list(abertas.filter(vencimento__lt=hoje)))
        url = reverse("admin:financeiro_parcelapagar_changelist")
        cards.append(_card(
            "A pagar vencido", f"R$ {moeda(vencidas)}", f"{n} parcela(s)",
            f"{url}?situacao=vencidas", "alerta" if n else "ok",
        ))
        semana, n = soma(list(abertas.filter(vencimento__gte=hoje, vencimento__lte=hoje + datetime.timedelta(days=7))))
        cards.append(_card(
            "A pagar nos próximos 7 dias", f"R$ {moeda(semana)}", f"{n} parcela(s)",
            f"{url}?situacao=7dias", "atencao" if n else "neutro",
        ))
    if user.has_perm("financeiro.view_parcelareceber"):
        vencidas, n = soma(list(ParcelaReceber.objects.em_aberto().filter(vencimento__lt=hoje)))
        cards.append(_card(
            "A receber vencido", f"R$ {moeda(vencidas)}", f"{n} parcela(s)",
            reverse("admin:financeiro_parcelareceber_changelist") + "?situacao=vencidas",
            "alerta" if n else "ok",
        ))
    if user.has_perm("financeiro.view_contabancaria"):
        contas = list(ContaBancaria.objects.filter(ativa=True))
        cards.append(_card(
            "Saldo em bancos", f"R$ {moeda(sum((c.saldo_atual for c in contas), 0))}",
            f"{len(contas)} conta(s) ativa(s)", reverse("admin:financeiro_contabancaria_changelist"),
        ))
    if user.has_perm("suprimentos.view_solicitacaocompra"):
        n = SolicitacaoCompra.objects.filter(status=SolicitacaoCompra.Status.ABERTA).count()
        cards.append(_card(
            "Solicitações para aprovar", str(n), "solicitações de compra abertas",
            reverse("admin:suprimentos_solicitacaocompra_changelist") + "?status__exact=ABERTA",
            "atencao" if n else "ok",
        ))
    if user.has_perm("suprimentos.view_pedidocompra"):
        n = PedidoCompra.objects.filter(status=PedidoCompra.Status.RASCUNHO).count()
        cards.append(_card(
            "Pedidos para aprovar", str(n), "pedidos de compra em rascunho",
            reverse("admin:suprimentos_pedidocompra_changelist") + "?status__exact=RASCUNHO",
            "atencao" if n else "ok",
        ))
    if user.has_perm("contratos.view_medicao"):
        n = Medicao.objects.filter(status=Medicao.Status.RASCUNHO).count()
        cards.append(_card(
            "Medições para aprovar", str(n), "medições em elaboração",
            reverse("admin:contratos_medicao_changelist") + "?status__exact=RASC",
            "atencao" if n else "ok",
        ))
    if user.has_perm("comercial.view_unidade"):
        dados = Unidade.objects.aggregate(total=Count("pk"), vendidas=Count("pk", filter=Q(status="VEND")))
        if dados["total"]:
            percentual = round(100 * dados["vendidas"] / dados["total"])
            cards.append(_card(
                "Unidades vendidas", f"{percentual}%", f"{dados['vendidas']} de {dados['total']} unidades",
                reverse("comercial:espelho"),
            ))
    return cards


def saudacao(agora=None):
    hora = (agora or datetime.datetime.now()).hour
    if hora < 12:
        return "Bom dia"
    return "Boa tarde" if hora < 18 else "Boa noite"
