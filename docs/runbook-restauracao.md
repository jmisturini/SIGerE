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

```bash
cd /var/www/sigere

# 1. Congelar o estado: nada escreve no banco durante a restauração.
sudo systemctl stop nginx sigere
sudo systemctl status nginx sigere          # ambos inactive (dead)

# 2. Escolher o backup (mais recente primeiro) e conferir qual é "bom":
ls -lt backups/ | head
set -a; source .env; set +a
venv/bin/flask --app run verify-restore     # verde = este snapshot volta
# (se backups/ estiver vazio, o verify-restore baixa o mais novo do bucket)

# 3. Recriar o banco e restaurar o snapshot escolhido:
sudo -u postgres dropdb --if-exists sigere
sudo -u postgres createdb -O sigere sigere
gunzip -c backups/sigere-AAAAMMDD-HHMMSS-postgres.sql.gz | \
  psql --set=ON_ERROR_STOP=1 "postgresql://sigere:SENHA@localhost:5432/sigere"
# alternativa guiada: python setup_interativo.py  →  modo 3 "Restaurar backup"

# 4. Subir e checar:
sudo systemctl start sigere
sudo journalctl -u sigere -n 30 --no-pager
# o gunicorn escuta em socket unix — teste direto nele antes de abrir o nginx:
curl -fsS --unix-socket /run/sigere/sigere.sock -o /dev/null -w '%{http_code}\n' http://localhost/
sudo systemctl start nginx
# smoke test no navegador: login de um usuário real + abrir cronograma + criar/editar uma reserva.

# 5. Regerar backup imediatamente — o próximo "ontem" precisa existir:
venv/bin/flask --app run backup
```

Se o passo 3 falhar no meio (`ON_ERROR_STOP`), o banco fica pela metade:
recrie (`dropdb`/`createdb`) e tente o snapshot anterior.

## O dia ruim — SQLite (desenvolvimento/avaliação)

```bash
sudo systemctl stop sigere                  # se houver serviço rodando
gunzip -c backups/sigere-AAAAMMDD-HHMMSS-sqlite.sqlite.gz > reservation.db
venv/bin/flask --app run verify-restore     # sanidade
sudo systemctl start sigere
```

## Depois de qualquer restauração

1. Se o código avançou desde o snapshot: `venv/bin/flask --app run db upgrade`
   e `sync-permissions` com o procedimento de revogações da doc de implantação.
2. Ajuste o relógio das expectativas: avisar usuários o que foi perdido no
   intervalo (reservas do dia refeitas à mão).
3. Investigar a causa antes de religar o mundo: disco cheio, update quebrado,
   DELETE acidental? O backup salva os dados; a causa segue lá fora.
