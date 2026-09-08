"""Blueprints da aplicação, um módulo (ou subpacote) por funcionalidade.

- auth         Autenticação (login, logout, troca de senha)
- main         Dashboard principal
- classrooms   Salas (listagem, detalhes, disponibilidade)
- reservations Reservas (CRUD, aprovações, repetição, conflitos)
- admin        Painel administrativo
- schedule     API JSON para o FullCalendar
- totem        Display de quiosque para TVs
- public       Portal público (home, busca)
- payments     Pagamentos docentes (hora extra)
- vt           Vale Transporte (Financeiro): importação do Pedido de Compra,
               edição e exportação da planilha de pagamento
- kitchen      Cozinha (fichas técnicas, preparações, requisição de compra)
"""
