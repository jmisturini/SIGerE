# Backlog de segurança

Ideias avaliadas em 2026-10-25 (após política de senha e bloqueio de conta por
tentativas) e **ainda não implementadas** — cada item descreve o porquê, onde
intervir e o esforço estimado. Ordem de valor percebido na avaliação.

Estado que motivou a lista (já coberto pela base atual): hash scrypt, CSRF em
todos os formulários, cookies `SameSite=Lax` e `Secure` atrás do ProxyFix,
rate limit no login (5/min) e API (120/min), `pip-audit` no CI, backups com
retenção/S3 (`app/backup.py`), secrets 0600, auditoria de eventos no log
(`app.utils.auditar`), política de senha e bloqueio por tentativas.

---

## 1. Aviso aos administradores quando uma conta for bloqueada

**Porquê:** com o bloqueio automático ativo, ninguém fica sabendo que uma
conta travou — só quando o usuário reclama. Um aviso distingue ataque real de
erro de digitação e encurta o desbloqueio.

**Como:** nos pontos que já chamam `auditar('conta_bloqueada_manual')` e
`conta_bloqueada_automatica` (`app/blueprints/admin.py` e `app/blueprints/auth.py`),
usar a infraestrutura de e-mail das notificações (`app/services/` — o espelho
por e-mail das notificações de reserva já existe) para avisar quem tem a
permissão `user:lock`. Agrupar avisos (ex.: máximo 1 e-mail por conta/hora)
para não virar spam em ataques distribuídos.

**Esforço:** pequeno (meio dia). Sem migration.

## 2. 2FA (TOTP) para papéis administrativos

**Porquê:** quem tem papel `admin`/`super_admin` movimenta reservas, dados de
RH e tokens de API. Senha + bloqueio protegem, mas o segundo fator fecha a
maior lacuna restante — principalmente porque o reset de senha pelo admin
entrega senha temporária por fora (chat/e-mail).

**Como:** `pyotp` + colunas `totp_secret`/`totp_enabled` em `users`; setup no
perfil (QR code), challenge no login depois da senha correta (usar uma
sessão "pré-autenticada" de curta duração, padrão do fluxo TOTP); exigir
enrollment apenas de quem tem `role_obj.is_system` na primeira entrada.
Cuidado: fornecer códigos de recuperação de uso único para não depender do
admin para desbloquear.

**Esforço:** médio (2–3 dias, com testes). Migration simples.

## 3. Headers de segurança

**Porquê:** a aplicação não define `X-Frame-Options`, `Referrer-Policy` nem
CSP; HSTS cabe no nginx. Clickjacking e mixed-content são riscos baratos de
fechar.

**Como (fácil primeiro):**
- `after_request` em `app/__init__.py`:
  `X-Frame-Options: DENY`, `Referrer-Policy: strict-origin-when-cross-origin`,
  `X-Content-Type-Options: nosniff`.
- HSTS no nginx do servidor (VM OCI, sigere.pixelping.cc):
  `add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;`
- CSP por fases: a aplicação carrega Bootstrap/TomSelect/fontes de
  cdn.jsdelivr.net e fonts.googleapis/gstatic — começar em modo
  `Content-Security-Policy-Report-Only`, ajustar até a página de reservas e o
  totem ficarem limpos, então promover para `Content-Security-Policy`.

**Esforço:** headers simples, 1 hora; CSP, 1–2 dias.

## 4. Rate limit em múltiplos workers (Redis)

**Porquê:** o Flask-Limiter usa memória por processo. Com 1 worker do gunicorn
não há impacto; ao escalar, cada worker conta 5 tentativas independentes e o
limite real do login vira 5×workers.

**Como:** definir `RATELIMIT_STORAGE_URI` (variável de ambiente em
`app/config.py`) apontando para Redis quando houver mais de um worker;
documentar no guia de implantação. Alternativa sem Redis: `worker=1` com
`threads` (o sistema é I/O-bound e já roda assim).

**Esforço:** pequeno (metade do dia), mas só quando a implantação escalar.

## 5. Monitoramento passivo de tentativas / fail2ban

**Porquê:** a trilha de auditoria registra `login_falha` com IP no journal, mas
ninguém olha o journal em tempo real. Ataques de dicionário ficam visíveis só
depois (contas bloqueadas).

**Como:** garantir que o journal do `sigere.service` seja persistido
(`Storage=persistent` no journald) e criar um filtro fail2ban para
`[AUDITORIA] evento=login_falha` (ban progressivo por IP — cuidado com NAT de
redes escolares; começar só em modo de observação). Opcional: rotacionar um
resumo diário para o painel (contagem de falhas por IP/conta).

**Esforço:** pequeno no servidor (infra, não código). Testar primeiro em
observação.

---

## Feitos (referência)

- Política de senha (mín. 8, 1 maiúscula, 1 número) — PR #156.
- Bloqueio de conta após 10 tentativas + desbloqueio com `user:lock` — PR #157.
- Trilha de auditoria de eventos de segurança — tabela `audit_logs`
  (migration `b4e8f2a6c9d1`) gravada por `app.utils.auditar` com cópia no
  log, consultável no Painel Admin em `/admin/auditoria` (permissão
  `system:audit`; filtros por evento, ator/alvo e período).
