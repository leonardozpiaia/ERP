"""Perfis de acesso (grupos) do ERP.

Cada perfil lista o que pode ALTERAR (ver, incluir, alterar e excluir) e o
que pode apenas CONSULTAR. Um item é um app inteiro ("orcamento") ou um
modelo ("cadastros.fornecedor"). Aplicado pelo comando `criar_perfis`.
"""

MODULOS = ["cadastros", "obras", "orcamento", "suprimentos", "financeiro", "comercial", "contratos"]

PERFIS = {
    "Diretoria": {
        "alterar": [],
        "consultar": MODULOS,
    },
    "Engenharia": {
        "alterar": [
            "obras", "orcamento", "contratos",
            "cadastros.insumo", "cadastros.composicao", "cadastros.composicaoitem",
            "cadastros.unidademedida",
            "suprimentos.solicitacaocompra", "suprimentos.itemsolicitacao",
            "suprimentos.recebimento", "suprimentos.itemrecebimento",
        ],
        "consultar": ["suprimentos", "cadastros.empresa", "cadastros.fornecedor"],
    },
    "Compras": {
        "alterar": [
            "suprimentos", "cadastros.fornecedor", "cadastros.insumo", "cadastros.unidademedida",
        ],
        "consultar": ["obras", "orcamento", "contratos", "cadastros.empresa", "cadastros.composicao"],
    },
    "Financeiro": {
        "alterar": ["financeiro", "cadastros.fornecedor", "cadastros.cliente"],
        "consultar": ["cadastros", "obras", "orcamento", "suprimentos", "comercial", "contratos"],
    },
    "Comercial": {
        "alterar": ["comercial", "cadastros.cliente"],
        "consultar": [
            "obras", "cadastros.empresa",
            "financeiro.tituloreceber", "financeiro.parcelareceber", "financeiro.titulo",
            "financeiro.parcela",
        ],
    },
}
