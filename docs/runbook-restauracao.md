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
sudo systemctl stop nginx sigere
sudo systemctl status nginx sigere          # ambos inactive (dead)

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

sudo -u postgres dropdb --if-exists sigere
sudo -u postgres createdb -O sigere sigere
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
venv/bin/flask --app run db upgrade
# se o código avançou desde o snapshot: registre as revogações de
# Painel Admin → Papéis, rode `venv/bin/flask --app run sync-permissions`
# e reaplique as revogações (procedimento completo na doc de implantação).
# Falhou aqui? Mantenha nginx e sigere PARADOS até resolver.

# 5. Subir e checar:
sudo systemctl start sigere
sudo journalctl -u sigere -n 30 --no-pager
# o gunicorn escuta em socket unix — teste direto nele antes de abrir o nginx:
curl -fsS --unix-socket /run/sigere/sigere.sock -o /dev/null -w '%{http_code}\n' http://localhost/
sudo systemctl start nginx
# smoke test no navegador: login de um usuário real + abrir cronograma + criar/editar uma reserva.

# 6. Regerar backup imediatamente e conferir o ciclo — a produção agora está
#    saudável, então a comparação contra ela é válida de novo:
venv/bin/flask --app run backup
venv/bin/flask --app run verify-restore
```

## O dia ruim — SQLite (desenvolvimento/avaliação)

```bash
sudo systemctl stop sigere                  # se houver serviço rodando

# 1. Alvo da restauração = o banco que a DATABASE_URL aponta, com a MESMA
#    resolução do app (relativo cai na instance/, absoluto fica como está —
#    o helper _caminho_sqlite): restaurar por hábito num reservation.db do
#    diretório corrente pode substituir o arquivo errado.
BANCO_ATUAL="$(venv/bin/python -c "
import os
os.environ.setdefault('SECRET_KEY', 'apenas-resolucao-de-caminho')
from dotenv import load_dotenv; load_dotenv()
from app import create_app
from app.backup import _caminho_sqlite, _interpretar_uri
app = create_app()
with app.app_context():
    _, dados = _interpretar_uri(app.config['SQLALCHEMY_DATABASE_URI'])
    print(_caminho_sqlite(dados))
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

# 3. Validar a integridade do extraído antes de tocar no banco atual:
venv/bin/python -c "import sqlite3; print(sqlite3.connect('$PASTA_TRABALHO/sigere-restaurado.sqlite').execute('PRAGMA integrity_check').fetchone()[0])"
# 'ok' esperado — qualquer outra coisa: NÃO substitua; tente outro snapshot.

# 4. Preservar o estado ruim PARA ANÁLISE e limpar o caminho — um journal
#    quente (-journal/-wal/-shm do banco do desastre) ao lado do arquivo
#    restaurado seria REPRODUZIDO pelo SQLite por cima das páginas novas:
#    o estado ruim vai embora inteiro, e nada de sidecar pode sobrar no nome
#    de destino (sem sidecars, os mv opcionais apenas não fazem nada):
mv "$BANCO_ATUAL" "$BANCO_ATUAL.bak-dia-ruim"
for sufixo in journal wal shm; do
  [ -f "$BANCO_ATUAL-$sufixo" ] && \
    mv "$BANCO_ATUAL-$sufixo" "$BANCO_ATUAL.bak-dia-ruim-$sufixo"
done
mv "$PASTA_TRABALHO/sigere-restaurado.sqlite" "$BANCO_ATUAL"
rm -rf "$PASTA_TRABALHO"

# 5. Alinhar schema e permissões ANTES de abrir o serviço (igual ao
#    PostgreSQL): o snapshot pode ser anterior a uma migration do código
#    atual. Falhou aqui? sigere segue PARADO.
set -a; source .env; set +a
venv/bin/flask --app run db upgrade
# se o código avançou: registre as revogações de Painel Admin → Papéis,
# rode `venv/bin/flask --app run sync-permissions` e reaplique-as
# (procedimento completo na doc de implantação).

# 6. Conferir o ciclo — com --arquivo, garante que o testado é o mesmo
#    snapshot restaurado, e não "o mais recente" da pasta/bucket. Só suba o
#    serviço com a verificação verde:
venv/bin/flask --app run verify-restore --arquivo "$BACKUP" || {
  echo "❌ Verificação reprovou — sigere segue PARADO; investigue antes de abrir."
  exit 1
}
sudo systemctl start sigere
```

## Depois de qualquer restauração

1. Migration e `sync-permissions` já rodaram antes de subir o serviço
   (passo 4 no PostgreSQL, passo 5 no SQLite) — se algo precisar ficar para
   depois, mantenha os serviços parados até concluir, com o procedimento de
   revogações da doc de implantação.
2. Ajuste o relógio das expectativas: avisar usuários o que foi perdido no
   intervalo (reservas do dia refeitas à mão).
3. Investigar a causa antes de religar o mundo: disco cheio, update quebrado,
   DELETE acidental? O backup salva os dados; a causa segue lá fora.
