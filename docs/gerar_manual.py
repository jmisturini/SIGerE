# -*- coding: utf-8 -*-
"""Gera o Manual do Usuário do SIGerE (docs/manual-do-usuario.pdf).

Uso:
    python docs/gerar_manual.py [saida.pdf]

O conteúdo vive na lista BLOCOS, na forma (tipo, ...). Tipos aceitos:
  ('h1', texto)                    — título de seção (entra no sumário)
  ('h2', texto)                    — título de subseção (entra no sumário)
  ('p', texto)                     — parágrafo (aceita <b> e <i>)
  ('ul', [itens])                  — lista com marcadores
  ('ol', [itens])                  — passos numerados
  ('passo', texto)                 — linha em negrito ("Passo 1 — ...")
  ('table', cabecalhos, linhas, larguras, legenda)  — larguras em pontos
  ('nota' | 'atencao' | 'importante', texto)

Regenerar exige apenas Python + reportlab e as fontes Calibri do Windows
(C:\\Windows\\Fonts); nada mais é necessário. A numeração de páginas do
sumário é resolvida com multiBuild (duas passagens automáticas).
"""

import os
import sys

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_CENTER
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak,
    HRFlowable, KeepTogether,
)
from reportlab.platypus.tableofcontents import TableOfContents

# ---------------------------------------------------------------- constantes

VERSAO = '1.25.0'
DATA_CAPA = 'Setembro de 2026'

PAGINA_W, PAGINA_H = A4
MARGEM = 56.0
LARGURA_UTIL = PAGINA_W - 2 * MARGEM

COR_TINTA = colors.HexColor('#1F1F1F')
COR_H1 = colors.HexColor('#33464F')      # títulos de seção, capa, cabeçalho de tabela
COR_H2 = colors.HexColor('#52798C')      # títulos de subseção
COR_CINZA = colors.HexColor('#7A7A7B')   # cabeçalho/rodapé de página, legendas
COR_BORDA_TABELA = colors.HexColor('#B5B7B7')
COR_ZEBRA = colors.HexColor('#EBEDED')
COR_MARCA_AGUA = colors.HexColor('#F2F2F3')

CALLOUTS = {
    'nota':       (colors.HexColor('#597785'), colors.HexColor('#EEF1F2')),
    'atencao':    (colors.HexColor('#A18246'), colors.HexColor('#F7F5F0')),
    'importante': (colors.HexColor('#91443D'), colors.HexColor('#F6F0EF')),
}

FONTE_DIR = r'C:\Windows\Fonts'


def _registrar_fontes():
    pdfmetrics.registerFont(TTFont('Corpo', os.path.join(FONTE_DIR, 'calibri.ttf')))
    pdfmetrics.registerFont(TTFont('Corpo-Negrito', os.path.join(FONTE_DIR, 'calibrib.ttf')))


# ------------------------------------------------------------------- estilos

def _estilos():
    s = {}
    s['h1'] = ParagraphStyle('h1', fontName='Corpo-Negrito', fontSize=19, leading=23,
                             textColor=COR_H1, spaceBefore=22, spaceAfter=4,
                             keepWithNext=1)
    s['h2'] = ParagraphStyle('h2', fontName='Corpo-Negrito', fontSize=13, leading=17,
                             textColor=COR_H2, spaceBefore=16, spaceAfter=6,
                             keepWithNext=1)
    s['p'] = ParagraphStyle('p', fontName='Corpo', fontSize=10.5, leading=15.5,
                            textColor=COR_TINTA, spaceAfter=8)
    s['ul'] = ParagraphStyle('ul', parent=s['p'], leftIndent=20, bulletIndent=7,
                             spaceAfter=3)
    s['ol'] = ParagraphStyle('ol', parent=s['p'], leftIndent=22, bulletIndent=7,
                             spaceAfter=3)
    s['passo'] = ParagraphStyle('passo', parent=s['p'], spaceBefore=6)
    s['callout'] = ParagraphStyle('callout', parent=s['p'], spaceAfter=0, fontSize=10.2)
    s['celula'] = ParagraphStyle('celula', fontName='Corpo', fontSize=9.8, leading=13,
                                 textColor=COR_TINTA)
    s['celula_n'] = ParagraphStyle('celula_n', parent=s['celula'],
                                   fontName='Corpo-Negrito')
    s['cab_tab'] = ParagraphStyle('cab_tab', fontName='Corpo-Negrito', fontSize=9.8,
                                  leading=13, textColor=colors.white, alignment=TA_CENTER)
    s['legenda'] = ParagraphStyle('legenda', fontName='Corpo', fontSize=8.5, leading=11,
                                  textColor=COR_CINZA, alignment=TA_CENTER,
                                  spaceBefore=5, spaceAfter=10)
    s['sum_titulo'] = ParagraphStyle('sum_titulo', parent=s['h1'], spaceBefore=0)
    s['toc0'] = ParagraphStyle('toc0', fontName='Corpo-Negrito', fontSize=10.8,
                               leading=15.5, textColor=COR_TINTA, spaceBefore=9)
    s['toc1'] = ParagraphStyle('toc1', fontName='Corpo', fontSize=10.2, leading=14.5,
                               textColor=COR_TINTA, leftIndent=15)
    return s


# ------------------------------------------------------- decoração de página

def _texto_espacado(canvas, x, y, texto, fonte, tamanho, espaco):
    """Desenha texto com espaçamento entre caracteres (letterspacing)."""
    t = canvas.beginText(x, y)
    t.setFont(fonte, tamanho)
    t.setCharSpace(espaco)
    t.textOut(texto)
    canvas.drawText(t)


def _capa(canvas, doc):
    canvas.saveState()
    # Marca d'água: a palavra MANUAL empilhada letra a letra na borda direita.
    canvas.setFillColor(COR_MARCA_AGUA)
    canvas.setFont('Corpo-Negrito', 205)
    y = 800
    for letra in 'MANUAL':
        canvas.drawString(447, y, letra)
        y -= 141
    # Traço decorativo, kicker, título e descrição.
    canvas.setStrokeColor(COR_H1)
    canvas.setLineWidth(3)
    canvas.line(73, 713, 110, 713)
    canvas.setFillColor(colors.HexColor('#6E7577'))
    _texto_espacado(canvas, 73, 665, 'MANUAL DO USUÁRIO · GUIA DE OPERAÇÃO',
                    'Corpo-Negrito', 11, 1.6)
    canvas.setFillColor(COR_H1)
    canvas.setFont('Corpo-Negrito', 66)
    canvas.drawString(71, 555, 'SIGerE')
    canvas.setFillColor(COR_TINTA)
    canvas.setFont('Corpo-Negrito', 15)
    texto = ('Sistema Integrado de Gerenciamento Educacional — guia completo de '
             'operação: reservas de salas, calendário, notificações, portal '
             'público, totem digital, financeiro (hora extra), RH '
             '(vale-transporte), cozinha e administração.')
    estilo = _estilos()['p']
    p = Paragraph(texto, ParagraphStyle('capa', parent=estilo, fontName='Corpo-Negrito',
                                        fontSize=15, leading=25.5, spaceAfter=0))
    _, altura = p.wrapOn(canvas, 345, 400)
    p.drawOn(canvas, 73, 480 - altura)
    # Bloco da versão com barra vertical à esquerda.
    canvas.rect(73, 160, 1.6, 125, stroke=0, fill=1)
    canvas.setFillColor(COR_TINTA)
    canvas.setFont('Corpo-Negrito', 13)
    canvas.drawString(89, 240, f'Versão do sistema v{VERSAO} · {DATA_CAPA}')
    # Rodapé da capa.
    canvas.setFillColor(colors.HexColor('#6E7577'))
    largura = pdfmetrics.stringWidth('USO INTERNO · DOCUMENTAÇÃO DE OPERAÇÃO',
                                     'Corpo-Negrito', 11) + 1.2 * 37
    _texto_espacado(canvas, (PAGINA_W - largura) / 2, 68,
                    'USO INTERNO · DOCUMENTAÇÃO DE OPERAÇÃO', 'Corpo-Negrito', 11, 1.2)
    canvas.restoreState()


def _pagina_comum(canvas, doc):
    canvas.saveState()
    # Cabeçalho.
    canvas.setFillColor(COR_CINZA)
    canvas.setFont('Corpo', 8)
    canvas.drawString(MARGEM, PAGINA_H - 40, 'SIGerE — Manual do Usuário')
    canvas.setStrokeColor(COR_H1)
    canvas.setLineWidth(1.5)
    canvas.line(MARGEM, PAGINA_H - 47, PAGINA_W - MARGEM, PAGINA_H - 47)
    # Rodapé.
    canvas.setStrokeColor(colors.HexColor('#D5DBDD'))
    canvas.setLineWidth(0.7)
    canvas.line(MARGEM, 54, PAGINA_W - MARGEM, 54)
    canvas.setFillColor(COR_CINZA)
    canvas.setFont('Corpo', 7.5)
    canvas.drawString(MARGEM, 42,
                      f'SIGerE v{VERSAO} · Sistema Integrado de Gerenciamento Educacional')
    canvas.drawRightString(PAGINA_W - MARGEM, 42, f'Página {canvas.getPageNumber() - 1}')
    canvas.restoreState()


class DocManual(SimpleDocTemplate):
    """Envia os títulos ao sumário; a capa não conta na numeração."""

    def afterFlowable(self, flowable):
        toc = getattr(flowable, '_toc', None)
        if toc:
            nivel, texto = toc
            self.notify('TOCEntry', (nivel, texto, self.page - 1, None))


# ------------------------------------------------------------- blocos → story

def _callout(tipo, texto, s):
    cor_borda, cor_fundo = CALLOUTS[tipo]
    rotulo = {'nota': 'Nota:', 'atencao': 'Atenção:', 'importante': 'Importante:'}[tipo]
    par = Paragraph(f'<font color="#{cor_borda.hexval()[2:]}"><b>{rotulo}</b></font> {texto}',
                    s['callout'])
    t = Table([[par]], colWidths=[LARGURA_UTIL])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), cor_fundo),
        ('LINEBEFORE', (0, 0), (0, -1), 3, cor_borda),
        ('LEFTPADDING', (0, 0), (-1, -1), 12),
        ('RIGHTPADDING', (0, 0), (-1, -1), 12),
        ('TOPPADDING', (0, 0), (-1, -1), 9),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 9),
    ]))
    return [Spacer(1, 4), t, Spacer(1, 10)]


def _tabela(cabecalhos, linhas, larguras, legenda, s):
    dados = [[Paragraph(c, s['cab_tab']) for c in cabecalhos]]
    for i, linha in enumerate(linhas):
        dados.append([Paragraph(c, s['celula_n'] if j == 0 else s['celula'])
                      for j, c in enumerate(linha)])
    t = Table(dados, colWidths=larguras, repeatRows=1)
    estilo = [
        ('BACKGROUND', (0, 0), (-1, 0), COR_H1),
        ('GRID', (0, 0), (-1, -1), 0.7, COR_BORDA_TABELA),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]
    for i in range(1, len(dados)):
        if i % 2 == 0:
            estilo.append(('BACKGROUND', (0, i), (-1, i), COR_ZEBRA))
    t.setStyle(TableStyle(estilo))
    # Sem Spacer antes da tabela: o keepWithNext do título precisa prender
    # diretamente à tabela, senão o título pode ficar órfão no fim da página.
    saida = [t]
    if legenda:
        saida.append(Paragraph(legenda, s['legenda']))
    else:
        saida.append(Spacer(1, 8))
    return saida


def montar_story(blocos, s):
    story = [Spacer(1, 1), PageBreak()]
    toc = TableOfContents()
    toc.levelStyles = [s['toc0'], s['toc1']]
    toc.dotsMinLevel = 1
    story.append(Paragraph('Sumário', s['sum_titulo']))
    story.append(HRFlowable(width='100%', thickness=1.2, color=COR_H1,
                            spaceBefore=2, spaceAfter=14))
    story.append(toc)
    story.append(PageBreak())

    for bloco in blocos:
        tipo = bloco[0]
        if tipo == 'h1':
            h = Paragraph(bloco[1], s['h1'])
            h._toc = (0, bloco[1])
            story.append(h)
            hr = HRFlowable(width='100%', thickness=1.1, color=COR_H1,
                            spaceBefore=1, spaceAfter=12)
            hr.keepWithNext = 1
            story.append(hr)
        elif tipo == 'h2':
            h = Paragraph(bloco[1], s['h2'])
            h._toc = (1, bloco[1])
            story.append(h)
        elif tipo == 'p':
            story.append(Paragraph(bloco[1], s['p']))
        elif tipo == 'ul':
            for item in bloco[1]:
                story.append(Paragraph(item, s['ul'], bulletText='•'))
            story.append(Spacer(1, 5))
        elif tipo == 'ol':
            for i, item in enumerate(bloco[1], 1):
                story.append(Paragraph(item, s['ol'], bulletText=f'{i}.'))
            story.append(Spacer(1, 5))
        elif tipo == 'passo':
            story.append(Paragraph(f'<b>{bloco[1]}</b>', s['passo']))
        elif tipo == 'table':
            story.extend(_tabela(bloco[1], bloco[2], bloco[3], bloco[4], s))
        elif tipo in CALLOUTS:
            story.extend(_callout(tipo, bloco[1], s))
        else:
            raise ValueError(f'bloco desconhecido: {tipo}')
    return story


# ------------------------------------------------------------------ conteúdo

BLOCOS = [
    # ================================================================ 1
    ('h1', '1. Introdução'),
    ('h2', '1.1 Sobre o SIGerE'),
    ('p', 'O SIGerE (Sistema Integrado de Gerenciamento Educacional) é uma plataforma web '
          'para instituições de ensino que precisam gerenciar, de forma integrada, a ocupação '
          'dos espaços físicos e as rotinas administrativas da instituição. O sistema opera com '
          'múltiplas unidades educacionais: salas, reservas, cursos, feriados, usuários e os '
          'módulos de Cozinha e Financeiro são isolados por unidade, e o operador trabalha '
          'sempre sobre a unidade ativa, exibida no topo da tela.'),
    ('p', 'Os módulos do sistema são:'),
    ('ul', [
        '<b>Reservas de salas</b> — agendamento de salas de aula, auditórios, laboratórios, '
        'cozinhas e quadras, com detecção automática de conflitos, séries de repetição e '
        'aprovação administrativa;',
        '<b>Calendário</b> — consulta visual das reservas aprovadas com filtros combinados;',
        '<b>Notificações</b> — avisos no sino do sistema quando uma atividade reservada se '
        'aproxima da data, com destinatários e antecedências definidos por unidade;',
        '<b>Portal público</b> — cronograma do dia e buscas de aula, sala e professor para '
        'alunos e visitantes, sem login;',
        '<b>Totem digital</b> — painel para TVs de corredor mostrando a ocupação das salas em '
        'tempo real;',
        '<b>Financeiro</b> — lançamento de horas extras docentes para pagamento;',
        '<b>RH</b> — Vale-Transporte: pedido público do colaborador, conferência do RH e '
        'planilhas e relatório do período;',
        '<b>Cozinha</b> — fichas técnicas operacionais (.docx), preparações com recálculo de '
        'porções e requisição de compra;',
        '<b>Administração</b> — usuários (com vínculo a uma ou mais unidades), salas, '
        'categorias, cursos, disciplinas, feriados, papéis, notificações, unidades e tokens de '
        'integração (API).',
    ]),
    ('h2', '1.2 Sobre este manual'),
    ('p', 'Este manual orienta o uso operacional do sistema por todos os perfis: professores, '
          'assistentes, gestores, analistas, pessoal do RH e da cozinha e administradores. Ele '
          'descreve cada tela, os campos dos formulários, as ações disponíveis, as regras de '
          'negócio e as mensagens mais comuns. A versão do sistema descrita é a '
          f'<b>{VERSAO}</b>.'),
    ('p', 'Convenções utilizadas:'),
    ('ul', [
        '<b>Negrito</b> indica nomes de botões, campos, menus e telas exatamente como aparecem '
        'no sistema;',
        '<b>Sequências numeradas</b> indicam passos na ordem em que devem ser executados;',
        'Os <b>quadros coloridos</b> destacam dicas (azul), atenção (âmbar) e pontos '
        'importantes (vermelho);',
        'Algumas ações só aparecem para quem possui a permissão correspondente — a seção 3 '
        'explica os papéis e permissões.',
    ]),
    ('h2', '1.3 Requisitos para uso'),
    ('ul', [
        '<b>Navegador atual</b> (Google Chrome, Microsoft Edge ou Safari). No formulário de '
        'Hora Extra, o calendário de seleção de dias funciona melhor nesses navegadores — evite '
        'o Mozilla Firefox;',
        '<b>Login válido</b> criado por um administrador (o sistema não possui autocadastro);',
        '<b>Computador, tablet ou celular</b> — todas as telas se adaptam ao tamanho da tela '
        'do dispositivo.',
    ]),

    # ================================================================ 2
    ('h1', '2. Acesso ao sistema'),
    ('h2', '2.1 Entrar no sistema'),
    ('ol', [
        'Abra o navegador e acesse o endereço do SIGerE fornecido pela instituição. A página '
        'inicial pública apresenta os cartões de acesso; clique em <b>Fazer Login</b>;',
        'Digite o <b>E-mail</b> e a <b>Senha</b> cadastrados. O e-mail é o identificador de '
        'login — não existe nome de usuário;',
        'Clique em <b>Entrar</b>. Em caso de sucesso, o painel inicial é exibido com a mensagem '
        'de boas-vindas.',
    ]),
    ('atencao', 'Por segurança, o login permite no máximo <b>5 tentativas por minuto</b> por '
                'computador. Após esgotar as tentativas, aguarde um momento antes de tentar '
                'novamente.'),
    ('h2', '2.2 Primeiro acesso e troca de senha obrigatória'),
    ('p', 'Contas recém-criadas e senhas redefinidas por um administrador chegam ao usuário em '
          'caráter temporário: o sistema <b>obriga a troca de senha</b> no primeiro login. Até a '
          'troca ser concluída, nenhuma outra tela é liberada.'),
    ('ol', [
        'Após entrar com a senha temporária, a tela de alteração de senha é apresentada;',
        'Informe a <b>Senha Atual</b>, a <b>Nova Senha</b> (mínimo de 8 caracteres) e a '
        '<b>Confirmação da Nova Senha</b>;',
        'Clique em <b>Atualizar Senha</b>. O sistema libera o acesso normal e confirma: “Sua '
        'senha foi atualizada com sucesso!”.',
    ]),
    ('h2', '2.3 Esqueci minha senha'),
    ('p', 'O sistema não envia e-mails de recuperação automática. Solicite ao <b>administrador</b> '
          'um <b>reset de senha</b> (seção 13.2): ele gera uma senha temporária que deve ser '
          'trocada no próximo login, conforme a seção 2.2.'),
    ('h2', '2.4 Meu Perfil'),
    ('p', 'No menu do usuário (canto superior direito, com o seu nome), acesse <b>Meu Perfil</b> '
          'para atualizar seus dados e senha:'),
    ('ul', [
        '<b>Nome Completo</b> e <b>Departamento</b> — editáveis;',
        '<b>E-mail</b> e <b>Papel</b> — somente leitura; o e-mail é o login e apenas um '
        'administrador pode alterá-lo;',
        '<b>Troca de senha</b> — opcional: informe a senha atual e a nova (mínimo de 8 '
        'caracteres, diferente da atual).',
    ]),
    ('p', 'Clique em <b>Salvar Alterações</b> para gravar.'),
    ('h2', '2.5 Sair'),
    ('p', 'No menu do usuário, clique em <b>Sair</b>. A sessão é encerrada e o sistema retorna à '
          'tela de login. Sempre encerre a sessão ao usar um computador compartilhado.'),
    ('h2', '2.6 Conhecendo a tela principal'),
    ('p', 'Após o login, o cabeçalho superior e o menu lateral organizam todo o sistema:'),
    ('ul', [
        '<b>Menu lateral</b> — agrupado em <b>Geral</b> (Painel, Calendário), <b>Salas e '
        'Reservas</b> (Salas; submenu Reservas com Nova Reserva, Minhas Reservas e Todas as '
        'Reservas), <b>Financeiro</b> (Hora Extra), <b>RH</b> (Vale Transporte) e <b>Cozinha</b> '
        '(Ficha Técnica, Preparações, Compras). Os grupos Financeiro, RH e Cozinha só aparecem '
        'para quem tem permissão e quando o módulo está ativado na unidade;',
        '<b>Botão de contrair menu</b> — no topo da barra lateral, alterna entre o modo '
        'expandido e o modo compacto de ícones; a preferência fica salva no navegador;',
        '<b>Unidade ativa</b> — exibida no topo com um ícone de localização. Usuários vinculados '
        'a mais de uma unidade — e administradores — veem o botão <b>Trocar</b> ao lado '
        '(seção 3.3);',
        '<b>Notificações</b> — o sino na barra superior mostra o contador de avisos não lidos e '
        'abre a tela de notificações (seção 7);',
        '<b>Painel Admin</b> — atalho em forma de engrenagem, visível para administradores;',
        '<b>Aparência</b> — um único seletor (ícone de paleta) reúne o tema claro/escuro e a '
        'cor da interface (Azul Senac padrão, Verde, Roxo, Laranja ou Grafite); a escolha fica '
        'salva no navegador;',
        '<b>Novidades</b> — o rodapé exibe a versão do sistema; o link abre o histórico de '
        'novidades de cada versão.',
    ]),
    ('nota', 'Campos com asterisco vermelho (*) são obrigatórios. Ações destrutivas — como '
             'excluir reservas, fichas ou pedidos — sempre pedem confirmação antes de executar. '
             'Mensagens coloridas no topo do conteúdo indicam o resultado: verde (sucesso), '
             'vermelho (erro), amarelo (aviso) e azul (informação).'),

    # ================================================================ 3
    ('h1', '3. Perfis de acesso e permissões'),
    ('h2', '3.1 Papéis do sistema'),
    ('p', 'O acesso às funcionalidades é controlado por <b>papéis (perfis)</b> com permissões '
          'granulares. Ao ser cadastrado, cada usuário recebe um papel principal; a permissão '
          'efetiva define o que aparece no menu e quais ações estão disponíveis. Os papéis '
          'padrão são:'),
    ('table',
     ['Papel', 'O que pode fazer'],
     [
         ['Super Administrador', 'Acesso irrestrito a todas as funcionalidades, incluindo '
          'papéis, unidades, tokens de API e o checklist de configuração inicial. Não pode ser '
          'editado por outros papéis.'],
         ['Administrador', 'Gestão de usuários, unidades, salas, categorias, cursos, '
          'disciplinas, feriados e tokens da API; aprova, edita, cancela e exclui quaisquer '
          'reservas; acesso ao módulo Cozinha; configura as notificações da unidade.'],
         ['Gestor', 'Operação completa de reservas (ver todas, criar, editar, aprovar, cancelar '
          'e excluir), gestão de salas e cursos, horas extras completas e exportações.'],
         ['Analista', 'Cria e edita as próprias reservas, aprova reservas pendentes, lança e '
          'edita horas extras e exporta relatórios.'],
         ['Professor', 'Cria, visualiza, edita e cancela as próprias reservas; consulta salas e '
          'cursos; exportações básicas.'],
         ['Assistente/Logística', 'Mesmas permissões do Professor: cria, visualiza, edita e '
          'cancela as próprias reservas e consulta salas e cursos.'],
     ],
     [105, 378],
     'Tabela 1 — Papéis padrão do sistema e alcance de cada um.'),
    ('h2', '3.2 Módulos adicionais (papéis extra)'),
    ('p', 'Além do papel principal, o usuário pode receber módulos adicionais no cadastro — a '
          'permissão efetiva é a soma dos dois. O adicional padrão é o <b>Módulo Cozinha</b>, '
          'que libera Ficha Técnica, Preparações e Compras para quem mantém o papel original '
          '(por exemplo, um professor de gastronomia). A atribuição é feita pelo administrador '
          'na tela de usuários (seção 13.2).'),
    ('h2', '3.3 Multi-unidade: alternar a unidade ativa'),
    ('p', 'Todo usuário está vinculado a uma ou mais unidades, definidas pelo administrador no '
          'cadastro (seção 13.2). Quem tem um único vínculo fica fixado nele; quem tem vários '
          'vínculos — ou é super administrador — alterna a unidade ativa pelo botão '
          '<b>Trocar</b>, ao lado do nome da unidade no topo da tela:'),
    ('ol', [
        'Clique em <b>Trocar</b>, ao lado do nome da unidade ativa;',
        'Selecione a unidade desejada na lista — a unidade atual aparece marcada com um ✓ e '
        'não é clicável; super administradores veem todas as unidades ativas, os demais usuários '
        'veem apenas as próprias;',
        'O sistema confirma a mudança e todas as telas passam a exibir os dados da nova unidade.',
    ]),
    ('atencao', 'Ao alternar de unidade, tudo muda junto: salas, reservas, cursos, feriados, '
                'usuários e os dados de Cozinha e Financeiro. Confira a unidade ativa antes de '
                'lançar ou cadastrar qualquer informação.'),

    # ================================================================ 4
    ('h1', '4. Painel (tela inicial)'),
    ('p', 'O Painel é a primeira tela após o login. Ele mostra o resumo das reservas aprovadas '
          'de hoje na unidade ativa, organizado em uma seção para cada categoria de sala '
          'cadastrada (Sala de Aula, Auditório, Laboratório etc.), com a cor e o ícone da '
          'categoria.'),
    ('ul', [
        'O período atual (Manhã, Tarde ou Noite) fica em destaque, com as reservas em '
        'andamento;',
        'Cada linha traz <b>Horário</b>, <b>Espaço</b> (código e nome da sala), <b>Curso</b> e '
        '<b>Professor</b>;',
        'As salas aparecem em ordem crescente de numeração do código (LI104 antes de LI205; '
        'LI9 antes de LI10), usando o horário apenas como desempate;',
        'O seletor <b>Visão em Lista / Visão em Cartões</b> alterna o formato de exibição (a '
        'preferência fica salva);',
        'O botão <b>Novidades</b>, com o número da versão, abre o histórico de novidades;',
        'O botão <b>Nova Reserva</b> aparece para quem tem permissão de criar reservas '
        '(seção 6.1).',
    ]),
    ('p', 'Se não houver reservas aprovadas para o período, o painel exibe a mensagem '
          '“Nenhum espaço agendado”.'),

    # ================================================================ 5
    ('h1', '5. Salas e espaços'),
    ('h2', '5.1 Consultar salas e disponibilidade'),
    ('p', 'O menu <b>Salas</b> lista todas as salas ativas da unidade, agrupadas por andar. Cada '
          'cartão mostra nome, código, prédio, capacidade, categoria e o número de computadores '
          '(quando aplicável).'),
    ('p', 'Use os filtros do painel superior para encontrar a sala ideal:'),
    ('ul', [
        '<b>Data Disponível + Período</b> (Manhã/Tarde/Noite) — mostra apenas as salas livres na '
        'data e período escolhidos;',
        '<b>Tipo de Sala</b> — restringe a uma categoria;',
        '<b>Mostrar apenas salas disponíveis AGORA</b> — filtra pelas salas livres no horário '
        'corrente; o filtro é aplicado na hora em que é marcado ou desmarcado, sem depender do '
        'botão Filtrar;',
        'Clique em <b>Filtrar</b> para aplicar ou use a borracha para limpar os critérios.',
    ]),
    ('p', 'Ações do topo da tela:'),
    ('ul', [
        '<b>Exportar PDF</b> — baixa o relatório de salas com os filtros aplicados, no padrão '
        'visual do SIGerE, com indicadores (salas listadas, capacidade total, salas com '
        'computadores e prédios) e a tabela completa;',
        '<b>Adicionar Sala</b> — abertura do cadastro de sala (somente com permissão; '
        'seção 13.3).',
    ]),
    ('h2', '5.2 Detalhes da sala'),
    ('p', 'Clique em <b>Detalhes</b> no cartão da sala para ver o tipo, a descrição e a tabela '
          'de <b>Próximas Reservas</b> (aprovadas e pendentes, de hoje em diante), em que cada '
          'linha tem o botão de detalhes (olho) que abre a reserva completa — para quem tem '
          'acesso a ela. Botões disponíveis:'),
    ('ul', [
        '<b>Disponibilidade</b> — abre o calendário da sala;',
        '<b>Reservar</b> — abre a tela de nova reserva com esta sala já selecionada (requer '
        'permissão de criar reservas);',
        '<b>Editar</b> — cadastro da sala (somente com permissão de administração).',
    ]),
    ('h2', '5.3 Disponibilidade e exportação'),
    ('p', 'A tela <b>Disponibilidade</b> exibe apenas reservas aprovadas, em três visualizações '
          'alternáveis pelos botões <b>Dia</b>, <b>Semana</b> e <b>Mês</b>. Use <b>Anterior</b> '
          'e <b>Próximo</b> para navegar no calendário.'),
    ('p', 'Ao clicar em uma reserva — nas pílulas das visões de semana e mês, ou no botão '
          '<b>Detalhes</b> da visão de dia — um banner é exibido com o bloco de data (dia, ano e '
          'horário) ao lado do título, da situação, do curso, da disciplina, do professor, de '
          'quem reservou e da descrição. O botão <b>Ver detalhes completos</b> aparece para quem '
          'tem acesso à reserva; os demais consultam o banner e fecham.'),
    ('p', 'O botão <b>Exportar Reservas do Dia/Semana/Mês (PDF)</b> gera o relatório do período '
          'exibido no padrão visual do SIGerE: cabeçalho com a unidade e a data de emissão, '
          'cartões de indicadores (reservas, horas reservadas, dias com atividade e quantas '
          'ainda vão ocorrer) e a tabela agrupada dia a dia, com faixas de data; reservas já '
          'ocorridas aparecem em cinza riscado.'),

    # ================================================================ 6
    ('h1', '6. Reservas'),
    ('h2', '6.1 Criar uma reserva'),
    ('p', 'Acesse <b>Reservas &gt; Nova Reserva</b> (ou o botão <b>Reservar</b> em uma sala / '
          '<b>Nova Reserva</b> no painel). Preencha o formulário:'),
    ('table',
     ['Campo', 'Obrigatório', 'Preenchimento'],
     [
         ['Sala', 'Sim', 'Selecione a sala desejada (apenas salas ativas da unidade).'],
         ['Curso', 'Não', 'Curso vinculado à reserva; “-- Nenhum --” se não se aplicar.'],
         ['Disciplina', 'Não', 'Ao escolher um curso, a lista mostra apenas as disciplinas dele.'],
         ['Professor', 'Não', 'Docente responsável pela atividade.'],
         ['Título / Assunto', 'Sim', 'Nome da atividade (até 200 caracteres; letras, números e '
          'pontuação comum).'],
         ['Descrição / Finalidade', 'Não', 'Detalhes livres sobre a reserva.'],
         ['Data', 'Sim', 'Data da reserva (datas passadas são recusadas).'],
         ['Horário de Início', 'Sim', 'Hora de início (no mesmo dia, não pode já ter passado).'],
         ['Horário de Término', 'Sim', 'Deve ser posterior ao horário de início.'],
     ],
     [108, 68, 307],
     'Tabela 2 — Campos do formulário de reserva.'),
    ('ol', [
        'Escolha a sala, o curso, a disciplina e o professor;',
        'Informe título, descrição, data e horários. Ainda antes de salvar, o formulário avisa '
        'se a data é feriado, domingo ou um sábado fora do horário permitido;',
        'Clique em <b>Cadastrar Reserva</b>.',
    ]),
    ('p', 'O resultado depende das regras da seção 6.2: sem conflitos, a reserva nasce '
          '<b>Aprovada</b>; se o professor escolhido já estiver alocado em outra sala no mesmo '
          'horário, a reserva nasce <b>Pendente</b> e o sistema explica o motivo; se a sala já '
          'estiver ocupada, o agendamento é bloqueado.'),
    ('h2', '6.2 Regras de agendamento'),
    ('table',
     ['Regra', 'Efeito'],
     [
         ['Domingos', 'Reservas bloqueadas em qualquer horário.'],
         ['Feriados', 'Reservas bloqueadas nos feriados cadastrados da unidade (seção 13.6).'],
         ['Sábados', 'Permitidos apenas pela manhã e tarde: início e término até as 18h00.'],
         ['Datas passadas', 'Não é possível reservar no passado; no dia corrente, o horário de '
          'início não pode já ter passado.'],
         ['Sala ocupada', 'Sobreposição com reserva aprovada bloqueia a criação (o fim de uma '
          'reserva pode coincidir com o início de outra).'],
         ['Professor ocupado', 'Se o professor já está em outra reserva (aprovada ou pendente) '
          'no mesmo horário, a reserva é criada como Pendente para avaliação do administrador.'],
         ['Reservas passadas', 'Viram registro histórico somente leitura: não podem ser '
          'editadas, canceladas nem excluídas.'],
     ],
     [95, 388],
     'Tabela 3 — Regras aplicadas na criação, edição e aprovação de reservas.'),
    ('h2', '6.3 Situações da reserva'),
    ('table',
     ['Situação', 'Significado'],
     [
         ['Aprovada', 'Confirmada e ocupando a sala. Reservas sem conflitos são aprovadas '
          'automaticamente.'],
         ['Pendente', 'Aguardando análise do administrador (normalmente por conflito de '
          'professor). Não aparece no totem, no portal nem no calendário público.'],
         ['Cancelada', 'Desativada por decisão do usuário ou do administrador; permanece no '
          'histórico.'],
     ],
     [80, 403],
     'Tabela 4 — Situações possíveis de uma reserva.'),
    ('h2', '6.4 Minhas Reservas'),
    ('p', 'Em <b>Reservas &gt; Minhas Reservas</b> ficam as reservas criadas por você, com abas '
          '<b>Todas</b>, <b>Aprovadas</b>, <b>Pendentes</b> e <b>Canceladas</b> (25 registros '
          'por página). A listagem é dividida em <b>Reservas Atuais e Futuras</b> e <b>Reservas '
          'Passadas</b> (exibidas em cinza, como histórico). Cada linha mostra data, horário, '
          'sala, título, professor, situação e o botão de detalhes.'),
    ('h2', '6.5 Todas as Reservas'),
    ('p', 'Quem tem permissão global de leitura acessa <b>Reservas &gt; Todas as Reservas</b>, '
          'com as abas <b>Atuais e Futuras</b> e <b>Passadas</b> (esta última somente leitura). '
          'Filtros combináveis:'),
    ('ul', [
        '<b>Data Inicial</b> e <b>Data Final</b>;',
        '<b>Período</b> (Manhã/Tarde/Noite) e <b>Status</b> (Aprovada/Pendente/Cancelada);',
        '<b>Sala</b>, <b>Professor</b>, <b>Curso</b> e <b>Disciplina</b>;',
        '<b>Ordenar por</b> — data (mais próxima ou mais distante), sala ou professor.',
    ]),
    ('p', 'Clique em <b>Aplicar Filtros</b> para consultar e <b>Limpar</b> para recomeçar. Além '
          'de visualizar, esta tela permite editar reservas diretamente (ícone de lápis), '
          'respeitando as permissões.'),
    ('h2', '6.6 Detalhes e ações sobre a reserva'),
    ('p', 'A tela de detalhes mostra situação, sala, curso, disciplina, professor, data e '
          'horário, quem reservou, quem aprovou e a data de registro. Os botões variam conforme '
          'a permissão e a situação:'),
    ('ul', [
        '<b>Editar</b> — abre o mesmo formulário da criação, pré-preenchido. Ao salvar, as '
        'regras são revalidadas; se passar a existir conflito de professor, a reserva volta a '
        'Pendente;',
        '<b>Aprovar Reserva</b> — analisa uma reserva pendente (permissão de aprovação). O '
        'sistema revalida a sala na aprovação: se outro pedido já ocupou o horário, a aprovação '
        'é recusada e a reserva permanece pendente;',
        '<b>Cancelar Reserva</b> — libera a sala mantendo o registro no histórico (após '
        'confirmação);',
        '<b>Excluir</b> — apaga permanentemente a reserva (permissão de exclusão global, após '
        'confirmação);',
        '<b>Repetir</b> — cria uma série de reservas a partir desta (seção 6.7);',
        '<b>Gerenciar Série (N)</b> — aparece quando a reserva pertence a uma série (seção 6.8);',
        '<b>Compartilhar</b> — envia os dados da reserva por e-mail ou WhatsApp (seção 6.9);',
        '<b>Ativar notificações</b> — liga os avisos no sino para esta reserva (seção 7.2): o '
        'botão passa a exibir <b>Notificações ativadas</b> e um novo clique desliga. Aparece '
        'para o dono da reserva (ou quem tem permissão de editar qualquer reserva) apenas em '
        'reservas aprovadas e futuras.',
    ]),
    ('importante', 'Reservas passadas não exibem nenhum botão de alteração — nem para '
                   'administradores. Elas servem apenas como registro histórico.'),
    ('h2', '6.7 Repetir uma reserva (séries de aulas)'),
    ('p', 'Para criar a mesma atividade em várias datas (por exemplo, uma aula semanal), abra a '
          'reserva aprovada e futura e clique em <b>Repetir</b>.'),
    ('passo', 'Passo 1 — Definir o intervalo'),
    ('ul', [
        'A <b>Data Inicial</b> é fixada no dia seguinte ao da reserva original;',
        'Escolha a <b>Data Final</b> (o intervalo total é limitado a <b>180 dias</b>);',
        'Marque <b>Apenas {dia da semana}</b> para repetir somente no mesmo dia da semana do '
        'evento original;',
        'Marque <b>Pular Finais de Semana</b> para descartar sábados e domingos;',
        'Clique em <b>Verificar Dias</b>.',
    ]),
    ('passo', 'Passo 2 — Conferir dia a dia e agendar'),
    ('p', 'O sistema lista um cartão para cada data do intervalo, classificado como '
          '<b>Disponível</b> ou <b>Indisponível</b> com o motivo (sala ocupada, professor '
          'ocupado, domingo, feriado ou sábado fora do horário). Então:'),
    ('ul', [
        '<b>Agendar</b> — cria a reserva daquele dia individualmente;',
        '<b>Agendar Todos</b> — cria de uma vez todas as datas disponíveis;',
        '<b>Resetar</b> — volta ao passo 1 para escolher outro intervalo.',
    ]),
    ('p', 'Todas as reservas criadas ficam vinculadas na mesma série e podem ser gerenciadas em '
          'lote.'),
    ('h2', '6.8 Gerenciar uma série'),
    ('p', 'No detalhe de qualquer reserva da série (ou na tela de repetição), clique em '
          '<b>Gerenciar Série (N)</b>. A tela lista as <b>Próximas</b> reservas da série, com '
          'caixa de seleção por linha e o atalho <b>Selecionar todas</b>.'),
    ('ul', [
        '<b>Editar em lote</b> — informe novo <b>Início</b>, <b>Término</b>, <b>Sala</b> e/ou '
        '<b>Título</b> (deixe em branco o que não deve mudar) e clique em <b>Aplicar</b>. '
        'Reservas com conflito de sala ficam de fora e são informadas na mensagem de resultado;',
        '<b>Cancelar selecionadas</b> — cancela em lote, liberando as datas;',
        '<b>Excluir permanentemente</b> — apaga em lote (permissão global de exclusão, após '
        'confirmação);',
        'A tabela <b>Passadas / Canceladas</b> registra o histórico da série.',
    ]),
    ('h2', '6.9 Compartilhar uma reserva'),
    ('p', 'No detalhe de reservas aprovadas ou pendentes (não passadas nem canceladas), o botão '
          '<b>Compartilhar</b> abre uma mensagem já pronta com sala, curso, disciplina, '
          'professor, data e horário por extenso e a finalidade. Duas abas estão disponíveis:'),
    ('ul', [
        '<b>E-mail</b> — informe o destinatário (opcional) e clique em <b>Abrir no programa de '
        'e-mail</b>; o aplicativo de e-mail do próprio computador abre com a mensagem pronta;',
        '<b>WhatsApp</b> — informe o número com DDD (opcional; o código do país 55 é adicionado '
        'automaticamente) e clique em <b>Abrir no WhatsApp</b>.',
    ]),
    ('p', 'Em ambas as abas a mensagem pode ser editada antes do envio e há o botão <b>Copiar</b> '
          'para levar o texto a qualquer outro aplicativo. Nenhum envio é feito pelo servidor — '
          'quem envia é o próprio usuário.'),

    # ================================================================ 7 (novo)
    ('h1', '7. Notificações'),
    ('p', 'O sistema avisa no próprio sino — sem e-mail — quando uma atividade reservada se '
          'aproxima da data. Este capítulo descreve o lado de quem recebe os avisos; a '
          'configuração por unidade (destinatários, antecedências e grupos) está na '
          'seção 13.10.'),
    ('h2', '7.1 O sino e a tela de notificações'),
    ('p', 'O sino na barra superior exibe um contador vermelho com as notificações não lidas, '
          'atualizado automaticamente a cada minuto. Ao clicar nele, abre-se a tela '
          '<b>Notificações</b>, com os avisos mais recentes primeiro (50 por página):'),
    ('ul', [
        'Cada aviso traz o título — <b>Hoje:</b>, <b>Amanhã:</b> ou <b>Em N dias:</b> seguidos '
        'do assunto da reserva —, a sala, a data e o horário da atividade e a data em que foi '
        'criado;',
        'Ao clicar no aviso, o criador da reserva vai ao detalhe dela; os demais destinatários '
        'vão ao calendário, já posicionado no dia da atividade;',
        '<b>Lida</b> — marca aquele aviso como lido;',
        '<b>Marcar todas como lidas</b> — marca todos os avisos da página de uma vez;',
        '<b>Limpar lidas</b> — remove permanentemente todos os avisos já lidos, após '
        'confirmação (a ação não pode ser desfeita).',
    ]),
    ('nota', 'Avisos já lidos continuam na lista até serem removidos com <b>Limpar lidas</b> — '
             'marcar como lida não apaga nada.'),
    ('h2', '7.2 Ativar os avisos de uma reserva'),
    ('p', 'Os avisos de atividade próxima são <b>opt-in por reserva</b>: nascem desativados e '
          'ninguém é notificado até que alguém os ative. No detalhe de uma reserva aprovada e '
          'futura, o dono (ou quem tem permissão de editar qualquer reserva) clica em '
          '<b>Ativar notificações</b>; o botão passa a exibir <b>Notificações ativadas</b> e um '
          'novo clique desliga os avisos.'),
    ('p', 'Ativada a reserva, o aviso chega ao sino nos marcos definidos pela unidade (ex.: '
          '7 dias antes, 1 dia antes e no próprio dia) para os destinatários configurados: '
          'professor designado, criador da reserva, aprovadores da unidade e grupos de '
          'notificação (seção 13.10).'),
    ('importante', 'Desativar as notificações de uma reserva não apaga os avisos já criados no '
                   'sino — apenas interrompe os próximos.'),

    # ================================================================ 8
    ('h1', '8. Calendário de reservas'),
    ('p', 'O <b>Calendário</b> (menu Geral) exibe as reservas aprovadas da unidade em cartões '
          'agrupados por data e por andar. Ao abrir, ele carrega automaticamente as reservas de '
          'hoje no período atual.'),
    ('p', 'Filtros combináveis no painel <b>Filtros de Reserva</b>:'),
    ('ul', [
        '<b>Data Inicial</b> e <b>Data Final</b> — intervalo de datas;',
        '<b>Período</b> — Todos, Manhã, Tarde ou Noite;',
        '<b>Sala</b>, <b>Professor</b>, <b>Curso</b> e <b>Disciplina</b> — restringem o '
        'resultado;',
        '<b>Aplicar Filtros</b> executa a consulta; <b>Limpar</b> remove os critérios.',
    ]),
    ('p', 'Cada cartão mostra código da sala, horário, título, curso e professor, com a cor da '
          'categoria da sala; ao clicar, o detalhe da reserva é aberto.'),

    # ================================================================ 9
    ('h1', '9. Portal público e totem digital'),
    ('p', 'As páginas desta seção não exigem login e servem a alunos, visitantes e TVs de '
          'corredor. Quando a instituição tem mais de uma unidade ativa, as páginas públicas '
          'exibem um seletor de unidade (também aceito na própria URL, pelo parâmetro '
          '<b>?unity=</b>). A unidade escolhida — pela lista ou pela detecção de unidade '
          'próxima — fica memorizada na sessão do visitante: navegar entre as páginas pelo menu '
          'não reseta a seleção.'),
    ('h2', '9.1 Página inicial pública'),
    ('p', 'A home pública apresenta três atalhos: <b>Buscar Minha Aula</b>, <b>Cronograma de '
          'Aulas</b> e <b>Entrar</b> (login). Quem já está logado é levado direto ao painel.'),
    ('h2', '9.2 Cronograma do dia'),
    ('p', 'A página <b>Cronograma</b> lista as aulas aprovadas da data escolhida em três '
          'colunas: <b>Manhã</b>, <b>Tarde</b> e <b>Noite</b> (a aula entra no período em que '
          'começa). Cada item mostra horário, código da sala, título, curso, disciplina e '
          'professor. No dia de hoje, o cartão do período em curso fica em destaque, com o selo '
          '<b>Agora</b>; nos demais dias, nenhum período é destacado. No campo de data, o rótulo '
          'indica “Hoje” ou o nome do dia da semana selecionado.'),
    ('p', 'No celular, uma barra fixa de atalhos <b>Manhã / Tarde / Noite</b> — com a contagem '
          'de aulas de cada período — fica presa abaixo do topo enquanto a página rola, levando '
          'direto ao período desejado.'),
    ('h2', '9.3 Buscar minha aula'),
    ('p', 'Em <b>Buscar Minha Aula</b>, o aluno informa o que procura (título da aula, curso, '
          'disciplina, professor ou código da sala) e a data. O resultado lista as aulas '
          'aprovadas correspondentes ao dia informado, com os mesmos dados do cronograma.'),
    ('h2', '9.4 Buscar salas e professores'),
    ('p', 'A busca geral (<b>Buscar Salas e Professores</b>) tem dois modos:'),
    ('ul', [
        '<b>Sala</b> — pesquisa por nome ou código; o resultado traz nome, código, prédio, '
        'andar e capacidade;',
        '<b>Professor</b> — pesquisa por nome; o resultado traz nome, departamento e matrícula.',
    ]),
    ('h2', '9.5 Totem digital (TV de corredor)'),
    ('p', 'O <b>Totem</b> é um painel de ocupação de salas para TVs, acessível pelo endereço do '
          'totem de cada unidade (formato <b>/totem/?unity=ID</b>). Não há interação: a tela se '
          'atualiza sozinha a cada 5 minutos.'),
    ('ul', [
        '<b>Cabeçalho</b> — data completa, relógio, nome da unidade e clima em tempo real da '
        'cidade da unidade;',
        '<b>Blocos por categoria</b> — a tela se monta a partir das categorias de sala '
        'cadastradas, usando a cor e o ícone de cada uma. Categorias sem atividade no recorte '
        'não aparecem;',
        '<b>Janela de exibição</b> — cada categoria define seu recorte: <b>Período atual</b> '
        '(manhã, tarde ou noite; o andar aparece no cartão de cada reserva) ou <b>Próximos '
        '7 dias</b> (configurado no cadastro da categoria, seção 13.4);',
        '<b>Cartões de reserva</b> — código da sala em destaque, horário, professor, curso, '
        'disciplina e assunto;',
        '<b>Tema automático</b> — claro entre 6h e 18h e escuro no restante do dia;',
        '<b>Tudo em uma única página</b> — todas as categorias ficam empilhadas na mesma '
        'tela; se o conteúdo não couber na altura, o totem reduz a escala até tudo aparecer '
        'de uma vez, sem rolagem automática e sem animação (leve o suficiente para rodar em '
        'Raspberry Pi). Em celulares a página rola normalmente.',
    ]),
    ('p', 'Sem atividade em andamento, o totem exibe “Nenhuma atividade em andamento no '
          'momento”.'),

    # ================================================================ 10
    ('h1', '10. Financeiro — Hora Extra'),
    ('p', 'O módulo <b>Hora Extra</b> (menu Financeiro) registra as horas extras docentes para '
          'pagamento. A listagem traz <b>Professor</b>, <b>Mês Base</b>, <b>Nível</b>, '
          '<b>Dias Selecionados</b>, <b>Turno</b>, <b>Código Orçamentário</b>, <b>Horas</b> e '
          '<b>Valor hora/aula</b>, com 25 registros por página. O ícone de olho abre o resumo '
          'completo do lançamento.'),
    ('h2', '10.1 Consultar lançamentos'),
    ('ul', [
        '<b>Mês Base</b> — a consulta abre no mês atual; a lista também oferece “Todos os '
        'meses” e os meses já lançados;',
        '<b>Professor</b> — filtra por docente;',
        '<b>Filtrar</b> aplica a combinação; <b>Limpar</b> volta ao mês atual;',
        'Lançamentos trancados (fora do prazo de edição) exibem um cadeado com o aviso '
        'correspondente.',
    ]),
    ('h2', '10.2 Lançar uma hora extra'),
    ('p', 'Clique em <b>Nova Hora Extra</b> e preencha:'),
    ('table',
     ['Campo', 'Obrigatório', 'Preenchimento'],
     [
         ['Professor', 'Sim', 'Docente da unidade ativa.'],
         ['Nível de Ensino', 'Sim', 'Técnico, Superior, FIC, FIC I, FIC II ou FIC III.'],
         ['Carga Horária Semanal', 'Sim', 'Informada em horas e minutos (ex.: 4h30); exibida '
          'também em hora decimal (4,5).'],
         ['Valor H/a', 'Sim', 'Valor da hora/aula em reais, aceitando vírgula ou ponto decimal '
          '(ex.: 15,50).'],
         ['Código Orçamentário', 'Sim', '9 ou 14 dígitos; a máscara com pontos '
          '(xx.xx.xxxx.x) é aplicada automaticamente ao digitar.'],
         ['Turno', 'Sim', 'Matutino, Vespertino ou Noturno.'],
         ['Mês Base', 'Sim', 'Mês e ano de referência do pagamento.'],
         ['Múltiplas Datas', 'Não', 'Calendário de seleção múltipla limitado ao Mês Base; '
          'apenas os dias são gravados (ex.: 10, 17, 25).'],
         ['Justificativa', 'Não', 'Texto curto (até 100 caracteres).'],
     ],
     [118, 68, 297],
     'Tabela 5 — Campos do lançamento de Hora Extra.'),
    ('p', 'Clique em <b>Lançar Hora Extra</b> para gravar. Regras de prazo:'),
    ('ul', [
        'Não é possível lançar para meses anteriores ao atual;',
        'Lançamentos do mês corrente só podem ser feitos até o dia 25; do dia 26 em diante, '
        'apenas para o mês seguinte;',
        'Edição e exclusão são permitidas somente para lançamentos criados no mês corrente e '
        'com até 30 dias; registros mais antigos ficam trancados.',
    ]),
    ('h2', '10.3 Exportar a planilha'),
    ('p', 'Com pelo menos o <b>Mês Base</b> ou o <b>Professor</b> selecionado, clique em '
          '<b>Exportar</b>. O arquivo Excel gerado (<b>overtime_export.xlsx</b>) preenche o '
          'modelo institucional da folha de pagamento de hora extra com os lançamentos '
          'filtrados: professor, nível, horas, valor, datas, turno, código orçamentário e '
          'justificativa.'),

    # ================================================================ 11
    ('h1', '11. RH — Vale-Transporte'),
    ('p', 'O módulo <b>Vale-Transporte</b> (menu RH) coleta, a cada mês, a intenção de uso do VT '
          'de cada colaborador e gera as planilhas de pagamento. O fluxo tem duas pontas:'),
    ('ul', [
        '<b>Colaborador</b> (sem login) responde o formulário público do pedido de VT da sua '
        'unidade;',
        '<b>RH</b> acompanha as respostas em <b>Pedidos VT</b>, corrige o que for necessário, '
        'exporta as planilhas por grupo e acompanha o <b>Relatório</b>.',
    ]),
    ('atencao', 'Antes de divulgar o formulário, o administrador precisa cadastrar as '
                '<b>Empresas de Ônibus</b> com as tarifas vigentes e definir as '
                '<b>Configurações do Pedido</b> (seção 11.6).'),
    ('h2', '11.1 Colaborador: preencher o pedido de VT'),
    ('p', 'O RH divulga o link do formulário público da unidade (o botão <b>Copiar link do '
          'formulário</b> em Pedidos VT gera o link pronto). A página indica a unidade e, quando '
          'configurada, a data limite — após o prazo, o formulário aparece encerrado.'),
    ('ol', [
        '<b>Identificação</b> — informe <b>E-mail</b>, <b>Nome</b> e <b>Matrícula</b>. Se o '
        'e-mail corresponder a uma conta ativa do sistema, nome, matrícula e vínculo são '
        'preenchidos automaticamente e ficam travados;',
        '<b>Deseja Vale-Transporte para o mês?</b> — responda <b>Sim</b> ou <b>Não</b>. '
        'Respondendo “Não”, basta clicar em <b>Enviar pedido</b>;',
        'Respondendo “Sim”, selecione o <b>Vínculo</b> (Técnico-Administrativo ou Professor) e '
        'a quantidade de empresas de ônibus usadas no deslocamento (1 ou 2);',
        'Para cada empresa, informe: a empresa de ônibus, o valor do vale (tarifa) vigente, o '
        'trajeto (<b>Somente Volta</b> ou <b>Ida e Volta</b>) e o número de vales necessários '
        '(de 1 a 49). Técnicos-administrativos podem usar o botão <b>Usar valor base</b> quando '
        'o RH configurou os números padrão;',
        'Clique em <b>Enviar pedido</b>. A confirmação é exibida na tela.',
    ]),
    ('h2', '11.2 RH: acompanhar os pedidos'),
    ('p', 'A tela <b>Pedidos VT</b> lista as respostas recebidas pela unidade, com data, '
          'colaborador (nome e matrícula), e-mail, se é optante, vínculo, empresas selecionadas '
          '(com tarifa e trajeto ao passar o mouse), total de passes e valor total.'),
    ('p', 'Recursos disponíveis:'),
    ('ul', [
        '<b>Copiar link do formulário</b> — copia o endereço público da unidade para '
        'divulgação;',
        '<b>Filtros</b> — busca por nome/e-mail/matrícula, vínculo, “Deseja VT” (Sim/Não), '
        'ordenação (mais recentes, nome, matrícula, valor total) e a opção de esconder não '
        'optantes com valor zero;',
        '<b>Editar</b> (lápis) — corrige qualquer campo do pedido (seção 11.3);',
        '<b>Excluir</b> (lixeira) — remove um pedido inválido, após confirmação.',
    ]),
    ('h2', '11.3 RH: corrigir um pedido'),
    ('p', 'Em <b>Editar pedido</b>, o RH ajusta a identificação (e-mail, nome, matrícula, deseja '
          'VT), o vínculo e os dados de cada empresa (empresa, tarifa, trajeto e número de '
          'vales). Os totais de passes e de reais são recalculados automaticamente. Clique em '
          '<b>Salvar alterações</b> para gravar.'),
    ('h2', '11.4 RH: exportar a planilha de pagamento'),
    ('p', 'O cartão <b>Exportar planilha de pagamento</b> gera o arquivo Excel do mês, '
          'preenchendo o modelo institucional com <b>Matrícula</b>, <b>Nome</b> e <b>Valor '
          'Total</b> de cada colaborador:'),
    ('ol', [
        'Selecione o <b>Grupo</b> de colaboradores: Todos os grupos, Técnico-Administrativo ou '
        'Professores;',
        'Clique em <b>Exportar</b>;',
        'O arquivo é gerado em ordem alfabética. São incluídos apenas os pedidos optantes por '
        'VT com total de passes maior que zero, dentro do grupo escolhido.',
    ]),
    ('atencao', 'O modelo institucional suporta até 72 linhas por arquivo. Acima disso, apenas '
                'as 72 primeiras em ordem alfabética são exportadas e o sistema alerta.'),
    ('h2', '11.5 RH: relatório do período'),
    ('p', 'A tela <b>Relatório</b> consolida o ciclo do VT da unidade, com botão '
          '<b>Imprimir / PDF</b>:'),
    ('ul', [
        '<b>Indicadores</b> — pedidos recebidos, optantes com percentual de adesão, vales '
        'necessários e investimento estimado (com média por optante);',
        '<b>Gráficos</b> — distribuição de “Deseja VT no mês”, optantes por vínculo, trajetos '
        '(Somente Volta × Ida e Volta), investimento por empresa e empresas por pedido;',
        '<b>Resumos</b> — tabela por empresa de ônibus (colaboradores, vales, investimento e '
        'participação) e planilha de pagamento por grupo;',
        '<b>Conferência do RH</b> — total de colaboradores identificados, maior pedido '
        'individual e alertas de e-mails ou matrículas repetidas.',
    ]),
    ('h2', '11.6 Administração: empresas, tarifas e configurações'),
    ('p', 'Dois cadastros no Painel Admin sustentam o formulário público:'),
    ('ul', [
        '<b>Empresas de Ônibus</b> — cadastre o nome da empresa e se ela aparece no formulário '
        'público; dentro de cada empresa, registre as tarifas como pares identificação + valor '
        '(ex.: “Patamar 3” + 7,24, com vírgula decimal). A exclusão de uma empresa não afeta '
        'pedidos antigos;',
        '<b>Configurações do Pedido VT</b> — defina o número base de vales para Somente Volta e '
        'para Ida e Volta (usados pelo botão “Usar valor base” do formulário) e a data de '
        'fechamento, que encerra automaticamente o preenchimento na data limite.',
    ]),

    # ================================================================ 12
    ('h1', '12. Cozinha'),
    ('p', 'O módulo <b>Cozinha</b> digitaliza as fichas técnicas operacionais e automatiza a '
          'requisição de compra. O caminho típico é: enviar a ficha (.docx), salvar como '
          'preparação, ajustar porções e ingredientes e, antes da aula, gerar a requisição de '
          'compra.'),
    ('h2', '12.1 Enviar fichas técnicas (.docx)'),
    ('ol', [
        'Acesse <b>Cozinha &gt; Ficha Técnica</b>;',
        'Selecione um ou vários arquivos .docx no campo de envio e clique em <b>Ler arquivos</b>;',
        'Cada ficha lida fica na área “Aguardando salvamento”, com nome da preparação, '
        'equipamentos, utensílios, tempo, rendimento e ingredientes extraídos. Use '
        '<b>Ver prévia</b> para conferir;',
        'Clique em <b>Salvar Ficha Técnica</b> (ou <b>Salvar todas</b>) para gerar as '
        'preparações — elas passam a aparecer no menu <b>Preparações</b>;',
        'Fichas com problemas de leitura aparecem em “Falha na leitura” com o motivo (ex.: '
        'arquivo fora do modelo). Envie novamente o arquivo corrigido.',
    ]),
    ('p', 'As fichas salvas ficam listadas com a data, o autor e o botão <b>Baixar .docx</b>; a '
          'exclusão de uma ficha remove também a preparação gerada por ela (com confirmação).'),
    ('h2', '12.2 Criar a ficha manualmente'),
    ('p', 'O botão <b>Criar Ficha Técnica</b> abre o mesmo modelo para preenchimento manual: '
          'identificação (nome da preparação, equipamentos, utensílios, tempo de preparo e '
          'rendimento), ingredientes em linhas dinâmicas (ingrediente, especificações, '
          'quantidade e unidade) e modo de preparo com notas técnicas (observações, alergênicos '
          'e referências). Clique em <b>Salvar Ficha Técnica</b> para gerar a preparação.'),
    ('h2', '12.3 Consultar preparações'),
    ('p', 'Em <b>Preparações</b>, as receitas salvas aparecem em <b>Cards</b> ou em <b>Lista</b> '
          '(a preferência fica salva no navegador), com busca por nome. A visualização completa '
          'traz equipamentos, utensílios, tempo, rendimento, ingredientes por sub-preparação '
          '(com especificação, quantidade e unidade), modo de preparo, alergênicos, '
          'observações, referências e o acesso à ficha de origem (.docx).'),
    ('h2', '12.4 Recalcular quantidades por porções'),
    ('p', 'Quando o rendimento da ficha traz um número de porções, a tela de preparação oferece '
          'o recálculo proporcional. A base é o menor número informado — “4 a 6 porções” '
          'usa 4.'),
    ('ol', [
        'Informe <b>Porções desejadas</b> e clique em <b>Recalcular quantidades</b> para ver a '
        'prévia;',
        'Confirme com <b>Salvar quantidades</b>: a partir daí, a exibição e a requisição de '
        'compra usam os novos valores (um selo indica a escala salva);',
        'Para voltar ao rendimento original da ficha, use <b>Restaurar originais</b>.',
    ]),
    ('h2', '12.5 Editar preparação e ingredientes'),
    ('ul', [
        '<b>Editar preparação</b> — ajusta nome, equipamentos, utensílios, tempo, rendimento, '
        'modo de preparo e notas técnicas;',
        '<b>Editar ingredientes</b> — corrige ingrediente, especificações, quantidade e '
        'unidade; adiciona novas linhas; marca ingredientes para exclusão; e ativa/desativa '
        'cada item — ingredientes inativos continuam na receita, mas ficam de fora da '
        'requisição de compra;',
        '<b>Excluir</b> — remove a preparação e a ficha de origem (com confirmação).',
    ]),
    ('h2', '12.6 Gerar a requisição de compra'),
    ('ol', [
        'Acesse <b>Cozinha &gt; Compras</b> e marque as preparações da aula (há o atalho '
        '<b>Selecionar todas</b>);',
        'Clique em <b>Relatório de Ingredientes</b>: o sistema soma os ingredientes comuns das '
        'receitas (reconhecendo variações de acento, plural e detalhes entre parênteses) e '
        'converte as unidades para o padrão de compra — gramas para KG, mililitros para L e '
        'unidades para UN. Água não entra na lista e ingredientes inativos são ignorados;',
        'Preencha os <b>Dados</b> da requisição: Professor responsável, Data da aula, Curso e '
        'Período;',
        'Confira a tabela consolidada (PRODUTO, QUANTIDADE, UNIDADE e DETALHES com a quebra por '
        'preparação) e clique em <b>Exportar Requisição (.xlsx)</b>.',
    ]),
    ('p', 'O arquivo Excel gerado preenche o modelo institucional “Requisição de Compra — '
          'Gastronomia” com os dados da aula e a lista de produtos; a coluna OBSERVAÇÃO sai em '
          'branco para preenchimento posterior.'),

    # ================================================================ 13
    ('h1', '13. Administração'),
    ('p', 'O <b>Painel Admin</b> (engrenagem no topo) concentra os cadastros do sistema. A '
          'página inicial do painel apresenta cartões-atalho com contadores e o acesso a cada '
          'seção descrita a seguir.'),
    ('h2', '13.1 Checklist de configuração inicial'),
    ('p', 'Na primeira implantação, o super administrador vê um checklist de 8 passos: unidade, '
          'categorias, salas, professores, funcionários, cursos, disciplinas e feriados. Cada '
          'item mostra o andamento, leva direto ao cadastro correspondente pelo botão '
          '<b>Cadastrar</b> e some da lista quando concluído.'),
    ('h2', '13.2 Usuários'),
    ('p', 'Em <b>Usuários</b> estão os cadastros de professores e funcionários, com busca por '
          'nome, filtro por tipo, ordenação (papel, nome, matrícula ou status) e a opção de '
          'exibir contas desativadas.'),
    ('passo', 'Cadastrar um usuário'),
    ('ol', [
        'Clique em <b>Cadastrar Usuário</b> (ou nos atalhos diretos para professor e '
        'funcionário do checklist);',
        'Selecione o <b>Tipo de Perfil</b>: <b>Professor</b> ou <b>Funcionário</b>;',
        'Informe o <b>E-mail</b> (será o login), o <b>Nome Completo</b> (aceita letras, números '
        'e pontuação) e a <b>Matrícula/ID</b>;',
        'Complete os dados do perfil: <b>Departamento</b> (professor) ou <b>Setor</b> e '
        '<b>Função</b> (funcionário). Para funcionários que também lecionam, marque '
        '<b>Também cadastrar como Professor</b>;',
        'Selecione as <b>Unidades</b> do usuário — o campo aceita vários vínculos de uma vez '
        '(segure Ctrl); quem tem mais de uma unidade alterna sozinho pelo botão <b>Trocar</b> '
        'no topo (seção 3.3). Escolha o <b>Papel</b> e, se necessário, os <b>Módulos '
        'Adicionais</b> (ex.: Módulo Cozinha);',
        'Defina a <b>Senha</b> inicial (mínimo de 8 caracteres — o usuário será obrigado a '
        'trocá-la no primeiro login) e mantenha <b>Ativo</b> marcado;',
        'Clique em <b>Salvar</b>.',
    ]),
    ('passo', 'Editar, ativar/desativar e resetar senha'),
    ('ul', [
        '<b>Editar</b> (lápis) — ajusta dados, unidades, papel, módulos adicionais e status; o '
        'tipo de perfil não muda após a criação. Preenchendo uma nova senha, o usuário será '
        'obrigado a trocá-la no próximo login;',
        '<b>Ativar/Desativar</b> — alterna o acesso do usuário sem apagar seus dados (contas '
        'desativadas não conseguem entrar). Ninguém consegue desativar a própria conta;',
        '<b>Resetar senha</b> (chave) — gera uma senha temporária exibida uma única vez na '
        'tela: copie e entregue ao usuário, que deverá trocá-la no próximo login.',
    ]),
    ('h2', '13.3 Salas'),
    ('p', 'O cadastro de salas fica no Painel Admin (a consulta foi descrita na seção 5). Em '
          '<b>Adicionar Sala / Editar</b>:'),
    ('ul', [
        '<b>Número da Sala</b> (obrigatório), <b>Nome</b> (opcional), <b>Prédio</b>, '
        '<b>Andar</b>, <b>Capacidade</b> (obrigatória) e <b>Categoria</b> (obrigatória);',
        '<b>Número de Computadores</b> — gravado apenas quando a categoria controla '
        'computadores (laboratórios);',
        '<b>Descrição</b> e o indicador <b>Ativo</b>;',
        'O código da sala é gerado automaticamente (abreviação da categoria + número, ex.: '
        'LI306); códigos repetidos na unidade são recusados.',
    ]),
    ('p', 'Na listagem, o botão de alternância ativa/desativa a sala sem excluir o histórico de '
          'reservas.'),
    ('h2', '13.4 Categorias de sala'),
    ('p', 'As categorias definem os tipos de sala e alimentam automaticamente o totem, o painel '
          'e os filtros — criar uma categoria nova já faz ela aparecer nas telas. Campos do '
          'cadastro:'),
    ('ul', [
        '<b>Nome da Categoria</b> (obrigatório);',
        '<b>Esta categoria controla computadores</b> — habilita a contagem de PCs nas salas '
        'vinculadas;',
        '<b>Abreviação para código</b> — até 3 letras usadas no código automático das salas '
        '(ex.: LI);',
        '<b>Cor de destaque</b> e <b>Ícone</b> — identificação visual nos cartões e blocos;',
        '<b>Janela exibida no Totem</b> — “Período atual (manhã/tarde/noite)” ou “Próximos '
        '7 dias”;',
        '<b>Ativo</b> — categorias inativas deixam de aparecer nas telas.',
    ]),
    ('h2', '13.5 Cursos e disciplinas'),
    ('p', 'Cursos e disciplinas compõem a estrutura acadêmica usada nas reservas. Ambos têm '
          'cadastro com nome (obrigatório), código (obrigatório e único na unidade), descrição e '
          'indicador ativo. As listagens têm o botão <b>Mostrar/Esconder inativos</b>, como na '
          'de usuários: por padrão, só os ativos aparecem. Nas disciplinas, o campo '
          '<b>Pertence ao Curso</b> vincula a disciplina a um curso — na reserva, ao escolher o '
          'curso, apenas as disciplinas dele são ofertadas; disciplinas sem curso aparecem '
          'sempre.'),
    ('h2', '13.6 Feriados'),
    ('p', 'Feriados cadastrados bloqueiam reservas na unidade. A tela oferece dois caminhos:'),
    ('ul', [
        '<b>Importar da BrasilAPI</b> — informe o <b>Ano</b> e clique em <b>Buscar e '
        'Importar</b>: os feriados nacionais do ano são cadastrados de uma vez (o sistema '
        'informa quantos foram importados e quantos já existiam);',
        '<b>Adicionar Manualmente</b> — nome e data do feriado (municipais, estaduais ou '
        'pontuais), com o indicador <b>Ativo</b> (Bloquear Reservas).',
    ]),
    ('p', 'Na listagem, cada feriado pode ser editado ou excluído (com confirmação).'),
    ('h2', '13.7 Papéis e permissões'),
    ('p', 'Em <b>Papéis</b> estão os perfis de acesso (seção 3). Papéis do sistema podem ser '
          'inspecionados; papéis customizados podem ser criados e editados com qualquer '
          'combinação de permissões, organizadas por módulo (reservas, salas, cursos, feriados, '
          'usuários, unidades, cozinha, financeiro, notificações, papéis, sistema e API). Regras '
          'de proteção:'),
    ('ul', [
        'O papel de <b>Super Administrador</b> não pode ser editado nem excluído;',
        'Um papel com usuários vinculados não pode ser excluído — migre os usuários primeiro;',
        'A permissão universal (*) é exclusiva do super administrador.',
    ]),
    ('h2', '13.8 Unidades educacionais'),
    ('p', 'Em <b>Unidades</b> ficam os campi/sedes do sistema. Cadastro: <b>Nome</b>, '
          '<b>Código Curto</b> (2 a 20 letras/números), <b>Endereço</b> e <b>Telefone</b> '
          '(opcionais) e o bloco <b>Clima no Totem</b>: use a busca de endereço para localizar a '
          'unidade e preencher automaticamente Latitude, Longitude e a cidade exibida no clima '
          '(ou digite as coordenadas manualmente).'),
    ('ul', [
        '<b>Módulos por unidade</b> — na criação, escolha se a unidade usa os módulos Cozinha e '
        'Financeiro (Reservas de Salas é sempre ativo). Depois de criada, os módulos podem ser '
        'ligados e desligados na tela da unidade; desligar o módulo Financeiro remove o acesso '
        'dos usuários tanto à Hora Extra quanto ao Vale-Transporte;',
        '<b>Ativa</b> — unidades inativas ficam fora dos seletores e do portal;',
        '<b>Reler arquivo</b> — atualiza as unidades oficiais da instituição a partir do arquivo '
        'público de unidades (cria as ausentes e atualiza endereço e telefone).',
    ]),
    ('atencao', 'A unidade em que você está operando não pode ser desativada. Troque de unidade '
                'antes.'),
    ('h2', '13.9 Tokens da API'),
    ('p', 'Aplicativos externos (como quadros de sala na porta) consomem a API de reservas '
          '(seção 14). Em <b>Tokens da API</b>:'),
    ('ol', [
        'Clique em <b>Gerar token</b>, informe o <b>Nome/aplicativo</b> (para identificar a '
        'origem das consultas) e a <b>Validade</b> (sem expiração, 30, 60, 90, 180 dias ou '
        '1 ano);',
        'O valor completo do token é exibido uma única vez — copie na hora e entregue ao '
        'responsável pelo aplicativo (o sistema guarda apenas um resumo seguro do token);',
        'Na listagem, acompanhe o <b>Último uso</b> e a validade; <b>Revogue</b> para cortar o '
        'acesso de imediato (pode ser reativado) ou <b>Exclua</b> permanentemente.',
    ]),
    ('h2', '13.10 Notificações — configuração por unidade'),
    ('p', 'O cartão <b>Notificações</b> do Painel Admin abre a configuração da unidade ativa. A '
          'varredura que gera os avisos roda automaticamente no servidor e avisa quando uma '
          'reserva aprovada com notificações ativadas se aproxima da data (seção 7):'),
    ('ul', [
        '<b>Notificar reservas próximas nesta unidade</b> — o interruptor geral do módulo; '
        'desligado, nenhuma reserva da unidade gera avisos;',
        '<b>Antecedências</b> — dias antes da reserva em que o aviso é criado, separados por '
        'vírgula (ex.: <b>7, 1, 0</b> avisa 7 dias antes, 1 dia antes e no próprio dia; o limite '
        'é 180 dias);',
        '<b>Destinatários fixos</b> — <b>Professor designado na reserva</b>, <b>Criador da '
        'reserva</b> e <b>Aprovadores da unidade</b>, cada um ligado ou desligado à parte;',
        '<b>Grupos personalizados</b> — seleciona quais grupos da unidade (seção 13.11) '
        'recebem os avisos, junto com os destinatários fixos.',
    ]),
    ('p', 'Clique em <b>Salvar configurações</b> para gravar.'),
    ('h2', '13.11 Grupos de notificação'),
    ('p', 'O cartão <b>Grupos de Notificação</b> reúne as pessoas que devem ser avisadas juntas '
          '— por exemplo, a coordenação de um curso. Em <b>Novo grupo</b>, informe o <b>Nome do '
          'grupo</b> (único na unidade) e selecione os <b>Membros do grupo</b> entre os '
          'usuários ativos; <b>Salvar grupo</b> grava.'),
    ('ul', [
        'Os grupos criados aparecem na configuração de notificações da unidade '
        '(seção 13.10);',
        'Excluir um grupo (com confirmação) não remove os avisos já criados, mas as '
        'configurações que o selecionam deixam de avisá-lo.',
    ]),

    # ================================================================ 14
    ('h1', '14. Integração — API de reservas'),
    ('p', 'A API de reservas permite que aplicativos externos consultem a ocupação das salas. '
          'Endereços disponíveis (todos apenas de leitura):'),
    ('table',
     ['Endpoint', 'Retorna'],
     [
         ['/api/v1/reservations', 'Lista paginada de reservas, com filtros por período, '
          'situação, sala, professor, curso, disciplina e turno.'],
         ['/api/v1/reservations/{id}', 'Detalhe completo de uma reserva.'],
         ['/api/v1/rooms', 'Salas ativas da unidade (para resolver códigos de sala).'],
     ],
     [150, 333],
     'Tabela 6 — Endpoints da API de reservas.'),
    ('p', 'Dois modos de acesso:'),
    ('ul', [
        '<b>Sem token (público)</b> — retorna apenas data, horário, sala e título das reservas '
        '<b>aprovadas</b>; suficiente para quadros de porta e consultas simples;',
        '<b>Com token (Bearer)</b> — o aplicativo envia o token gerado no Painel Admin '
        '(seção 13.9) no cabeçalho da requisição e recebe <b>todos os detalhes</b>, em qualquer '
        'situação da reserva.',
    ]),
    ('p', 'Parâmetros mais usados na listagem: <b>start</b> e <b>end</b> (datas AAAA-MM-DD), '
          '<b>status</b> (approved/pending/cancelled/all), <b>classroom_code</b> (código da '
          'sala), <b>period</b> (morning/afternoon/night), <b>unity_id</b> e a paginação '
          '<b>page/per_page</b>. O limite de uso é de 120 consultas por minuto por endereço IP. '
          'A documentação completa, com exemplos, está no guia “API de Reservas” do projeto.'),

    # ================================================================ 15
    ('h1', '15. Mensagens e solução de problemas'),
    ('h2', '15.1 Mensagens mais comuns'),
    ('table',
     ['Mensagem', 'Significado e o que fazer'],
     [
         ['“E-mail ou senha inválidos.”', 'Verifique o e-mail e a senha (o e-mail é o login). '
          'Após 5 tentativas em um minuto, aguarde e tente de novo.'],
         ['“Sua conta foi desativada...”', 'A conta foi desativada por um administrador. '
          'Contate a administração.'],
         ['“Reservas não podem ser agendadas aos domingos.”', 'Escolha outro dia para a '
          'reserva.'],
         ['“Reservas não podem ser agendadas em feriados.”', 'A data escolhida é feriado '
          'cadastrado da unidade. Escolha outro dia.'],
         ['“Aos sábados, as reservas são permitidas apenas pela manhã e tarde (até 18:00).”',
          'Ajuste os horários para terminar até as 18h.'],
         ['“Conflito de sala com ...”', 'Já existe reserva aprovada nesta sala e horário. '
          'Escolha outro horário ou outra sala.'],
         ['“Reserva criada como PENDENTE devido a conflito de professor.”', 'O professor já está '
          'alocado em outra sala no mesmo horário. A reserva aguarda análise do administrador.'],
         ['“Reservas passadas não podem ser editadas/canceladas/excluídas.”', 'Reservas com '
          'data anterior a hoje são registro histórico, sem alteração.'],
         ['“O intervalo da repetição é limitado a 180 dias.”', 'Crie a série em trechos '
          'menores, de até 180 dias.'],
         ['“Apenas reservas aprovadas e futuras podem ter notificações.”', 'O botão de avisos '
          'do detalhe só existe para reservas aprovadas com data de hoje em diante.'],
         ['“Não é possível lançar Hora Extra de meses anteriores ao mês atual.”', 'Lançamentos '
          'retroativos não são permitidos; utilize o mês corrente ou o seguinte.'],
         ['“Lançamentos do mês atual só podem ser feitos até o dia 25.”', 'Do dia 26 em diante, '
          'lance apenas para o mês seguinte.'],
         ['“O modelo suporta 72 linhas...” (Vale-Transporte)', 'A planilha exportada atingiu o '
          'limite do modelo; divida a exportação por grupos.'],
         ['“O token de segurança (CSRF) expirou.”', 'A tela ficou aberta por muito tempo. '
          'Atualize a página (F5) e refaça a operação.'],
     ],
     [205, 278],
     'Tabela 7 — Mensagens frequentes do sistema e providências.'),
    ('h2', '15.2 Perguntas frequentes'),
    ('ul', [
        '<b>Minha reserva não aparece no totem, no portal nem no calendário público. Por quê?</b>',
        'Apenas reservas aprovadas são exibidas publicamente. Verifique se a reserva está '
        'pendente ou cancelada;',
        '<b>Por que minha reserva ficou pendente se a sala estava livre?</b>',
        'O professor selecionado já tem reserva em outra sala no mesmo horário. O administrador '
        'analisa e aprova;',
        '<b>Posso editar uma reserva de outro usuário?</b>',
        'Somente perfis com permissão global de edição (Gestor, Administrador). Professores e '
        'assistentes editam apenas as próprias reservas;',
        '<b>Cadastrei uma sala nova e ela não aparece no totem.</b>',
        'O totem mostra apenas categorias com atividade no recorte configurado. Confira se a '
        'sala está ativa, se a categoria está ativa e se existe reserva aprovada no período;',
        '<b>Esqueci a senha. Existe e-mail de recuperação?</b>',
        'Não há recuperação automática: solicite o reset de senha a um administrador '
        '(seções 2.3 e 13.2);',
        '<b>Não recebi aviso de uma reserva que está próxima. Por quê?</b>',
        'Os avisos são opt-in: alguém com acesso à reserva precisa ter clicado em <b>Ativar '
        'notificações</b> no detalhe dela (seção 7.2), e a configuração da unidade define quem '
        'recebe e com que antecedência (seção 13.10);',
        '<b>O menu Financeiro, RH ou Cozinha desapareceu.</b>',
        'Os módulos podem ter sido desligados para a sua unidade (seção 13.8). Contate o '
        'administrador;',
        '<b>Quem pode alternar de unidade?</b>',
        'Qualquer usuário vinculado a mais de uma unidade alterna sozinho pelo botão '
        '<b>Trocar</b>, no topo; super administradores alternam entre todas as unidades. Veja a '
        'seção 3.3.',
    ]),
]


# ---------------------------------------------------------------------- main

def gerar(caminho):
    _registrar_fontes()
    s = _estilos()
    doc = DocManual(
        os.path.abspath(caminho), pagesize=A4,
        leftMargin=MARGEM, rightMargin=MARGEM, topMargin=64, bottomMargin=64,
        title='SIGerE — Manual do Usuário', author='SIGerE',
        subject=f'Manual do usuário v{VERSAO}',
    )
    doc.multiBuild(montar_story(BLOCOS, s), onFirstPage=_capa, onLaterPages=_pagina_comum)
    return caminho


if __name__ == '__main__':
    saida = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__),
                                                               'manual-do-usuario.pdf')
    gerar(saida)
    print('OK:', os.path.abspath(saida))
