import datetime
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from cadastros.models import Cliente, Empresa
from financeiro import services as financeiro
from financeiro.models import ContaBancaria, Parcela
from obras.models import Obra

from . import services
from .models import (
    ContratoVenda,
    IndiceEconomico,
    ReajusteParcela,
    SerieParcelas,
    Unidade,
    somar_meses,
)

D = Decimal
T = SerieParcelas.Tipo
DATA = datetime.date(2026, 1, 31)


class Base(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(razao_social="E", cnpj="1")
        self.obra = Obra.objects.create(empresa=self.empresa, codigo="OB1", nome="Obra")
        self.unidade = Unidade.objects.create(
            obra=self.obra, bloco="A", andar=1, identificador="101", preco_tabela=D("300000")
        )
        self.cliente = Cliente.objects.create(nome="Cliente", cpf_cnpj="1")
        self.conta = ContaBancaria.objects.create(empresa=self.empresa, descricao="Conta")

    def contrato(self, valor="100000", series=None, unidade=None, indice="INCC"):
        contrato = ContratoVenda.objects.create(
            unidade=unidade or self.unidade, cliente=self.cliente, data_contrato=DATA,
            valor_total=D(valor), indice=indice,
        )
        for tipo, qtd, valor_parc, venc, intervalo in series or [
            (T.ENTRADA, 1, "10000", DATA, 1),
            (T.MENSAL, 12, "5000", somar_meses(DATA, 1), 1),
            (T.INTERMEDIARIA, 2, "15000", somar_meses(DATA, 6), 6),
        ]:
            SerieParcelas.objects.create(
                contrato=contrato, tipo=tipo, quantidade=qtd, valor=D(valor_parc),
                primeiro_vencimento=venc, intervalo_meses=intervalo,
            )
        return contrato


class RegrasTests(Base):
    def test_somar_meses_respeita_fim_do_mes(self):
        self.assertEqual(somar_meses(DATA, 1), datetime.date(2026, 2, 28))
        self.assertEqual(somar_meses(DATA, 13), datetime.date(2027, 2, 28))
        self.assertEqual(somar_meses(datetime.date(2026, 11, 15), 3), datetime.date(2027, 2, 15))

    def test_efetivar_gera_parcelas_e_vende_unidade(self):
        contrato = self.contrato()
        self.assertEqual(contrato.data_base, DATA)  # vazia vira a data do contrato
        titulo = services.efetivar(contrato)

        contrato.refresh_from_db()
        self.unidade.refresh_from_db()
        self.assertEqual(contrato.status, ContratoVenda.Status.ATIVO)
        self.assertEqual(contrato.titulo, titulo)
        self.assertEqual(self.unidade.status, Unidade.Status.VENDIDA)
        self.assertEqual(titulo.cliente, self.cliente)
        self.assertEqual(titulo.obra, self.obra)
        parcelas = list(titulo.parcelas.order_by("numero"))
        self.assertEqual(len(parcelas), 15)
        self.assertEqual(titulo.total, D("100000"))
        # Numeradas em ordem de vencimento, intercalando as séries.
        self.assertEqual([p.vencimento for p in parcelas], sorted(p.vencimento for p in parcelas))
        intermediarias = [p.vencimento for p in parcelas if p.valor == D("15000")]
        self.assertEqual(intermediarias, [datetime.date(2026, 7, 31), datetime.date(2027, 1, 31)])

    def test_efetivar_exige_soma_igual_ao_valor(self):
        contrato = self.contrato(valor="100000.01")
        with self.assertRaises(ValidationError):
            services.efetivar(contrato)
        self.assertEqual(Parcela.objects.count(), 0)

    def test_unidade_nao_pode_ter_dois_contratos_vigentes(self):
        services.efetivar(self.contrato())
        segundo = ContratoVenda(unidade=self.unidade, cliente=self.cliente, valor_total=1, data_base=DATA)
        with self.assertRaises(ValidationError):
            segundo.full_clean()

    def test_distrato_libera_unidade_e_cancela_saldo(self):
        contrato = self.contrato()
        titulo = services.efetivar(contrato)
        entrada, primeira = titulo.parcelas.order_by("numero")[:2]
        financeiro.baixar(entrada, self.conta)
        financeiro.baixar(primeira, self.conta, valor=D("2000"))

        services.distratar(contrato)
        self.unidade.refresh_from_db()
        self.assertEqual(self.unidade.status, Unidade.Status.DISPONIVEL)
        self.assertEqual(contrato.status, ContratoVenda.Status.DISTRATADO)
        self.assertEqual(titulo.parcelas.count(), 2)
        self.assertEqual(titulo.total, D("12000"))
        self.assertEqual(titulo.saldo, D("0"))
        # A unidade pode ser vendida de novo.
        services.efetivar(self.contrato())

    def test_reajuste_corrige_saldo_futuro_uma_vez(self):
        contrato = self.contrato(series=[
            (T.ENTRADA, 1, "10000", DATA, 1),
            (T.MENSAL, 3, "1000", datetime.date(2026, 2, 10), 1),
        ], valor="13000")
        titulo = services.efetivar(contrato)
        entrada, fev, mar, abr = titulo.parcelas.order_by("numero")
        financeiro.baixar(mar, self.conta, valor=D("400"))
        IndiceEconomico.objects.create(indice="INCC", mes=datetime.date(2026, 1, 1), variacao=D("5"))  # data-base: não entra
        IndiceEconomico.objects.create(indice="INCC", mes=datetime.date(2026, 2, 14), variacao=D("1"))
        IndiceEconomico.objects.create(indice="IGPM", mes=datetime.date(2026, 2, 1), variacao=D("9"))

        self.assertEqual(services.reajustar(contrato), 1)
        valores = {p.pk: p.valor for p in titulo.parcelas.all()}
        self.assertEqual(valores[entrada.pk], D("10000"))  # vencida antes de março
        self.assertEqual(valores[fev.pk], D("1000"))
        self.assertEqual(valores[mar.pk], D("1006.00"))  # 400 pago + 600 x 1,01
        self.assertEqual(valores[abr.pk], D("1010.00"))
        self.assertEqual(ReajusteParcela.objects.count(), 2)
        reajuste = contrato.reajustes.get()
        self.assertEqual((reajuste.saldo_antes, reajuste.saldo_depois), (D("1600"), D("1616.00")))

        self.assertEqual(services.reajustar(contrato), 0)  # não aplica de novo
        IndiceEconomico.objects.create(indice="INCC", mes=datetime.date(2026, 3, 1), variacao=D("-1"))
        self.assertEqual(services.reajustar(contrato), 1)
        self.assertEqual(Parcela.objects.get(pk=abr.pk).valor, D("999.90"))

    def test_sem_indice_nao_reajusta(self):
        contrato = self.contrato(indice="NENHUM")
        services.efetivar(contrato)
        IndiceEconomico.objects.create(indice="INCC", mes=datetime.date(2026, 5, 1), variacao=D("1"))
        self.assertEqual(services.reajustar(contrato), 0)


class TelasTests(Base):
    def setUp(self):
        super().setUp()
        self.client.force_login(User.objects.create_superuser("admin", "a@a.com", "senha"))

    def form(self, **extra):
        dados = {
            "unidade": self.unidade.pk, "cliente": self.cliente.pk, "data_contrato": "31/01/2026",
            "valor_total": "30000", "indice": "INCC", "data_base": "", "observacao": "",
            "series-TOTAL_FORMS": "2", "series-INITIAL_FORMS": "0",
            "series-MIN_NUM_FORMS": "0", "series-MAX_NUM_FORMS": "1000",
            "series-0-tipo": "ENT", "series-0-quantidade": "1", "series-0-valor": "10000",
            "series-0-primeiro_vencimento": "31/01/2026", "series-0-intervalo_meses": "1",
            "series-1-tipo": "MEN", "series-1-quantidade": "10", "series-1-valor": "2000",
            "series-1-primeiro_vencimento": "28/02/2026", "series-1-intervalo_meses": "1",
            "reajustes-TOTAL_FORMS": "0", "reajustes-INITIAL_FORMS": "0",
            "reajustes-MIN_NUM_FORMS": "0", "reajustes-MAX_NUM_FORMS": "1000",
        }
        dados.update(extra)
        return dados

    def test_contrato_pelo_admin(self):
        url = reverse("admin:comercial_contratovenda_add")
        resp = self.client.get(url, {"unidade": self.unidade.pk})
        self.assertEqual(resp.context["adminform"].form.initial["valor_total"], D("300000"))

        resp = self.client.post(url, self.form(valor_total="31000"))
        self.assertContains(resp, "diferença de R$ 1.000,00")
        resp = self.client.post(url, self.form())
        self.assertEqual(resp.status_code, 302)
        contrato = ContratoVenda.objects.get()
        self.assertEqual(contrato.data_base, DATA)

        changelist = reverse("admin:comercial_contratovenda_changelist")
        self.client.post(changelist, {"action": "efetivar", "_selected_action": [contrato.pk]})
        contrato.refresh_from_db()
        self.assertEqual(contrato.status, ContratoVenda.Status.ATIVO)
        self.assertEqual(contrato.titulo.parcelas.count(), 11)

        # Contrato efetivado não pode ser excluído.
        resp = self.client.get(reverse("admin:comercial_contratovenda_delete", args=[contrato.pk]))
        self.assertEqual(resp.status_code, 403)
        self.client.post(changelist, {"action": "delete_selected", "_selected_action": [contrato.pk], "post": "yes"})
        self.assertTrue(ContratoVenda.objects.filter(pk=contrato.pk).exists())

        # Distrato pede confirmação antes.
        resp = self.client.post(changelist, {"action": "distratar", "_selected_action": [contrato.pk]})
        self.assertContains(resp, "Sim, distratar")
        contrato.refresh_from_db()
        self.assertEqual(contrato.status, ContratoVenda.Status.ATIVO)
        self.client.post(changelist, {"action": "distratar", "_selected_action": [contrato.pk], "confirmar": "sim"})
        contrato.refresh_from_db()
        self.assertEqual(contrato.status, ContratoVenda.Status.DISTRATADO)

    def test_unidade_vendida_nao_aparece_para_novo_contrato(self):
        services.efetivar(self.contrato())
        resp = self.client.get(reverse("admin:comercial_contratovenda_add"))
        opcoes = resp.context["adminform"].form.fields["unidade"].queryset
        self.assertNotIn(self.unidade, opcoes)

    def test_acoes_de_status_nao_mexem_em_vendidas(self):
        services.efetivar(self.contrato())
        livre = Unidade.objects.create(obra=self.obra, bloco="A", andar=1, identificador="102")
        url = reverse("admin:comercial_unidade_changelist")
        self.client.post(url, {"action": "bloquear", "_selected_action": [self.unidade.pk, livre.pk]})
        self.unidade.refresh_from_db()
        livre.refresh_from_db()
        self.assertEqual(self.unidade.status, Unidade.Status.VENDIDA)
        self.assertEqual(livre.status, Unidade.Status.BLOQUEADA)

    def test_telas_com_dados_de_exemplo(self):
        call_command("carregar_exemplo", stdout=open("/dev/null", "w"))
        contrato = ContratoVenda.objects.filter(reajustes__isnull=False).first()
        obra = Obra.objects.get(codigo="OB-001")
        urls = [
            reverse("comercial:espelho"),
            reverse("comercial:espelho") + f"?obra={obra.pk}",
            reverse("admin:comercial_unidade_changelist"),
            reverse("admin:comercial_unidade_change", args=[obra.unidades.first().pk]),
            reverse("admin:comercial_contratovenda_changelist"),
            reverse("admin:comercial_contratovenda_change", args=[contrato.pk]),
            reverse("admin:comercial_contratovenda_add"),
            reverse("admin:comercial_indiceeconomico_changelist"),
            reverse("admin:index"),
        ]
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)
        resp = self.client.get(reverse("comercial:espelho") + f"?obra={obra.pk}")
        self.assertContains(resp, "Maria Exemplo")
        self.assertEqual(resp.context["total_unidades"], 16)
