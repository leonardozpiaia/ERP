import datetime

from django.test import SimpleTestCase

from .condicao import CondicaoInvalida, descrever, interpretar, previa, vencimentos

d = datetime.date
NOTA = d(2026, 10, 10)


class InterpretarTests(SimpleTestCase):
    def test_formatos(self):
        casos = {
            "": ("dias", [0]),
            "À vista": ("dias", [0]),
            "30": ("dias", [30]),
            "28 dias": ("dias", [28]),
            "28 DDL": ("dias", [28]),
            "30/60/90": ("dias", [30, 60, 90]),
            "0 / 30 / 60 dias": ("dias", [0, 30, 60]),
            "30, 60 e 90": ("dias", [30, 60, 90]),
            "3x": ("mensal", (3, None)),
            "3 X sem juros": ("mensal", (3, None)),
            "10 vezes": ("mensal", (10, None)),
            "4 parcelas": ("mensal", (4, None)),
            "dia 10": ("mensal", (1, 10)),
            "3x dia 15": ("mensal", (3, 15)),
            "todo dia 5, em 2 parcelas": ("mensal", (2, 5)),
        }
        for texto, esperado in casos.items():
            with self.subTest(texto=texto):
                self.assertEqual(interpretar(texto), esperado)

    def test_textos_invalidos(self):
        for texto in ["boleto", "90/60/30", "dia 32", "0x", "30/60 e 3x", "99999 dias"]:
            with self.subTest(texto=texto), self.assertRaises(CondicaoInvalida):
                interpretar(texto)


class VencimentosTests(SimpleTestCase):
    def test_dias(self):
        self.assertEqual(vencimentos("30/60/90", NOTA), [d(2026, 11, 9), d(2026, 12, 9), d(2027, 1, 8)])
        self.assertEqual(vencimentos("à vista", NOTA), [NOTA])

    def test_parcelas_sem_dia_sao_a_cada_30_dias(self):
        self.assertEqual(vencimentos("3x", NOTA), [d(2026, 11, 9), d(2026, 12, 9), d(2027, 1, 8)])

    def test_dia_fixo(self):
        self.assertEqual(vencimentos("dia 15", NOTA), [d(2026, 10, 15)])
        self.assertEqual(vencimentos("dia 10", NOTA), [d(2026, 11, 10)])  # no próprio dia 10: vai para o mês seguinte
        self.assertEqual(vencimentos("dia 5", NOTA), [d(2026, 11, 5)])
        self.assertEqual(
            vencimentos("3x dia 31", d(2027, 1, 20)), [d(2027, 1, 31), d(2027, 2, 28), d(2027, 3, 31)]
        )
        self.assertEqual(vencimentos("2x dia 10", d(2026, 12, 20)), [d(2027, 1, 10), d(2027, 2, 10)])

    def test_primeiro_vencimento(self):
        primeiro = d(2026, 11, 20)
        self.assertEqual(vencimentos("30/60/90", NOTA, primeiro), [primeiro, d(2026, 12, 20), d(2027, 1, 19)])
        self.assertEqual(vencimentos("3x", NOTA, primeiro), [primeiro, d(2026, 12, 20), d(2027, 1, 20)])
        self.assertEqual(vencimentos("", NOTA, primeiro), [primeiro])

    def test_descricao_e_previa(self):
        self.assertEqual(descrever([d(2026, 11, 9)]), "1 parcela: 09/11/2026")
        self.assertEqual(
            descrever([d(2026, 11, 9), d(2026, 12, 9)]), "2 parcelas: 09/11/2026 e 09/12/2026"
        )
        self.assertEqual(previa("30/60", NOTA), (True, "Se a nota chegar em 10/10/2026: 2 parcelas: 09/11/2026 e 09/12/2026."))
        ok, erro = previa("boleto", NOTA)
        self.assertFalse(ok)
        self.assertIn("Não entendi", erro)
