"""Versionamento do SIGerE.

Número da versão da aplicação em SemVer (MAJOR.MINOR.PATCH):
  - MAJOR: mudanças incompatíveis (ex.: quebra de contrato da API, schema sem migração);
  - MINOR: novas funcionalidades compatíveis com as anteriores;
  - PATCH: correções de defeitos.

A cada release, atualize APP_VERSION e adicione a entrada correspondente no
topo de RELEASES — a tela /changelog (main.changelog) e o rodapé exibem estes
dados automaticamente.
"""

APP_VERSION = '1.2.0'

# Histórico de versões, do mais novo para o mais antigo. Cada release tem
# versão, data (AAAA-MM-DD), título e grupos no padrão do "Keep a Changelog"
# (Adicionado, Alterado, Corrigido, Removido).
RELEASES = [
    {
        'versao': '1.2.0',
        'data': '2026-09-15',
        'titulo': 'Cadastro unificado de Professor e Funcionário',
        'grupos': [
            ('Adicionado', [
                'Formulário único e dinâmico de cadastro de usuários: o tipo de perfil (Professor/Funcionário) alterna os campos específicos e pode ser trocado antes de salvar; as telas "Cadastrar Professor" e "Cadastrar Funcionário" continuam existindo e apenas abrem o formulário com o tipo pré-escolhido.',
                'Matrícula obrigatória com mensagem que cita o perfil escolhido ("Informe a matrícula/ID do professor / do funcionário").',
            ]),
            ('Alterado', [
                'A edição de usuário usa o mesmo formulário único, com o tipo de perfil travado (não pode ser alterado, nem por envio forjado do formulário).',
                'Mapeamento entre tipo de perfil e papel interno centralizado em um único lugar do código, aplicado igualmente na criação e na edição.',
            ]),
            ('Corrigido', [
                'Cadastro de salas: nome e prédio passam a aceitar números e pontuação (SA212, Lab 101-B, Prédio 2) — a validação anterior bloqueava inclusive a edição de salas com o próprio código gerado.',
                'Tela de edição de usuário exibe o cabeçalho em português ("Editar Professor"/"Editar Funcionário") em vez do valor interno em inglês.',
            ]),
        ],
    },
    {
        'versao': '1.1.0',
        'data': '2026-09-15',
        'titulo': 'Migração do sistema legado (Django/MySQL)',
        'grupos': [
            ('Adicionado', [
                'Comando flask import-legacy: importa o banco do sistema antigo (dump MySQL do phpMyAdmin) em uma única operação — usuários, salas, cursos, disciplinas, reservas de sala e de auditório e hora extra, tudo na unidade Faculdade Senac Florianópolis.',
                'Senhas do sistema antigo aproveitadas: quem tinha senha válida entra com ela e a troca é obrigatória no primeiro acesso.',
                'Documentação da migração (docs/migracao-legado.md) com o mapeamento das tabelas, decisões de importação e checklist pós-migração.',
            ]),
            ('Corrigido', [
                'Teste do filtro de disciplinas não falha mais quando executado depois das 14h (usava horário do próprio dia e esbarrava na validação de horário no passado).',
            ]),
        ],
    },
    {
        'versao': '1.0.0',
        'data': '2026-09-14',
        'titulo': 'Primeira versão estável',
        'grupos': [
            ('Adicionado', [
                'Login pelo e-mail do usuário — o campo "nome de usuário" foi removido do sistema.',
                'Tela de novidades (changelog) com o histórico de versões e o número no rodapé.',
                'Papéis adicionais por usuário (ex.: Módulo Cozinha para professores de gastronomia).',
                'Detecção automática da unidade mais próxima pela geolocalização no cronograma e na busca de aulas.',
                'Cenário de demonstração completo (flask seed-demo) com datas relativas a hoje.',
            ]),
            ('Removido', [
                'Papéis "Visualizador" e "Administrador Financeiro" (substituídos pelos novos papéis padrão).',
            ]),
        ],
    },
    {
        'versao': '0.5.0',
        'data': '2026-09-12',
        'titulo': 'API pública de reservas e módulos opcionais por unidade',
        'grupos': [
            ('Adicionado', [
                'API REST de leitura de reservas (/api/v1) com tokens Bearer gerados no painel.',
                'App de exemplo de quadro de porta consumindo a API, com CORS liberado.',
                'Módulos Cozinha e Financeiro que ligam/desligam por unidade (reservas seguem sempre ativas).',
                'Botão de compartilhar reserva por e-mail ou WhatsApp no detalhe da reserva.',
                'Cozinha: ficha técnica em tabelas, relatório de ingredientes em tela e requisição de compra em grade.',
                'Salas: disponibilidade com visões por dia, semana e mês, com exportação fiel à visão atual.',
            ]),
        ],
    },
    {
        'versao': '0.4.0',
        'data': '2026-09-10',
        'titulo': 'Permissões por módulo e portal público',
        'grupos': [
            ('Adicionado', [
                'Permissões agrupadas por módulo na tela de papéis, com marcar/limpar por grupo.',
                'Checklist de configuração inicial no primeiro acesso do super-admin.',
                'Menu lateral dividido em seções por módulo.',
                'Importação das unidades do Senac SC pelo comando seed-unidades, com botão "Reler arquivo" no painel.',
                'Listagem de unidades com ordenação por coluna e exibição do ID (usado pelo totem).',
            ]),
        ],
    },
    {
        'versao': '0.3.0',
        'data': '2026-09-03',
        'titulo': 'Módulo Cozinha e multi-unidade',
        'grupos': [
            ('Adicionado', [
                'Módulo Cozinha: fichas técnicas, preparações e requisições de compra.',
                'Suporte a múltiplas unidades educacionais com seletor de unidade ativa.',
            ]),
        ],
    },
    {
        'versao': '0.2.0',
        'data': '2026-08-14',
        'titulo': 'Novo design e pagamento extra',
        'grupos': [
            ('Adicionado', [
                'Lançamentos de Pagamento Extra (hora extra) para professores.',
            ]),
            ('Alterado', [
                'Renovação visual completa das páginas, com tema claro/escuro.',
            ]),
        ],
    },
    {
        'versao': '0.1.0',
        'data': '2026-07-20',
        'titulo': 'Núcleo de reservas de salas',
        'grupos': [
            ('Adicionado', [
                'Autenticação com troca de senha obrigatória no primeiro acesso.',
                'Cadastro de salas, categorias, cursos, disciplinas e feriados.',
                'Reservas com fluxo de aprovação, conflitos de sala/professor e calendário.',
            ]),
        ],
    },
]
