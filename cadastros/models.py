from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import F, Sum


class Empresa(models.Model):
    razao_social = models.CharField("razão social", max_length=200)
    nome_fantasia = models.CharField("nome fantasia", max_length=200, blank=True)
    cnpj = models.CharField("CNPJ", max_length=18, unique=True)
    ativa = models.BooleanField("ativa", default=True)

    class Meta:
        verbose_name = "empresa"
        verbose_name_plural = "empresas"
        ordering = ["razao_social"]

    def __str__(self):
        return self.nome_fantasia or self.razao_social


class Fornecedor(models.Model):
    razao_social = models.CharField("razão social", max_length=200)
    nome_fantasia = models.CharField("nome fantasia", max_length=200, blank=True)
    cpf_cnpj = models.CharField("CPF/CNPJ", max_length=18, unique=True)
    contato = models.CharField("contato", max_length=100, blank=True)
    email = models.EmailField("e-mail", blank=True)
    telefone = models.CharField("telefone", max_length=20, blank=True)
    cidade = models.CharField("cidade", max_length=100, blank=True)
    uf = models.CharField("UF", max_length=2, blank=True)
    ativo = models.BooleanField("ativo", default=True)

    class Meta:
        verbose_name = "fornecedor"
        verbose_name_plural = "fornecedores"
        ordering = ["razao_social"]

    def __str__(self):
        return self.nome_fantasia or self.razao_social


class UnidadeMedida(models.Model):
    sigla = models.CharField("sigla", max_length=10, unique=True)
    descricao = models.CharField("descrição", max_length=60)

    class Meta:
        verbose_name = "unidade de medida"
        verbose_name_plural = "unidades de medida"
        ordering = ["sigla"]

    def __str__(self):
        return self.sigla


class Insumo(models.Model):
    """Material, mão de obra, equipamento ou serviço com preço unitário."""

    class Tipo(models.TextChoices):
        MATERIAL = "MAT", "Material"
        MAO_DE_OBRA = "MO", "Mão de obra"
        EQUIPAMENTO = "EQP", "Equipamento"
        SERVICO = "SRV", "Serviço"

    codigo = models.CharField("código", max_length=30, unique=True)
    descricao = models.CharField("descrição", max_length=255)
    unidade = models.ForeignKey(
        UnidadeMedida, on_delete=models.PROTECT, verbose_name="unidade"
    )
    tipo = models.CharField("tipo", max_length=3, choices=Tipo.choices)
    preco_unitario = models.DecimalField(
        "preço unitário",
        max_digits=14,
        decimal_places=4,
        default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0"))],
    )
    ativo = models.BooleanField("ativo", default=True)

    class Meta:
        verbose_name = "insumo"
        verbose_name_plural = "insumos"
        ordering = ["codigo"]

    def __str__(self):
        return f"{self.codigo} - {self.descricao}"


class Composicao(models.Model):
    """Composição de custo unitário: um serviço formado por insumos e coeficientes."""

    codigo = models.CharField("código", max_length=30, unique=True)
    descricao = models.CharField("descrição", max_length=255)
    unidade = models.ForeignKey(
        UnidadeMedida, on_delete=models.PROTECT, verbose_name="unidade"
    )
    ativa = models.BooleanField("ativa", default=True)

    class Meta:
        verbose_name = "composição"
        verbose_name_plural = "composições"
        ordering = ["codigo"]

    def __str__(self):
        return f"{self.codigo} - {self.descricao}"

    @property
    def custo_unitario(self):
        """Soma de coeficiente x preço de cada insumo, com os preços atuais."""
        total = self.itens.aggregate(
            total=Sum(F("coeficiente") * F("insumo__preco_unitario"))
        )["total"]
        return (total or Decimal("0")).quantize(Decimal("0.0001"))


class ComposicaoItem(models.Model):
    composicao = models.ForeignKey(
        Composicao,
        on_delete=models.CASCADE,
        related_name="itens",
        verbose_name="composição",
    )
    insumo = models.ForeignKey(Insumo, on_delete=models.PROTECT, verbose_name="insumo")
    coeficiente = models.DecimalField(
        "coeficiente",
        max_digits=14,
        decimal_places=6,
        validators=[MinValueValidator(Decimal("0"))],
    )

    class Meta:
        verbose_name = "item da composição"
        verbose_name_plural = "itens da composição"
        constraints = [
            models.UniqueConstraint(
                fields=["composicao", "insumo"], name="composicao_insumo_unico"
            )
        ]

    def __str__(self):
        return f"{self.insumo} x {self.coeficiente}"

    @property
    def custo(self):
        return (self.coeficiente * self.insumo.preco_unitario).quantize(
            Decimal("0.0001")
        )
