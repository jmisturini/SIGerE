"""Módulo Vale Transporte do Financeiro.

Adaptação web do "Gerador Unificado" (script local de vale transporte),
organizado em duas páginas:

1. Importação (/vt/): upload do "Pedido de Compra" (.xlsx); a aba
   "Vale Transporte" é lida inteira (todas as colunas A–P, uma linha por
   colaborador) e gravada em VtRecord — mesma ideia das fichas técnicas da
   Cozinha (importar, revisar, depois exportar);
2. Colaboradores (/vt/colaboradores): listagem com filtros (vínculo,
   unidade, nome), ordenação, marcação de inconsistências (nome fora do
   padrão, nome/matrícula repetidos) e a exportação da planilha de pagamento
   (planilha_base_vt.xlsx, Matrícula/Nome/Total a partir da linha 5),
   filtrável pelos grupos do gerador: Técnico-Administrativo (Faculdade),
   Professores e Técnico-Administrativo (Restaurante/Lanchonete) — apenas
   Optante VT "Sim" com passes > 0, critérios do script original.
"""
import io
import os
from collections import Counter
from datetime import datetime

from flask import (Blueprint, abort, current_app, flash, redirect,
                   render_template, request, send_file, url_for)
from openpyxl import load_workbook

from app.extensions import db
from flask_login import current_user, login_required
from app.forms import FormVtRecord, FormVtUpload
from app.models import VtRecord
from app.permissions import require_module, require_permission
from app.unity_context import current_unity_id
from app.blueprints.payments import parse_currency

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


# ── Padronização de nomes ────────────────────────────────────────────────────

# Partículas que ficam em minúscula (exceto quando primeira palavra) no
# padrão "João Alfredo Misturini".
_NAME_PARTICLES = {'de', 'da', 'do', 'das', 'dos', 'e'}


def normalize_name(raw):
    """Formata o nome no padrão apenas-com-iniciais-maiúsculas:
    'JÉSSICA ROCHA DE SOUZA PEREIRA' → 'Jéssica Rocha de Souza Pereira'."""
    formatted = []
    for index, word in enumerate((raw or '').strip().split()):
        lowered = word.lower()
        if index > 0 and lowered in _NAME_PARTICLES:
            formatted.append(lowered)
        else:
            formatted.append('-'.join(
                part[:1].upper() + part[1:] for part in lowered.split('-')))
    return ' '.join(formatted)


def is_name_standard(raw):
    """Verifica se o nome já está no padrão (iniciais maiúsculas) —
    usada na importação e na edição para decidir pela formatação."""
    return normalize_name(raw) == (raw or '').strip()


def _matricula_sort_key(record):
    """Chave de ordenação da matrícula que aceita valores numéricos e de
    texto na mesma lista (números primeiro, em ordem crescente)."""
    value = record.registration or ''
    if value.isdigit():
        return (0, int(value), '')
    return (1, 0, value)


def _cell_text(value):
    """Texto normalizado da célula: erros de fórmula e zeros viram None."""
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        if not value or value.startswith('#'):
            return None
        return value
    if isinstance(value, (int, float)) and value == 0:
        return None
    return str(value)


def _cell_int(value):
    """Inteiro da célula (contagens/passes): 0 quando vazio ou inválido."""
    if isinstance(value, bool) or value in (None, ''):
        return 0
    if isinstance(value, str):
        value = value.strip()
        if value.startswith('#'):
            return 0
        value = value.replace('.', '').replace(',', '.')
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _cell_money(value):
    """Valor monetário da célula com 2 decimais (a planilha origem carrega
    resíduos de ponto flutuante, ex.: 435.53999999999996)."""
    if isinstance(value, str):
        value = parse_currency(value)
    if value is None:
        return None
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return None


def parse_vt_sheet(stream):
    """Lê a aba "Vale Transporte" do Pedido de Compra e devolve uma lista de
    dicionários com todos os campos de cada colaborador.

    Levanta ValueError com mensagem amigável quando o arquivo não tem a aba.
    Linhas inválidas (fórmulas vazias que retornam #VALUE!, matrícula ausente)
    são ignoradas.
    """
    try:
        workbook = load_workbook(stream, data_only=True, read_only=True)
    except Exception as exc:
        raise ValueError(f'Não foi possível ler o arquivo Excel: {exc}') from exc

    if VT_SOURCE_SHEET in workbook.sheetnames:
        worksheet = workbook[VT_SOURCE_SHEET]
    else:
        # O gerador original processava sempre a terceira aba do arquivo.
        if len(workbook.sheetnames) < 3:
            workbook.close()
            raise ValueError(f'O arquivo não possui a aba "{VT_SOURCE_SHEET}".')
        worksheet = workbook.worksheets[2]

    records = []
    try:
        for row in worksheet.iter_rows(min_row=2, max_col=16, values_only=True):
            registration = _cell_text(row[0])
            full_name = _cell_text(row[1])
            # Linhas de fórmula vazia retornam erro de fórmula ou não têm
            # matrícula/nome — não são colaboradores.
            if not registration or not full_name:
                continue
            optant = _cell_text(row[2]) or 'Não'
            records.append({
                'registration': registration[:20],
                'full_name': full_name[:255],
                'optant': optant if optant in ('Sim', 'Não') else 'Não',
                'link': _cell_text(row[3]),
                'unity': _cell_text(row[4]),
                'company_count': _cell_int(row[5]),
                'company_a_name': _cell_text(row[6]),
                'company_a_value': _cell_money(row[7]),
                'company_a_passes': _cell_int(row[8]),
                'company_a_total': _cell_money(row[9]),
                'company_b_name': _cell_text(row[10]),
                'company_b_value': _cell_money(row[11]),
                'company_b_passes': _cell_int(row[12]),
                'company_b_total': _cell_money(row[13]),
                'total_passes': _cell_int(row[14]),
                'total_value': _cell_money(row[15]),
            })
    finally:
        workbook.close()

    if not records:
        raise ValueError(f'A aba "{VT_SOURCE_SHEET}" não contém linhas de '
                         'colaboradores válidas (verifique se é o Pedido de '
                         'Compra correto).')
    return records


# ── Helpers ──────────────────────────────────────────────────────────────────

def _get_record_scoped(record_id):
    record = db.session.get(VtRecord, record_id)
    if record is None or record.unity_id != current_unity_id():
        abort(404)
    return record


def _apply_record_form(record, form):
    raw_name = form.full_name.data.strip()[:255]
    # Padroniza o nome (iniciais maiúsculas) e guarda o original quando
    # houver ajuste, para auditoria na listagem.
    normalized = normalize_name(raw_name)
    record.original_name = raw_name if normalized != raw_name else None
    record.full_name = normalized
    record.registration = form.registration.data.strip()[:20]
    record.optant = form.optant.data
    record.link = form.link.data or None
    record.unity = form.unity.data or None
    record.company_count = form.company_count.data or 0
    record.company_a_name = form.company_a_name.data or None
    record.company_a_value = parse_currency(form.company_a_value.data)
    record.company_a_passes = form.company_a_passes.data
    record.company_a_total = parse_currency(form.company_a_total.data)
    record.company_b_name = form.company_b_name.data or None
    record.company_b_value = parse_currency(form.company_b_value.data)
    record.company_b_passes = form.company_b_passes.data
    record.company_b_total = parse_currency(form.company_b_total.data)
    record.total_passes = form.total_passes.data or 0
    record.total_value = parse_currency(form.total_value.data)


def _money_text(value):
    """Formata Decimal/float como texto editável com vírgula decimal."""
    if value in (None, ''):
        return ''
    return f'{float(value):.2f}'.replace('.', ',')


# ── Rotas ────────────────────────────────────────────────────────────────────

@bp.route('/')
@login_required
@require_permission('payment:read')
@require_module('finance')
def index():
    """Página de importação: apenas o upload do Pedido de Compra. Após ler o
    arquivo, o usuário é levado à listagem de colaboradores para revisão."""
    total = VtRecord.query.filter_by(unity_id=current_unity_id()).count()
    return render_template('vt/index.html', total=total,
                           can_manage=current_user.has_permission('payment:create'))


@bp.route('/colaboradores')
@login_required
@require_permission('payment:read')
@require_module('finance')
def records():
    search = (request.args.get('q') or '').strip()
    group_filter = request.args.get('group') or ''
    link_filter = (request.args.get('link') or '').strip()
    unity_filter = (request.args.get('unity') or '').strip()
    sort = request.args.get('sort') or ''
    hide_without_vt = request.args.get('ocultar_sem_vt') == '1'

    uid = current_unity_id()
    records = VtRecord.query.filter_by(unity_id=uid).all()

    # Valores distintos presentes na base para os selects de filtro.
    links = sorted({r.link for r in records if r.link})
    unities = sorted({r.unity for r in records if r.unity})

    # Duplicados são marcados sobre a base inteira da unidade — assim um
    # registro continua marcado mesmo quando o par fica fora do filtro.
    name_counts = Counter(r.full_name.casefold() for r in records)
    registration_counts = Counter(r.registration for r in records)
    for record in records:
        record.duplicate_name = name_counts[record.full_name.casefold()] > 1
        record.duplicate_registration = registration_counts[record.registration] > 1

    # ── Filtros ──
    if search:
        records = [r for r in records if search.casefold() in r.full_name.casefold()]
    if link_filter:
        records = [r for r in records if r.link == link_filter]
    if unity_filter:
        records = [r for r in records if r.unity == unity_filter]
    if hide_without_vt:
        records = [r for r in records
                   if r.optant == 'Sim' and r.total_value is not None and r.total_value > 0]

    # ── Ordenação (padrão: ordem de importação) ──
    if sort == 'nome':
        records.sort(key=lambda r: r.full_name.casefold())
    elif sort == 'matricula':
        records.sort(key=_matricula_sort_key)
    elif sort == 'valor':
        records.sort(key=lambda r: float(r.total_value or 0), reverse=True)

    # Contagem por grupo do gerador (colaboradores exportáveis), como nas
    # opções 1/2/3 do script original.
    group_counts = {key: 0 for key in GROUP_LABELS}
    for record in records:
        if record.is_exportable and record.group:
            group_counts[record.group] += 1

    flagged = any(r.original_name or r.duplicate_name or r.duplicate_registration
                  for r in records)

    return render_template('vt/records.html', records=records, search=search,
                           group_filter=group_filter, group_counts=group_counts,
                           group_labels=GROUP_LABELS,
                           link_filter=link_filter, unity_filter=unity_filter,
                           links=links, unities=unities,
                           sort=sort, hide_without_vt=hide_without_vt,
                           flagged=flagged,
                           can_edit=current_user.has_permission('payment:edit'),
                           can_delete=current_user.has_permission('payment:delete'),
                           can_export=current_user.has_permission('payment:export'))


@bp.route('/upload', methods=['POST'])
@login_required
@require_permission('payment:create')
@require_module('finance')
def upload():
    """Lê o Pedido de Compra e substitui os registros da unidade ativa —
    cada arquivo traz a lista completa do mês/competência."""
    form = FormVtUpload()
    if not form.validate_on_submit():
        flash('Selecione um arquivo .xlsx do Pedido de Compra.', 'warning')
        return redirect(url_for('vt.records'))

    try:
        data = parse_vt_sheet(form.file.data.stream)
    except ValueError as exc:
        flash(f'Erro na leitura: {exc}', 'danger')
        return redirect(url_for('vt.records'))

    # Substituição completa: os dados importados são a fonte única vigente.
    replaced = VtRecord.query.filter_by(unity_id=current_unity_id()).delete()
    for item in data:
        raw_name = item['full_name']
        normalized = normalize_name(raw_name)
        if normalized != raw_name:
            item['original_name'] = raw_name
            item['full_name'] = normalized
        db.session.add(VtRecord(unity_id=current_unity_id(), **item))
    db.session.commit()

    adjusted = sum(1 for r in VtRecord.query.filter_by(unity_id=current_unity_id())
                   if r.original_name)

    if replaced:
        flash(f'Importação concluída: {len(data)} colaborador(es) lidos '
              f'({replaced} registro(s) anterior(is) substituído(s)). '
              f'{adjusted} nome(s) padronizado(s) automaticamente — linhas '
              'destacadas na listagem.', 'success')
    else:
        flash(f'Importação concluída: {len(data)} colaborador(es) lidos. '
              f'{adjusted} nome(s) padronizado(s) automaticamente — linhas '
              'destacadas na listagem.', 'success')
    return redirect(url_for('vt.records'))


@bp.route('/<int:record_id>/editar', methods=['GET', 'POST'])
@login_required
@require_permission('payment:edit')
@require_module('finance')
def edit_record(record_id):
    record = _get_record_scoped(record_id)
    form = FormVtRecord(obj=record)

    if request.method == 'GET':
        # Valores monetários voltam com vírgula decimal para edição.
        form.company_a_value.data = _money_text(record.company_a_value)
        form.company_a_total.data = _money_text(record.company_a_total)
        form.company_b_value.data = _money_text(record.company_b_value)
        form.company_b_total.data = _money_text(record.company_b_total)
        form.total_value.data = _money_text(record.total_value)

    if form.validate_on_submit():
        _apply_record_form(record, form)
        db.session.commit()
        flash(f'Registro de {record.full_name} atualizado.', 'success')
        return redirect(url_for('vt.records'))

    return render_template('vt/form.html', form=form, record=record)


@bp.route('/<int:record_id>/excluir', methods=['POST'])
@login_required
@require_permission('payment:delete')
@require_module('finance')
def delete_record(record_id):
    record = _get_record_scoped(record_id)
    name = record.full_name
    db.session.delete(record)
    db.session.commit()
    flash(f'Registro de {name} excluído.', 'info')
    return redirect(url_for('vt.records'))


@bp.route('/limpar', methods=['POST'])
@login_required
@require_permission('payment:delete')
@require_module('finance')
def clear_all():
    """Apaga todos os registros importados da unidade ativa (recomeçar)."""
    removed = VtRecord.query.filter_by(unity_id=current_unity_id()).delete()
    db.session.commit()
    flash(f'{removed} registro(s) removido(s).', 'info')
    return redirect(url_for('vt.records'))


@bp.route('/exportar')
@login_required
@require_permission('payment:export')
@require_module('finance')
def export():
    """Gera a planilha final a partir do modelo planilha_base_vt.xlsx —
    Matrícula, Nome e Valor Total a partir da linha 5, nos mesmos moldes do
    gerador original (somente Optante "Sim" com passes > 0)."""
    group = request.args.get('group') or ''
    if group and group not in GROUP_LABELS:
        abort(404)

    records = VtRecord.query.filter_by(unity_id=current_unity_id()).all()
    selected = [r for r in records
                if r.is_exportable and r.group and (not group or r.group == group)]
    selected.sort(key=lambda r: r.full_name)

    if not selected:
        flash('Nenhum colaborador elegível para o grupo selecionado '
              '(é preciso estar como Optante VT "Sim" e com passes maior que 0).',
              'warning')
        return redirect(url_for('vt.records'))

    template_path = os.path.join(current_app.root_path, 'static',
                                 'templates_excel', VT_TEMPLATE_FILE)
    try:
        workbook = load_workbook(template_path)
    except FileNotFoundError:
        flash(f'Modelo do Excel não encontrado no servidor ({VT_TEMPLATE_FILE}).',
              'danger')
        return redirect(url_for('vt.records'))

    worksheet = workbook[VT_SOURCE_SHEET]

    truncated = len(selected) > EXPORT_MAX_ROWS
    for offset, record in enumerate(selected[:EXPORT_MAX_ROWS]):
        row = EXPORT_FIRST_ROW + offset
        matricula = record.registration
        # O modelo espera a matrícula numérica.
        if isinstance(matricula, str) and matricula.isdigit():
            matricula = int(matricula)
        worksheet.cell(row=row, column=1, value=matricula)
        worksheet.cell(row=row, column=2, value=record.full_name)
        worksheet.cell(row=row, column=3,
                       value=float(record.total_value or 0))

    output = io.BytesIO()
    workbook.save(output)
    workbook.close()
    output.seek(0)

    if truncated:
        flash(f'Atenção: o modelo suporta {EXPORT_MAX_ROWS} linhas — a '
              f'exportação incluiu apenas as {EXPORT_MAX_ROWS} primeiras '
              'em ordem alfabética.', 'warning')

    stamp = datetime.now().strftime('%d-%m-%Y %H-%M-%S')
    group_tag = GROUP_LABELS.get(group, 'Colaboradores')
    filename = f'Tabela Vale Transporte {group_tag} ({stamp}).xlsx'
    return send_file(output, as_attachment=True, download_name=filename,
                     mimetype='application/vnd.openxmlformats-officedocument'
                              '.spreadsheetml.sheet')
