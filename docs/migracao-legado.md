# Migração do sistema legado (Django/MySQL) para o SIGERE

Migração **one-shot**: o banco antigo (`sigere_active`, MySQL 8, dump do
phpMyAdmin) é importado para o SIGERE e o sistema antigo é desativado em
seguida — não há sincronização entre os dois.

## Como executar

```bash
# 1. Banco novo, com o schema atual do SIGERE
export DATABASE_URL='postgresql://sigere:sigere@localhost:5432/sigeredb'  # ou sqlite:///caminho/reservation.db
flask --app run db upgrade

# 2. Importação (lê o .sql diretamente; não precisa de servidor MySQL)
flask --app run import-legacy --dump caminho/sigere_active.sql
```

O comando recusa bancos com dados existentes (`--force` contorna, sob sua
responsabilidade). Ao final, imprime um relatório com as contagens.

## O que é importado

| Legado (MySQL) | SIGERE | Observações |
|---|---|---|
| `units` | `unities` (unidade única) | **Não cria as unidades do dump.** Todo o acervo (salas, cursos, matérias, reservas, usuários, hora extra) fica na unidade **Faculdade Senac Florianópolis** (código `FLO`, mesmo cadastro do seed padrão em `docs/unidades-senac-sc.json` — criada pelo importador se ainda não existir). |
| `authenticator_customuser` + `authenticator_teachersuser` | `users` | **Fusão por `registration`** (matrícula): quem existe nas duas tabelas vira um usuário único (dados do quadro prevalecem; perfil docente marcado). 64 + 182 − 11 = 235 usuários. |
| `classroom` | `classrooms` + `room_categories` | Categoria deduzida da descrição (informática/saúde/cozinha/sala). “Sem Uso” vira sala inativa. Capacidade nula de sala ativa = 30. |
| — (módulo próprio) | sala sintética **Auditório** (`AUDITORIO`) | O legado gerenciava o auditório fora da tabela de salas. |
| `courses` | `courses` | Código gerado `C{id:4}`; núcleo (NES/NEB…) preservado na descrição. |
| `matters` | `subjects` | Código gerado `M{id:4}`. No legado matéria não pertence a curso — o vínculo fica na reserva. |
| `class_control` | `reservations` | 22.394 registros. `reservation` → data; turno (`shifts`) → janela 07–12 / 12–18 / 18–22 (padrão idêntico aos horários gravados no `auditorium_control`). Título = “Curso · Matéria”. |
| `auditorium_control` | `reservations` na sala Auditório | 529 registros, com horários explícitos do legado. |
| `teacher_overtime_pay` | `teacher_overtime_pay` | 724 lançamentos; professor resolvido por matrícula. |
| `contracts`, `levels`, `status_user_base`, `teacher_base_pay(+_course)`, `teacher_additive_payment(+_course)` | — | Sem equivalente no SIGERE; apenas contados no relatório. |
| Resto (`django_*`, `auth_*`, `axes_*`, sessões, logs) | — | Infraestrutura Django, descartada. |

## Decisões de mapeamento (verificar após a migração)

1. **Status legado 1/2** — análise do dump: **todos** os registros com status 2
   (1.238 aulas + 18 eventos) têm data no passado; futuros são todos 1.
   Interpretação: 1 = ativa, 2 = cancelada/não realizada → mapeados para
   `approved` e `cancelled`. O número original fica em
   `reservations.review_note` (“status legado: N”), então re-mapear é um
   `UPDATE` simples caso a interpretação esteja errada.

2. **Senhas** — o legado usa `pbkdf2_sha256$iterações$salt$digest_base64`
   (formato Django). O digest é decodificado e reencodado em hex no formato
   `pbkdf2:sha256:iterações$salt$hex` do Werkzeug 3.x — **o mesmo algoritmo**,
   então quem tinha senha utilizável entra com ela no SIGERE. 144 registros
   tinham hash corrompido no legado (prefixo `S&n@`, etc.) e receberam senha
   aleatória inutilizável. **Todos** os usuários importados iniciam com
   `force_password_change=True`: o admin reseta o acesso de quem precisar e a
   troca é obrigatória no primeiro login.

3. **Papéis** — derivados dos grupos de permissão do Django
   (`authenticator_customuser_groups`): `power_user` → admin;
   grupos `*_full` (room_control, auditorium, teacher_pay, general_registration)
   → room_manager; `*_base` → coordinator; professores → teacher; sem grupo →
   employee. `is_superuser` → super_admin. Ajustes finos pela tela de usuários.

4. **Campos de RH** — núcleo → `department`, setor → `sector`, função →
   `function`, matrícula → `registration`. Matrícula repetida no legado (ex.:
   9999) fica nula no segundo registro.

5. **E-mails** — únicos por construção; colisão entre registros distintos do
   legado recebe sufixo `+leg<matrícula>` antes da arroba.

6. **Duplicatas** — 32 chaves de aula exatamente duplicadas no legado
   (sala+data+turno+curso+matéria+professor) foram mantidas como estão
   (registro histórico).

## Pós-migração (checklist)

- [ ] Conferir o relatório de contagens do comando.
- [ ] Resetar a senha do superadmin (`informatica`) e dos administradores.
- [ ] Revisar papéis atribuídos (regra dos grupos do Django no item 3).
- [ ] Validar com as coordenações: salas “Sem Uso” inativas, sala Auditório
      criada, cursos/matérias importados.
- [ ] Desativar o sistema antigo.
