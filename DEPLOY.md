# Colocando o ERP Obras no ar

Este guia sobe o sistema em um servidor próprio (VPS) com **um único
comando**. O pacote já inclui:

- o sistema (Django + Gunicorn);
- o banco de dados **PostgreSQL**;
- **HTTPS automático** (Caddy: o certificado é emitido e renovado sozinho);
- **backup diário** do banco, guardando os últimos 14 dias.

Tempo estimado: 1 hora, na primeira vez.

## 1. O que você precisa

1. **Um servidor (VPS)** com Ubuntu 24.04, pelo menos **2 GB de RAM** e
   20 GB de disco. Prefira um datacenter **em São Paulo**: o sistema fica
   mais rápido para a equipe e os dados ficam no Brasil (LGPD). Vários
   provedores oferecem isso (por exemplo AWS Lightsail, Vultr, Magalu Cloud,
   Locaweb); compare preço e suporte. **Ative os snapshots/backup automáticos
   do provedor**, se houver: é uma segunda proteção além do backup do sistema.
2. **Um domínio ou subdomínio**, por exemplo `erp.suaempresa.com.br`. No
   painel onde o domínio está registrado, crie um **registro DNS do tipo A**
   apontando esse nome para o **IP do servidor**.
3. Acesso ao servidor por **SSH** (o provedor informa usuário, IP e senha ou chave).

## 2. Preparar o servidor (uma vez)

Conecte-se ao servidor (`ssh root@IP-DO-SERVIDOR`) e rode:

```bash
# Atualiza o sistema e instala o Docker
apt update && apt upgrade -y
curl -fsSL https://get.docker.com | sh

# Firewall: libera só SSH, HTTP e HTTPS
ufw allow OpenSSH && ufw allow 80 && ufw allow 443 && ufw --force enable

# Baixa o ERP
git clone https://github.com/leonardozpiaia/ERP.git /opt/erp
cd /opt/erp
```

> Se o repositório for privado, o `git clone` vai pedir usuário e um
> *token de acesso* do GitHub (Settings → Developer settings → Personal
> access tokens), no lugar da senha.

## 3. Configurar

```bash
cp .env.exemplo .env
python3 -c "import secrets; print(secrets.token_urlsafe(50))"   # chave secreta
python3 -c "import secrets; print(secrets.token_urlsafe(24))"   # senha do banco
nano .env
```

No `.env`, preencha:

| Variável | O que colocar |
|---|---|
| `DOMINIO` | o domínio, ex.: `erp.suaempresa.com.br` |
| `DJANGO_ALLOWED_HOSTS` | o mesmo domínio |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | o domínio com `https://` na frente |
| `DJANGO_SECRET_KEY` | a primeira sequência gerada acima |
| `POSTGRES_PASSWORD` | a segunda sequência gerada acima |

Salve (Ctrl+O, Enter) e saia (Ctrl+X). **Guarde uma cópia do `.env` em local
seguro** (um gerenciador de senhas, por exemplo): sem ele não é possível
recuperar o sistema em outro servidor. Nunca envie o `.env` para o GitHub.

## 4. Subir o sistema

```bash
docker compose up -d --build
```

Na primeira vez leva alguns minutos. Para acompanhar: `docker compose logs -f web`
(Ctrl+C para sair). Quando aparecer `Booting worker`, o sistema está no ar.

Confira em `https://erp.suaempresa.com.br/saude/`, que deve mostrar `{"status": "ok"}`.

## 5. Criar o primeiro acesso

```bash
docker compose exec web python manage.py createsuperuser
```

Informe usuário, e-mail e uma senha forte. Esse é o **administrador**: ele
pode tudo, inclusive criar os outros usuários. Entre em
`https://erp.suaempresa.com.br` com ele.

## 6. Cadastrar a equipe

No painel, vá em **Usuários → Adicionar**. Depois de definir usuário e senha:

1. marque **Membro da equipe** (sem isso a pessoa não consegue entrar);
2. em **Grupos**, escolha o perfil;
3. salve.

| Perfil | Pode alterar | Pode consultar |
|---|---|---|
| **Diretoria** | nada | tudo |
| **Engenharia** | obras, orçamentos, contratos e medições, insumos e composições, solicitações de compra, recebimentos | suprimentos, empresas, fornecedores |
| **Compras** | suprimentos (cotações, pedidos...), fornecedores, insumos | obras, orçamentos, contratos |
| **Financeiro** | contas a pagar e a receber, baixas, contas bancárias, fornecedores, clientes | todos os outros módulos |
| **Comercial** | unidades, contratos de venda, índices, clientes | obras, contas a receber |

Uma pessoa pode ter mais de um perfil. Os perfis são atualizados
automaticamente a cada atualização do sistema; para mudar o que cada perfil
pode fazer, altere `config/perfis.py`.

> Dica: não use o administrador no dia a dia. Crie um usuário para você com
> o perfil Diretoria (ou o que fizer sentido) e guarde o administrador para
> cadastrar pessoas.

## 7. Backups

- Um backup completo do banco é gerado **todo dia** na pasta
  `/opt/erp/backups` (arquivos `erp-AAAA-MM-DD_HHMM.dump`), e os mais antigos
  que 14 dias são apagados (ajuste `BACKUP_DIAS` no `.env`).
- **Importante:** esses arquivos ficam no próprio servidor. Se o servidor
  for perdido, eles vão junto. Por isso ative os snapshots do provedor e,
  de tempos em tempos, baixe uma cópia para outro lugar:
  `scp root@IP-DO-SERVIDOR:/opt/erp/backups/erp-*.dump .`
- Junto com cada backup do banco é gerado o arquivo dos **anexos** (notas
  fiscais): `erp-AAAA-MM-DD_HHMM-anexos.tar.gz`. Para restaurá-los:

  ```bash
  docker compose run --rm -v "$PWD/backups:/b" --entrypoint sh web \
    -c 'tar -xzf /b/erp-AAAA-MM-DD_HHMM-anexos.tar.gz -C /app/media'
  ```

- Para **restaurar** um backup (substitui todos os dados atuais):

  ```bash
  cd /opt/erp
  sh deploy/restaurar.sh backups/erp-AAAA-MM-DD_HHMM.dump
  ```

  O script pede para digitar `RESTAURAR` antes de continuar.

## 8. Atualizar o sistema

Quando houver uma nova versão no GitHub:

```bash
cd /opt/erp
git pull
docker compose up -d --build
```

As mudanças no banco são aplicadas sozinhas ao subir. Por segurança,
antes de atualizar gere um backup na hora:

```bash
docker compose exec backup sh -c 'pg_dump -h db -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc -f /backups/antes-da-atualizacao.dump'
```

## 9. Comandos úteis

| Para | Comando |
|---|---|
| Ver se tudo está rodando | `docker compose ps` |
| Ver os registros do sistema | `docker compose logs -f web` |
| Reiniciar o sistema | `docker compose restart web` |
| Parar tudo | `docker compose down` (os dados continuam salvos) |
| Carregar dados de exemplo (só em ambiente de teste!) | `docker compose exec web python manage.py carregar_exemplo` |

## Problemas comuns

- **O site não abre / erro de certificado:** confira se o registro DNS aponta
  para o IP do servidor (pode levar até algumas horas para propagar) e se as
  portas 80 e 443 estão liberadas. Veja `docker compose logs caddy`.
- **"Bad Request (400)":** o domínio acessado não está em `DJANGO_ALLOWED_HOSTS`.
- **"Proibido (403) - verificação CSRF":** falta o endereço com `https://` em
  `DJANGO_CSRF_TRUSTED_ORIGINS`.
- **O sistema não sobe e o log fala em `DJANGO_SECRET_KEY`:** a chave secreta
  não foi preenchida no `.env`.
