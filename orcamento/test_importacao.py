import datetime
import io
from decimal import Decimal

import openpyxl
from django.contrib.auth.models import Group, User
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.db import IntegrityError
from django.test import TestCase
from django.urls import reverse

from cadastros.models import Composicao, Empresa, UnidadeMedida
from obras.models import Obra

from . import importacao
from .models import Etapa, ItemOrcamento, Orcamento

D = Decimal


def planilha(linhas):
    livro = openpyxl.Workbook()
    for linha in linhas:
        livro.active.append(linha)
    arquivo = io.BytesIO()
    livro.save(arquivo)
    arquivo.seek(0)
    return arquivo


PLANILHA_REAL = [
    ["CONSTRUTORA EXEMPLO LTDA"],
    ["Obra: Residencial Teste", None, None, "Data-base: 08/2026"],
    [],
    ["ITEM", "CÓDIGO", "BANCO", "DESCRIÇÃO DOS SERVIÇOS", "UND", "QUANT.", "CUSTO UNIT. (R$)",
     "PREÇO UNIT. COM BDI", "TOTAL (R$)"],
    [1, None, None, "SERVIÇOS PRELIMINARES", None, None, None, None, None],
    [1.1, "98459", "SINAPI", "Tapume com telha metálica", "m²", "85,50", "120,00", "150,00", "10.260,00"],
    [1.2, None, "PRÓPRIO", "Placa de obra", "UN", 1, 850, 1062.5, 850],
    [2, None, None, "ESTRUTURA", None, None, None, None, None],
    ["2.1", None, None, "Fundações", None, None, None, None, None],
    ["2.1.1", "C-001", None, "Concreto fck 25", "m3", "12", "600,00", "750,00", "7.200,00"],
    ["2.1.2", None, None, "Forma de madeira", "m2", "40", "55,00", "68,75", "9.999,00"],
    [None, None, None, None, None, None, None, None, None],
    [None, None, None, "TOTAL GERAL", None, None, None, None, "20.510,00"],
]


class LeituraTests(TestCase):
    def test_planilha_do_mundo_real(self):
        leitura = importacao.ler_planilha(planilha(PLANILHA_REAL))
        self.assertEqual(leitura.erros, [])
        self.assertEqual(
            [(e.codigo, e.pai) for e in leitura.etapas], [("1", None), ("2", None), ("2.1", "2")]
        )
        self.assertEqual(
            [(i.etapa, i.codigo, i.quantidade, i.preco) for i in leitura.itens],
            [("1", "1.1", "85.50", "120.00"), ("1", "1.2", "1", "850"),
             ("2.1", "2.1.1", "12", "600.00"), ("2.1", "2.1.2", "40", "55.00")],
        )
        # Usa o preço sem BDI e reconhece a coluna Código como referência.
        self.assertEqual(leitura.itens[2].referencia, "C-001")
        self.assertEqual(leitura.total, D("20510.00"))
        # 40 x 55 = 2.200, mas o total da planilha diz 9.999.
        self.assertEqual(len(leitura.avisos), 1)
        self.assertIn("Linha 11: quantidade × preço = 2.200,00, mas o total da planilha é 9.999,00", leitura.avisos[0])
        resumo = {l["etapa"].codigo: (l["nivel"], l["itens"], l["total"]) for l in leitura.resumo()}
        self.assertEqual(resumo["2"], (0, 0, D("9400.00")))
        self.assertEqual(resumo["2.1"], (1, 2, D("9400.00")))

    def test_modelo_e_lido_pela_propria_importacao(self):
        arquivo = io.BytesIO()
        importacao.gerar_modelo(arquivo)
        arquivo.seek(0)
        leitura = importacao.ler_planilha(arquivo)
        self.assertEqual(leitura.erros, [])
        self.assertEqual(len(leitura.etapas), 4)
        self.assertEqual(len(leitura.itens), 6)

    def test_sem_coluna_item_numera_etapas_em_sequencia(self):
        leitura = importacao.ler_planilha(planilha([
            ["Descrição", "Unidade", "Quantidade", "Valor unitário"],
            ["Fundação", None, None, None],
            ["Estaca", "m", 100, 45],
            ["Cobertura", None, None, None],
            ["Telha", "m2", 200, 38.9],
        ]))
        self.assertEqual(leitura.erros, [])
        self.assertEqual([e.codigo for e in leitura.etapas], ["01", "02"])
        self.assertEqual([i.etapa for i in leitura.itens], ["01", "02"])
        self.assertTrue(any("não tem coluna" in a for a in leitura.avisos))

    def test_itens_antes_de_qualquer_etapa(self):
        leitura = importacao.ler_planilha(planilha([
            ["Item", "Descrição", "Und", "Quant", "Preço unitário"],
            ["1", "Serviço solto", "vb", 1, 1000],
        ]))
        self.assertEqual(leitura.erros, [])
        self.assertEqual(leitura.etapas[0].codigo, "00")
        self.assertEqual(leitura.itens[0].etapa, "00")

    def test_erros(self):
        casos = {
            "cabeçalho": [["Nome", "Valor"], ["x", 1]],
            "negativo": [["Item", "Descrição", "Quant", "Preço unitário"], ["1", "Etapa", None, None],
                         ["1.1", "Item", -2, 10]],
            "inválido": [["Item", "Descrição", "Quant", "Preço unitário"], ["1", "Etapa", None, None],
                         ["1.1", "Item", "dois", 10]],
            "sem preço": [["Item", "Descrição", "Quant", "Preço unitário"], ["1", "Etapa", None, None],
                          ["1.1", "Item", 2, None]],
            "duplicada": [["Item", "Descrição", "Quant", "Preço unitário"], ["1", "Etapa", None, None],
                          ["1", "De novo", None, None], ["1.1", "Item", 1, 1]],
        }
        for nome, linhas in casos.items():
            with self.subTest(nome):
                self.assertTrue(importacao.ler_planilha(planilha(linhas)).erros)
        self.assertTrue(importacao.ler_planilha(io.BytesIO(b"isto nao e excel")).erros)

    def test_ler_numero(self):
        self.assertEqual(importacao.ler_numero("R$ 1.234,56"), D("1234.56"))
        self.assertEqual(importacao.ler_numero(12.5), D("12.5"))
        self.assertEqual(importacao.ler_numero("1234.5"), D("1234.5"))
        self.assertIsNone(importacao.ler_numero(" - "))
        self.assertEqual(importacao.ler_codigo(2.0), "2")
        self.assertEqual(importacao.ler_codigo(" 01.02. "), "01.02")
        self.assertEqual(importacao.formatar(D("1234.5")), "1.234,50")


class ImportarTests(TestCase):
    def setUp(self):
        empresa = Empresa.objects.create(razao_social="E", cnpj="1")
        self.obra = Obra.objects.create(empresa=empresa, codigo="OB1", nome="Obra")
        m3 = UnidadeMedida.objects.create(sigla="m3", descricao="metro cúbico")
        self.concreto = Composicao.objects.create(codigo="C-001", descricao="Concreto", unidade=m3)

    def test_cria_orcamento_com_eap(self):
        leitura = importacao.ler_planilha(planilha(PLANILHA_REAL))
        importacao.conferir_cadastros(leitura)
        orc = importacao.importar(leitura, self.obra, "Importado", datetime.date(2026, 8, 1), D("25"))
        self.assertEqual(orc.versao, 1)
        self.assertEqual(orc.custo_direto, D("20510.00"))
        self.assertEqual(orc.preco_total, D("25637.50"))
        self.assertEqual(Etapa.objects.get(orcamento=orc, codigo="2.1").pai.codigo, "2")
        concreto = ItemOrcamento.objects.get(codigo="2.1.1")
        self.assertEqual(concreto.composicao, self.concreto)
        self.assertEqual(concreto.preco_unitario, D("600"))  # o preço da planilha vale
        tapume = ItemOrcamento.objects.get(codigo="1.1")
        self.assertIsNone(tapume.origem)
        self.assertEqual(str(tapume.unidade), "m²")
        # "UN" e "un" são a mesma unidade; m² foi criada.
        self.assertTrue(UnidadeMedida.objects.filter(sigla="m²").exists())
        # Segunda importação na mesma obra vira a versão 2.
        orc2 = importacao.importar(leitura, self.obra, "Revisão", datetime.date(2026, 8, 1), D("0"))
        self.assertEqual(orc2.versao, 2)

    def test_item_sem_preco_usa_cadastro(self):
        leitura = importacao.ler_planilha(planilha([
            ["Item", "Código", "Descrição", "Und", "Quant", "Preço unitário"],
            ["1", None, "Estrutura", None, None, None],
            ["1.1", "C-001", "Concreto", "m3", 10, None],
            ["1.2", "X-999", "Sem cadastro", "m3", 10, None],
        ]))
        importacao.conferir_cadastros(leitura)
        self.assertEqual(len(leitura.erros), 1)
        self.assertIn("X-999", leitura.erros[0])

    def test_item_avulso_exige_descricao(self):
        orc = Orcamento.objects.create(obra=self.obra, descricao="O", data_base=datetime.date.today())
        etapa = Etapa.objects.create(orcamento=orc, codigo="1", descricao="E")
        item = ItemOrcamento(etapa=etapa, quantidade=1, preco_unitario=1)
        with self.assertRaises(ValidationError):
            item.full_clean()
        with self.assertRaises(IntegrityError):
            item.save()


class TelaImportacaoTests(TestCase):
    def setUp(self):
        empresa = Empresa.objects.create(razao_social="E", cnpj="1")
        self.obra = Obra.objects.create(empresa=empresa, codigo="OB1", nome="Obra")
        self.client.force_login(User.objects.create_superuser("admin", "a@a.com", "x"))
        self.url = reverse("orcamento:importar")

    def enviar(self, linhas):
        arquivo = SimpleUploadedFile("orc.xlsx", planilha(linhas).read())
        return self.client.post(self.url, {
            "obra": self.obra.pk, "descricao": "Importado", "data_base": "01/08/2026",
            "bdi_percentual": "20", "arquivo": arquivo,
        })

    def test_previa_e_confirmacao(self):
        self.assertContains(self.client.get(reverse("admin:orcamento_orcamento_changelist")), "Importar planilha")
        resp = self.enviar(PLANILHA_REAL)
        self.assertContains(resp, "Prévia da importação")
        self.assertContains(resp, "20.510,00")
        self.assertContains(resp, "24.612,00")  # com BDI de 20%
        self.assertFalse(Orcamento.objects.exists())  # nada criado antes de confirmar

        resp = self.client.post(self.url, {"confirmar": "1"})
        orc = Orcamento.objects.get()
        self.assertRedirects(resp, reverse("orcamento:eap", args=[orc.pk]))
        self.assertEqual(orc.bdi_percentual, D("20"))
        self.assertEqual(orc.data_base, datetime.date(2026, 8, 1))
        self.assertEqual(orc.custo_direto, D("20510.00"))
        # Confirmar de novo não duplica: a prévia já foi usada.
        self.client.post(self.url, {"confirmar": "1"})
        self.assertEqual(Orcamento.objects.count(), 1)

    def test_planilha_com_erro_nao_permite_confirmar(self):
        resp = self.enviar([["Nome", "Valor"]])
        self.assertContains(resp, "Não encontrei a linha de cabeçalho")
        self.assertNotContains(resp, "Confirmar e criar")

    def test_arquivo_que_nao_e_xlsx(self):
        resp = self.client.post(self.url, {
            "obra": self.obra.pk, "descricao": "X", "data_base": "01/08/2026", "bdi_percentual": "0",
            "arquivo": SimpleUploadedFile("orc.xls", b"x"),
        })
        self.assertContains(resp, "Envie um arquivo .xlsx")

    def test_modelo_para_baixar(self):
        resp = self.client.get(reverse("orcamento:modelo_planilha"))
        self.assertEqual(resp.status_code, 200)
        livro = openpyxl.load_workbook(io.BytesIO(resp.content))
        self.assertEqual(livro.active["C4"].value, "Descrição")

    def test_permissao(self):
        call_command("criar_perfis", stdout=io.StringIO())
        comercial = User.objects.create_user("com", is_staff=True)
        comercial.groups.add(Group.objects.get(name="Comercial"))
        self.client.force_login(comercial)
        self.assertEqual(self.client.get(self.url).status_code, 403)
