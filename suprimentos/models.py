"""Suprimentos: solicitação -> cotação -> pedido de compra -> recebimento.

Toda compra pertence a uma obra e pode ser apropriada a uma etapa do
orçamento dessa obra, o que permite comparar o orçado com o comprado.
"""

import datetime
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import F, Sum

from cadastros.models import Fornecedor, Insumo
from config.anexos import caminho_nota, validar_extensao_nota, validar_tamanho
from financeiro.condicao import CondicaoInvalida
from financeiro.condicao import interpretar as interpretar_condicao
from obras.models import Obra
from orcamento.models import Etapa, arredondar

QUANTIDADE = {"max_digits": 14, "decimal_places": 4, "validators": [MinValueValidator(Decimal("0.0001"))]}
PRECO = {"max_digits": 14, "decimal_places": 4, "validators": [MinValueValidator(Decimal("0"))]}


def formatar_quantidade(valor):
    """1234.5000 -> "1.234,5" (sem zeros à direita, no padrão brasileiro)."""
    texto = f"{valor:,.4f}".rstrip("0").rstrip(".")
    return texto.replace(",", "_").replace(".", ",").replace("_", ".")


def pai(instancia, campo):
    """Objeto relacionado, ou None se ainda não foi definido.

    Nos formulários do admin os itens são validados antes de o cabeçalho ser
    salvo; o objeto pai já está atribuído, mas ainda não tem pk.
    """
    try:
        return getattr(instancia, campo)
    except models.ObjectDoesNotExist:
        return None


def validar_condicao(condicao):
    try:
        interpretar_condicao(condicao)
    except CondicaoInvalida as erro:
        raise ValidationError({"condicao_pagamento": str(erro)}) from None


def validar_etapa_da_obra(etapa, obra_id):
    if etapa is not None and etapa.orcamento.obra_id != obra_id:
        raise ValidationError({"etapa": "A etapa deve ser de um orçamento da mesma obra."})


class SolicitacaoCompra(models.Model):
    class Status(models.TextChoices):
        ABERTA = "ABERTA", "Aberta"
        APROVADA = "APROVADA", "Aprovada"
        ATENDIDA = "ATENDIDA", "Atendida"
        CANCELADA = "CANCELADA", "Cancelada"

    obra = models.ForeignKey(
        Obra, on_delete=models.PROTECT, related_name="solicitacoes", verbose_name="obra"
    )
    data = models.DateField("data", default=datetime.date.today)
    solicitante = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        verbose_name="solicitante",
    )
    status = models.CharField(
        "status", max_length=10, choices=Status.choices, default=Status.ABERTA
    )
    observacao = models.TextField("observação", blank=True)

    class Meta:
        verbose_name = "solicitação de compra"
        verbose_name_plural = "solicitações de compra"
        ordering = ["-pk"]

    def __str__(self):
        return f"SC {self.pk} - {self.obra.codigo}"

    def editavel(self):
        return self.status == self.Status.ABERTA


class ItemSolicitacao(models.Model):
    solicitacao = models.ForeignKey(
        SolicitacaoCompra,
        on_delete=models.CASCADE,
        related_name="itens",
        verbose_name="solicitação",
    )
    insumo = models.ForeignKey(Insumo, on_delete=models.PROTECT, verbose_name="insumo")
    etapa = models.ForeignKey(
        Etapa,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        verbose_name="etapa (apropriação)",
    )
    quantidade = models.DecimalField("quantidade", **QUANTIDADE)
    data_necessidade = models.DateField("necessário até", null=True, blank=True)

    class Meta:
        verbose_name = "item da solicitação"
        verbose_name_plural = "itens da solicitação"

    def __str__(self):
        return f"{self.insumo} ({formatar_quantidade(self.quantidade)} {self.insumo.unidade})"

    def clean(self):
        solicitacao = pai(self, "solicitacao")
        if solicitacao is not None:
            validar_etapa_da_obra(self.etapa, solicitacao.obra_id)

    @property
    def quantidade_pedida(self):
        total = self.itens_pedido.exclude(
            pedido__status=PedidoCompra.Status.CANCELADO
        ).aggregate(total=Sum("quantidade"))["total"]
        return total or Decimal("0")

    @property
    def saldo(self):
        return max(self.quantidade - self.quantidade_pedida, Decimal("0"))


class Cotacao(models.Model):
    class Status(models.TextChoices):
        ABERTA = "ABERTA", "Aberta"
        CONCLUIDA = "CONCLUIDA", "Concluída"
        CANCELADA = "CANCELADA", "Cancelada"

    data = models.DateField("data", default=datetime.date.today)
    prazo_resposta = models.DateField("prazo de resposta", null=True, blank=True)
    status = models.CharField(
        "status", max_length=10, choices=Status.choices, default=Status.ABERTA
    )
    observacao = models.TextField("observação", blank=True)

    class Meta:
        verbose_name = "cotação"
        verbose_name_plural = "cotações"
        ordering = ["-pk"]

    def __str__(self):
        return f"Cotação {self.pk}"

    def editavel(self):
        return self.status == self.Status.ABERTA


class ItemCotacao(models.Model):
    """Item de solicitação que está sendo cotado."""

    cotacao = models.ForeignKey(
        Cotacao, on_delete=models.CASCADE, related_name="itens", verbose_name="cotação"
    )
    item_solicitacao = models.ForeignKey(
        ItemSolicitacao,
        on_delete=models.PROTECT,
        related_name="itens_cotacao",
        verbose_name="item da solicitação",
    )
    quantidade = models.DecimalField("quantidade", **QUANTIDADE)

    class Meta:
        verbose_name = "item da cotação"
        verbose_name_plural = "itens da cotação"
        constraints = [
            models.UniqueConstraint(
                fields=["cotacao", "item_solicitacao"], name="cotacao_item_unico"
            )
        ]

    def __str__(self):
        return str(self.item_solicitacao.insumo)


class PropostaFornecedor(models.Model):
    """Resposta de um fornecedor para uma cotação."""

    cotacao = models.ForeignKey(
        Cotacao, on_delete=models.CASCADE, related_name="propostas", verbose_name="cotação"
    )
    fornecedor = models.ForeignKey(
        Fornecedor, on_delete=models.PROTECT, verbose_name="fornecedor"
    )
    prazo_entrega_dias = models.PositiveIntegerField(
        "prazo de entrega (dias)", null=True, blank=True
    )
    condicao_pagamento = models.CharField(
        "condição de pagamento", max_length=100, blank=True,
        help_text="Ex.: \"30/60/90\", \"28 dias\", \"3x\", \"dia 10\" ou \"à vista\".",
    )

    class Meta:
        verbose_name = "proposta de fornecedor"
        verbose_name_plural = "propostas de fornecedores"
        constraints = [
            models.UniqueConstraint(
                fields=["cotacao", "fornecedor"], name="cotacao_fornecedor_unico"
            )
        ]

    def __str__(self):
        return f"{self.fornecedor} - {self.cotacao}"

    def clean(self):
        validar_condicao(self.condicao_pagamento)

    @property
    def total(self):
        total = self.precos.aggregate(
            total=Sum(F("preco_unitario") * F("item__quantidade"))
        )["total"]
        return arredondar(total)


class PrecoCotado(models.Model):
    proposta = models.ForeignKey(
        PropostaFornecedor,
        on_delete=models.CASCADE,
        related_name="precos",
        verbose_name="proposta",
    )
    item = models.ForeignKey(
        ItemCotacao, on_delete=models.CASCADE, related_name="precos", verbose_name="item"
    )
    preco_unitario = models.DecimalField("preço unitário", **PRECO)

    class Meta:
        verbose_name = "preço cotado"
        verbose_name_plural = "preços cotados"
        constraints = [
            models.UniqueConstraint(fields=["proposta", "item"], name="preco_proposta_item_unico")
        ]

    def clean(self):
        proposta, item = pai(self, "proposta"), pai(self, "item")
        if proposta and item and proposta.cotacao_id != item.cotacao_id:
            raise ValidationError("O item e a proposta devem ser da mesma cotação.")


class PedidoCompra(models.Model):
    class Status(models.TextChoices):
        RASCUNHO = "RASCUNHO", "Rascunho"
        APROVADO = "APROVADO", "Aprovado"
        PARCIAL = "PARCIAL", "Entregue parcialmente"
        ENTREGUE = "ENTREGUE", "Entregue"
        CANCELADO = "CANCELADO", "Cancelado"

    obra = models.ForeignKey(
        Obra, on_delete=models.PROTECT, related_name="pedidos", verbose_name="obra"
    )
    fornecedor = models.ForeignKey(
        Fornecedor, on_delete=models.PROTECT, related_name="pedidos", verbose_name="fornecedor"
    )
    cotacao = models.ForeignKey(
        Cotacao,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="pedidos",
        verbose_name="cotação de origem",
    )
    data = models.DateField("data", default=datetime.date.today)
    previsao_entrega = models.DateField("previsão de entrega", null=True, blank=True)
    condicao_pagamento = models.CharField(
        "condição de pagamento", max_length=100, blank=True,
        help_text="Prazos contados da data da nota: \"30/60/90\", \"28 dias\", \"3x\", \"dia 10\", "
                  "\"3x dia 10\" ou \"à vista\".",
    )
    primeiro_vencimento = models.DateField(
        "1º vencimento", null=True, blank=True,
        help_text="Opcional. Data da 1ª parcela da primeira nota; as demais seguem os intervalos da condição.",
    )
    status = models.CharField(
        "status", max_length=10, choices=Status.choices, default=Status.RASCUNHO
    )
    observacao = models.TextField("observação", blank=True)

    class Meta:
        verbose_name = "pedido de compra"
        verbose_name_plural = "pedidos de compra"
        ordering = ["-pk"]

    def __str__(self):
        return f"PC {self.pk} - {self.fornecedor}"

    @property
    def total(self):
        total = self.itens.aggregate(total=Sum(F("quantidade") * F("preco_unitario")))["total"]
        return arredondar(total)

    def editavel(self):
        return self.status == self.Status.RASCUNHO

    def clean(self):
        validar_condicao(self.condicao_pagamento)

    @property
    def pode_receber(self):
        return self.status in {self.Status.APROVADO, self.Status.PARCIAL}


class ItemPedido(models.Model):
    pedido = models.ForeignKey(
        PedidoCompra, on_delete=models.CASCADE, related_name="itens", verbose_name="pedido"
    )
    insumo = models.ForeignKey(Insumo, on_delete=models.PROTECT, verbose_name="insumo")
    etapa = models.ForeignKey(
        Etapa,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        verbose_name="etapa (apropriação)",
    )
    item_solicitacao = models.ForeignKey(
        ItemSolicitacao,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="itens_pedido",
        verbose_name="item da solicitação",
    )
    quantidade = models.DecimalField("quantidade", **QUANTIDADE)
    preco_unitario = models.DecimalField("preço unitário", **PRECO)

    class Meta:
        verbose_name = "item do pedido"
        verbose_name_plural = "itens do pedido"

    def __str__(self):
        return f"{self.insumo} ({formatar_quantidade(self.quantidade)} {self.insumo.unidade})"

    def clean(self):
        pedido = pai(self, "pedido")
        if pedido is not None:
            validar_etapa_da_obra(self.etapa, pedido.obra_id)

    @property
    def total(self):
        return arredondar(self.quantidade * self.preco_unitario)

    @property
    def quantidade_recebida(self):
        total = self.recebimentos.aggregate(total=Sum("quantidade"))["total"]
        return total or Decimal("0")

    @property
    def saldo(self):
        return max(self.quantidade - self.quantidade_recebida, Decimal("0"))


class Recebimento(models.Model):
    """Entrada de material na obra, normalmente vinculada a uma nota fiscal."""

    pedido = models.ForeignKey(
        PedidoCompra,
        on_delete=models.PROTECT,
        related_name="recebimentos",
        verbose_name="pedido",
    )
    data = models.DateField("data", default=datetime.date.today)
    numero_nota = models.CharField("nº da nota fiscal", max_length=30, blank=True)
    arquivo_nota = models.FileField(
        "arquivo da nota fiscal",
        upload_to=caminho_nota,
        blank=True,
        max_length=255,
        validators=[validar_extensao_nota, validar_tamanho],
        help_text="PDF, XML, JPG ou PNG, até 10 MB. Pode ser anexado depois.",
    )
    observacao = models.TextField("observação", blank=True)

    class Meta:
        verbose_name = "recebimento"
        verbose_name_plural = "recebimentos"
        ordering = ["-data", "-pk"]

    def __str__(self):
        nota = f" NF {self.numero_nota}" if self.numero_nota else ""
        return f"Receb. {self.pk} - PC {self.pedido_id}{nota}"

    def clean(self):
        if self.pedido_id and not self.pk and not self.pedido.pode_receber:
            raise ValidationError(
                {"pedido": "Só é possível receber pedidos aprovados ou entregues parcialmente."}
            )
        if self.pedido_id:
            try:
                interpretar_condicao(self.pedido.condicao_pagamento)
            except CondicaoInvalida as erro:
                raise ValidationError(
                    {"pedido": f"Corrija a condição de pagamento do pedido antes de receber: {erro}"}
                ) from None


class ItemRecebimento(models.Model):
    recebimento = models.ForeignKey(
        Recebimento, on_delete=models.CASCADE, related_name="itens", verbose_name="recebimento"
    )
    item_pedido = models.ForeignKey(
        ItemPedido,
        on_delete=models.PROTECT,
        related_name="recebimentos",
        verbose_name="item do pedido",
    )
    quantidade = models.DecimalField("quantidade", **QUANTIDADE)

    class Meta:
        verbose_name = "item recebido"
        verbose_name_plural = "itens recebidos"

    def __str__(self):
        return f"{self.item_pedido.insumo} - {formatar_quantidade(self.quantidade)} {self.item_pedido.insumo.unidade}"

    def clean(self):
        recebimento = pai(self, "recebimento")
        item_pedido = pai(self, "item_pedido")
        if recebimento is None or item_pedido is None or not self.quantidade:
            return
        if item_pedido.pedido_id != recebimento.pedido_id:
            raise ValidationError({"item_pedido": "O item não pertence a este pedido."})
        ja_recebido = (
            item_pedido.recebimentos.exclude(pk=self.pk).aggregate(total=Sum("quantidade"))[
                "total"
            ]
            or Decimal("0")
        )
        saldo = item_pedido.quantidade - ja_recebido
        if self.quantidade > saldo:
            raise ValidationError(
                {"quantidade": f"Quantidade maior que o saldo a receber ({saldo:f})."}
            )
