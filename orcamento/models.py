from decimal import ROUND_HALF_UP, Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import F, Sum

from cadastros.models import Composicao, Insumo
from obras.models import Obra

CENTAVOS = Decimal("0.01")


def arredondar(valor):
    return (valor or Decimal("0")).quantize(CENTAVOS, rounding=ROUND_HALF_UP)


class Orcamento(models.Model):
    class Status(models.TextChoices):
        RASCUNHO = "RASC", "Rascunho"
        APROVADO = "APROV", "Aprovado"
        CANCELADO = "CANC", "Cancelado"

    obra = models.ForeignKey(
        Obra, on_delete=models.PROTECT, related_name="orcamentos", verbose_name="obra"
    )
    descricao = models.CharField("descrição", max_length=200)
    versao = models.PositiveIntegerField("versão", default=1)
    data_base = models.DateField("data-base dos preços")
    bdi_percentual = models.DecimalField(
        "BDI (%)",
        max_digits=6,
        decimal_places=2,
        default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0"))],
    )
    status = models.CharField(
        "status", max_length=5, choices=Status.choices, default=Status.RASCUNHO
    )

    class Meta:
        verbose_name = "orçamento"
        verbose_name_plural = "orçamentos"
        ordering = ["obra", "-versao"]
        constraints = [
            models.UniqueConstraint(fields=["obra", "versao"], name="orcamento_versao_unica")
        ]

    def __str__(self):
        return f"{self.obra.codigo} - {self.descricao} (v{self.versao})"

    @property
    def custo_direto(self):
        total = ItemOrcamento.objects.filter(etapa__orcamento=self).aggregate(
            total=Sum(F("quantidade") * F("preco_unitario"))
        )["total"]
        return arredondar(total)

    @property
    def valor_bdi(self):
        return arredondar(self.custo_direto * self.bdi_percentual / Decimal("100"))

    @property
    def preco_total(self):
        return self.custo_direto + self.valor_bdi

    def arvore(self, *valores_por_etapa):
        """EAP completa como lista de (etapa, nível, total, *extras) em ordem de exibição.

        O total de cada etapa inclui as subetapas. Cada dicionário extra
        {etapa_id: valor} passado é acumulado da mesma forma (por exemplo, o
        valor comprado por etapa) e aparece após o total, na mesma ordem.
        """
        etapas = list(self.etapas.all())
        orcado = {}
        itens = ItemOrcamento.objects.filter(etapa__orcamento=self).values(
            "etapa_id", "quantidade", "preco_unitario"
        )
        for item in itens:
            orcado[item["etapa_id"]] = (
                orcado.get(item["etapa_id"], Decimal("0"))
                + item["quantidade"] * item["preco_unitario"]
            )
        series = [orcado, *valores_por_etapa]

        filhos = {}
        for etapa in etapas:
            filhos.setdefault(etapa.pai_id, []).append(etapa)

        resultado = []

        def visitar(etapa, nivel):
            posicao = len(resultado)
            resultado.append(None)
            totais = [serie.get(etapa.pk) or Decimal("0") for serie in series]
            for filho in filhos.get(etapa.pk, []):
                totais = [a + b for a, b in zip(totais, visitar(filho, nivel + 1))]
            resultado[posicao] = (etapa, nivel, *(arredondar(t) for t in totais))
            return totais

        for raiz in filhos.get(None, []):
            visitar(raiz, 0)
        return resultado


class Etapa(models.Model):
    """Nó da EAP (estrutura analítica do projeto) do orçamento."""

    orcamento = models.ForeignKey(
        Orcamento, on_delete=models.CASCADE, related_name="etapas", verbose_name="orçamento"
    )
    pai = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="subetapas",
        verbose_name="etapa pai",
    )
    codigo = models.CharField("código", max_length=30, help_text="Ex.: 01, 01.02, 01.02.03")
    descricao = models.CharField("descrição", max_length=255)

    class Meta:
        verbose_name = "etapa"
        verbose_name_plural = "etapas"
        ordering = ["orcamento", "codigo"]
        constraints = [
            models.UniqueConstraint(fields=["orcamento", "codigo"], name="etapa_codigo_unico")
        ]

    def __str__(self):
        return f"{self.codigo} - {self.descricao}"

    def clean(self):
        if self.pai_id is None:
            return
        if self.pai.orcamento_id != self.orcamento_id:
            raise ValidationError({"pai": "A etapa pai deve ser do mesmo orçamento."})
        ancestral = self.pai
        while ancestral is not None:
            if ancestral.pk == self.pk:
                raise ValidationError({"pai": "Uma etapa não pode ser subetapa dela mesma."})
            ancestral = ancestral.pai


class ItemOrcamento(models.Model):
    """Serviço orçado dentro de uma etapa, baseado em uma composição ou um insumo."""

    etapa = models.ForeignKey(
        Etapa, on_delete=models.CASCADE, related_name="itens", verbose_name="etapa"
    )
    composicao = models.ForeignKey(
        Composicao,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        verbose_name="composição",
    )
    insumo = models.ForeignKey(
        Insumo, on_delete=models.PROTECT, null=True, blank=True, verbose_name="insumo"
    )
    quantidade = models.DecimalField(
        "quantidade",
        max_digits=14,
        decimal_places=4,
        validators=[MinValueValidator(Decimal("0"))],
    )
    preco_unitario = models.DecimalField(
        "preço unitário",
        max_digits=14,
        decimal_places=4,
        blank=True,
        help_text="Deixe em branco para copiar o preço atual da composição ou do insumo.",
    )

    class Meta:
        verbose_name = "item do orçamento"
        verbose_name_plural = "itens do orçamento"
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(composicao__isnull=False, insumo__isnull=True)
                    | models.Q(composicao__isnull=True, insumo__isnull=False)
                ),
                name="item_composicao_ou_insumo",
            )
        ]

    def __str__(self):
        return str(self.origem)

    @property
    def origem(self):
        return self.composicao or self.insumo

    @property
    def unidade(self):
        return self.origem.unidade if self.origem else None

    @property
    def total(self):
        return arredondar(self.quantidade * self.preco_unitario)

    def preco_atual(self):
        if self.composicao_id:
            return self.composicao.custo_unitario
        return self.insumo.preco_unitario

    def clean(self):
        if bool(self.composicao_id) == bool(self.insumo_id):
            raise ValidationError("Informe uma composição ou um insumo (apenas um dos dois).")

    def save(self, *args, **kwargs):
        if self.preco_unitario is None:
            self.preco_unitario = self.preco_atual()
        super().save(*args, **kwargs)
