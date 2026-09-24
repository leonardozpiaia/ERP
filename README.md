# ERP Obras

ERP para construtoras e incorporadoras, no estilo do Sienge. Tudo gira em
torno da **obra**: orçamento, compras, custos e financeiro ficam apropriados
a ela, o que permite comparar o **orçado com o realizado**.

Feito em **Python + Django**, com banco **PostgreSQL** em produção e SQLite
no desenvolvimento.

## Módulos

| Módulo | Situação | Conteúdo |
|---|---|---|
| Cadastros | ✅ pronto | Empresas, fornecedores, unidades de medida, insumos, composições de custo |
| Obras | ✅ pronto | Cadastro de obras por empresa, com status e datas |
| Orçamento | ✅ pronto | Orçamento por obra com versões, EAP hierárquica, BDI e tela de EAP |
| Suprimentos | ✅ pronto | Solicitação, cotação com mapa, pedido de compra, recebimento e relatório orçado × comprado |
| Financeiro | ⏳ próximo | Contas a pagar/receber, centros de custo, fluxo de caixa |
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

## Fluxo de compras (Suprimentos)

```
Solicitação ──aprovar──▶ Cotação ──mapa de cotação──▶ Pedidos ──aprovar──▶ Recebimentos
 (obra pede)            (fornecedores dão preço)    (1 por fornecedor/obra)  (notas fiscais)
```

1. **Solicitação de compra**: a obra lista os insumos de que precisa. Cada item
   pode ser apropriado a uma **etapa do orçamento**. Depois é aprovada (ação
   na lista de solicitações).
2. **Cotação**: na lista de solicitações, selecione as aprovadas e use
   *"Gerar cotação"*. Adicione os fornecedores na cotação e abra o **mapa de
   cotação** para digitar os preços. O menor preço de cada item fica destacado.
3. **Pedidos**: no mapa, *"Salvar e gerar pedidos pelo menor preço"* cria um
   pedido por fornecedor e obra, em rascunho. Revise e aprove.
4. **Recebimento**: no pedido aprovado, use *"Registrar recebimento"*. Os
   itens com saldo já aparecem listados; basta digitar o que chegou. O pedido
   passa a *entregue parcialmente* ou *entregue* sozinho, e não é possível
   receber mais do que foi pedido.

Itens que ficaram sem preço, ou pedidos cancelados, voltam como saldo na
solicitação e podem ser cotados de novo.

O relatório **Orçado × comprado** (link na tela da EAP) compara, por etapa, o
custo orçado com o valor dos pedidos aprovados.

## Como rodar localmente

Pré-requisito: Python 3.11 ou mais novo.

```bash
python3 -m venv .venv
source .venv/bin/activate          # no Windows: .venv\Scripts\activate
pip install -r requirements.txt

python manage.py migrate           # cria o banco
python manage.py carregar_exemplo  # opcional: obra, orçamento e um ciclo de compras de exemplo
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
cadastros/   empresas, fornecedores, unidades, insumos, composições
obras/       obras
orcamento/   orçamentos, EAP, itens e a tela de EAP
suprimentos/ solicitações, cotações, pedidos, recebimentos
             (regras de negócio em suprimentos/services.py)
```
