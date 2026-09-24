from decimal import Decimal

from django.test import TestCase

from .models import Composicao, ComposicaoItem, Insumo, UnidadeMedida


class ComposicaoTests(TestCase):
    def test_custo_unitario_soma_coeficiente_vezes_preco(self):
        m3 = UnidadeMedida.objects.create(sigla="m3", descricao="metro cúbico")
        sc = UnidadeMedida.objects.create(sigla="sc", descricao="saco")
        cimento = Insumo.objects.create(
            codigo="I1", descricao="Cimento", unidade=sc, tipo=Insumo.Tipo.MATERIAL,
            preco_unitario=Decimal("40"),
        )
        areia = Insumo.objects.create(
            codigo="I2", descricao="Areia", unidade=m3, tipo=Insumo.Tipo.MATERIAL,
            preco_unitario=Decimal("100"),
        )
        comp = Composicao.objects.create(codigo="C1", descricao="Concreto", unidade=m3)
        ComposicaoItem.objects.create(composicao=comp, insumo=cimento, coeficiente=Decimal("7"))
        ComposicaoItem.objects.create(composicao=comp, insumo=areia, coeficiente=Decimal("0.5"))

        self.assertEqual(comp.custo_unitario, Decimal("330.0000"))

    def test_composicao_vazia_custa_zero(self):
        un = UnidadeMedida.objects.create(sigla="un", descricao="unidade")
        comp = Composicao.objects.create(codigo="C1", descricao="Vazia", unidade=un)
        self.assertEqual(comp.custo_unitario, Decimal("0"))
