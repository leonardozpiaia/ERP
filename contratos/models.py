"""Contratos de empreitada e medições.

O contrato lista os serviços (itens) com quantidade e preço, apropriados às
etapas do orçamento. Cada medição informa o quanto foi executado no período;
ao ser aprovada, gera o título a pagar ao empreiteiro pelo valor líquido
(bruto menos caução, INSS e ISS retidos).
"""

import datetime
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import F, Max, Sum

from cadastros.models import Fornecedor, UnidadeMedida
from financeiro.models import CategoriaFinanceira, Titulo
from obras.models import Obra
from orcamento.models import Etapa, arredondar
from suprimentos.models import pai, validar_etapa_da_obra

ZERO = Decimal("0")
QUANTIDADE = {"max_digits": 14, "decimal_places": 4}
PERCENTUAL = {
    "max_digits": 5,
    "decimal_places": 2,
    "default": ZERO,
    "validators": [MinValueValidator(ZERO), MaxValueValidator(Decimal("100"))],
}


class ContratoServico(models.Model):
    class Status(models.TextChoices):
        RASCUNHO = "RASC", "Em elaboração"
        ATIVO = "ATIVO", "Ativo"
        ENCERRADO = "ENC", "Encerrado"
        CANCELADO = "CANC", "Cancelado"

    obra = models.ForeignKey(
        Obra, on_delete=models.PROTECT, related_name="contratos_servico", verbose_name="obra"
    )
    fornecedor = models.ForeignKey(
        Fornecedor, on_delete=models.PROTECT, related_name="contratos_servico", verbose_name="empreiteiro"
    )
    objeto = models.CharField("objeto", max_length=200, help_text="Ex.: Execução de alvenaria da Torre A")
    data = models.DateField("data do contrato", default=datetime.date.today)
    data_termino = models.DateField("término previsto", null=True, blank=True)
    retencao_caucao = models.DecimalField(
        "caução / retenção técnica (%)", help_text="Retida em cada medição e devolvida no encerramento.",
        **PERCENTUAL,
    )
    retencao_inss = models.DecimalField("INSS retido (%)", **PERCENTUAL)
    retencao_iss = models.DecimalField("ISS retido (%)", **PERCENTUAL)
    prazo_pagamento_dias = models.PositiveIntegerField(
        "prazo de pagamento (dias)", default=15, help_text="Contados a partir da data da medição."
    )
    categoria = models.ForeignKey(
        CategoriaFinanceira,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        limit_choices_to={"tipo": CategoriaFinanceira.Tipo.DESPESA},
        verbose_name="categoria financeira",
    )
    status = models.CharField(
        "situação", max_length=5, choices=Status.choices, default=Status.RASCUNHO
    )
    titulo_caucao = models.OneToOneField(
        Titulo,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="contrato_caucao",
        verbose_name="título de devolução da caução",
    )
    observacao = models.TextField("observação", blank=True)

    class Meta:
        verbose_name = "contrato de empreitada"
        verbose_name_plural = "contratos de empreitada"
        ordering = ["-data", "-pk"]

    def __str__(self):
        return f"CT {self.pk} - {self.fornecedor} - {self.objeto}"

    def editavel(self):
        return self.status == self.Status.RASCUNHO

    def aceita_aditivo(self):
        return self.status in {self.Status.RASCUNHO, self.Status.ATIVO}

    @property
    def valor_total(self):
        total = self.itens.aggregate(total=Sum(F("quantidade") * F("preco_unitario")))["total"]
        return arredondar(total)

    def medicoes_aprovadas(self):
        return self.medicoes.filter(status=Medicao.Status.APROVADA)

    @property
    def valor_medido(self):
        return sum((m.valor_bruto for m in self.medicoes_aprovadas()), ZERO)

    @property
    def caucao_retida(self):
        return sum((m.valor_caucao for m in self.medicoes_aprovadas()), ZERO)

    @property
    def percentual_executado(self):
        total = self.valor_total
        return (self.valor_medido / total * 100) if total else ZERO


class ItemContrato(models.Model):
    contrato = models.ForeignKey(
        ContratoServico, on_delete=models.CASCADE, related_name="itens", verbose_name="contrato"
    )
    descricao = models.CharField("serviço", max_length=255)
    unidade = models.ForeignKey(UnidadeMedida, on_delete=models.PROTECT, verbose_name="unidade")
    quantidade = models.DecimalField(
        "quantidade contratada", validators=[MinValueValidator(Decimal("0.0001"))], **QUANTIDADE
    )
    preco_unitario = models.DecimalField(
        "preço unitário", max_digits=14, decimal_places=4, validators=[MinValueValidator(ZERO)]
    )
    etapa = models.ForeignKey(
        Etapa, on_delete=models.PROTECT, null=True, blank=True, verbose_name="etapa (apropriação)"
    )

    class Meta:
        verbose_name = "item do contrato"
        verbose_name_plural = "itens do contrato"
        ordering = ["pk"]

    def __str__(self):
        return f"{self.descricao} ({self.unidade})"

    @property
    def total(self):
        return arredondar((self.quantidade or ZERO) * (self.preco_unitario or ZERO))

    def quantidade_medida(self, excluir_medicao=None, incluir_rascunhos=False):
        """Quantidade já medida. Por padrão só conta medições aprovadas."""
        medicoes = self.medicoes.all()
        if not incluir_rascunhos:
            medicoes = medicoes.filter(medicao__status=Medicao.Status.APROVADA)
        if excluir_medicao is not None:
            medicoes = medicoes.exclude(medicao=excluir_medicao)
        return medicoes.aggregate(total=Sum("quantidade"))["total"] or ZERO

    @property
    def saldo(self):
        """Saldo a medir, descontando só o que já foi aprovado."""
        return self.quantidade - self.quantidade_medida()

    def saldo_a_lancar(self, excluir_medicao=None):
        """Saldo para uma nova medição: desconta também as medições em elaboração."""
        return self.quantidade - self.quantidade_medida(excluir_medicao, incluir_rascunhos=True)

    def clean(self):
        contrato = pai(self, "contrato")
        if contrato is not None:
            validar_etapa_da_obra(self.etapa, contrato.obra_id)
        if self.pk and self.quantidade is not None:
            medido = self.quantidade_medida(incluir_rascunhos=True)
            if self.quantidade < medido:
                raise ValidationError(
                    {"quantidade": f"Já foram medidos {medido:f}; a quantidade não pode ser menor."}
                )


class Medicao(models.Model):
    class Status(models.TextChoices):
        RASCUNHO = "RASC", "Em elaboração"
        APROVADA = "APROV", "Aprovada"

    contrato = models.ForeignKey(
        ContratoServico, on_delete=models.PROTECT, related_name="medicoes", verbose_name="contrato"
    )
    numero = models.PositiveIntegerField("nº", editable=False)
    data = models.DateField("data da medição", default=datetime.date.today)
    periodo_inicio = models.DateField("período de")
    periodo_fim = models.DateField("até")
    status = models.CharField(
        "situação", max_length=5, choices=Status.choices, default=Status.RASCUNHO
    )
    titulo = models.OneToOneField(
        Titulo,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="medicao",
        verbose_name="título a pagar",
    )
    observacao = models.TextField("observação", blank=True)

    class Meta:
        verbose_name = "medição"
        verbose_name_plural = "medições"
        ordering = ["-data", "-pk"]
        constraints = [
            models.UniqueConstraint(fields=["contrato", "numero"], name="medicao_numero_unico")
        ]

    def __str__(self):
        return f"Medição {self.numero} - CT {self.contrato_id}"

    def editavel(self):
        return self.status == self.Status.RASCUNHO

    def save(self, *args, **kwargs):
        if not self.numero:
            ultimo = Medicao.objects.filter(contrato_id=self.contrato_id).aggregate(n=Max("numero"))["n"]
            self.numero = (ultimo or 0) + 1
        super().save(*args, **kwargs)

    def clean(self):
        erros = {}
        if self.periodo_inicio and self.periodo_fim and self.periodo_fim < self.periodo_inicio:
            erros["periodo_fim"] = "O fim do período deve ser depois do início."
        if self.contrato_id and not self.pk and self.contrato.status != ContratoServico.Status.ATIVO:
            erros["contrato"] = "Só é possível medir contratos ativos."
        if erros:
            raise ValidationError(erros)

    @property
    def valor_bruto(self):
        total = self.itens.aggregate(total=Sum(F("quantidade") * F("item_contrato__preco_unitario")))["total"]
        return arredondar(total)

    def _retencao(self, percentual):
        return arredondar(self.valor_bruto * percentual / 100)

    @property
    def valor_caucao(self):
        return self._retencao(self.contrato.retencao_caucao)

    @property
    def valor_inss(self):
        return self._retencao(self.contrato.retencao_inss)

    @property
    def valor_iss(self):
        return self._retencao(self.contrato.retencao_iss)

    @property
    def valor_liquido(self):
        return self.valor_bruto - self.valor_caucao - self.valor_inss - self.valor_iss


class ItemMedicao(models.Model):
    medicao = models.ForeignKey(
        Medicao, on_delete=models.CASCADE, related_name="itens", verbose_name="medição"
    )
    item_contrato = models.ForeignKey(
        ItemContrato, on_delete=models.PROTECT, related_name="medicoes", verbose_name="serviço"
    )
    quantidade = models.DecimalField(
        "quantidade medida", validators=[MinValueValidator(Decimal("0.0001"))], **QUANTIDADE
    )

    class Meta:
        verbose_name = "item medido"
        verbose_name_plural = "itens medidos"
        constraints = [
            models.UniqueConstraint(fields=["medicao", "item_contrato"], name="medicao_item_unico")
        ]

    @property
    def total(self):
        return arredondar(self.quantidade * self.item_contrato.preco_unitario)

    def clean(self):
        medicao = pai(self, "medicao")
        item = pai(self, "item_contrato")
        if medicao is None or item is None or self.quantidade is None:
            return
        if item.contrato_id != medicao.contrato_id:
            raise ValidationError({"item_contrato": "O serviço não é deste contrato."})
        saldo = item.saldo_a_lancar(excluir_medicao=medicao if medicao.pk else None)
        if self.quantidade > saldo:
            raise ValidationError(
                {"quantidade": f"Maior que o saldo a medir ({saldo:f} {item.unidade})."}
            )
