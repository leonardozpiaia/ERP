import datetime
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from cadastros.models import Composicao, ComposicaoItem, Empresa, Insumo, UnidadeMedida
from obras.models import Obra
from orcamento.models import Etapa, ItemOrcamento, Orcamento


class Command(BaseCommand):
    help = "Carrega uma empresa, uma obra e um orçamento de exemplo para testes."

    @transaction.atomic
    def handle(self, *args, **options):
        if Obra.objects.filter(codigo="OB-001").exists():
            self.stdout.write("Dados de exemplo já carregados.")
            return

        un = {
            sigla: UnidadeMedida.objects.get_or_create(sigla=sigla, defaults={"descricao": desc})[0]
            for sigla, desc in [
                ("m2", "metro quadrado"), ("m3", "metro cúbico"), ("kg", "quilograma"),
                ("h", "hora"), ("un", "unidade"), ("sc", "saco"),
            ]
        }
        T = Insumo.Tipo
        insumos = {}
        for codigo, desc, sigla, tipo, preco in [
            ("I-001", "Cimento Portland CP II-32 (50 kg)", "sc", T.MATERIAL, "38.90"),
            ("I-002", "Areia média", "m3", T.MATERIAL, "120.00"),
            ("I-003", "Brita 1", "m3", T.MATERIAL, "135.00"),
            ("I-004", "Pedreiro", "h", T.MAO_DE_OBRA, "28.50"),
            ("I-005", "Servente", "h", T.MAO_DE_OBRA, "21.00"),
            ("I-006", "Bloco cerâmico 9x19x19", "un", T.MATERIAL, "1.35"),
            ("I-007", "Aço CA-50", "kg", T.MATERIAL, "7.80"),
        ]:
            insumos[codigo] = Insumo.objects.create(
                codigo=codigo, descricao=desc, unidade=un[sigla], tipo=tipo,
                preco_unitario=Decimal(preco),
            )

        concreto = Composicao.objects.create(
            codigo="C-001", descricao="Concreto fck 25 MPa, preparo em betoneira", unidade=un["m3"]
        )
        alvenaria = Composicao.objects.create(
            codigo="C-002", descricao="Alvenaria de vedação com bloco cerâmico 9 cm", unidade=un["m2"]
        )
        for comp, codigo, coef in [
            (concreto, "I-001", "7.0"), (concreto, "I-002", "0.60"), (concreto, "I-003", "0.75"),
            (concreto, "I-005", "6.0"),
            (alvenaria, "I-006", "26.0"), (alvenaria, "I-001", "0.15"),
            (alvenaria, "I-004", "0.80"), (alvenaria, "I-005", "0.40"),
        ]:
            ComposicaoItem.objects.create(
                composicao=comp, insumo=insumos[codigo], coeficiente=Decimal(coef)
            )

        empresa = Empresa.objects.create(
            razao_social="Construtora Exemplo Ltda", nome_fantasia="Construtora Exemplo",
            cnpj="00.000.000/0001-00",
        )
        obra = Obra.objects.create(
            empresa=empresa, codigo="OB-001", nome="Residencial Exemplo",
            cidade="Porto Alegre", uf="RS", area_construida=Decimal("1200"),
            data_inicio=datetime.date.today(),
        )
        orc = Orcamento.objects.create(
            obra=obra, descricao="Orçamento executivo", data_base=datetime.date.today(),
            bdi_percentual=Decimal("25"),
        )
        infra = Etapa.objects.create(orcamento=orc, codigo="01", descricao="Infraestrutura")
        fund = Etapa.objects.create(orcamento=orc, pai=infra, codigo="01.01", descricao="Fundações")
        supra = Etapa.objects.create(orcamento=orc, codigo="02", descricao="Supraestrutura")
        alv = Etapa.objects.create(orcamento=orc, codigo="03", descricao="Alvenaria")
        ItemOrcamento.objects.create(etapa=fund, composicao=concreto, quantidade=Decimal("45"))
        ItemOrcamento.objects.create(etapa=fund, insumo=insumos["I-007"], quantidade=Decimal("3500"))
        ItemOrcamento.objects.create(etapa=supra, composicao=concreto, quantidade=Decimal("110"))
        ItemOrcamento.objects.create(etapa=alv, composicao=alvenaria, quantidade=Decimal("1850"))

        self.stdout.write(self.style.SUCCESS(f"Exemplo carregado: {orc} — total R$ {orc.preco_total}"))
