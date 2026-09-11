# 📡 API de Reservas — Documentação de Uso

Documentação completa da API REST de **leitura de reservas** do SIGerE, destinada a
aplicativos externos (apps de exibição, painéis de ocupação, integrações acadêmicas,
bots, etc.).

> **Versão:** 1 — URL base `/api/v1`
> **Blueprint:** `app/blueprints/api.py`
> **Somente leitura:** a API não cria, altera nem exclui reservas.

---

## Índice

- [Visão geral](#-visão-geral)
- [Autenticação](#-autenticação)
  - [Sem token (anônimo)](#sem-token-anônimo)
  - [Bearer token](#bearer-token)
  - [Resumo de visibilidade](#resumo-de-visibilidade)
- [Endpoints](#-endpoints)
  - [Listar reservas](#get-apiv1reservations)
  - [Detalhe de uma reserva](#get-apiv1reservationsid)
  - [Listar salas](#get-apiv1rooms)
- [Escopo multi-unidade](#-escopo-multi-unidade)
- [Erros](#-erros)
- [Limites de requisições](#-limites-de-requisições)
- [Exemplos práticos](#-exemplos-práticos)
  - [cURL](#curl)
  - [Python (requests)](#python-requests)
  - [JavaScript (fetch)](#javascript-fetch)
  - [Cenário: painel de ocupação de salas](#cenário-painel-de-ocupação-de-salas)
- [Perguntas frequentes](#-perguntas-frequentes)

---

## 🧭 Visão geral

A API permite que outros aplicativos leiam as reservas de salas de uma unidade
educacional. O nível de detalhe da resposta depende do token:

| Modo | Campos retornados | Situações visíveis |
|------|-------------------|--------------------|
| **Anônimo** (sem token) | Apenas `id`, `title`, `date`, `start_time`, `end_time` e `classroom` (id/código/nome) | Somente `approved` |
| **Com Bearer token** (Painel Admin → Tokens da API) | **Todos** os campos da reserva: descrição, `status`, docente, curso, disciplina, criador, revisor, unidade, sala completa, série de repetição, timestamps | Todas (`approved`, `pending`, `cancelled`) |

Requisições **sem token continuam funcionando** — recebem apenas o payload
público. Não existe endpoint "bloqueado": o que muda é o quanto ele revela.

> 🚪 **App de exemplo incluída no repositório:** [examples/quadro-sala](../../examples/quadro-sala/)
> — um quadro de sala para tablet afixado na porta que consome a API
> anonimamente de outra origem, com atualização automática. Serve de referência
> prática para integrações web.

Todos os horários seguem o formato ISO `HH:MM:SS` (horário local da instituição) e
as datas `AAAA-MM-DD`.

---

## 🔑 Autenticação

### Sem token (anônimo)

Basta chamar qualquer endpoint sem cabeçalho `Authorization`. A resposta traz
somente data, horário, sala e título de reservas aprovadas — o mínimo necessário
para exibir a ocupação de uma sala sem expor dados pessoais ou internos.

```bash
curl http://localhost:5000/api/v1/reservations
```

> A lista anônima mostra **somente reservas aprovadas**: pendências e cancelamentos
> são situações internas do fluxo de aprovação e ficam invisíveis, inclusive no
> endpoint de detalhe (que responde `404` para elas).

### Bearer token

O acesso completo usa um **token de integração** gerado no sistema:
**Painel Admin → Tokens da API** (exige a permissão `api:manage`, concedida por
padrão ao papel *Administrador*).

```bash
curl -H "Authorization: Bearer sige_SEU_TOKEN" http://localhost:5000/api/v1/reservations
```

Como funciona:

- Na geração, informe um **nome** (para identificar o app de origem) e a
  **validade** (sem expiração, 30/60/90/180/365 dias). O valor completo
  (`sige_…`) é exibido **uma única vez** — o banco guarda apenas o hash
  SHA-256, então um vazamento do banco não revela nenhum token válido.
- A listagem mostra o **prefixo** do token, quem criou, quando foi usado pela
  última vez, a validade e o status; tokens podem ser **revogados** (sem perder
  o histórico), reativados ou excluídos permanentemente.
- O **escopo de dados** do token é o da conta que o criou: as reservas ficam
  limitadas à unidade do criador (a menos que ele tenha permissão de alternar
  unidade, usando `?unity_id=`).
- Tokens de contas **desativadas** param de autenticar imediatamente.
- Credenciais inválidas retornam `401` com o cabeçalho
  `WWW-Authenticate: Bearer realm="SIGerE API"`.

### Resumo de visibilidade

| Campo | Anônimo | Com token |
|-------|:-------:|:---------:|
| `id` | ✅ | ✅ |
| `title` | ✅ | ✅ |
| `date`, `start_time`, `end_time` | ✅ | ✅ |
| `classroom` (id, código, nome) | ✅ | ✅ (com prédio, andar, número, capacidade e categoria) |
| `description` | ❌ | ✅ |
| `status` | ❌ | ✅ |
| `unity` | ❌ | ✅ |
| `created_by` | ❌ | ✅ |
| `teacher` | ❌ | ✅ |
| `course`, `subject` | ❌ | ✅ |
| `reviewed_by`, `review_note` | ❌ | ✅ |
| `repeat_group_id` | ❌ | ✅ |
| `created_at`, `updated_at` | ❌ | ✅ |

> O campo `id` é sempre incluído para que o app externo possa referenciar a reserva
> (por exemplo, para paginar ou buscar o detalhe). Ele não revela informação sobre
> a reserva.

---

## 🌐 Endpoints

### `GET /api/v1/reservations`

Lista paginada de reservas da unidade escopada.

**Parâmetros de query (todos opcionais):**

| Parâmetro | Tipo | Padrão | Descrição |
|-----------|------|--------|-----------|
| `start` | data `AAAA-MM-DD` | — | Inclui apenas reservas a partir desta data (inclusive) |
| `end` | data `AAAA-MM-DD` | — | Inclui apenas reservas até esta data (inclusive) |
| `status` | `approved` · `pending` · `cancelled` · `all` | `approved` | Situação das reservas. **Sem autenticação o valor é ignorado** (sempre `approved`) |
| `classroom_id` | inteiro | — | Filtra por uma sala (ID interno) |
| `classroom_code` | texto | — | Filtra por código da sala (ex.: `S101`) — mais estável para integrações |
| `teacher_id` | inteiro | — | Filtra por docente |
| `course_id` | inteiro | — | Filtra por curso |
| `subject_id` | inteiro | — | Filtra por disciplina |
| `period` | `morning` · `afternoon` · `night` | — | Manhã (00:00–12:00), tarde (12:00–18:00) ou noite (18:00–23:59). Considera sobreposição: uma reserva 11:00–13:00 aparece em `morning` **e** `afternoon` |
| `unity_id` | inteiro | unidade do usuário / primeira ativa | Escolhe a unidade (respeitado apenas por anônimos e por quem pode alternar unidade) |
| `page` | inteiro (≥ 1) | `1` | Página atual |
| `per_page` | inteiro (1–500) | `100` | Itens por página |

**Resposta `200`:**

```jsonc
{
  "unity_id": 1,              // unidade escopada desta resposta
  "authenticated": true,      // false = payload público (campos reduzidos)
  "page": 1,
  "per_page": 100,
  "total": 3,                 // total de reservas que atendem aos filtros
  "pages": 1,
  "reservations": [ /* itens no formato público ou completo */ ]
}
```

**Ordenação:** por `date`, depois `start_time`, depois `id`.

**Exemplos de uso dos filtros:**

```bash
# Reservas aprovadas da semana (anônimo — payload público)
curl "http://localhost:5000/api/v1/reservations?start=2026-09-07&end=2026-09-13"

# Todas as situações de uma sala, com token
curl -H "Authorization: Bearer sige_SEU_TOKEN" \
  "http://localhost:5000/api/v1/reservations?classroom_code=S101&status=all"

# Aulas noturnas de um docente
curl -H "Authorization: Bearer sige_SEU_TOKEN" \
  "http://localhost:5000/api/v1/reservations?teacher_id=5&period=night"

# Página 2 com 50 itens
curl -H "Authorization: Bearer sige_SEU_TOKEN" \
  "http://localhost:5000/api/v1/reservations?per_page=50&page=2"
```

**Payload público (item):**

```json
{
  "id": 42,
  "title": "Aula de Matemática",
  "date": "2026-09-10",
  "start_time": "08:00:00",
  "end_time": "10:00:00",
  "classroom": { "id": 7, "code": "S101", "name": "Sala 101" }
}
```

**Payload com token (item):**

```json
{
  "id": 42,
  "title": "Aula de Matemática",
  "description": "Capítulo 4",
  "date": "2026-09-10",
  "start_time": "08:00:00",
  "end_time": "10:00:00",
  "status": "approved",
  "classroom": {
    "id": 7,
    "code": "S101",
    "name": "Sala 101",
    "room_number": "101",
    "building": "Bloco A",
    "floor": "1º Andar",
    "capacity": 30,
    "category": "Sala de Aula"
  },
  "unity": { "id": 1, "code": "CTR", "name": "Unidade Centro" },
  "created_by": { "id": 3, "username": "prof1", "full_name": "Prof. Um" },
  "teacher": { "id": 5, "username": "prof5", "full_name": "Prof. Cinco" },
  "course": { "id": 2, "code": "INF", "name": "Informática" },
  "subject": { "id": 9, "code": "MAT", "name": "Matemática" },
  "reviewed_by": null,
  "review_note": null,
  "repeat_group_id": null,
  "created_at": "2026-09-01T13:22:41",
  "updated_at": "2026-09-01T13:22:41"
}
```

Campos anuláveis quando a reserva não os usa: `description`, `teacher`, `course`,
`subject`, `reviewed_by`, `review_note`, `repeat_group_id`.

---

### `GET /api/v1/reservations/<id>`

Detalhe de uma reserva pelo `id`.

```bash
curl http://localhost:5000/api/v1/reservations/42                            # público
curl -H "Authorization: Bearer sige_SEU_TOKEN" http://localhost:5000/api/v1/reservations/42   # completo
```

Comportamentos importantes:

- Reserva de **outra unidade** responde `404` (mesmo existindo) — a API não
  confirma a existência de reservas fora do escopo do chamador.
- **Anônimo** só consegue detalhar reservas `approved`; pendentes/canceladas
  respondem `404`.
- Resposta `200`: o objeto da reserva (mesmos formatos dos itens acima, sem o
  envelope de paginação).

---

### `GET /api/v1/rooms`

Salas **ativas** da unidade escopada. Serve para o app externo descobrir os
`classroom_id`/códigos de sala antes de consultar as reservas.

| Parâmetro | Descrição |
|-----------|-----------|
| `unity_id` | Mesma regra de unidade dos demais endpoints |

**Payload anônimo:**

```json
{
  "unity_id": 1,
  "authenticated": false,
  "rooms": [
    { "id": 7, "code": "S101", "name": "Sala 101" }
  ]
}
```

**Payload com token** (inclui detalhes da sala):

```json
{
  "unity_id": 1,
  "authenticated": true,
  "rooms": [
    { "id": 7, "code": "S101", "name": "Sala 101", "building": "Bloco A",
      "floor": "1º Andar", "capacity": 30, "category": "Sala de Aula" }
  ]
}
```

---

## 🏢 Escopo multi-unidade

O SIGerE é multi-unidade e a API respeita o isolamento de dados:

| Chamador | Unidade retornada |
|----------|-------------------|
| **Anônimo** sem `unity_id` | Primeira unidade **ativa** (ordem alfabética de nome) — mesma regra do totem |
| **Anônimo** com `?unity_id=<id>` | A unidade indicada, se existir e estiver ativa (`404` caso contrário) |
| **Token de usuário comum** | **Sempre a própria unidade** — `?unity_id` é ignorado |
| **Token de usuário com permissão `*` ou `unity:switch`** | A própria unidade por padrão; `?unity_id=<id>` troca o escopo |

Cada resposta inclui o campo `unity_id` no topo para o cliente confirmar o escopo
que recebeu. Reservas de outra unidade jamais aparecem — e o detalhe delas responde
`404`, não `403`.

---

## ❌ Erros

Todos os erros retornam JSON com a chave `error` (nunca uma página HTML):

```json
{ "error": "Usuário ou senha inválidos." }
```

| Código | Quando acontece |
|--------|-----------------|
| `400` | Parâmetro inválido (data fora do formato `AAAA-MM-DD`, `status` desconhecido, `period` desconhecido, `start` maior que `end`) |
| `401` | Token fornecido e inválido: desconhecido, expirado, revogado, esquema não suportado (ex.: `Basic`) ou conta do criador desativada. Inclui `WWW-Authenticate: Bearer realm="SIGerE API"` |
| `404` | Reserva/unidade inexistente, **fora do escopo da unidade** ou não aprovada (anônimo) |
| `429` | Limite de requisições excedido (ver próxima seção) |

> **Importante:** requisição **sem** token não gera `401` — ela é atendida
> com o payload público. O `401` ocorre somente quando o token enviado
> é inválido, expirado ou revogado.

---

## 🚦 Limites de requisições

Cada endpoint da API aceita **120 requisições por minuto por IP** (via
Flask-Limiter). Ao exceder, a resposta é `429`. Apps que atualizam em intervalos
regulares (ex.: painel a cada 60 s) ficam muito abaixo do limite.

---

## 💻 Exemplos práticos

### cURL

```bash
# 1. Descobrir as salas da unidade
curl -H "Authorization: Bearer sige_SEU_TOKEN" http://localhost:5000/api/v1/rooms

# 2. Reservas de hoje em diante de uma sala específica
curl -H "Authorization: Bearer sige_SEU_TOKEN" \
  "http://localhost:5000/api/v1/reservations?classroom_code=S101&start=$(date +%F)"

# 3. Sem token (painel público)
curl "http://localhost:5000/api/v1/reservations?start=$(date +%F)"
```

### Python (requests)

```python
import requests
from datetime import date

BASE = "http://localhost:5000/api/v1"
HEADERS = {"Authorization": "Bearer sige_SEU_TOKEN"}   # token do Painel Admin

# Ocupação de hoje em diante, com todos os detalhes
resp = requests.get(f"{BASE}/reservations", headers=HEADERS, timeout=10,
                    params={"start": date.today().isoformat()})
resp.raise_for_status()
data = resp.json()

for r in data["reservations"]:
    print(f"{r['date']} {r['start_time']}–{r['end_time']} "
          f"[{r['classroom']['code']}] {r['title']} — {r['teacher']['full_name']}")

# Paginação completa
page = 1
while page <= data["pages"]:
    data = requests.get(f"{BASE}/reservations", headers=HEADERS,
                        params={"start": date.today().isoformat(), "page": page},
                        timeout=10).json()
    processar(data["reservations"])
    page += 1
```

### JavaScript (fetch)

```javascript
const BASE = 'http://localhost:5000/api/v1';

// Com Bearer token
const resp = await fetch(`${BASE}/reservations?start=2026-09-11`, {
  headers: { Authorization: 'Bearer sige_SEU_TOKEN' },
});
if (!resp.ok) {
  const { error } = await resp.json();
  throw new Error(`API: ${resp.status} — ${error}`);
}
const { reservations, pages, authenticated } = await resp.json();
console.log(`Autenticado: ${authenticated}, ${reservations.length} reservas (pág. 1 de ${pages})`);
```

### Cenário: painel de ocupação de salas

Aplicativo público (sem login) que mostra "o que está acontecendo agora":

```python
import requests
from datetime import datetime

BASE = "http://localhost:5000/api/v1"   # sem autenticação

agora = datetime.now()
# Busca do dia e filtra o período atual no cliente:
reservas = requests.get(BASE + "/reservations", timeout=10,
                        params={"start": agora.date().isoformat()}).json()["reservations"]

em_andamento = [r for r in reservas
                if r["date"] == agora.date().isoformat()
                and r["start_time"] <= agora.strftime("%H:%M:%S") < r["end_time"]]

for r in em_andamento:
    # Anônimo só tem: título, data, horário e sala — exatamente o que um painel precisa
    print(f"{r['classroom']['name']}: {r['title']} (até {r['end_time']})")
```

---

## ❓ Perguntas frequentes

**Posso criar/editar reservas pela API?**
Não. A API é somente leitura por decisão de design; a gravação continua acontecendo
pela interface web, com CSRF, permissões e validação de conflitos.

**Como obtenho um token?**
No sistema: **Painel Admin → Tokens da API** (permissão `api:manage`, que o papel
*Administrador* já tem). Dê um nome que identifique o app, escolha a validade e
copie o valor exibido — ele não é mostrado novamente. Para integrações, uma boa
prática é gerar um token por aplicativo.

**O token pode vazar — qual o impacto?**
Ele concede leitura completa das reservas no escopo do criador. Por isso o
banco guarda só o hash (vazamento do banco não revela tokens), a listagem mostra
apenas o prefixo e a revogação é imediata. **Use sempre HTTPS em produção** e
revogue tokens de apps desativados.

**Por que meu token não vê reservas da outra unidade?**
O escopo segue a unidade da conta que criou o token. Só contas com permissão
`*` ou `unity:switch` podem trocar a unidade com `?unity_id`.

**Por que o endpoint responde 404 para uma reserva que sei que existe?**
Ou ela é de outra unidade, ou está pendente/cancelada e a chamada é anônima. O 404
é deliberado: a API não confirma a existência de registros fora do escopo.

**Qual o volume máximo por resposta?**
`per_page` limitado a 500 itens; use `page` para percorrer o restante.

**Os horários estão em qual fuso?**
Nos horários locais da instituição, como exibidos no sistema — sem conversão de
fuso pela API.
