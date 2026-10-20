# 🚪 Quadro de Sala — painel para tablet na porta

App externa de exemplo que consome a **API pública de reservas** do SIGerE
(`/api/v1`) de forma **anônima** — recebe apenas data, horário, sala e título de
reservas aprovadas, exatamente o que um painel de porta pode exibir. Sem login,
sem credenciais, sem dados pessoais.

Arquivo único (`index.html`), sem dependências: basta hospedar e abrir no
navegador kiosk do tablet.

## Como usar

1. Hospede a pasta em qualquer servidor estático (ou abra direto no tablet):

   ```bash
   python -m http.server 8000 --directory examples/quadro-sala
   ```

2. Abra no navegador do tablet, configurando pela URL:

   ```
   http://host-do-quadro:8000/?api=http://servidor-sigere:5000&room=S101&unity=1
   ```

   Salve essa URL como página inicial do navegador em modo kiosk/tela cheia.

3. Sem `?room=`, o próprio quadro exibe uma tela de configuração que monta a
   URL para você (útil para calibrar o tablet na primeira instalação).

## Parâmetros da URL

| Parâmetro | Obrigatório | Descrição |
|-----------|:-----------:|-----------|
| `api`     | sim (se o quadro não estiver na mesma origem do SIGerE) | URL base do SIGerE, ex.: `http://10.0.0.5:5000` |
| `room`    | sim | **Código** da sala no SIGerE (ex.: `S101`). Case-insensitive |
| `unity`   | não | ID da unidade. Sem ele, a API usa a primeira unidade ativa |
| `refresh` | não | Intervalo de atualização em segundos (padrão 60, mínimo 10) |
| `org`     | não | Rótulo exibido no cabeçalho (padrão `SIGerE`) |

## O que o quadro mostra

- **Relógio** com data por extenso (pt-BR) — o tablet precisa estar com o fuso
  horário correto, pois os horários de "agora" são calculados no cliente.
- **Faixa de status**: `EM USO` (vermelho, com o título da reserva em andamento
  e o horário de término) ou `LIVRE` (verde, com o horário da próxima reserva).
- **Lista do dia**: reservas aprovadas de hoje na sala, com a em andamento
  destacada (`AGORA`) e as passadas apagadas.
- **Atualização automática** a cada `refresh` segundos; se a API ficar
  inacessível, exibe aviso e mantém tentando.

## Notas técnicas

- A API do SIGerE responde com cabeçalhos CORS (`Access-Control-Allow-Origin: *`)
  justamente para permitir este tipo de app em outra origem/porta.
- A lista vem de `GET /api/v1/reservations?classroom_code=…&start=hoje&end=hoje`
  e o nome da sala de `GET /api/v1/rooms` — endpoints públicos da API; veja
  [docs/api-reservas.md](../../docs/api-reservas.md) para a documentação completa.
- Títulos são inseridos via `textContent` (anti-XSS); a API é somente leitura.
