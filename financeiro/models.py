"""Financeiro: títulos a pagar e a receber, parcelas, baixas e contas bancárias.

Um título (a pagar ou a receber) é dividido em parcelas. Cada parcela é
quitada por uma ou mais baixas, que movimentam uma conta bancária. Títulos a
pagar podem ser apropriados, em percentual, às etapas do orçamento da obra.
"""

import datetime
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import F, Q, Sum

from cadastros.models import Cliente, Empresa, Fornecedor
from config.anexos import (
    caminho_boleto,
    caminho_comprovante,
    validar_extensao_documento,
    validar_tamanho,
)
from obras.models import Obra
from orcamento.models import Etapa, arredondar
from suprimentos.models import Recebimento, pai

ZERO = Decimal("0")
DINHEIRO = {"max_digits": 14, "decimal_places": 2}
POSITIVO = [MinValueValidator(Decimal("0.01"))]
NAO_NEGATIVO = [MinValueValidator(ZERO)]


class ContaBancaria(models.Model):
    empresa = models.ForeignKey(
        Empresa, on_delete=models.PROTECT, related_name="contas", verbose_name="empresa"
    )
    descricao = models.CharField("descrição", max_length=100, help_text="Ex.: Banrisul - conta movimento")
    banco = models.CharField("banco", max_length=60, blank=True)
    agencia = models.CharField("agência", max_length=20, blank=True)
    numero = models.CharField("conta", max_length=30, blank=True)
    saldo_inicial = models.DecimalField("saldo inicial", default=ZERO, **DINHEIRO)
    data_saldo_inicial = models.DateField("data do saldo inicial", default=datetime.date.today)
    ativa = models.BooleanField("ativa", default=True)

    class Meta:
        verbose_name = "conta bancária"
        verbose_name_plural = "contas bancárias"
        ordering = ["empresa", "descricao"]

    def __str__(self):
        return self.descricao

    def saldo_em(self, data=None):
        """Saldo inicial + recebimentos - pagamentos, até a data (inclusive)."""
        baixas = self.baixas.all()
        if data is not None:
            baixas = baixas.filter(data__lte=data)
        movimento = ZERO
        for tipo, total in baixas.values_list("parcela__titulo__tipo").annotate(
            total=Sum(F("valor") + F("juros") + F("multa") - F("desconto"))
        ):
            movimento += total if tipo == Titulo.Tipo.RECEBER else -total
        return self.saldo_inicial + movimento

    @property
    def saldo_atual(self):
        return self.saldo_em()


class CategoriaFinanceira(models.Model):
    """Plano financeiro: classifica receitas e despesas (ex.: 2.01 Materiais)."""

    class Tipo(models.TextChoices):
        RECEITA = "RECEITA", "Receita"
        DESPESA = "DESPESA", "Despesa"

    codigo = models.CharField("código", max_length=20, unique=True)
    descricao = models.CharField("descrição", max_length=100)
    tipo = models.CharField("tipo", max_length=7, choices=Tipo.choices)
    ativa = models.BooleanField("ativa", default=True)

    class Meta:
        verbose_name = "categoria financeira"
        verbose_name_plural = "plano financeiro"
        ordering = ["codigo"]

    def __str__(self):
        return f"{self.codigo} - {self.descricao}"


class Titulo(models.Model):
    class Tipo(models.TextChoices):
        PAGAR = "PAGAR", "A pagar"
        RECEBER = "RECEBER", "A receber"

    tipo = models.CharField("tipo", max_length=7, choices=Tipo.choices)
    empresa = models.ForeignKey(Empresa, on_delete=models.PROTECT, verbose_name="empresa")
    obra = models.ForeignKey(
        Obra,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="titulos",
        verbose_name="obra",
        help_text="Deixe em branco para despesas e receitas administrativas.",
    )
    fornecedor = models.ForeignKey(
        Fornecedor, on_delete=models.PROTECT, null=True, blank=True, verbose_name="fornecedor"
    )
    cliente = models.ForeignKey(
        Cliente, on_delete=models.PROTECT, null=True, blank=True, verbose_name="cliente"
    )
    categoria = models.ForeignKey(
        CategoriaFinanceira,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        verbose_name="categoria",
    )
    documento = models.CharField("documento", max_length=50, blank=True, help_text="Nº da nota, boleto, contrato...")
    data_emissao = models.DateField("emissão", default=datetime.date.today)
    descricao = models.CharField("descrição", max_length=200, blank=True)
    recebimento = models.OneToOneField(
        Recebimento,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="titulo",
        verbose_name="recebimento de origem",
    )

    class Meta:
        verbose_name = "título"
        verbose_name_plural = "títulos"
        ordering = ["-data_emissao", "-pk"]
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(tipo="PAGAR", fornecedor__isnull=False, cliente__isnull=True)
                    | Q(tipo="RECEBER", cliente__isnull=False, fornecedor__isnull=True)
                ),
                name="titulo_pessoa_conforme_tipo",
            )
        ]

    def __str__(self):
        doc = f" {self.documento}" if self.documento else ""
        return f"{self.get_tipo_display()} {self.pk}{doc} - {self.pessoa}"

    @property
    def pessoa(self):
        return self.fornecedor if self.tipo == self.Tipo.PAGAR else self.cliente

    @property
    def total(self):
        return arredondar(self.parcelas.aggregate(total=Sum("valor"))["total"])

    @property
    def baixado(self):
        return arredondar(
            Baixa.objects.filter(parcela__titulo=self).aggregate(total=Sum("valor"))["total"]
        )

    @property
    def saldo(self):
        return self.total - self.baixado

    def tem_baixas(self):
        return self.pk is not None and Baixa.objects.filter(parcela__titulo=self).exists()

    def clean(self):
        erros = {}
        if self.tipo == self.Tipo.PAGAR:
            if not self.fornecedor_id:
                erros["fornecedor"] = "Informe o fornecedor."
            self.cliente = None
        elif self.tipo == self.Tipo.RECEBER:
            if not self.cliente_id:
                erros["cliente"] = "Informe o cliente."
            self.fornecedor = None
        if self.obra_id and self.empresa_id and self.obra.empresa_id != self.empresa_id:
            erros["obra"] = "A obra deve ser da mesma empresa do título."
        esperado = (
            CategoriaFinanceira.Tipo.DESPESA
            if self.tipo == self.Tipo.PAGAR
            else CategoriaFinanceira.Tipo.RECEITA
        )
        if self.categoria_id and self.categoria.tipo != esperado:
            erros["categoria"] = f"Use uma categoria de {esperado.label.lower()}."
        if erros:
            raise ValidationError(erros)


class ParcelaQuerySet(models.QuerySet):
    def com_saldo(self):
        return self.annotate(
            total_baixado=models.functions.Coalesce(
                Sum("baixas__valor"), ZERO, output_field=models.DecimalField()
            ),
        ).annotate(saldo_aberto=F("valor") - F("total_baixado"))

    def em_aberto(self):
        return self.com_saldo().filter(saldo_aberto__gt=0)


class Parcela(models.Model):
    titulo = models.ForeignKey(
        Titulo, on_delete=models.CASCADE, related_name="parcelas", verbose_name="título"
    )
    numero = models.PositiveIntegerField("nº")
    vencimento = models.DateField("vencimento")
    valor = models.DecimalField("valor", validators=POSITIVO, **DINHEIRO)
    arquivo_boleto = models.FileField(
        "boleto", upload_to=caminho_boleto, blank=True, max_length=255,
        validators=[validar_extensao_documento, validar_tamanho],
        help_text="PDF, JPG ou PNG, até 10 MB.",
    )
    linha_digitavel = models.CharField(
        "linha digitável", max_length=60, blank=True,
        help_text="Código do boleto, para copiar e colar no banco.",
    )

    objects = ParcelaQuerySet.as_manager()

    class Meta:
        verbose_name = "parcela"
        verbose_name_plural = "parcelas"
        ordering = ["vencimento", "titulo", "numero"]
        constraints = [
            models.UniqueConstraint(fields=["titulo", "numero"], name="parcela_numero_unico")
        ]

    def __str__(self):
        return f"{self.titulo} - parc. {self.numero}"

    @property
    def baixado(self):
        return self.baixas.aggregate(total=Sum("valor"))["total"] or ZERO

    @property
    def saldo(self):
        return self.valor - self.baixado

    @property
    def situacao(self):
        saldo = self.saldo
        if saldo <= 0:
            return "Quitada"
        if self.vencimento < datetime.date.today():
            return "Vencida"
        return "Parcial" if saldo < self.valor else "A vencer"


class Apropriacao(models.Model):
    """Parte (%) de um título a pagar que é custo de uma etapa do orçamento."""

    titulo = models.ForeignKey(
        Titulo, on_delete=models.CASCADE, related_name="apropriacoes", verbose_name="título"
    )
    etapa = models.ForeignKey(Etapa, on_delete=models.PROTECT, verbose_name="etapa")
    percentual = models.DecimalField(
        "percentual (%)",
        max_digits=9,
        decimal_places=6,
        validators=[MinValueValidator(Decimal("0.000001")), MaxValueValidator(Decimal("100"))],
    )

    class Meta:
        verbose_name = "apropriação"
        verbose_name_plural = "apropriações por etapa"
        constraints = [
            models.UniqueConstraint(fields=["titulo", "etapa"], name="apropriacao_etapa_unica")
        ]

    def __str__(self):
        return f"{self.etapa} ({self.percentual:.2f}%)"

    def clean(self):
        titulo = pai(self, "titulo")
        if titulo is None or self.etapa_id is None:
            return
        if titulo.obra_id is None:
            raise ValidationError("Informe a obra do título para apropriar por etapa.")
        if self.etapa.orcamento.obra_id != titulo.obra_id:
            raise ValidationError({"etapa": "A etapa deve ser de um orçamento da obra do título."})


class Baixa(models.Model):
    """Pagamento ou recebimento (total ou parcial) de uma parcela."""

    parcela = models.ForeignKey(
        Parcela, on_delete=models.PROTECT, related_name="baixas", verbose_name="parcela"
    )
    data = models.DateField("data", default=datetime.date.today)
    conta = models.ForeignKey(
        ContaBancaria, on_delete=models.PROTECT, related_name="baixas", verbose_name="conta bancária"
    )
    valor = models.DecimalField(
        "valor principal", validators=POSITIVO, help_text="Quanto do saldo da parcela está sendo quitado.",
        **DINHEIRO,
    )
    juros = models.DecimalField("juros", default=ZERO, validators=NAO_NEGATIVO, **DINHEIRO)
    multa = models.DecimalField("multa", default=ZERO, validators=NAO_NEGATIVO, **DINHEIRO)
    desconto = models.DecimalField("desconto", default=ZERO, validators=NAO_NEGATIVO, **DINHEIRO)
    arquivo_comprovante = models.FileField(
        "comprovante", upload_to=caminho_comprovante, blank=True, max_length=255,
        validators=[validar_extensao_documento, validar_tamanho],
        help_text="Comprovante do pagamento: PDF, JPG ou PNG, até 10 MB.",
    )

    class Meta:
        verbose_name = "baixa"
        verbose_name_plural = "baixas"
        ordering = ["-data", "-pk"]

    def __str__(self):
        return f"Baixa {self.pk} - {self.parcela}"

    @property
    def valor_movimentado(self):
        """Valor que efetivamente saiu ou entrou na conta."""
        return arredondar(self.valor + self.juros + self.multa - self.desconto)

    def clean(self):
        parcela = pai(self, "parcela")
        if parcela is None or self.valor is None:
            return
        erros = {}
        ja_baixado = parcela.baixas.exclude(pk=self.pk).aggregate(total=Sum("valor"))["total"] or ZERO
        saldo = parcela.valor - ja_baixado
        if self.valor > saldo:
            erros["valor"] = f"Valor maior que o saldo da parcela (R$ {saldo})."
        if self.desconto and self.desconto > self.valor + (self.juros or ZERO) + (self.multa or ZERO):
            erros["desconto"] = "Desconto maior que o valor da baixa."
        if self.conta_id and self.conta.empresa_id != parcela.titulo.empresa_id:
            erros["conta"] = "A conta bancária deve ser da mesma empresa do título."
        if erros:
            raise ValidationError(erros)


# Visões separadas no painel: a pagar e a receber.


class TituloPagarManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(tipo=Titulo.Tipo.PAGAR)


class TituloReceberManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(tipo=Titulo.Tipo.RECEBER)


class TituloPagar(Titulo):
    objects = TituloPagarManager()

    class Meta:
        proxy = True
        verbose_name = "título a pagar"
        verbose_name_plural = "contas a pagar - títulos"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.tipo = Titulo.Tipo.PAGAR


class TituloReceber(Titulo):
    objects = TituloReceberManager()

    class Meta:
        proxy = True
        verbose_name = "título a receber"
        verbose_name_plural = "contas a receber - títulos"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.tipo = Titulo.Tipo.RECEBER


class ParcelaPagarManager(models.Manager.from_queryset(ParcelaQuerySet)):
    def get_queryset(self):
        return super().get_queryset().filter(titulo__tipo=Titulo.Tipo.PAGAR)


class ParcelaReceberManager(models.Manager.from_queryset(ParcelaQuerySet)):
    def get_queryset(self):
        return super().get_queryset().filter(titulo__tipo=Titulo.Tipo.RECEBER)


class ParcelaPagar(Parcela):
    objects = ParcelaPagarManager()

    class Meta:
        proxy = True
        verbose_name = "parcela a pagar"
        verbose_name_plural = "contas a pagar - parcelas e baixas"


class ParcelaReceber(Parcela):
    objects = ParcelaReceberManager()

    class Meta:
        proxy = True
        verbose_name = "parcela a receber"
        verbose_name_plural = "contas a receber - parcelas e baixas"
