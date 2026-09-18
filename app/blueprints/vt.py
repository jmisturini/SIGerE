"""Módulo Vale Transporte do Financeiro.

Adaptação web do "Gerador Unificado" (script local de vale transporte),
organizado em duas páginas:

1. Pedido público (/vt/pedido, sem login): réplica do formulário
   "Pedido de Vale-Transporte" (Microsoft Forms) com identificação apenas
   pelo e-mail; as respostas ficam em VtRequest;
2. Pedidos VT (/vt/pedidos): as respostas do formulário DA UNIDADE ATIVA,
   com filtros, correção individual (editar/excluir, vt:edit / vt:delete)
   e a planilha de pagamento (planilha_base_vt.xlsx, Matrícula/Nome/Total
   a partir da linha 5) filtrável pelos grupos do gerador:
   Técnico-Administrativo (Faculdade), Professores e
   Técnico-Administrativo (Restaurante/Lanchonete) — apenas Optante VT
   "Sim" com passes > 0, critérios do script original.

A importação do "Pedido de Compra" (.xlsx) e a listagem de colaboradores
importados (VtRecord) saíram do ar: o formulário público alimenta a
listagem diretamente — /vt/ e /vt/colaboradores viraram redirecionamentos.
"""
import io
import os
from datetime import date, datetime

from flask import (Blueprint, abort, current_app, flash, jsonify, redirect,
                   render_template, request, send_file, url_for)
from openpyxl import load_workbook
from sqlalchemy import func

from app.extensions import db, limiter
from flask_login import current_user, login_required
from app.forms import FormVtPedido, VT_VINCULOS_PEDIDO
from app.models import Unity, User, VtConfig, VtEmpresa, VtRecord, VtRequest
from app.permissions import require_module, require_permission
from app.unity_context import current_unity_id
from app.utils import redirect_back, redirect_preserving_args

bp = Blueprint('vt', __name__, url_prefix='/vt')

# A aba oculta "Não mexer nesta planilha" do modelo referencia as linhas 5–76
# da aba "Vale Transporte"; acima disso o arquivo gerado perde o vínculo.
EXPORT_MAX_ROWS = 72
EXPORT_FIRST_ROW = 5

VT_SOURCE_SHEET = 'Vale Transporte'
VT_TEMPLATE_FILE = 'planilha_base_vt.xlsx'

GROUP_LABELS = {
    VtRecord.GROUP_FACULDADE: 'Técnico-Administrativo (Faculdade)',
    VtRecord.GROUP_PROFESSORES: 'Professores',
    VtRecord.GROUP_RESTAURANTE: 'Técnico-Administrativo (Restaurante/Lanchonete)',
}


# ── Helpers ──────────────────────────────────────────────────────────────────

def _matricula_sort_key(pedido):
    """Chave de ordenação da matrícula que aceita valores numéricos e de
    texto na mesma lista (números primeiro, em ordem crescente)."""
    value = pedido.registration or ''
    if value.isdigit():
        return (0, int(value), '')
    return (1, 0, value)


def _get_request_scoped(request_id):
    pedido = db.session.get(VtRequest, request_id)
    if pedido is None or pedido.unity_id != current_unity_id():
        abort(404)
    return pedido


def _brl(valor):
    """Valor no padrão brasileiro (R$ 1.234,56) para o relatório."""
    return (f'R$ {valor:,.2f}'
            .replace(',', 'X').replace('.', ',').replace('X', '.'))


def _inteiro(valor):
    """Inteiro com separador de milhar brasileiro (12.345)."""
    return f'{valor:,.0f}'.replace(',', '.')


# ── Rotas ────────────────────────────────────────────────────────────────────

@bp.route('/')
def index():
    """A importação do "Pedido de Compra" saiu do ar — o pedido público
    (/vt/pedido) alimenta a listagem diretamente. Endpoints e URLs antigos
    seguem vivos apenas como redirecionamento para links guardados."""
    return redirect(url_for('vt.requests'))


@bp.route('/colaboradores')
def records():
    """A listagem de colaboradores importados virou a página única
    Pedidos VT (/vt/pedidos)."""
    return redirect(url_for('vt.requests'))


@bp.route('/pedidos')
@login_required
@require_permission('vt:read')
@require_module('finance')
def requests():
    """Pedidos VT: respostas recebidas pelo formulário público DA UNIDADE
    ATIVA, da mais recente para a mais antiga (cada pedido fica vinculado à
    unidade do link usado pelo colaborador), com filtros, correção
    individual e a exportação da planilha de pagamento."""
    search = (request.args.get('q') or '').strip()
    optant_filter = request.args.get('optant') or ''
    link_filter = (request.args.get('link') or '').strip()
    sort = request.args.get('sort') or ''
    hide_without_vt = request.args.get('ocultar_sem_vt') == '1'

    base = VtRequest.query.filter_by(unity_id=current_unity_id())

    query = base
    if search:
        like = f'%{search}%'
        query = query.filter(db.or_(VtRequest.full_name.ilike(like),
                                    VtRequest.email.ilike(like),
                                    VtRequest.registration.ilike(like)))
    if optant_filter in ('Sim', 'Não'):
        query = query.filter(VtRequest.optant == optant_filter)
    if link_filter:
        query = query.filter(VtRequest.link == link_filter)

    # Ordenação (padrão: mais recentes primeiro).
    pedidos = query.order_by(VtRequest.created_at.desc(), VtRequest.id.desc()).all()
    if hide_without_vt:
        pedidos = [p for p in pedidos if p.optant == 'Sim' and p.total_value > 0]
    if sort == 'nome':
        pedidos.sort(key=lambda p: p.full_name.casefold())
    elif sort == 'matricula':
        pedidos.sort(key=_matricula_sort_key)
    elif sort == 'valor':
        pedidos.sort(key=lambda p: p.total_value, reverse=True)

    # Contagem por grupo do gerador (pedidos exportáveis), como nas opções
    # 1/2/3 do script original.
    group_counts = {key: 0 for key in GROUP_LABELS}
    for pedido in pedidos:
        if pedido.is_exportable and pedido.group:
            group_counts[pedido.group] += 1

    com_vt = sum(1 for p in pedidos if p.optant == 'Sim')
    # O select de vínculo oferece apenas os vínculos do formulário atual —
    # valores antigos que existam na base não viram opção de filtro.
    return render_template('vt/pedidos.html', pedidos=pedidos,
                           search=search, optant_filter=optant_filter,
                           link_filter=link_filter, links=VT_VINCULOS_PEDIDO,
                           sort=sort, hide_without_vt=hide_without_vt,
                           group_counts=group_counts, group_labels=GROUP_LABELS,
                           total_com_vt=com_vt,
                           can_edit=current_user.has_permission('vt:edit'),
                           can_delete=current_user.has_permission('vt:delete'),
                           can_export=current_user.has_permission('vt:export'))


@bp.route('/pedidos/<int:request_id>/editar', methods=['GET', 'POST'])
@login_required
@require_permission('vt:edit')
@require_module('finance')
def edit_request(request_id):
    """Correção de um pedido recebido pelo formulário — mesmo formulário do
    colaborador, com empresas/tarifas do cadastro da unidade do pedido."""
    pedido = _get_request_scoped(request_id)
    unity = db.session.get(Unity, pedido.unity_id)
    if unity is None:
        abort(404)
    form = FormVtPedido(obj=pedido)
    _preparar_form_pedido(form, unity)

    if request.method == 'GET':
        # RadioField espera texto ('1'/'2') e o select de valor espera o id
        # da linha de tarifa — o pedido gravou o VALOR (pedidos antigos, só
        # texto), então localiza a linha vigente correspondente.
        form.company_count.data = str(pedido.company_count or '')
        for sufixo in ('a', 'b'):
            linha_id = _linha_id_por_valor(
                pedido.unity_id,
                getattr(pedido, f'company_{sufixo}_name'),
                getattr(pedido, f'company_{sufixo}_value'))
            if linha_id:
                getattr(form, f'company_{sufixo}_value').data = str(linha_id)

    if form.validate_on_submit():
        _aplicar_form_em_pedido(pedido, form, unity)
        db.session.commit()
        flash(f'Pedido de {pedido.full_name} atualizado.', 'success')
        # A edição abre com os filtros da listagem na URL; preserva ao voltar.
        return redirect_preserving_args('vt.requests')

    return render_template('vt/pedido_form.html', form=form, pedido=pedido,
                           empresas_valores=_mapa_empresas_valores(pedido.unity_id))


@bp.route('/pedidos/<int:request_id>/excluir', methods=['POST'])
@login_required
@require_permission('vt:delete')
@require_module('finance')
def delete_request(request_id):
    pedido = _get_request_scoped(request_id)
    name = pedido.full_name
    db.session.delete(pedido)
    db.session.commit()
    flash(f'Pedido de {name} excluído.', 'info')
    return redirect_back('vt.requests')


@bp.route('/pedidos/exportar-pagamento')
@login_required
@require_permission('vt:export')
@require_module('finance')
def payment_export():
    """Gera a planilha de pagamento a partir dos PEDIDOS do formulário da
    unidade ativa, no modelo planilha_base_vt.xlsx — Matrícula, Nome e
    Valor Total (Σ tarifa × vales) a partir da linha 5, nos mesmos moldes do
    gerador original (somente Optante "Sim" com passes > 0)."""
    group = request.args.get('group') or ''
    if group and group not in GROUP_LABELS:
        abort(404)

    pedidos = VtRequest.query.filter_by(unity_id=current_unity_id()).all()
    selected = [p for p in pedidos
                if p.is_exportable and p.group and (not group or p.group == group)]
    selected.sort(key=lambda p: p.full_name.casefold())

    if not selected:
        flash('Nenhum pedido elegível para o grupo selecionado '
              '(é preciso ser Optante VT "Sim", com passes maior que 0, '
              'e vínculo/unidade dentro de um dos grupos).',
              'warning')
        return redirect(url_for('vt.requests'))

    template_path = os.path.join(current_app.root_path, 'static',
                                 'templates_excel', VT_TEMPLATE_FILE)
    try:
        workbook = load_workbook(template_path)
    except FileNotFoundError:
        flash(f'Modelo do Excel não encontrado no servidor ({VT_TEMPLATE_FILE}).',
              'danger')
        return redirect(url_for('vt.requests'))

    worksheet = workbook[VT_SOURCE_SHEET]

    truncated = len(selected) > EXPORT_MAX_ROWS
    for offset, pedido in enumerate(selected[:EXPORT_MAX_ROWS]):
        row = EXPORT_FIRST_ROW + offset
        matricula = pedido.registration
        # O modelo espera a matrícula numérica.
        if isinstance(matricula, str) and matricula.isdigit():
            matricula = int(matricula)
        worksheet.cell(row=row, column=1, value=matricula)
        worksheet.cell(row=row, column=2, value=pedido.full_name)
        worksheet.cell(row=row, column=3, value=pedido.total_value)

    output = io.BytesIO()
    workbook.save(output)
    workbook.close()
    output.seek(0)

    if truncated:
        flash(f'Atenção: o modelo suporta {EXPORT_MAX_ROWS} linhas — a '
              f'exportação incluiu apenas as {EXPORT_MAX_ROWS} primeiras '
              'em ordem alfabética.', 'warning')

    stamp = datetime.now().strftime('%d-%m-%Y %H-%M-%S')
    group_tag = GROUP_LABELS.get(group, 'Pedidos VT')
    filename = f'Tabela Vale Transporte {group_tag} ({stamp}).xlsx'
    return send_file(output, as_attachment=True, download_name=filename,
                     mimetype='application/vnd.openxmlformats-officedocument'
                              '.spreadsheetml.sheet')


@bp.route('/relatorio')
@login_required
@require_permission('vt:read')
@require_module('finance')
def relatorio():
    """Relatório visual dos pedidos VT da unidade ativa: adesão ao
    benefício, vínculos, empresas de ônibus, trajetos, passes e
    investimento — com versão para impressão/PDF, pronto para
    apresentação."""
    pedidos = (VtRequest.query.filter_by(unity_id=current_unity_id())
               .order_by(VtRequest.created_at.desc(),
                         VtRequest.id.desc()).all())

    total = len(pedidos)
    optantes = [p for p in pedidos if p.optant == 'Sim']
    qtde_optantes = len(optantes)
    # Vales e investimento só existem para quem disse que quer o benefício.
    total_passes = sum(p.total_passes for p in optantes)
    valor_total = sum(p.total_value for p in optantes)
    adesao = (qtde_optantes / total * 100) if total else 0

    datas = [p.created_at for p in pedidos if p.created_at]
    periodo = (f"{min(datas).strftime('%d/%m/%Y')} – "
               f"{max(datas).strftime('%d/%m/%Y')}") if datas else None
    maior = max(optantes, key=lambda p: p.total_value, default=None)

    # ── Vínculo (optantes): pedidos, passes e investimento ──
    vinculos = {}
    for p in optantes:
        v = vinculos.setdefault(p.link or 'Não informado',
                                {'pedidos': 0, 'passes': 0, 'valor': 0.0})
        v['pedidos'] += 1
        v['passes'] += p.total_passes
        v['valor'] += p.total_value
    vinculos_lista = sorted(
        ({'nome': nome, 'pedidos': d['pedidos'], 'passes': d['passes'],
          'valor': d['valor'], 'valor_brl': _brl(d['valor'])}
         for nome, d in vinculos.items()),
        key=lambda v: v['pedidos'], reverse=True)

    # ── Empresas de ônibus (posições A e B dos optantes) ──
    empresas = {}
    for p in optantes:
        for posicao in ('a', 'b'):
            nome = getattr(p, f'company_{posicao}_name')
            if not nome:
                continue
            e = empresas.setdefault(
                nome, {'colaboradores': set(), 'passes': 0, 'valor': 0.0})
            e['colaboradores'].add(p.email.casefold())
            passes = getattr(p, f'company_{posicao}_passes') or 0
            e['passes'] += passes
            e['valor'] += float((getattr(p, f'company_{posicao}_value') or 0)
                                * passes)
    empresas_lista = sorted(
        ({'nome': nome, 'colaboradores': len(d['colaboradores']),
          'passes': d['passes'], 'valor': d['valor'],
          'valor_brl': _brl(d['valor'])}
         for nome, d in empresas.items()),
        key=lambda e: e['valor'], reverse=True)
    top_empresas = empresas_lista[:6]
    outras_valor = sum(e['valor'] for e in empresas_lista[6:])

    # ── Trajetos e nº de empresas por pedido (posições A e B) ──
    trajetos = {'Somente Volta': 0, 'Ida e Volta': 0}
    for p in optantes:
        for posicao in ('a', 'b'):
            trajeto = getattr(p, f'company_{posicao}_route')
            if trajeto in trajetos:
                trajetos[trajeto] += 1
    uma_empresa = sum(1 for p in optantes if p.company_count == 1)
    duas_empresas = sum(1 for p in optantes if p.company_count == 2)

    # ── Grupos da planilha de pagamento (critérios do gerador) ──
    grupos = [{'chave': chave, 'rotulo': rotulo, 'pedidos': 0, 'valor': 0.0}
              for chave, rotulo in GROUP_LABELS.items()]
    for p in pedidos:
        if p.is_exportable and p.group:
            for g in grupos:
                if g['chave'] == p.group:
                    g['pedidos'] += 1
                    g['valor'] += p.total_value
    total_grupo_valor = sum(g['valor'] for g in grupos)

    # ── Conferência do RH: identificação única dos colaboradores ──
    emails = [p.email.casefold() for p in pedidos]
    matriculas = [p.registration for p in pedidos if p.registration]
    emails_repetidos = len(emails) - len(set(emails))
    matriculas_repetidas = len(matriculas) - len(set(matriculas))

    return render_template('vt/relatorio.html',
                           total=total,
                           qtde_optantes=qtde_optantes,
                           nao_optantes=total - qtde_optantes,
                           adesao=adesao,
                           total_passes=total_passes,
                           media_passes=(total_passes / qtde_optantes
                                         if qtde_optantes else 0),
                           valor_total=valor_total,
                           ticket_medio=(valor_total / qtde_optantes
                                         if qtde_optantes else 0),
                           valor_por_passe=(valor_total / total_passes
                                            if total_passes else 0),
                           periodo=periodo,
                           maior_pedido=maior,
                           vinculos=vinculos_lista,
                           empresas=empresas_lista,
                           top_empresas=top_empresas,
                           outras_valor=outras_valor,
                           trajetos=trajetos,
                           uma_empresa=uma_empresa,
                           duas_empresas=duas_empresas,
                           grupos=grupos,
                           total_grupo_valor=total_grupo_valor,
                           emails_repetidos=emails_repetidos,
                           matriculas_repetidas=matriculas_repetidas,
                           brl=_brl, inteiro=_inteiro,
                           gerado_em=datetime.now().strftime('%d/%m/%Y %H:%M'))


# ── Pedido público de Vale-Transporte ────────────────────────────────────────
#
# Adaptação do formulário "Pedido de Vale-Transporte" (Microsoft Forms): a
# página /vt/pedido é pública (sem login) e identifica o colaborador apenas
# pelo e-mail informado — as demais perguntas e a ramificação (deseja VT →
# vínculo → nº de empresas) são as mesmas do formulário original. As respostas
# ficam em VtRequest, listadas em /vt/pedidos para conferência do RH.

def _aplicar_form_em_pedido(pedido, form, unity):
    """Grava no VtRequest os campos do FormVtPedido validado — usado na
    criação (pedido público) e na correção pelo RH (Pedidos VT). Sem
    pergunta de unidade no formulário: a coluna unity registra o nome da
    unidade do link (ou da unidade do pedido, na correção). O valor vem da
    linha de tarifa resolvida na validação; o trajeto é a resposta própria
    do formulário."""
    linha_a = getattr(form, '_linha_a', None)
    linha_b = getattr(form, '_linha_b', None)
    pedido.unity_id = unity.id if unity else None
    pedido.unity = unity.name if unity else None
    pedido.email = form.email.data.strip().lower()
    pedido.full_name = form.full_name.data.strip()
    pedido.registration = form.registration.data.strip()
    pedido.optant = form.optant.data
    pedido.link = form.link.data
    pedido.company_count = int(form.company_count.data) if form.company_count.data else 0
    pedido.company_a_name = form.company_a_name.data or None
    pedido.company_a_value = linha_a.valor if linha_a else None
    pedido.company_a_passes = form.company_a_passes.data
    pedido.company_a_route = form.company_a_route.data
    pedido.company_b_name = form.company_b_name.data or None
    pedido.company_b_value = linha_b.valor if linha_b else None
    pedido.company_b_passes = form.company_b_passes.data
    pedido.company_b_route = form.company_b_route.data
    return pedido


def _criar_pedido_de_form(form, unity):
    """VtRequest novo preenchido a partir do FormVtPedido validado."""
    return _aplicar_form_em_pedido(VtRequest(), form, unity)


def _linha_id_por_valor(unity_id, empresa_nome, valor):
    """Id da linha de tarifa do cadastro correspondente ao valor gravado no
    pedido — para pré-selecionar o select na correção. None quando a empresa
    saiu do cadastro ou o valor não corresponde a nenhuma linha vigente
    (pedidos antigos guardam texto)."""
    if not (empresa_nome and valor is not None):
        return None
    for linha in VtEmpresa.mapa_tarifas(unity_id).get(empresa_nome, []):
        if linha.valor == valor:
            return linha.id
    return None


def _mapa_empresas_valores(unity_id):
    """{nome_da_empresa: [{id, rotulo}...]} da unidade — alimenta os selects
    dependentes empresa → linha de tarifa (formato simples para o
    JavaScript)."""
    return {nome: [{'id': v.id, 'rotulo': v.rotulo} for v in linhas]
            for nome, linhas in VtEmpresa.mapa_tarifas(unity_id).items()}


def _pedido_unity():
    """Unidade do formulário público: ?unity=<id> ativa ou a primeira ativa
    (fallback), mesmo comportamento do portal — o visitante é anônimo, então
    não há unidade ativa de sessão; o RH distribui o link da própria unidade."""
    unity_id = request.args.get('unity', type=int)
    if unity_id:
        unity = Unity.query.filter_by(id=unity_id, is_active=True).first()
        if unity:
            return unity
    return Unity.query.filter_by(is_active=True).order_by(Unity.name).first()


def _preparar_form_pedido(form, unity):
    """Choices de empresa/tarifa do pedido público a partir do cadastro
    administrado em /admin/vt-empresas (empresas da unidade do link). O
    select de valor lista as LINHAS de tarifa da empresa (id de
    VtEmpresaValor — "Identificação — R$ valor"); o pareamento é validado
    no form."""
    form._unity_id = unity.id if unity else None
    empresas = VtEmpresa.empresas_ativas(unity.id if unity else None)
    nomes = [(e.nome, e.nome) for e in empresas]
    linhas = [(str(v.id), v.rotulo) for e in empresas for v in e.valores]
    form.company_a_name.choices = [('', 'Selecione…')] + nomes
    form.company_b_name.choices = [('', 'Selecione…')] + nomes
    form.company_a_value.choices = [('', 'Selecione…')] + linhas
    form.company_b_value.choices = [('', 'Selecione…')] + linhas
    return form


@bp.route('/pedido', methods=['GET', 'POST'])
@limiter.limit('10 per minute', methods=['POST'])
def request_form():
    """Formulário público (sem login): o colaborador informa o e-mail e
    responde ao pedido de VT da unidade do link (?unity=<id>). "Não" encerra
    o pedido; "Sim" abre vínculo e os blocos de empresa/vales/trajeto
    guiados pela página. Quando a unidade configura os números base de
    vales, eles são aplicados automaticamente conforme o trajeto; depois da
    data de fechamento o formulário é bloqueado."""
    unity = _pedido_unity()
    config = (VtConfig.query.filter_by(unity_id=unity.id).first()
              if unity else None)
    hoje = date.today()
    fechado = config.esta_fechado(hoje) if config else False

    form = _preparar_form_pedido(FormVtPedido(), unity)
    # Números base da unidade: alimentam o botão "usar valor base" do
    # formulário (oferecido apenas para Técnico-Administrativo).
    vales_base = None
    if config and config.vales_somente_ida and config.vales_ida_e_volta:
        vales_base = {'Somente Volta': config.vales_somente_ida,
                      'Ida e Volta': config.vales_ida_e_volta}

    if not fechado and form.validate_on_submit():
        db.session.add(_criar_pedido_de_form(form, unity))
        db.session.commit()
        flash('Pedido enviado com sucesso! A equipe de RH receberá suas '
              'respostas.', 'success')
        return redirect(url_for('vt.request_form', unity=unity.id) if unity
                        else url_for('vt.request_form'))
    # ocultar_sidebar: página pública em tela cheia, sem a navegação do painel.
    # empresas_valores alimenta o select de tarifa dependente da empresa
    # (linhas identificação + valor, em formato simples para o JavaScript).
    unity_id = unity.id if unity else None
    empresas_valores = _mapa_empresas_valores(unity_id)
    return render_template('vt/pedido.html', form=form, ocultar_sidebar=True,
                           pedido_unity=unity, config=config,
                           fechado=fechado, vales_base=vales_base,
                           empresas_valores=empresas_valores)


def _vinculo_por_perfil(user):
    """Vínculo do formulário de VT derivado do perfil do usuário: professor
    é Professor(a); demais perfis (funcionário) são Técnico-Administrativo."""
    return 'Professor(a)' if user.profile_type == 'teacher' else 'Técnico - Administrativo'


@bp.route('/pedido/colaborador')
@limiter.limit('30 per minute')
def request_form_colaborador():
    """Auto-preenchimento do formulário público: dado o e-mail informado,
    devolve nome, matrícula e vínculo da conta ATIVA correspondente (found
    false quando não há — o colaborador preenche à mão)."""
    email = (request.args.get('email') or '').strip().lower()
    user = None
    if email:
        user = (User.query
                .filter(func.lower(User.email) == email,
                        User.is_active_user == True)
                .first())
    return jsonify({
        'found': user is not None,
        'full_name': user.full_name if user else None,
        'registration': user.registration if user else None,
        'vinculo': _vinculo_por_perfil(user) if user else None,
    })
