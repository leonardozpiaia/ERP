# ERP Obras

ERP para construtoras e incorporadoras, no estilo do Sienge. Tudo gira em
torno da **obra**: orçamento, compras, custos e financeiro ficam apropriados
a ela, o que permite comparar o **orçado com o realizado**.

Feito em **Python + Django**, com banco **PostgreSQL** em produção e SQLite
no desenvolvimento.

## Módulos

| Módulo | Situação | Conteúdo |
|---|---|---|
| Cadastros | ✅ pronto | Empresas, fornecedores, clientes, unidades de medida, insumos, composições de custo |
| Obras | ✅ pronto | Cadastro de obras por empresa, com status e datas |
| Orçamento | ✅ pronto | Orçamento por obra com versões, EAP hierárquica, BDI e tela de EAP |
| Suprimentos | ✅ pronto | Solicitação, cotação com mapa, pedido de compra, recebimento e relatório orçado × comprado |
| Financeiro | ✅ pronto | Contas a pagar e a receber, baixas, contas bancárias, plano financeiro, apropriação por etapa, fluxo de caixa |
| Contratos e medições | ✅ pronto | Contratos de empreitada, medições, boletim, retenções (caução/INSS/ISS), encerramento |
| Comercial | ✅ pronto | Unidades, espelho de vendas, contratos com séries de parcelas, reajuste por índice, distrato |

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

O relatório **Orçado × realizado** (link na tela da EAP) compara, por etapa, o
custo orçado com o valor dos pedidos aprovados e das medições de empreiteiros.

## Financeiro

- **Títulos a pagar e a receber**, divididos em **parcelas**. Cada parcela é
  quitada por uma ou mais **baixas** (pagamento/recebimento), com juros,
  multa e desconto, sempre em uma **conta bancária** da mesma empresa.
- **Integração com Suprimentos**: ao registrar um recebimento, o título a
  pagar é gerado sozinho. As parcelas seguem a condição de pagamento do
  pedido ("30/60/90 dias" = 3 parcelas a partir da data do recebimento) e o
  título já sai **apropriado por etapa** conforme os itens da nota. Depois
  disso o recebimento não pode mais ser alterado.
- **Parcelas e baixas**: a tela do dia a dia. Filtros por situação (vencidas,
  vencem em 7 dias, em aberto, quitadas), por obra e por vencimento. Selecione
  várias e use *"Baixar parcelas selecionadas"* para quitar tudo de uma vez,
  ou abra uma parcela para lançar baixa parcial ou com juros. Para estornar,
  exclua a baixa.
- Depois da primeira baixa, as parcelas do título ficam travadas.
- **Fluxo de caixa**: por dia, semana ou mês, com o realizado (baixas), o
  previsto (parcelas em aberto), os vencidos em aberto e o saldo acumulado a
  partir do saldo bancário. Filtra por empresa e por obra.
- O relatório **Orçado × comprado** ganhou a coluna **pago**.

Os relatórios ficam no topo do painel inicial.

## Comercial (incorporação)

- **Unidades** de cada empreendimento (a obra), com bloco, andar, área,
  dormitórios, preço de tabela e situação: disponível, reservada, vendida ou
  bloqueada.
- **Espelho de vendas**: mapa das unidades por bloco e andar, colorido pela
  situação, com total de unidades, % vendido, VGV, valor vendido e recebido.
  Clicar numa unidade disponível já abre um contrato para ela.
- **Contrato de venda**: cliente, valor, índice de reajuste (INCC, IGP-M,
  IPCA ou nenhum) e a condição de pagamento em **séries de parcelas**
  (ex.: 1 entrada + 36 mensais + 3 intermediárias anuais + chaves +
  financiamento). A soma das séries precisa fechar com o valor do contrato.
- **Efetivar** (ação na lista de contratos): gera as parcelas no contas a
  receber e marca a unidade como vendida. Uma unidade só pode ter um contrato
  vigente, e contrato efetivado não pode ser excluído.
- **Reajuste**: cadastre a variação mensal dos índices e use *"Aplicar
  reajustes pendentes"*. A variação de cada mês após a data-base corrige o
  saldo em aberto das parcelas que vencem depois daquele mês. Cada mês é
  aplicado uma única vez, com histórico do saldo antes e depois.
- **Distrato** (com tela de confirmação): a unidade volta a ficar disponível,
  as parcelas não pagas são excluídas e as pagas em parte ficam só com o
  valor recebido. A devolução ao cliente, se houver, é lançada em contas a
  pagar.

## Contratos e medições (empreiteiros)

- **Contrato de empreitada**: obra, empreiteiro, objeto, itens de serviço
  (quantidade, unidade, preço e etapa do orçamento), prazo de pagamento e
  retenções em %: **caução** (retenção técnica), **INSS** e **ISS**.
  *"Ativar"* libera o contrato para medições. Com o contrato ativo é possível
  fazer aditivos: incluir itens ou aumentar quantidades (nunca abaixo do já
  medido).
- **Medição**: no contrato, *"Nova medição"* já lista os serviços com saldo;
  basta digitar o executado no período. Não é possível medir além do
  contratado: medições em elaboração também reservam saldo.
- **Aprovar** a medição gera o título a pagar ao empreiteiro pelo **valor
  líquido** (bruto - caução - INSS - ISS), com vencimento pelo prazo do
  contrato e apropriação por etapa. *"Reabrir"* desfaz a aprovação enquanto
  o título não tiver pagamentos.
- **Boletim de medição** para imprimir e assinar: contratado, anterior,
  nesta medição, acumulado, saldo e % executado por serviço, com as
  retenções e o líquido.
- **Encerrar** o contrato gera o título de **devolução da caução** retida.
- **Retenções de medições**: relatório por período com o INSS e o ISS a
  recolher e a caução retida.
- O relatório da obra virou **Orçado × realizado**: comprado (pedidos) +
  medido (empreiteiros), saldo, % realizado e pago, por etapa.

## Colocar no ar (produção)

O guia completo, passo a passo, está em **[DEPLOY.md](DEPLOY.md)**. Em resumo,
em um servidor com Docker:

```bash
cp .env.exemplo .env   # preencha domínio, chave secreta e senha do banco
docker compose up -d --build
docker compose exec web python manage.py createsuperuser
```

Isso sobe o sistema com PostgreSQL, HTTPS automático (Caddy) e backup diário
do banco. Ao iniciar, o sistema aplica as mudanças no banco e atualiza os
**perfis de acesso** (Diretoria, Engenharia, Compras, Financeiro,
Comercial), definidos em `config/perfis.py`. As telas de relatório também
respeitam os perfis.

## Testar no seu computador (sem instalar nada além do Python)

1. Instale o **Python 3.12 ou mais novo** em https://www.python.org/downloads/.
   No Windows, marque **"Add python.exe to PATH"** na primeira tela do instalador.
2. Baixe o projeto (no GitHub: botão **Code → Download ZIP**) e descompacte.
3. Dê dois cliques em:
   - **Windows:** `iniciar-windows.bat`
   - **Mac:** `iniciar-mac-linux.command` (se o Mac bloquear, clique com o botão
     direito → Abrir → Abrir)
4. Na primeira vez leva alguns minutos. Depois o navegador abre sozinho em
   http://127.0.0.1:8000. Entre com usuário **admin** e senha **admin**.

O sistema já vem com os dados de exemplo (obra "Residencial Exemplo"). Para
começar do zero, apague o arquivo `db.sqlite3` da pasta e rode o
iniciador com a opção `limpo` (no Windows: `iniciar-windows.bat limpo` no
Prompt de Comando). Enquanto a janela preta estiver aberta, o sistema está
no ar; feche-a para encerrar. Os dados ficam salvos no `db.sqlite3` entre um
uso e outro.

> Isto é só para teste: o usuário `admin`/`admin` e o banco em arquivo não
> são seguros para uso real. Para a equipe usar, veja [DEPLOY.md](DEPLOY.md).

## Como rodar localmente (desenvolvedores)

Pré-requisito: Python 3.11 ou mais novo.

```bash
python3 -m venv .venv
source .venv/bin/activate          # no Windows: .venv\Scripts\activate
pip install -r requirements.txt

python manage.py migrate           # cria o banco
python manage.py carregar_exemplo  # opcional: dados de exemplo de todos os módulos
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
| `DJANGO_CSRF_TRUSTED_ORIGINS` | *(vazio)* | Endereços com `https://` de onde vêm os formulários |
| `DATABASE_URL` | *(vazio)* | Endereço completo do PostgreSQL (`postgres://usuario:senha@servidor:5432/banco`); tem prioridade |
| `POSTGRES_DB` | *(vazio)* | Se definido, usa PostgreSQL em vez de SQLite |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_HOST` / `POSTGRES_PORT` | `postgres` / vazio / `localhost` / `5432` | Conexão com o PostgreSQL |

## Estrutura

```
config/      configurações do projeto e rotas principais
cadastros/   empresas, fornecedores, clientes, unidades, insumos, composições
obras/       obras
orcamento/   orçamentos, EAP, itens e a tela de EAP
suprimentos/ solicitações, cotações, pedidos, recebimentos
             (regras de negócio em suprimentos/services.py)
financeiro/  títulos, parcelas, baixas, contas bancárias, fluxo de caixa
             (regras de negócio em financeiro/services.py)
comercial/   unidades, espelho de vendas, contratos, reajustes, distrato
             (regras de negócio em comercial/services.py)
contratos/   contratos de empreitada, medições, boletim, retenções
             (regras de negócio em contratos/services.py)
templates/   ajustes nas telas do painel (relatórios na página inicial)
config/      configurações, rotas, perfis de acesso (perfis.py) e /saude/
deploy/      script de inicialização, backup, restauração e Caddyfile
```
