# ERP Obras

ERP para construtoras e incorporadoras, no estilo do Sienge. Tudo gira em
torno da **obra**: orçamento, compras, custos e financeiro ficam apropriados
a ela, o que permite comparar o **orçado com o realizado**.

Feito em **Python + Django**, com banco **PostgreSQL** em produção e SQLite
no desenvolvimento.

## Módulos

| Módulo | Situação | Conteúdo |
|---|---|---|
| Cadastros | ✅ pronto | Empresas, unidades de medida, insumos, composições de custo |
| Obras | ✅ pronto | Cadastro de obras por empresa, com status e datas |
| Orçamento | ✅ pronto | Orçamento por obra com versões, EAP hierárquica, BDI e tela de EAP |
| Suprimentos | ⏳ próximo | Solicitação, cotação e pedido de compra por obra |
| Financeiro | ⏳ | Contas a pagar/receber, centros de custo, fluxo de caixa |
| Contratos e medições | ⏳ | Contratos com empreiteiros, medições, retenções |
| Comercial | ⏳ | Espelho de vendas, contratos de venda, recebíveis |

## Conceitos do orçamento

- **Insumo**: material, mão de obra, equipamento ou serviço com preço unitário.
- **Composição**: um serviço (ex.: "concreto fck 25") formado por insumos e
  coeficientes. O custo unitário é a soma de coeficiente × preço de cada insumo.
- **Orçamento**: pertence a uma obra e tem versão, data-base e BDI (%).
- **Etapa (EAP)**: estrutura em árvore do orçamento (01, 01.01, 01.01.01...).
  O total de cada etapa inclui as subetapas.
- **Item**: quantidade de uma composição **ou** de um insumo dentro de uma
  etapa. O preço unitário é **copiado no momento da criação**, então mudar o
  preço de um insumo depois não altera orçamentos já feitos. Para trazer os
  preços novos para um orçamento em rascunho, use a ação *"Atualizar preços"*
  na lista de orçamentos.

## Como rodar localmente

Pré-requisito: Python 3.11 ou mais novo.

```bash
python3 -m venv .venv
source .venv/bin/activate          # no Windows: .venv\Scripts\activate
pip install -r requirements.txt

python manage.py migrate           # cria o banco
python manage.py carregar_exemplo  # opcional: obra e orçamento de exemplo
python manage.py createsuperuser   # cria seu usuário de acesso
python manage.py runserver
```

Acesse http://localhost:8000 e entre com o usuário criado.

## Testes

```bash
python manage.py test
```

## Configuração (variáveis de ambiente)

| Variável | Padrão | Uso |
|---|---|---|
| `DJANGO_SECRET_KEY` | chave de desenvolvimento | **Obrigatório trocar em produção** |
| `DJANGO_DEBUG` | `true` | Use `false` em produção |
| `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1` | Domínios aceitos, separados por vírgula |
| `POSTGRES_DB` | *(vazio)* | Se definido, usa PostgreSQL em vez de SQLite |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_HOST` / `POSTGRES_PORT` | `postgres` / vazio / `localhost` / `5432` | Conexão com o PostgreSQL |

## Estrutura

```
config/      configurações do projeto e rotas principais
cadastros/   empresas, unidades, insumos, composições
obras/       obras
orcamento/   orçamentos, EAP, itens e a tela de EAP
```
