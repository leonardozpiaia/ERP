from django.db import models

from cadastros.models import Empresa


class Obra(models.Model):
    class Status(models.TextChoices):
        PLANEJAMENTO = "PLAN", "Em planejamento"
        ANDAMENTO = "AND", "Em andamento"
        PARALISADA = "PAR", "Paralisada"
        CONCLUIDA = "CONC", "Concluída"

    empresa = models.ForeignKey(
        Empresa, on_delete=models.PROTECT, related_name="obras", verbose_name="empresa"
    )
    codigo = models.CharField("código", max_length=30, unique=True)
    nome = models.CharField("nome", max_length=200)
    endereco = models.CharField("endereço", max_length=255, blank=True)
    cidade = models.CharField("cidade", max_length=100, blank=True)
    uf = models.CharField("UF", max_length=2, blank=True)
    area_construida = models.DecimalField(
        "área construída (m²)", max_digits=12, decimal_places=2, null=True, blank=True
    )
    data_inicio = models.DateField("data de início", null=True, blank=True)
    data_previsao_termino = models.DateField(
        "previsão de término", null=True, blank=True
    )
    status = models.CharField(
        "status", max_length=4, choices=Status.choices, default=Status.PLANEJAMENTO
    )

    class Meta:
        verbose_name = "obra"
        verbose_name_plural = "obras"
        ordering = ["codigo"]

    def __str__(self):
        return f"{self.codigo} - {self.nome}"
