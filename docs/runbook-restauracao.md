# 🚑 Runbook: restauração do banco (o dia que der ruim)

Guia curto para o dia do desastre. Detalhe completo de implantação:
[implantacao-producao.md](implantacao-producao.md#-operação-monitoramento-e-backup).

## O que existe de proteção hoje

| Camada | O que é | Frequência | Guardado onde | Volta até |
|--------|---------|------------|---------------|-----------|
| Backup do app (`flask backup`) | Dump `pg_dump` comprimido | Diário, 03:20 (`sigere-backup.timer`) | Pasta `backups/` da VM + bucket S3 quando `BACKUP_S3_BUCKET` configurado | 7 diárias + 4 semanais (~35 dias) |
| Verificação (`flask verify-restore`) | Restaura o mais recente num banco descartável e compara com produção | Junto do backup diário | — (prova, não guarda) | — |

**Não existe PITR** (replay de WAL): restaura-se no ponto de um snapshot — não
"no horário 14h32 de ontem". Não há backup gerenciado do provedor: a VM é
Oracle Cloud autogerenciada; o bucket S3 é a única cópia fora do servidor.

## Quanto tempo leva

- **Snapshot mais recente, banco atual:** segundos a poucos minutos. O número
  real está no journal do timer ou rodando
  `flask --app run verify-restore` — ele mede e imprime o tempo de restauração.
- **Somar:** parar serviços (1 min) → restaurar (o tempo medido) → subir e
  checar (5 min). **Cenário típico: menos de 15 minutos ponta a ponta** com o
  banco no tamanho atual; cresce com o volume de dados.

## O que eu perco

- **Tudo gerado depois do último backup bom** — pior caso ~24 h (backup roda
  03:20): reservas criadas/alteradas no período, contas novas, notificações,
  trilha de auditoria do intervalo.
- **O que não se perde:** tudo que já estava no snapshot — usuários, salas,
  reservas passadas, feriados, permissões (senhas são hash; ninguém as vê).
- **Fora do backup:** `app/static/uploads/` (arquivos enviados) **não** vai no
  dump — sincronize a pasta à parte (ex.: `rclone sync` semanal para o mesmo
  bucket) se os anexos importarem.

## Antes do dia ruim (checklist único)

1. `BACKUP_S3_BUCKET` configurado no `.env` da VM e ao menos um objeto no
   bucket (`aws s3 ls s3://MEU-BUCKET/sigere/` ou console do provedor).
2. `sudo systemctl list-timers sigere-backup*` mostra próximo disparo e a
   última execução **sem falha** (`sudo journalctl -u sigere-backup.service -n 50`).
3. `venv/bin/flask --app run verify-restore` já rodou verde ao menos uma vez
   (inclui `ALTER USER sigere WITH CREATEDB;` quando pedirem a permissão).
4. Saber de cor: `.env` da VM tem a `DATABASE_URL` correta e a chave do bucket.

## O dia ruim — PostgreSQL (produção)

> **Importante sobre o `verify-restore`:** ele compara o snapshot com a
> **produção atual** — é garantia diária, não ferramenta de triagem de
> desastre. Se a produção foi apagada, a aplicação nem sobe para ele rodar;
> se a causa foi um DELETE acidental, a comparação reprova justamente o
> snapshot bom de antes do erro. Nesses cenários, baixe o snapshot direto do
> bucket (cópia fora do servidor) e escolha pela data no nome do arquivo —
> não espere uma conferência verde contra a produção atual.

```bash
cd /var/www/sigere

# 1. Congelar o estado: nada escreve no banco durante a restauração.
#    (guarda: se um stop falhar, a restauração NÃO começa — banco ainda em uso)
# stop com recuperação para host SEM as units (CodeRabbit #243): cada unit é
# parada SEPARADAMENTE e avaliada por si — o stop combinado falhava pelo
# nginx ausente mesmo com o sigere parado, e o aborte geral bloqueava o host
# que só tem o sigere. Unit EXISTENTE que não para continua ABORTANDO; a
# CONSULTA das units falhando também ABORTA (não dá para distinguir ausência
# de falha); unit inexistente (dev) só segue com confirmação explícita de
# que NADA escreve no banco — o bloco colado inteiro não passa sem digitar.
# Consulta ÚNICA, com a saída capturada e o retorno checado:
stop_ok_nginx=0; stop_ok_sigere=0
sudo systemctl stop nginx 2>/dev/null && stop_ok_nginx=1
sudo systemctl stop sigere 2>/dev/null && stop_ok_sigere=1
if [ "$stop_ok_nginx" = 0 ] || [ "$stop_ok_sigere" = 0 ]; then
  UNITS_INSTALADAS="$(systemctl list-unit-files)" \
    || { echo '❌ Falhou a consulta das units (systemctl) — ABORTE: não é possível distinguir unit ausente de falha do systemctl. Verifique o ambiente.'
         exit 1; }
  if [ "$stop_ok_nginx" = 0 ] && grep -qE '^nginx\.service' <<< "$UNITS_INSTALADAS"; then
    echo '❌ Não conseguiu parar o nginx — ABORTE: restaurar com o banco em uso corrompe os dados. Resolva o stop antes de prosseguir.'
    exit 1
  fi
  if [ "$stop_ok_sigere" = 0 ] && grep -qE '^sigere\.service' <<< "$UNITS_INSTALADAS"; then
    echo '❌ Não conseguiu parar o sigere — ABORTE: restaurar com o banco em uso corrompe os dados. Resolva o stop antes de prosseguir.'
    exit 1
  fi
  { if ! read -r -p 'Unit(s) ausentes (host de dev). NENHUM processo (gunicorn, psql, flask shell) pode escrever no banco? Digite SEGURO para prosseguir: ' CONFIRMACAO_ESCRITORES \
         || [ "$CONFIRMACAO_ESCRITORES" != "SEGURO" ]; then
    echo '❌ ABORTE — confira os processos que podem escrever no banco e recomece do passo 1.'
    exit 1
  fi
  }
fi
sudo systemctl status nginx sigere 2>/dev/null || true   # inactive (dead) ou inexistente no dev

# 2. Escolher o backup — mais novo primeiro, pelo CARIMBO DO NOME (mtime
#    mente: um snapshot antigo baixado agora do bucket apareceria na frente):
ls -1 backups/sigere-*.gz | sort -r | head
# backups/ indisponível ou comprometido? baixe do bucket:
#   aws s3 cp "s3://MEU-BUCKET/sigere/sigere-AAAAMMDD-HHMMSS-postgres.sql.gz" backups/
#   (ou pelo console do provedor; rclone também serve)

# 3. Extrair e validar ANTES de tocar na produção — num pipeline
#    `gunzip | psql`, o gunzip com arquivo errado falha "quieto", o psql
#    recebe entrada vazia e TERMINA BEM — com a produção já dropada.
#    mktemp -d cria pasta PRIVADA (0700): o dump é confidencial — nada
#    world-readable em /tmp — e sai do disco no fim do procedimento:
BACKUP=backups/sigere-AAAAMMDD-HHMMSS-postgres.sql.gz
PASTA_TRABALHO="$(mktemp -d)"
gunzip -tc "$BACKUP" && gunzip -c "$BACKUP" > "$PASTA_TRABALHO/restaurado.sql" \
  || { echo "❌ Extração falhou — o caminho do BACKUP existe?"; rm -rf "$PASTA_TRABALHO"; exit 1; }
ls -l "$PASTA_TRABALHO/restaurado.sql"      # tem de ser maior que zero
[ -s "$PASTA_TRABALHO/restaurado.sql" ] \
  || { echo "❌ Extração produziu arquivo vazio"; rm -rf "$PASTA_TRABALHO"; exit 1; }
# falhou em qualquer passo acima? PARE — produção intacta, serviços
# parados; tente outro snapshot.

# Guarda nos dois (CodeRabbit #243): dropdb barrado por conexão ativa deixa
# o banco de pé — o createdb falharia por já existir e, sem o guarda, o psql
# rodaria sobre o banco ANTIGO (erro de SQL no meio do dump deixaria
# mudanças parciais na produção). São mundos diferentes (CodeRabbit #243):
# dropdb falhou = produção INTACTA; createdb falhou = o banco NÃO EXISTE.
sudo -u postgres dropdb --if-exists sigere \
  || { echo "❌ dropdb falhou — o banco pode estar em uso (outra conexão ativa). Restauração NÃO começa; produção INTACTA; confira quem conecta: sudo -u postgres psql -c 'SELECT pid, application_name FROM pg_stat_activity'"; rm -rf "$PASTA_TRABALHO"; exit 1; }
# A PARTIR DAQUI A PRODUÇÃO NÃO EXISTE MAIS — o dropdb acima a apagou. Se o
# createdb falhar, sigere e nginx seguem PARADOS e o caminho de volta é
# RECRIAR o banco e RODAR DE NOVO este bloco de restauração (CodeRabbit
# #243) — nada de "segue intacta":
sudo -u postgres createdb -O sigere sigere \
  || { echo "❌ createdb falhou — o banco de produção NÃO EXISTE (o dropdb acima o apagou). Sigere e nginx seguem PARADOS: recree com 'sudo -u postgres createdb -O sigere sigere' e rode este bloco de restauração de novo (passo 2 em diante) antes de subir qualquer serviço."; rm -rf "$PASTA_TRABALHO"; exit 1; }
# --no-psqlrc: o ~/.psqlrc do operador não pode desligar o ON_ERROR_STOP
# (\set ON_ERROR_STOP off nele deixaria restauração pela metade "passar bem").
psql --no-psqlrc --set=ON_ERROR_STOP=1 -f "$PASTA_TRABALHO/restaurado.sql" \
  "postgresql://sigere:SENHA@localhost:5432/sigere" || {
  echo "❌ Restauração falhou no meio — recrie (dropdb/createdb) e tente o snapshot anterior"
  rm -rf "$PASTA_TRABALHO"
  exit 1
}
rm -rf "$PASTA_TRABALHO"
# alternativa guiada: python setup_interativo.py  →  modo 3 "Restaurar backup"

# 4. Alinhar schema e permissões ANTES de abrir o serviço — o snapshot pode
#    ser anterior a uma migration do código atual, e o app atual contra
#    schema antigo quebra na frente do usuário:
set -a; source .env; set +a
venv/bin/flask --app run db upgrade \
  || { echo '❌ db upgrade falhou — NÃO suba o serviço: app atual contra schema antigo quebra na frente do usuário. nginx e sigere seguem PARADOS até resolver.'; exit 1; }
# revogações de propósito feitas DEPOIS do snapshot morreram com ele —
# reaplique e confira SEMPRE, mesmo sem mudança de código, ANTES de abrir o
# serviço — rota OFFLINE, pois o Painel Admin → Papéis exige o serviço no
# ar: Flask shell via SSH, com nginx e sigere PARADOS (procedimento
# completo na doc de implantação, seção «Atualizando a aplicação»). O
# `sync-permissions` é que fica condicionado ao código avançado — rode-o
# ANTES de reaplicar as revogações.
# Falhou aqui? Mantenha nginx e sigere PARADOS até resolver.

# 5. Subir e checar — GATE (CodeRabbit #243): as revogações acima são
#    trabalho MANUAL; o bloco inteiro colado não pode subir o serviço sem
#    a conferência:
# GATE (CodeRabbit #243): confirmação e start no MESMO comando composto —
# colando o bloco inteiro, o read não pode consumir a linha seguinte e
# subir o serviço sem a conferência manual:
{ if ! read -r -p 'Revogações reaplicadas e conferidas? Digite CONFIRMO para subir o sigere: ' CONFIRMACAO_PERMISSOES \
       || [ "$CONFIRMACAO_PERMISSOES" != "CONFIRMO" ]; then
  echo '❌ Serviço segue PARADO — confira as permissões (rota OFFLINE) e volte ao passo 5.'
  exit 1
fi
sudo systemctl start sigere
}
# Subida e checagem DIVERGEM por host (CodeRabbit #243): com a unit, journal
# + socket + nginx; SEM a unit (dev), o socket unix não existe e o servidor
# nativo OCUPA o terminal — os passos de produção abaixo abortariam à toa.
# Consulta capturada UMA vez, com o retorno checado (mesmo padrão do passo 1):
UNITS_INSTALADAS="$(systemctl list-unit-files)" \
  || { echo '❌ Falhou a consulta das units (systemctl) — ABORTE: não é possível decidir o caminho de subida. Verifique o ambiente.'
       exit 1; }
if grep -qE '^sigere\.service' <<< "$UNITS_INSTALADAS"; then
  sudo journalctl -u sigere -n 30 --no-pager
  # o gunicorn escuta em socket unix — teste direto nele ANTES de abrir o nginx
  # (CodeRabbit #243): curl falhando, o nginx segue FECHADO — abrir o mundo
  # para um app que não responde só empurra o erro para o usuário:
  curl -fsS --unix-socket /run/sigere/sigere.sock -o /dev/null -w '%{http_code}\n' http://localhost/ \
    || { echo "❌ O sigere não respondeu no socket unix — nginx segue PARADO; confira o journal acima e tente de novo."; exit 1; }
  sudo systemctl start nginx
  # smoke test no navegador: login de um usuário real + abrir cronograma + criar/editar uma reserva.
  # GATE (CodeRabbit #243): o MESMO portão do ramo dev — o curl só atesta o
  # socket, não a aplicação; o backup do passo 6 roda a retenção, e um
  # snapshot antigo na borda da janela poderia sair antes de o smoke test
  # confirmar a aplicação restaurada. Colado, o bloco não passa sem digitar:
  { if ! read -r -p 'Smoke test OK? Digite CONFIRMO para gerar o backup: ' CONFIRMACAO_SMOKE \
         || [ "$CONFIRMACAO_SMOKE" != "CONFIRMO" ]; then
    echo '❌ Backup adiado — faça o smoke test e rode o passo 6 de novo.'
    exit 1
  fi
  }
else
  # DEV (sem unit): o servidor nativo OCUPA o terminal em que roda — inicie
  # em um terminal PRÓPRIO carregando o ambiente ANTES (as exportações do
  # passo 4 não atravessam terminais, e o app não chama load_dotenv — o
  # Config lê os.environ direto; CodeRabbit #243):
  #   cd /var/www/sigere
  #   set -a; source .env; set +a
  #   python run.py
  # (alternativa: `venv/bin/flask --app run run` — o CLI do Flask auto-carrega
  # o .env, pois python-dotenv está instalado; docs/desenvolvimento-debug.md)
  # e faça o smoke test DE OUTRO terminal/navegador enquanto ele permanece no
  # ar (login real + cronograma + criar/editar reserva) em
  # http://127.0.0.1:5000. Sem gunicorn não há socket unix nem nginx — pule
  # journalctl/curl/socket/nginx: não existem neste host.
  echo 'ℹ️  Host sem unit sigere (dev): num terminal próprio faça `set -a; source .env; set +a` e `python run.py`; o smoke test é de outro terminal/navegador em http://127.0.0.1:5000.'
  # GATE (CodeRabbit #243): o backup do passo 6 roda a retenção — um
  # snapshot antigo na borda da janela poderia sair antes de o smoke test
  # confirmar a aplicação restaurada. Colado, o bloco não passa sem digitar:
  { if ! read -r -p 'Smoke test OK? Digite CONFIRMO para gerar o backup: ' CONFIRMACAO_SMOKE \
         || [ "$CONFIRMACAO_SMOKE" != "CONFIRMO" ]; then
    echo '❌ Backup adiado — faça o smoke test e rode o passo 6 de novo.'
    exit 1
  fi
  }
fi

# 6. Regerar backup imediatamente e conferir o ciclo — a produção agora está
#    saudável, então a comparação contra ela é válida de novo:
venv/bin/flask --app run backup
venv/bin/flask --app run verify-restore
```

## O dia ruim — SQLite (desenvolvimento/avaliação)

```bash
# stop com recuperação para host SEM a unit (CodeRabbit #243): unit
# existente que não para continua ABORTANDO; a CONSULTA das units falhando
# também ABORTA; unit inexistente (dev) só segue com confirmação explícita —
# o bloco colado inteiro não passa sem digitar. Units consultadas UMA vez,
# com a saída capturada (mesmo guarda do bloco PostgreSQL):
if ! sudo systemctl stop sigere 2>/dev/null; then
  UNITS_INSTALADAS="$(systemctl list-unit-files)" \
    || { echo '❌ Falhou a consulta das units (systemctl) — ABORTE: não é possível distinguir unit ausente de falha do systemctl. Verifique o ambiente.'
         exit 1; }
  if grep -qE '^sigere\.service' <<< "$UNITS_INSTALADAS"; then
    echo '❌ Não conseguiu parar o sigere — ABORTE: restaurar com o banco em uso corrompe os dados. Resolva o stop antes de prosseguir.'
    exit 1
  fi
  { if ! read -r -p 'Unit ausente (host de dev). NENHUM processo (gunicorn, psql, flask shell) pode escrever no banco? Digite SEGURO para prosseguir: ' CONFIRMACAO_ESCRITORES \
         || [ "$CONFIRMACAO_ESCRITORES" != "SEGURO" ]; then
    echo '❌ ABORTE — confira os processos que podem escrever no banco e recomece do passo 1.'
    exit 1
  fi
  }
fi
# confira: status inactive (dead) ou inexistente no dev

# 1. Alvo da restauração = o banco que a DATABASE_URL aponta, com a MESMA
#    resolução do app (relativo cai na instance/, absoluto fica como está —
#    o helper _caminho_sqlite): restaurar por hábito num reservation.db do
#    diretório corrente pode substituir o arquivo errado. Usa um Flask
#    descartável — NÃO abre o banco, que pode estar corrompido justamente
#    neste cenário (o boot da aplicação inspecionaria as tabelas):
BANCO_ATUAL="$(venv/bin/python -c "
from dotenv import load_dotenv; load_dotenv()
from app.config import Config
from app.backup import _caminho_sqlite, _interpretar_uri
from flask import Flask
uri = Config.SQLALCHEMY_DATABASE_URI
_, dados = _interpretar_uri(uri)
print(_caminho_sqlite(dados, Flask(__name__)))
")"
echo "Banco atual: $BANCO_ATUAL"

# 2. Extrair num arquivo privado (mktemp -d, 0700) e EXIGIR sucesso — o
#    `> reservation.db` direto trunca o banco atual antes de o gunzip
#    reclamar de caminho errado; e um BACKUP ausente criaria arquivo VAZIO
#    (SQLite abre arquivo vazio e integrity_check responde 'ok'):
BACKUP=backups/sigere-AAAAMMDD-HHMMSS-sqlite.sqlite.gz
PASTA_TRABALHO="$(mktemp -d)"
gunzip -c "$BACKUP" > "$PASTA_TRABALHO/sigere-restaurado.sqlite" \
  || { echo "❌ Extração falhou — o caminho do BACKUP existe?"; rm -rf "$PASTA_TRABALHO"; exit 1; }
[ -s "$PASTA_TRABALHO/sigere-restaurado.sqlite" ] \
  || { echo "❌ Extração produziu arquivo vazio"; rm -rf "$PASTA_TRABALHO"; exit 1; }

# 3. Validar a integridade do extraído e SÓ SEGUIR com 'ok' — num bloco
#    colado, o procedimento continuaria e substituiria o banco por um
#    snapshot inválido:
INTEGRIDADE="$(venv/bin/python -c "import sqlite3; print(sqlite3.connect('$PASTA_TRABALHO/sigere-restaurado.sqlite').execute('PRAGMA integrity_check').fetchone()[0])")"
if [ "$INTEGRIDADE" != "ok" ]; then
  echo "❌ integrity_check: $INTEGRIDADE — NÃO substitua; tente outro snapshot."
  rm -rf "$PASTA_TRABALHO"
  exit 1
fi

# 4. Preservar o estado ruim PARA ANÁLISE e limpar o caminho — um journal
#    quente (-journal/-wal/-shm do banco do desastre) ao lado do arquivo
#    restaurado seria REPRODUZIDO pelo SQLite por cima das páginas novas:
#    o estado ruim vai embora inteiro, e nada de sidecar pode sobrar no nome
#    de destino (sem sidecars, os mv opcionais apenas não fazem nada):
# o banco atual pode nem existir (host novo, disco formatado) — só preserva
# quando existe; se a preservação falhar, PARA antes de qualquer substituição
# — senão o mv de instalação apagaria o estado ruim antes da análise.
# PRÉ-CHECAGEM de TODOS os destinos antes de QUALQUER mv (CodeRabbit #243):
# guardas durante o lote moviam o banco/-journal antes de uma colisão
# posterior no -wal abortar, e o aviso "nada foi movido" não correspondia ao
# estado real. Colisão em QUALQUER destino com fonte a mover = aborte SEM
# mover nada — mesmo contrato do guard do .bak-dia-ruim:
if [ -e "$BANCO_ATUAL" ] && [ -e "$BANCO_ATUAL.bak-dia-ruim" ]; then
  echo "❌ $BANCO_ATUAL.bak-dia-ruim já existe — preservação de restauração anterior. O mv abaixo o sobrescreveria com o banco desta rodada; confira/realoque o .bak e só então recomece (banco atual NÃO substituído; snapshot extraído preservado em $PASTA_TRABALHO)."
  exit 1
fi
for sufixo in journal wal shm; do
  # Retry destrutivo nos sidecars: a fonte órfã (banco atual ausente, -wal
  # sobrando) com preservação anterior no destino a SOBRESCREVIA:
  if [ -f "$BANCO_ATUAL-$sufixo" ] && [ -e "$BANCO_ATUAL.bak-dia-ruim-$sufixo" ]; then
    echo "❌ $BANCO_ATUAL.bak-dia-ruim-$sufixo já existe — preservação de restauração anterior. O mv abaixo a sobrescreveria; confira/realoque e só então recomece (nada foi movido; snapshot extraído preservado em $PASTA_TRABALHO)."
    exit 1
  fi
done
if [ -e "$BANCO_ATUAL" ]; then
  mv "$BANCO_ATUAL" "$BANCO_ATUAL.bak-dia-ruim" \
    || { echo "❌ Preservação falhou — banco atual NÃO substituído; snapshot extraído preservado em $PASTA_TRABALHO"; exit 1; }
fi
for sufixo in journal wal shm; do
  # bloco if, não `&& ... || ...`: com `||`, a ausência do sidecar (teste
  # falso) dispararia o ramo de erro. Falha no mv PARA — um -journal/-wal
  # antigo sobrando no nome de destino seria REPRODUZIDO pelo SQLite por
  # cima das páginas novas (as colisões de destino já foram barradas na
  # pré-checagem acima, antes de qualquer mv):
  if [ -f "$BANCO_ATUAL-$sufixo" ]; then
    mv "$BANCO_ATUAL-$sufixo" "$BANCO_ATUAL.bak-dia-ruim-$sufixo" \
      || { echo "❌ Preservação de $BANCO_ATUAL-$sufixo falhou — banco atual NÃO substituído; snapshot extraído preservado em $PASTA_TRABALHO"; exit 1; }
  fi
done
# 0600 antes de sair da pasta privada (0700): entre o mv e o chown/chmod do
# bloco seguinte — sudo pode esperar senha — o arquivo já instalado não fica
# legível para os demais usuários; o modo FINAL vem do .bak logo em seguida:
chmod 600 "$PASTA_TRABALHO/sigere-restaurado.sqlite"
mv "$PASTA_TRABALHO/sigere-restaurado.sqlite" "$BANCO_ATUAL" \
  || { echo "❌ Instalação falhou — snapshot extraído preservado em $PASTA_TRABALHO"; exit 1; }
# dono e permissões do arquivo movido para o .bak — o extraído herda o do
# operador; se o serviço rodar com outro usuário, ele não escreveria (com
# umask restritivo, nem leria) o banco restaurado. Falhou aqui? O serviço
# não pode abrir banco inacessível — o procedimento PARA antes de qualquer
# start:
if [ -f "$BANCO_ATUAL.bak-dia-ruim" ]; then
  sudo chown --reference="$BANCO_ATUAL.bak-dia-ruim" "$BANCO_ATUAL" \
    || { echo "❌ chown falhou — sigere segue PARADO; ajuste dono e permissão à mão (modo do .bak: stat -c %a) e continue do passo 5"; exit 1; }
  sudo chmod --reference="$BANCO_ATUAL.bak-dia-ruim" "$BANCO_ATUAL" \
    || { echo "❌ chmod falhou — sigere segue PARADO; ajuste permissão à mão e continue do passo 5"; exit 1; }
else
  # sem o .bak de referência (o banco atual nem existia): copie dono/permissão
  # de outro arquivo do serviço ou derive da unidade — `sudo systemctl cat
  # sigere` mostra User=/Group= (na instalação padrão, www-data:www-data);
  # modo 644 (não 600): o timer de backup roda como o dono do repositório
  # (User= da unit sigere-backup) e lê o banco diretamente — 644 é o modo
  # que a própria instalação produz em operação. RISCO RESIDUAL
  # (CodeRabbit #243): 644 deixa o banco legível por QUALQUER usuário local
  # que atravesse os diretórios até a instance/ — confira os modos de
  # /var/www/sigere e da pasta do banco (sem 777, sem world-writable; o
  # contendo deve pertencer a root ou www-data); para restringir mais,
  # grupo/ACL entre www-data e o dono do timer sigere-backup exige mudar o
  # provisionamento — decisão de implantação, fora do escopo do runbook:
  sudo chown www-data:www-data "$BANCO_ATUAL" \
    || { echo "❌ chown falhou — sigere segue PARADO; ajuste dono e permissão à mão — dono/grupo do \`systemctl cat sigere\` (User=/Group=) e modo 644 — e continue do passo 5"; exit 1; }
  sudo chmod 644 "$BANCO_ATUAL" \
    || { echo "❌ chmod falhou — sigere segue PARADO; ajuste permissão à mão e continue do passo 5"; exit 1; }
fi
rm -rf "$PASTA_TRABALHO"

# 5. Conferir o ciclo ANTES das migrations — com --arquivo, garante que o
#    testado é o MESMO snapshot restaurado, e não "o mais recente" da
#    pasta/bucket. Verificar aqui (e não depois das migrations): se uma
#    migration adicionar tabela, o snapshot — que não a tem — seria
#    reprovado injustamente pela comparação:
venv/bin/flask --app run verify-restore --arquivo "$BACKUP" || {
  echo "❌ Verificação reprovou — sigere segue PARADO; investigue antes de abrir."
  exit 1
}

# 6. Alinhar schema e permissões ANTES de abrir o serviço: o snapshot pode
#    ser anterior a uma migration do código atual. Falhou aqui? sigere segue
#    PARADO.
set -a; source .env; set +a
venv/bin/flask --app run db upgrade || {
  echo "❌ db upgrade falhou — sigere segue PARADO; resolva antes de abrir."
  exit 1
}
# revogações de propósito feitas DEPOIS do snapshot morreram com ele —
# reaplique e confira SEMPRE, mesmo sem mudança de código, ANTES de subir —
# rota OFFLINE, pois o Painel Admin → Papéis exige o serviço no ar: Flask
# shell via SSH, com sigere (e o Nginx, se houver) PARADOS (procedimento
# completo na doc de implantação, seção «Atualizando a aplicação»). O
# `sync-permissions` é que fica condicionado ao código avançado — rode-o
# ANTES de reaplicar as revogações. O serviço só sobe com as revogações
# reaplicadas e conferidas — GATE (CodeRabbit #243): o bloco colado não
# sobe o serviço sem a conferência manual:
# GATE (CodeRabbit #243): confirmação e start no MESMO comando composto —
# colando o bloco inteiro, o read não pode consumir a linha seguinte e
# subir o serviço sem a conferência manual:
{ if ! read -r -p 'Revogações reaplicadas e conferidas? Digite CONFIRMO para subir o sigere: ' CONFIRMACAO_PERMISSOES \
       || [ "$CONFIRMACAO_PERMISSOES" != "CONFIRMO" ]; then
  echo '❌ Serviço segue PARADO — confira as permissões e volte ao passo 5.'
  exit 1
fi
sudo systemctl start sigere
}
# Host SEM a unit sigere (dev): o start acima falha sem efeito — suba à mão
# com o servidor nativo NO MESMO terminal (o passo 6 já exportou o .env):
# `python run.py` ou `flask --app run run` (docs/desenvolvimento-debug.md);
# a verificação é o smoke test no navegador (o app não tem rota de health).
```

## Depois de qualquer restauração

1. Migration e `sync-permissions` já rodaram antes de subir o serviço
   (passo 4 no PostgreSQL, passos 5–6 no SQLite) — se algo precisar ficar
   para depois, mantenha os serviços parados até concluir, com o
   procedimento de revogações da doc de implantação.
2. Ajuste o relógio das expectativas: avisar usuários o que foi perdido no
   intervalo (reservas do dia refeitas à mão).
3. Investigar a causa antes de religar o mundo: disco cheio, update quebrado,
   DELETE acidental? O backup salva os dados; a causa segue lá fora.
