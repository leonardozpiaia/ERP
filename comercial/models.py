"""Comercial (incorporação): unidades, contratos de venda e reajustes.

O empreendimento é a própria obra. Um contrato de venda descreve o preço em
séries de parcelas (entrada, mensais, intermediárias...). Ao ser efetivado,
gera o título a receber no financeiro e marca a unidade como vendida.
"""

import datetime
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q, Sum

from cadastros.models import Cliente
from config.datas import somar_meses
from financeiro.models import Parcela, Titulo
from obras.models import Obra
from orcamento.models import arredondar

ZERO = Decimal("0")
DINHEIRO = {"max_digits": 14, "decimal_places": 2}




class Indice(models.TextChoices):
    NENHUM = "NENHUM", "Sem reajuste"
    INCC = "INCC", "INCC"
    IGPM = "IGPM", "IGP-M"
    IPCA = "IPCA", "IPCA"


class Unidade(models.Model):
    class Tipo(models.TextChoices):
        APARTAMENTO = "APTO", "Apartamento"
        CASA = "CASA", "Casa"
        SALA = "SALA", "Sala comercial"
        LOJA = "LOJA", "Loja"
        LOTE = "LOTE", "Lote"
        VAGA = "VAGA", "Vaga de garagem"

    class Status(models.TextChoices):
        DISPONIVEL = "DISP", "Disponível"
        RESERVADA = "RES", "Reservada"
        VENDIDA = "VEND", "Vendida"
        BLOQUEADA = "BLOQ", "Bloqueada"

    obra = models.ForeignKey(
        Obra, on_delete=models.PROTECT, related_name="unidades", verbose_name="empreendimento (obra)"
    )
    bloco = models.CharField("bloco / torre", max_length=30, blank=True)
    andar = models.IntegerField("andar", null=True, blank=True)
    identificador = models.CharField("unidade", max_length=30, help_text="Ex.: 101, Casa 3, Lote 12")
    tipo = models.CharField("tipo", max_length=4, choices=Tipo.choices, default=Tipo.APARTAMENTO)
    area_privativa = models.DecimalField(
        "área privativa (m²)", max_digits=10, decimal_places=2, null=True, blank=True
    )
    quartos = models.PositiveSmallIntegerField("dormitórios", null=True, blank=True)
    vagas = models.PositiveSmallIntegerField("vagas", null=True, blank=True)
    preco_tabela = models.DecimalField(
        "preço de tabela", validators=[MinValueValidator(ZERO)], default=ZERO, **DINHEIRO
    )
    status = models.CharField(
        "situação", max_length=4, choices=Status.choices, default=Status.DISPONIVEL
    )

    class Meta:
        verbose_name = "unidade"
        verbose_name_plural = "unidades"
        ordering = ["obra", "bloco", "-andar", "identificador"]
        constraints = [
            models.UniqueConstraint(
                fields=["obra", "bloco", "identificador"], name="unidade_identificador_unico"
            )
        ]

    def __str__(self):
        bloco = f"{self.bloco} - " if self.bloco else ""
        return f"{self.obra.codigo} {bloco}{self.identificador}"

    @property
    def contrato_vigente(self):
        return self.contratos.exclude(status=ContratoVenda.Status.DISTRATADO).first()


class IndiceEconomico(models.Model):
    """Variação mensal de um índice (ex.: INCC de março/2026 = 0,45%)."""

    indice = models.CharField(
        "índice", max_length=6, choices=[c for c in Indice.choices if c[0] != Indice.NENHUM]
    )
    mes = models.DateField("mês de referência", help_text="Qualquer dia do mês; é guardado o dia 1.")
    variacao = models.DecimalField(
        "variação (%)", max_digits=8, decimal_places=4, validators=[MinValueValidator(Decimal("-99"))]
    )

    class Meta:
        verbose_name = "índice econômico"
        verbose_name_plural = "índices econômicos"
        ordering = ["indice", "-mes"]
        constraints = [
            models.UniqueConstraint(fields=["indice", "mes"], name="indice_mes_unico")
        ]

    def __str__(self):
        return f"{self.get_indice_display()} {self.mes:%m/%Y}: {self.variacao}%"

    def save(self, *args, **kwargs):
        self.mes = self.mes.replace(day=1)
        super().save(*args, **kwargs)


class ContratoVenda(models.Model):
    class Status(models.TextChoices):
        RASCUNHO = "RASC", "Em elaboração"
        ATIVO = "ATIVO", "Ativo"
        DISTRATADO = "DIST", "Distratado"

    unidade = models.ForeignKey(
        Unidade, on_delete=models.PROTECT, related_name="contratos", verbose_name="unidade"
    )
    cliente = models.ForeignKey(Cliente, on_delete=models.PROTECT, verbose_name="cliente")
    data_contrato = models.DateField("data do contrato", default=datetime.date.today)
    valor_total = models.DecimalField(
        "valor total", validators=[MinValueValidator(Decimal("0.01"))], **DINHEIRO
    )
    indice = models.CharField(
        "índice de reajuste", max_length=6, choices=Indice.choices, default=Indice.INCC
    )
    data_base = models.DateField(
        "data-base do reajuste",
        blank=True,
        help_text="Os índices dos meses seguintes a este corrigem o saldo. Em branco: a data do contrato.",
    )
    status = models.CharField(
        "situação", max_length=5, choices=Status.choices, default=Status.RASCUNHO
    )
    data_distrato = models.DateField("data do distrato", null=True, blank=True)
    titulo = models.OneToOneField(
        Titulo,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="contrato_venda",
        verbose_name="título a receber",
    )
    observacao = models.TextField("observação", blank=True)

    class Meta:
        verbose_name = "contrato de venda"
        verbose_name_plural = "contratos de venda"
        ordering = ["-data_contrato", "-pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["unidade"],
                condition=~Q(status="DIST"),
                name="unidade_um_contrato_vigente",
                violation_error_message="Esta unidade já tem um contrato vigente.",
            )
        ]

    def __str__(self):
        return f"CV {self.pk} - {self.unidade} - {self.cliente}"

    def editavel(self):
        return self.status == self.Status.RASCUNHO

    def save(self, *args, **kwargs):
        if self.data_base is None:
            self.data_base = self.data_contrato
        super().save(*args, **kwargs)

    @property
    def recebido(self):
        if not self.titulo_id:
            return ZERO
        return arredondar(self.titulo.parcelas.aggregate(total=Sum("baixas__valor"))["total"])

    @property
    def saldo(self):
        return self.titulo.saldo if self.titulo_id else ZERO

    @property
    def total_series(self):
        return sum((s.total for s in self.series.all()), ZERO)

    def clean(self):
        if self.unidade_id and self.status == self.Status.RASCUNHO:
            if self.unidade.status in {Unidade.Status.VENDIDA, Unidade.Status.BLOQUEADA}:
                raise ValidationError(
                    {"unidade": f"A unidade está {self.unidade.get_status_display().lower()}."}
                )


class SerieParcelas(models.Model):
    """Grupo de parcelas iguais do contrato (ex.: 36 mensais de R$ 2.000)."""

    class Tipo(models.TextChoices):
        ENTRADA = "ENT", "Entrada / sinal"
        MENSAL = "MEN", "Mensais"
        INTERMEDIARIA = "INT", "Intermediárias"
        CHAVES = "CHV", "Chaves"
        FINANCIAMENTO = "FIN", "Financiamento bancário"

    contrato = models.ForeignKey(
        ContratoVenda, on_delete=models.CASCADE, related_name="series", verbose_name="contrato"
    )
    tipo = models.CharField("tipo", max_length=3, choices=Tipo.choices)
    quantidade = models.PositiveIntegerField("quantidade", validators=[MinValueValidator(1)], default=1)
    valor = models.DecimalField(
        "valor de cada parcela", validators=[MinValueValidator(Decimal("0.01"))], **DINHEIRO
    )
    primeiro_vencimento = models.DateField("1º vencimento")
    intervalo_meses = models.PositiveIntegerField(
        "intervalo (meses)", default=1, validators=[MinValueValidator(1)],
        help_text="1 = mensal, 6 = semestral, 12 = anual.",
    )

    class Meta:
        verbose_name = "série de parcelas"
        verbose_name_plural = "condição de pagamento (séries de parcelas)"
        ordering = ["primeiro_vencimento", "pk"]

    def __str__(self):
        return f"{self.quantidade}x {self.get_tipo_display()} de {self.valor}"

    @property
    def total(self):
        return (self.quantidade or 0) * (self.valor or ZERO)

    def vencimentos(self):
        return [
            somar_meses(self.primeiro_vencimento, n * self.intervalo_meses)
            for n in range(self.quantidade)
        ]


class ReajusteContrato(models.Model):
    """Registro de um índice mensal aplicado a um contrato (nunca aplicado duas vezes)."""

    contrato = models.ForeignKey(
        ContratoVenda, on_delete=models.CASCADE, related_name="reajustes", verbose_name="contrato"
    )
    indice = models.ForeignKey(IndiceEconomico, on_delete=models.PROTECT, verbose_name="índice")
    aplicado_em = models.DateField("aplicado em", default=datetime.date.today)
    saldo_antes = models.DecimalField("saldo antes", **DINHEIRO)
    saldo_depois = models.DecimalField("saldo depois", **DINHEIRO)

    class Meta:
        verbose_name = "reajuste aplicado"
        verbose_name_plural = "reajustes aplicados"
        ordering = ["indice__mes"]
        constraints = [
            models.UniqueConstraint(fields=["contrato", "indice"], name="reajuste_indice_unico")
        ]

    def __str__(self):
        return f"{self.contrato} - {self.indice}"


class ReajusteParcela(models.Model):
    """Histórico do valor de cada parcela antes e depois de um reajuste."""

    reajuste = models.ForeignKey(
        ReajusteContrato, on_delete=models.CASCADE, related_name="parcelas", verbose_name="reajuste"
    )
    parcela = models.ForeignKey(Parcela, on_delete=models.CASCADE, related_name="reajustes")
    valor_anterior = models.DecimalField("valor anterior", **DINHEIRO)
    valor_novo = models.DecimalField("valor novo", **DINHEIRO)
