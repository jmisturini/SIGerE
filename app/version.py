"""Versionamento do SIGerE.

Número da versão da aplicação em SemVer (MAJOR.MINOR.PATCH):
  - MAJOR: mudanças incompatíveis (ex.: quebra de contrato da API, schema sem migração);
  - MINOR: novas funcionalidades compatíveis com as anteriores;
  - PATCH: correções de defeitos.

A cada release, atualize APP_VERSION e adicione a entrada correspondente no
topo de RELEASES — a tela /changelog (main.changelog) e o rodapé exibem estes
dados automaticamente.
"""

APP_VERSION = '1.20.0'

# Histórico de versões, do mais novo para o mais antigo. Cada release tem
# versão, data (AAAA-MM-DD), título e grupos no padrão do "Keep a Changelog"
# (Adicionado, Alterado, Corrigido, Removido).
RELEASES = [
    {
        'versao': '1.20.0',
        'data': '2026-09-23',
        'titulo': 'Atalhos de período no cronograma mobile, salas em ordem no painel e unidade memorizada',
        'grupos': [
            ('Adicionado', [
                'No cronograma público acessado pelo celular, barra fixa de atalhos Manhã/Tarde/Noite (com a contagem de aulas de cada período) presa abaixo do topo enquanto a página rola — não é mais preciso deslizar pelos períodos anteriores para chegar à Tarde ou à Noite. Abrindo o cronograma do dia, a página rola sozinha até o cartão do período em curso (o do selo "Agora"); o atalho do período que está na tela fica marcado durante a rolagem e o do período em curso leva um ponto pulsante; tocar num atalho desliza suavemente até o cartão do período. No desktop nada muda: os três períodos continuam lado a lado, sem a barra.',
            ]),
            ('Alterado', [
                'No painel, as salas do dia agora aparecem em ordem crescente de numeração (LI104, LI202, LI205...), comparando os números do código como inteiros — LI9 viria antes de LI10 — e usando o horário da aula apenas como desempate; antes, salas com o mesmo horário saíam em ordem imprevisível, que dependia da ordem de cadastro das reservas.',
                'No portal público (cronograma e busca de aula), a unidade escolhida — pela lista ou pela detecção de unidade próxima — fica memorizada na sessão do visitante: navegar entre as páginas pelo menu não reseta mais a seleção para a primeira unidade. Unidade desativada depois da escolha ou endereço com unidade inexistente caem na primeira unidade ativa, sem erro.',
            ]),
        ],
    },
    {
        'versao': '1.19.0',
        'data': '2026-09-21',
        'titulo': 'Favicon do site e filtro instantâneo de salas disponíveis',
        'grupos': [
            ('Adicionado', [
                'Favicon do site: o prédio da marca (o mesmo do menu lateral) sobre o Azul Senac nas abas do navegador e nos atalhos de tela inicial — SVG vetorial para navegadores modernos, .ico para os mais antigos, PNGs de 16 e 32 px e ícone apple-touch.',
            ]),
            ('Alterado', [
                'Na listagem de salas, o checkbox "Mostrar apenas salas disponíveis AGORA" aplica o filtro na hora em que é marcado e também quando é desmarcado, sem depender do botão Filtrar — ao desmarcar, a listagem volta a mostrar todas as salas mantendo os demais filtros ativos.',
            ]),
        ],
    },
    {
        'versao': '1.18.2',
        'data': '2026-09-21',
        'titulo': 'Caixas dos códigos de sala uniformes',
        'grupos': [
            ('Corrigido', [
                'Nas listagens (painel, cronograma público, busca de aula e Todas as Reservas), as caixas com o código da sala ganharam largura mínima uniforme com o número centralizado e dígitos de largura fixa — na fonte proporcional, códigos com "1" (ex.: 103) ficavam mais estreitos que os demais (302).',
            ]),
        ],
    },
    {
        'versao': '1.18.1',
        'data': '2026-09-21',
        'titulo': 'Manual do usuário e README atualizados',
        'grupos': [
            ('Alterado', [
                'Manual do usuário em PDF atualizado para a v1.18.0: a seção do cronograma público descreve o destaque do período atual com o selo "Agora" e a seção de cursos e disciplinas documenta o botão Mostrar/Esconder inativos; referências de versão revisadas na capa, nos rodapés e na introdução.',
                'Manual do usuário: descrição do campo Título / Assunto da reserva corrigida na Tabela 2 — o campo aceita letras, números e pontuação comum, não "apenas letras" — e o passo de cadastro de usuário documenta que o Nome Completo aceita letras, números e pontuação (regras da v1.17.2 que o manual ainda não refletia).',
                'README: as seções de Estrutura Acadêmica e Portal Público passam a descrever o filtro de inativos das listagens de cursos e disciplinas e o destaque do período atual no cronograma; captura de tela do cronograma público refeita com o novo destaque.',
            ]),
        ],
    },
    {
        'versao': '1.18.0',
        'data': '2026-09-21',
        'titulo': 'Filtro de inativos e período atual em destaque',
        'grupos': [
            ('Adicionado', [
                'Botão "Mostrar/Esconder inativos" nas páginas de Cursos e Disciplinas, como já existia na listagem de usuários: por padrão as páginas exibem apenas os registros ativos e o botão revela também os desativados. A escolha é preservada ao reordenar a listagem e a ordenação continua funcionando com os inativos visíveis.',
                'No cronograma público de aulas (/cronograma), o cartão do período em curso (Manhã/Tarde/Noite, mesmos cortes do totem) recebe destaque visual — borda e ícone em destaque, selo "Agora" e contador sólido — quando a consulta é do dia de hoje; em outros dias nenhum período é destacado.',
            ]),
        ],
    },
    {
        'versao': '1.17.2',
        'data': '2026-09-21',
        'titulo': 'Textos de formulário aceitam números, ordinais e pontuação',
        'grupos': [
            ('Corrigido', [
                'O título/assunto da reserva volta a aceitar números, ordinais e pontuação comuns ("2º Concurso de Integração", "Reunião de pais 1º semestre"): o filtro "apenas alfabético" herdado dos formulários antigos recusava qualquer dígito ou ponto e bloqueava o envio do formulário.',
                'O nome completo de Professor/Funcionário aceita pontuação e números ("Senac T.I.", "2º Sargento João"), no cadastro e na edição — o mesmo filtro recusava nomes legítimos já gravados no sistema.',
                'O mesmo filtro permissivo passa a valer para todos os campos de texto que ainda usavam o validador antigo: nomes de curso, disciplina, feriado, unidade, categoria de sala e papel, além da justificativa da hora extra — valores como "7 de Setembro" e "Coord. Geral" não são mais rejeitados.',
            ]),
        ],
    },
    {
        'versao': '1.17.1',
        'data': '2026-09-19',
        'titulo': 'Manual do usuário e documentação',
        'grupos': [
            ('Adicionado', [
                'Manual do Usuário em PDF (docs/manual-do-usuario.pdf, 23 páginas): guia de operação de todos os módulos — acesso, reservas, salas, calendário, portal público, totem, financeiro (hora extra e vale-transporte), cozinha, administração e API — com passo a passo, campos dos formulários, regras de negócio, mensagens comuns e solução de problemas.',
            ]),
            ('Alterado', [
                'README: manual do usuário incluído na tabela de Documentação; seção Vale-Transporte reescrita com o fluxo atual (formulário público, Pedidos VT, relatório e administração), URL correta da exportação da planilha de pagamento e permissões vt:* incluídas no catálogo de permissões.',
            ]),
        ],
    },
    {
        'versao': '1.17.0',
        'data': '2026-09-19',
        'titulo': 'Menu lateral reorganizado e carga horária em hora e minuto',
        'grupos': [
            ('Alterado', [
                'Menu lateral reorganizado: itens em pílulas arredondadas com respiro das bordas, item ativo em pílula clara que acompanha todos os temas de cor e o modo escuro, fios divisórios entre as seções, linha-guia ligando os itens de cada submenu e marca fixa no topo com o menu rolando de forma independente, com barra de rolagem discreta.',
                'A carga horária semanal do formulário de hora extra passa a ser informada em dois campos (hora e minuto), com dica mostrando o valor já convertido para hora decimal (ex.: 4h30 = 4,5) — o decimal é o que fica gravado, é exportado na coluna Horas da planilha e exibido na consulta e no modal. A coluna vira Numeric(5,2) em migração; lançamentos antigos (inteiros) continuam válidos.',
                'Detalhes do lançamento de hora extra exibem a carga horária nos dois formatos — "4,5 h (4h30)" — com a conversão de decimal para minutos centralizada em um helper reaproveitado pela edição.',
            ]),
            ('Corrigido', [
                'Editar uma hora extra não zera mais o professor do lançamento: o select voltava para o primeiro professor da lista porque o campo do formulário colidia com o relationship do modelo no repovoamento do WTForms.',
                'Implantação: cliente Python do Redis incluído no requirements (apontar o rate limit para Redis sem o pacote quebrava o startup), Redis com teste de conectividade no instalador interativo e criação da pasta instance/uploads; a documentação de atualização sai do sudo -u www-data, que descartava as variáveis de ambiente e tornava o .env ilegível.',
            ]),
        ],
    },
    {
        'versao': '1.16.0',
        'data': '2026-09-18',
        'titulo': 'Permissões do Vale-Transporte revisadas',
        'grupos': [
            ('Adicionado', [
                'Nova permissão "vt:config" (Configurar o pedido público de VT: vales base e data de fechamento) — as configurações deixam de emprestar a permissão de empresas de ônibus, permitindo separar quem gerencia tarifas de quem define prazos. O papel Administrador recebe a permissão nova automaticamente na sincronização.',
            ]),
            ('Alterado', [
                'Descrições das permissões do Vale-Transporte atualizadas para o produto atual (Pedidos VT, relatório e correção individual) — a sincronização de permissões (flask sync-permissions, executada também no startup) passou a atualizar descrições de permissões já existentes, não só criar as novas.',
            ]),
            ('Removido', [
                'A permissão "vt:create" (importação do Pedido de Compra) saiu do catálogo junto com a funcionalidade que foi desativada; a sincronização a aposenta dos bancos existentes, removendo os vínculos com papéis.',
            ]),
        ],
    },
    {
        'versao': '1.15.0',
        'data': '2026-09-18',
        'titulo': 'Temas de cor personalizáveis',
        'grupos': [
            ('Adicionado', [
                'Nova paleta de temas na topbar (botão de paleta, ao lado do claro/escuro): Azul Senac (padrão), Verde, Roxo, Laranja e Grafite — a cor escolhida tinge botões, links, foco de campos, paginação, sidebar e os gráficos do relatório, nos modos claro e escuro.',
                'A escolha do tema e do modo fica salva no navegador (localStorage) e é aplicada antes da página renderizar, sem piscar a paleta padrão.',
            ]),
        ],
    },
    {
        'versao': '1.14.1',
        'data': '2026-09-18',
        'titulo': 'Grupos da planilha de pagamento simplificados',
        'grupos': [
            ('Alterado', [
                'Os grupos de colaboradores da planilha de pagamento do Vale-Transporte passam a ser apenas "Técnico-Administrativo" e "Professores", definidos pelo vínculo do pedido — técnicos de todas as unidades entram no grupo único de Técnico-Administrativo.',
            ]),
            ('Removido', [
                'O grupo "Técnico-Administrativo (Restaurante/Lanchonete)" da exportação — a divisão por unidade (Faculdade / Restaurante/Lanchonete) herdada do gerador original saiu da planilha.',
            ]),
        ],
    },
    {
        'versao': '1.14.0',
        'data': '2026-09-18',
        'titulo': 'Relatório visual do Vale-Transporte',
        'grupos': [
            ('Adicionado', [
                'Nova página "Relatório" no módulo Vale Transporte: panorama dos pedidos da unidade com indicadores de pedidos recebidos, adesão ao benefício, vales necessários e investimento estimado; gráficos de optantes (deseja VT, vínculo, trajetos, empresas por pedido) e investimento por empresa de ônibus; resumo por empresa e por grupo da planilha de pagamento; conferências do RH (maior pedido, e-mails e matrículas repetidas).',
                'O relatório tem versão para impressão/PDF pronta para apresentação — botão "Imprimir / PDF" que removes o painel de navegação e preserva as cores — e atalho no menu Vale Transporte e na página Pedidos VT.',
            ]),
        ],
    },
    {
        'versao': '1.13.4',
        'data': '2026-09-18',
        'titulo': 'Planilha de pagamento reconhece as unidades reais',
        'grupos': [
            ('Corrigido', [
                'A exportação da planilha de pagamento voltou a encontrar pedidos elegíveis: a classificação por grupo comparava o nome da unidade a textos exatos do sistema antigo ("Faculdade", "Restaurante - ALESC/…") e unidades com o nome real, como "Faculdade Senac Florianópolis", ficavam fora de todos os grupos — o reconhecimento agora é pelo trecho do nome da unidade do pedido.',
            ]),
        ],
    },
    {
        'versao': '1.13.3',
        'data': '2026-09-18',
        'titulo': 'Tarifas fantasmas no cadastro de empresas eliminadas',
        'grupos': [
            ('Corrigido', [
                'O cadastro de empresas de ônibus não mostra mais tarifas "fantasma": linhas deixadas no banco por exclusões feitas fora do aplicativo (o SQLite não valida a chave estrangeira por padrão) reapareciam numa empresa nova quando o id dela era reutilizado, como uma tarifa extra sem identificação — a atualização remove as órfãs e as duplicatas sem identificação, e o formulário de edição deixa de exibir o texto "None" no lugar da identificação.',
            ]),
        ],
    },
    {
        'versao': '1.13.2',
        'data': '2026-09-18',
        'titulo': 'Cadastro de empresas sem valores repetidos pelo navegador',
        'grupos': [
            ('Corrigido', [
                'No cadastro de empresas de ônibus, os campos de tarifa voltaram a abrir vazios: o navegador estava repetindo neles valores armazenados de envios anteriores (autocomplete e retorno pelo cache ao botão Voltar) quando uma empresa nova era cadastrada.',
            ]),
        ],
    },
    {
        'versao': '1.13.1',
        'data': '2026-09-18',
        'titulo': 'Filtro de vínculo atual e exportação única em Pedidos VT',
        'grupos': [
            ('Corrigido', [
                'O filtro de Vínculo da listagem Pedidos VT voltou a oferecer apenas os vínculos do formulário atual (Técnico - Administrativo e Professor(a)) — o select listava também valores antigos gravados na base, que não filtravam nada.',
            ]),
            ('Removido', [
                'O botão "Exportar respostas (.xlsx)" saiu da página Pedidos VT — a exportação da listagem fica apenas com a planilha de pagamento por grupo.',
            ]),
        ],
    },
    {
        'versao': '1.13.0',
        'data': '2026-09-17',
        'titulo': 'Página única Pedidos VT',
        'grupos': [
            ('Adicionado', [
                'A listagem "Pedidos VT" (respostas do formulário público) ganhou o layout completo da antiga página de Colaboradores: card de exportação da planilha de pagamento por grupo — agora calculada dos pedidos, com valor = tarifa × vales —, filtros de nome/vínculo/deseja VT, ordenação (mais recentes, nome, matrícula, valor) e opção de esconder não optantes.',
                'Correção individual dos pedidos: editar (mesmo formulário do colaborador, com as tarifas do cadastro da unidade) e excluir, conforme as permissões vt:edit e vt:delete.',
            ]),
            ('Removido', [
                'A importação do "Pedido de Compra" (.xlsx) e a listagem de colaboradores importados saíram do ar — o formulário público alimenta a listagem diretamente; /vt/ e /vt/colaboradores viraram redirecionamentos para Pedidos VT.',
            ]),
        ],
    },
    {
        'versao': '1.12.2',
        'data': '2026-09-18',
        'titulo': 'Nº de vales livre com botão de valor base',
        'grupos': [
            ('Alterado', [
                'O nº de vales do pedido público voltou a ser um campo livre (somente número, menor que 50); quando a unidade configura os números base, o botão "Usar valor base" preenche o campo com um clique conforme o trajeto escolhido.',
                'O botão "Usar valor base" é oferecido apenas para o vínculo Técnico-Administrativo — professores digitam o número.',
            ]),
        ],
    },
    {
        'versao': '1.12.1',
        'data': '2026-09-18',
        'titulo': 'Identificação do colaborador travada pelo cadastro',
        'grupos': [
            ('Alterado', [
                'No pedido público de VT, ao informar um e-mail de conta ativa do sistema, nome, matrícula e vínculo passam a vir direto do cadastro e ficam travados (o vínculo é derivado do perfil: funcionário é Técnico-Administrativo e professor é Professor(a)); e-mail sem cadastro mantém a digitação manual.',
            ]),
            ('Corrigido', [
                'Valores enviados por POST para nome, matrícula ou vínculo diferentes do cadastro são ignorados quando o e-mail corresponde a uma conta ativa.',
            ]),
        ],
    },
    {
        'versao': '1.12.0',
        'data': '2026-09-18',
        'titulo': 'Painel Administrativo como central de gestão e configurações do pedido de VT',
        'grupos': [
            ('Adicionado', [
                'Nova página "Configurações do Pedido de VT" na administração (por unidade): números base de vales para Somente Volta e Ida e Volta — quando definidos, o pedido público aplica o número automaticamente conforme o trajeto, sem o colaborador digitar — e data de fechamento do formulário, que passa a ser bloqueado após o prazo, com aviso do último dia durante o período aberto.',
                'O Painel Administrativo virou a central de gestão: cards de acesso a Unidades, Tokens da API, Empresas de Ônibus e Configurações do Pedido de VT, cada um exibido conforme a permissão.',
            ]),
            ('Alterado', [
                'As páginas de Unidades e Tokens da API saíram da barra lateral e passam a ser acessadas pelo Painel Administrativo; quem tem qualquer uma das permissões de administração acessa o painel, mesmo sem a permissão de painel do sistema.',
            ]),
        ],
    },
    {
        'versao': '1.11.4',
        'data': '2026-09-17',
        'titulo': 'Pergunta de unidade removida do pedido de VT',
        'grupos': [
            ('Removido', [
                'A pergunta "Unidade" (Faculdade / Restaurante / Lanchonete) saiu do pedido público — o pedido já fica registrado na unidade do link usado pelo colaborador, e a coluna Unidade da listagem passa a mostrar essa unidade.',
            ]),
            ('Alterado', [
                'Com a pergunta de unidade removida, o vínculo (Técnico-Administrativo ou Professor) passou a ser perguntado para todos os colaboradores, sem exceção por unidade.',
            ]),
        ],
    },
    {
        'versao': '1.11.3',
        'data': '2026-09-17',
        'titulo': 'Empresas de ônibus exclusivas de cada unidade',
        'grupos': [
            ('Alterado', [
                'As empresas de ônibus do pedido de VT deixaram de ser compartilhadas entre unidades: cada empresa pertence exclusivamente à unidade que a cadastrou, aparece apenas no formulário e na administração dela, e as de outras unidades ficam invisíveis.',
            ]),
            ('Removido', [
                'O conceito de empresa compartilhada (visível/editável por todas as unidades) — as empresas cadastradas antes da atualização foram atribuídas à primeira unidade ativa.',
            ]),
        ],
    },
    {
        'versao': '1.11.2',
        'data': '2026-09-17',
        'titulo': 'Identificação da tarifa no lugar do trajeto',
        'grupos': [
            ('Alterado', [
                'No cadastro de empresas, o primeiro campo da linha de tarifa passou a ser a identificação da tarifa aplicada, em texto livre (ex.: "Patamar 3", da tabela Metropolis) — no pedido público, a opção aparece como "Patamar 3 — R$ 7,38".',
                'A pergunta de trajeto (Somente Volta / Ida e Volta) voltou ao pedido público, agora independente da tarifa escolhida.',
            ]),
        ],
    },
    {
        'versao': '1.11.1',
        'data': '2026-09-17',
        'titulo': 'Tarifa por trajeto e ajuste no pedido de VT',
        'grupos': [
            ('Alterado', [
                'No cadastro de empresas de ônibus, as tarifas passaram a ser linhas dinâmicas com trajeto e valor (botão "Adicionar tarifa") — cada empresa informa a tarifa de cada trajeto.',
                'No pedido público, a opção de "Valor do vale" mostra o trajeto junto ("Ida e Volta — R$ 7,24") e já define o trajeto do pedido; a pergunta separada de trajeto foi incorporada a essa escolha.',
            ]),
            ('Corrigido', [
                'No pedido público, ao selecionar uma empresa o select de tarifa continuava exibindo as tarifas de todas as empresas (o autocomplete Tom Select guardava as opções do carregamento inicial).',
            ]),
        ],
    },
    {
        'versao': '1.11.0',
        'data': '2026-09-17',
        'titulo': 'Vale-Transporte gerenciável por unidade',
        'grupos': [
            ('Adicionado', [
                'O pedido público de Vale-Transporte passou a pertencer a uma unidade: o link enviado aos colaboradores leva a unidade (/vt/pedido?unity=N, exibida no topo do formulário) e as respostas ficam na listagem e na exportação da unidade ativa.',
                'O cadastro de empresas de ônibus ficou por unidade — cada uma mantém as próprias empresas e tarifas. As cadastradas antes da atualização viraram "compartilhadas", valendo para todas as unidades e editáveis apenas por contas globais ou super-admin.',
                'Nomes de empresa podem se repetir entre unidades diferentes; a checagem de duplicidade é dentro da unidade.',
            ]),
        ],
    },
    {
        'versao': '1.10.0',
        'data': '2026-09-17',
        'titulo': 'Empresas de ônibus gerenciáveis na administração',
        'grupos': [
            ('Adicionado', [
                'Nova área Administração → Empresas de Ônibus (permissão "vt:empresas", concedida ao papel Administrador): cadastro de empresas e tarifas vigentes usadas pelo pedido público de Vale-Transporte, com criação, edição, exclusão e ativação/desativação — excluí-las não afeta pedidos antigos.',
            ]),
            ('Alterado', [
                'As empresas e tarifas do pedido público de VT deixaram de ser fixas no código e passaram a vir desse cadastro; papel "Administrador" padrão recebe a permissão de gerenciá-las.',
            ]),
        ],
    },
    {
        'versao': '1.9.1',
        'data': '2026-09-17',
        'titulo': 'Empresa e tarifa separadas no pedido de VT',
        'grupos': [
            ('Alterado', [
                'No pedido público de Vale-Transporte, a empresa de ônibus passou a mostrar apenas o nome; logo abaixo, um campo de valor oferece as tarifas vigentes da empresa escolhida (7,20 a 12,08, conforme a empresa).',
                'A tarifa escolhida agora é gravada e exportada separadamente nas respostas (colunas Valor A e Valor B da exportação .xlsx).',
            ]),
        ],
    },
    {
        'versao': '1.9.0',
        'data': '2026-09-17',
        'titulo': 'Ajustes no pedido público de Vale-Transporte',
        'grupos': [
            ('Adicionado', [
                'O formulário público de VT em tela cheia, sem a barra lateral do painel.',
                'Ao informar o e-mail, nome e matrícula são preenchidos automaticamente quando existe conta ativa com aquele e-mail.',
                'O botão de envio só é habilitado quando os campos obrigatórios da ramificação visível estão preenchidos.',
            ]),
            ('Alterado', [
                'A pergunta de vínculo agora aparece apenas quando a unidade é a Faculdade; Restaurante e Lanchonete assumem Técnico-Administrativo no pedido.',
            ]),
        ],
    },
    {
        'versao': '1.8.0',
        'data': '2026-09-17',
        'titulo': 'Pedido público de Vale-Transporte dentro do sistema',
        'grupos': [
            ('Adicionado', [
                'O "Pedido de Vale-Transporte" (antes no Microsoft Forms) virou página do sistema: /vt/pedido é pública, com acesso identificado apenas pelo e-mail, e replica as perguntas originais — deseja VT no mês, unidade, vínculo, empresas de ônibus (com tarifas), número de vales e trajetos, com a mesma ramificação do formulário original.',
                'As respostas recebidas aparecem em Vale Transporte → "Pedidos do Formulário", com busca e filtro por quem deseja VT, e exportação para .xlsx para a conferência do RH.',
            ]),
        ],
    },
    {
        'versao': '1.7.0',
        'data': '2026-09-16',
        'titulo': 'Conta super-administrador protegida e tokens da API sem reenvio',
        'grupos': [
            ('Adicionado', [
                'A conta super-administrador ficou protegida: operadores sem a permissão universal não podem editá-la, desativá-la nem redefinir sua senha — a listagem de usuários exibe o selo "Protegida" nessas linhas.',
                'Atribuir papéis com permissão universal (*) passou a ser exclusivo do super-administrador, na criação e na edição de usuários; a permissão "*" também saiu da grade do formulário de papéis para quem não é super-admin, e POST forjado é rejeitado.',
                'Alternar a unidade ativa de operação agora é exclusivo do super-administrador: a permissão "unity:switch" deixou de liberar o seletor do topo e saiu do papel padrão Administrador.',
            ]),
            ('Corrigido', [
                'A criação de token da API voltou a seguir o padrão Post/Redirect/Get: recarregar a página logo após gerar um token não cria mais tokens extras, e a primeira revogação/exclusão depois da criação não falha mais com erro 405.',
            ]),
        ],
    },
    {
        'versao': '1.6.1',
        'data': '2026-09-16',
        'titulo': 'Correção de layout no seletor de ícone da categoria',
        'grupos': [
            ('Corrigido', [
                'Na edição de categorias, o seletor de ícone voltou ao layout correto — o campo de busca automática quebrava o campo quando ele estava dentro de um grupo com botão anexo; selects nesse formato seguem nativos.',
            ]),
        ],
    },
    {
        'versao': '1.6.0',
        'data': '2026-09-16',
        'titulo': 'Unidade ativa no topo à esquerda, com botão de troca',
        'grupos': [
            ('Adicionado', [
                'A unidade ativa mudou para o lado esquerdo do topo, ao lado da barra lateral, exibindo o nome completo.',
                'Botão "Trocar" ao lado do nome abre a lista de unidades — visível apenas para quem tem permissão de alternar unidade; quem não tem vê apenas o nome.',
            ]),
        ],
    },
    {
        'versao': '1.5.6',
        'data': '2026-09-16',
        'titulo': 'Seletor de unidade compatível com Firefox',
        'grupos': [
            ('Corrigido', [
                'No Firefox, a seta do seletor de unidade continuava sobreposta ao nome — a seta foi movida para fora do select (ícone externo com espaço reservado pelo padding), eliminando a sobreposição em qualquer navegador.',
            ]),
        ],
    },
    {
        'versao': '1.5.5',
        'data': '2026-09-16',
        'titulo': 'Menu lateral sinaliza corretamente a página visitada',
        'grupos': [
            ('Corrigido', [
                'Unidades agora fica sinalizado no menu ao acessar qualquer tela de unidades — antes o destaque ficava preso no Painel Admin.',
                'Painel, Calendário, itens do submenu (Nova/Minhas/Todas as Reservas, Hora Extra, Vale-Transporte) e Cozinha também mantêm o destaque nas respectivas páginas, incluindo telas de detalhe e edição.',
            ]),
        ],
    },
    {
        'versao': '1.5.4',
        'data': '2026-09-16',
        'titulo': 'Seletor de unidade sem sobreposição da seta',
        'grupos': [
            ('Corrigido', [
                'Nomes longos de unidade não são mais cobertos pela seta do seletor no topo da página — o nome é exibido abreviado com reticências e o nome completo aparece no tooltip.',
            ]),
        ],
    },
    {
        'versao': '1.5.3',
        'data': '2026-09-16',
        'titulo': 'Ordenação nas demais listagens administrativas',
        'grupos': [
            ('Adicionado', [
                'Filtro "Ordenar por" na listagem de usuários (papel+nome, nome A–Z/Z–A, matrícula com vazias por último, ativas primeiro), salas (código, nome, capacidade maior primeiro, prédio/andar), categorias de sala e papéis (nome A–Z/Z–A).',
            ]),
        ],
    },
    {
        'versao': '1.5.2',
        'data': '2026-09-16',
        'titulo': 'Mostrar/esconder desativados na listagem de usuários',
        'grupos': [
            ('Adicionado', [
                'Botão na página Gerenciar Usuários para exibir ou ocultar as contas desativadas — por padrão a listagem mostra apenas as contas ativas, e o estado persiste ao filtrar e paginar.',
            ]),
        ],
    },
    {
        'versao': '1.5.1',
        'data': '2026-09-16',
        'titulo': 'Importação legada: quadro lotado entra como funcionário',
        'grupos': [
            ('Alterado', [
                'Na importação do sistema antigo, usuário com setor, departamento ou função preenchidos passa a ser importado como funcionário — mesmo com função de professor, que segue podendo ser designado nas reservas (flag "também professor").',
                'Professor passa a ser apenas quem não tem nenhum vínculo administrativo: os importados só da tabela de professores ou os que chegam sem setor/departamento/função.',
            ]),
        ],
    },
    {
        'versao': '1.5.0',
        'data': '2026-09-16',
        'titulo': 'Perfil do usuário (Meu Perfil)',
        'grupos': [
            ('Adicionado', [
                'Nova área "Meu Perfil" no menu do usuário: cada pessoa atualiza o próprio nome completo e departamento e troca a própria senha sem depender da administração.',
                'A troca de senha pelo perfil exige a senha atual, recusa a repetição da senha vigente e pede confirmação da nova senha.',
            ]),
            ('Alterado', [
                'O e-mail (login) aparece como somente leitura no perfil — mudança de e-mail continua exclusividade da administração.',
            ]),
        ],
    },
    {
        'versao': '1.4.2',
        'data': '2026-09-16',
        'titulo': 'Ordenação nas páginas de Cursos e Disciplinas',
        'grupos': [
            ('Adicionado', [
                'Filtro "Ordenar por" nas páginas de Cursos e Disciplinas: nome (A–Z/Z–A), código e — nos cursos — quantidade de disciplinas; nas disciplinas, agrupamento por curso (sem curso por último).',
            ]),
        ],
    },
    {
        'versao': '1.4.1',
        'data': '2026-09-16',
        'titulo': 'Editar reservas direto da página da sala',
        'grupos': [
            ('Adicionado', [
                'A lista de próximas reservas na página de detalhes da sala ganhou botão de edição — visível para quem tem permissão de editar qualquer reserva ou para o dono da reserva.',
            ]),
        ],
    },
    {
        'versao': '1.4.0',
        'data': '2026-09-16',
        'titulo': 'Todas as Reservas com filtros do calendário',
        'grupos': [
            ('Adicionado', [
                'A página Todas as Reservas ganhou os mesmos filtros do calendário — datas inicial/final, período do dia (manhã/tarde/noite), sala, professor, curso e disciplina — além de filtro por status e de ordenação (data crescente/decrescente, sala ou professor).',
                'Filtro de ordenamento com padrão "Data — da atual para a futura"; abas e filtros continuam aplicados ao trocar de página da paginação.',
            ]),
            ('Alterado', [
                'A barra de abas Todas/Aprovadas/Pendentes/Canceladas foi substituída por duas abas — Atuais e Futuras, e Passadas — com contagem de registros; o status virou filtro comum na barra de filtros.',
            ]),
        ],
    },
    {
        'versao': '1.3.1',
        'data': '2026-09-16',
        'titulo': 'Busca limpa nas caixas de seleção',
        'grupos': [
            ('Corrigido', [
                'Ao digitar para buscar em uma caixa de seleção simples, o texto do item selecionado não fica mais preso ao lado da busca — só o que está sendo digitado aparece; ao fechar, o item volta ao normal.',
            ]),
        ],
    },
    {
        'versao': '1.3.0',
        'data': '2026-09-16',
        'titulo': 'Busca nas caixas de seleção',
        'grupos': [
            ('Adicionado', [
                'Caixas de seleção com muitas opções (a partir de 6) ganharam busca digitável em todo o sistema — papéis, unidades, módulos, salas, cursos, disciplinas e professores — com seleção múltipla em etiquetas removíveis e tema claro/escuro integrado.',
            ]),
            ('Alterado', [
                'O filtro curso → disciplina das reservas atualiza também a caixa com busca, mantendo a disciplina já escolhida quando ela continua válida.',
            ]),
        ],
    },
    {
        'versao': '1.2.2',
        'data': '2026-09-16',
        'titulo': 'Setor e Função aceitam siglas e abreviações',
        'grupos': [
            ('Corrigido', [
                'Cadastro/edição de usuários: Setor e Função (e Departamento) passam a aceitar pontos, números e pontuação — valores reais como "T.I" e "Assist. Suporte em TI" eram recusados pela validação "apenas alfabética".',
            ]),
        ],
    },
    {
        'versao': '1.2.1',
        'data': '2026-09-16',
        'titulo': 'Entrada única de cadastro de usuário',
        'grupos': [
            ('Alterado', [
                'A tela "Gerenciar Usuários" agora abre o formulário único por um único botão "Cadastrar Usuário" — o tipo (Professor/Funcionário) é escolhido dentro do formulário, que abre pedindo a seleção.',
            ]),
            ('Corrigido', [
                'O seletor de tipo de perfil vinha renderizado desabilitado na criação, impedindo a troca do perfil no navegador.',
            ]),
        ],
    },
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
