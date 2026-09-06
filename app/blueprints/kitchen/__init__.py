"""Módulo Cozinha do SIGERE.

Sub-menus:
- Ficha Técnica: envio de arquivos .docx (múltiplos por vez), leitura do
  conteúdo pelo submódulo parser (parser.py) e botão "Salvar Ficha Técnica" que gera a
  preparação;
- Preparações: receitas geradas pelas fichas, em cards ou lista (à escolha do
  usuário), com visualização completa;
- Compras: soma por similaridade dos ingredientes das preparações selecionadas
  e exportação da requisição em XLSX (submódulo export.py).
"""
import io
import json
import os
import uuid
from datetime import date, datetime

from flask import (Blueprint, abort, current_app, flash, redirect,
                   render_template, request, send_file, url_for)
from werkzeug.utils import secure_filename

from app.extensions import db
from flask_login import current_user, login_required
from app.models import (KitchenRecipe, KitchenRecipeIngredient, KitchenPreparation,
                        TechnicalSheet)
from app.permissions import require_permission
from app.unity_context import current_unity_id

bp = Blueprint('kitchen', __name__, url_prefix='/kitchen')

ALLOWED_EXTENSIONS = {'.docx'}


# ── Helpers ──────────────────────────────────────────────────────────────────

def _sheet_upload_folder():
    """Pasta de upload DENTRO do instance path — fora de static/, os arquivos
    só são acessíveis pela rota autenticada de download (não servidos ao
    público pelo roteador de estáticos do Flask)."""
    folder = os.path.join(current_app.instance_path, 'uploads', 'technical_sheets')
    os.makedirs(folder, exist_ok=True)
    return folder


def _sheet_file_path(sheet):
    """Caminho do arquivo da ficha: instância nova primeiro, pasta legada
    (app/static/uploads/technical_sheets de instalações antigas) como fallback."""
    if not sheet.stored_filename:
        return None
    candidate = os.path.join(_sheet_upload_folder(), sheet.stored_filename)
    if os.path.exists(candidate):
        return candidate
    legacy = os.path.join(current_app.root_path, 'static', 'uploads',
                          'technical_sheets', sheet.stored_filename)
    return legacy if os.path.exists(legacy) else candidate


def _get_sheet_scoped(sheet_id):
    """Carrega a ficha da unidade ativa — fichas de outras unidades dão 404."""
    sheet = db.session.get(TechnicalSheet, sheet_id)
    if sheet is None or sheet.unity_id != current_unity_id():
        abort(404)
    return sheet


def _get_recipe_scoped(recipe_id):
    recipe = db.session.get(KitchenRecipe, recipe_id)
    if recipe is None or recipe.unity_id != current_unity_id():
        abort(404)
    return recipe


def _store_uploaded_docx(file_storage):
    """Grava o DOCX enviado com nome único; retorna (original, armazenado)."""
    original = os.path.basename(file_storage.filename or '')
    extension = os.path.splitext(original)[1].lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise ValueError(f'Formato não suportado: "{extension or original}". '
                         'Envie arquivos .docx.')
    stored = f"{datetime.now():%Y%m%d%H%M%S}_{uuid.uuid4().hex[:8]}_" \
             f"{secure_filename(original) or 'ficha.docx'}"
    file_storage.save(os.path.join(_sheet_upload_folder(), stored))
    return original, stored


def _create_recipe_from_data(data, unity_id, technical_sheet_id=None):
    """Transforma o dicionário no formato do parser (kitchen/parser.py) em
    KitchenRecipe com preparações e ingredientes."""
    recipe = KitchenRecipe(
        unity_id=unity_id,
        technical_sheet_id=technical_sheet_id,
        name=data['nome'],
        equipments=data.get('equipamentos') or None,
        utensils=data.get('utensilios') or None,
        prep_time=(data.get('tempo_preparo') or '')[:255] or None,
        yield_info=(data.get('rendimento') or '')[:255] or None,
        steps_text='\n'.join(data.get('modo_preparo') or []) or None,
        general_notes=data.get('observacoes') or None,
        allergens=data.get('alergenicos') or None,
        references=data.get('referencias') or None,
    )
    for position, prep_data in enumerate(data.get('preparacoes') or []):
        preparation = KitchenPreparation(
            name=prep_data['nome'], position=position, recipe=recipe)
        for ing_position, ing_data in enumerate(prep_data.get('ingredientes') or []):
            preparation.ingredients.append(KitchenRecipeIngredient(
                name=ing_data['nome'],
                specification=ing_data.get('especificacao') or None,
                quantity=ing_data.get('quantidade'),
                quantity_raw=(ing_data.get('quantidade_raw') or '')[:50] or None,
                unit=(ing_data.get('unidade') or '')[:30],
                position=ing_position,
            ))
    db.session.add(recipe)
    return recipe


def _create_recipe_from_sheet(sheet):
    """Transforma o JSON extraído da ficha pendente em KitchenRecipe."""
    data = sheet.parsed_data
    if not data:
        raise ValueError('Ficha sem conteúdo extraído.')
    recipe = _create_recipe_from_data(data, unity_id=sheet.unity_id,
                                      technical_sheet_id=sheet.id)
    sheet.status = 'saved'
    sheet.data_json = None
    return recipe


@bp.app_template_filter('qtyfmt')
def quantity_format(value):
    """400.0 → '400'; 12.5 → '12,5'."""
    if value is None:
        return ''
    if float(value) == int(value):
        return str(int(value))
    return f'{value:.2f}'.rstrip('0').replace('.', ',')


# ── Ficha Técnica ────────────────────────────────────────────────────────────

@bp.route('/fichas')
@login_required
@require_permission('kitchen:read')
def sheets():
    sheets_list = TechnicalSheet.query.filter_by(unity_id=current_unity_id()) \
        .order_by(TechnicalSheet.uploaded_at.desc()).all()
    pending = [s for s in sheets_list if s.status == 'pending']
    errored = [s for s in sheets_list if s.status == 'error']
    saved = [s for s in sheets_list if s.status == 'saved']
    can_manage = current_user.has_permission('kitchen:sheet_create')
    can_delete = current_user.has_permission('kitchen:sheet_delete')
    return render_template('kitchen/sheets.html', sheets=sheets_list,
                           pending=pending, errored=errored, saved=saved,
                           can_manage=can_manage, can_delete=can_delete)


@bp.route('/fichas/criar', methods=['GET', 'POST'])
@login_required
@require_permission('kitchen:sheet_create')
def create_sheet():
    """Cria uma ficha técnica manualmente, seguindo o mesmo modelo das fichas
    enviadas em .docx (nome, equipamentos, utensílios, tempo, rendimento,
    preparações com insumos, modo de preparo e notas técnicas)."""
    if request.method == 'POST':
        data = _sheet_data_from_form()
        if data is None:
            flash('Informe o nome da preparação.', 'warning')
            return redirect(url_for('kitchen.create_sheet'))
        recipe = _create_recipe_from_data(data, unity_id=current_unity_id())
        db.session.commit()
        flash(f'Ficha Técnica criada! A preparação "{recipe.name}" está '
              'disponível em Preparações.', 'success')
        return redirect(url_for('kitchen.preparation_detail', recipe_id=recipe.id))
    return render_template('kitchen/sheet_form.html')


@bp.route('/fichas/upload', methods=['POST'])
@login_required
@require_permission('kitchen:sheet_create')
def upload_sheets():
    """Lê vários arquivos .docx de uma vez. Cada ficha fica 'pendente' até o
    usuário confirmar com o botão Salvar Ficha Técnica."""
    from app.blueprints.kitchen.parser import FichaParseError, parse_ficha_docx

    files = [f for f in request.files.getlist('files') if f and f.filename]
    if not files:
        flash('Selecione ao menos um arquivo de ficha técnica (.docx).', 'warning')
        return redirect(url_for('kitchen.sheets'))

    success, failure = 0, 0
    for file_storage in files:
        original, stored = None, None
        try:
            original, stored = _store_uploaded_docx(file_storage)
        except ValueError as exc:
            flash(str(exc), 'danger')
            failure += 1
            continue

        sheet = TechnicalSheet(
            unity_id=current_unity_id(),
            original_filename=original[:255],
            stored_filename=stored[:255],
            uploaded_by_id=current_user.id,
        )
        try:
            with open(os.path.join(_sheet_upload_folder(), stored), 'rb') as handle:
                data = parse_ficha_docx(handle)
            sheet.data_json = json.dumps(data, ensure_ascii=False)
            sheet.status = 'pending'
            success += 1
        except FichaParseError as exc:
            sheet.status = 'error'
            sheet.parse_error = str(exc)
            failure += 1
        except OSError:
            sheet.status = 'error'
            sheet.parse_error = 'Falha de leitura do arquivo enviado.'
            failure += 1
        db.session.add(sheet)

    db.session.commit()
    if success:
        flash(f'{success} ficha(s) lida(s) com sucesso. '
              'Revise o conteúdo e clique em "Salvar Ficha Técnica".', 'success')
    if failure:
        flash(f'{failure} arquivo(s) não puderam ser lidos — veja os detalhes '
              'na lista abaixo.', 'danger')
    return redirect(url_for('kitchen.sheets'))


@bp.route('/fichas/<int:sheet_id>')
@login_required
@require_permission('kitchen:read')
def sheet_preview(sheet_id):
    """Prévia do conteúdo extraído da ficha antes/depois de salvar."""
    sheet = _get_sheet_scoped(sheet_id)
    data = sheet.parsed_data
    if data is None and sheet.recipe:
        data = {
            'nome': sheet.recipe.name,
            'equipamentos': sheet.recipe.equipments,
            'utensilios': sheet.recipe.utensils,
            'tempo_preparo': sheet.recipe.prep_time,
            'rendimento': sheet.recipe.yield_info,
            'preparacoes': [
                {'nome': p.name,
                 'ingredientes': [{
                     'nome': i.name, 'especificacao': i.specification,
                     'quantidade': i.quantity, 'quantidade_raw': i.quantity_raw,
                     'unidade': i.unit,
                 } for i in p.ingredients]}
                for p in sheet.recipe.preparations
            ],
            'modo_preparo': sheet.recipe.step_list,
            'observacoes': sheet.recipe.general_notes,
            'alergenicos': sheet.recipe.allergens,
            'referencias': sheet.recipe.references,
        }
    return render_template('kitchen/sheet_preview.html', sheet=sheet, data=data,
                           can_manage=current_user.has_permission('kitchen:sheet_create'),
                           can_delete=current_user.has_permission('kitchen:sheet_delete'))


@bp.route('/fichas/<int:sheet_id>/salvar', methods=['POST'])
@login_required
@require_permission('kitchen:sheet_create')
def save_sheet(sheet_id):
    sheet = _get_sheet_scoped(sheet_id)
    if sheet.status != 'pending':
        flash('Esta ficha já foi salva.', 'info')
        return redirect(url_for('kitchen.sheets'))
    try:
        recipe = _create_recipe_from_sheet(sheet)
        db.session.commit()
        flash(f'Ficha Técnica salva! Preparação "{recipe.name}" criada.', 'success')
        return redirect(url_for('kitchen.preparation_detail', recipe_id=recipe.id))
    except (ValueError, KeyError) as exc:
        db.session.rollback()
        flash(f'Não foi possível salvar a ficha: {exc}', 'danger')
        return redirect(url_for('kitchen.sheet_preview', sheet_id=sheet.id))


@bp.route('/fichas/salvar-todas', methods=['POST'])
@login_required
@require_permission('kitchen:sheet_create')
def save_all_sheets():
    pending = TechnicalSheet.query.filter_by(unity_id=current_unity_id(),
                                             status='pending').all()
    if not pending:
        flash('Nenhuma ficha pendente para salvar.', 'info')
        return redirect(url_for('kitchen.sheets'))
    saved_names = []
    for sheet in pending:
        try:
            saved_names.append(_create_recipe_from_sheet(sheet).name)
        except (ValueError, KeyError) as exc:
            db.session.rollback()
            sheet.status = 'error'
            sheet.parse_error = str(exc)
            db.session.add(sheet)
    db.session.commit()
    flash(f'{len(saved_names)} ficha(s) salva(s): {", ".join(saved_names)}.', 'success')
    return redirect(url_for('kitchen.sheets'))


@bp.route('/fichas/<int:sheet_id>/excluir', methods=['POST'])
@login_required
@require_permission('kitchen:sheet_delete')
def delete_sheet(sheet_id):
    sheet = _get_sheet_scoped(sheet_id)
    name = sheet.original_filename
    file_path = _sheet_file_path(sheet)
    db.session.delete(sheet)  # cascade remove a preparação vinculada
    db.session.commit()
    if file_path and os.path.exists(file_path):
        try:
            os.remove(file_path)
        except OSError:
            pass
    flash(f'Ficha "{name}" excluída.', 'info')
    return redirect(url_for('kitchen.sheets'))


@bp.route('/fichas/<int:sheet_id>/download')
@login_required
@require_permission('kitchen:read')
def download_sheet(sheet_id):
    sheet = _get_sheet_scoped(sheet_id)
    file_path = _sheet_file_path(sheet)
    if not file_path or not os.path.exists(file_path):
        abort(404)
    return send_file(file_path, as_attachment=True,
                     download_name=sheet.original_filename)


# ── Preparações ──────────────────────────────────────────────────────────────

@bp.route('/preparacoes')
@login_required
@require_permission('kitchen:read')
def preparations():
    query = KitchenRecipe.query.filter_by(unity_id=current_unity_id(),
                                          is_active=True)
    search = (request.args.get('q') or '').strip()
    if search:
        query = query.filter(KitchenRecipe.name.ilike(f'%{search}%'))
    recipes = query.order_by(KitchenRecipe.created_at.desc()).all()
    return render_template('kitchen/preparations.html', recipes=recipes,
                           search=search)


@bp.route('/preparacoes/<int:recipe_id>')
@login_required
@require_permission('kitchen:read')
def preparation_detail(recipe_id):
    recipe = _get_recipe_scoped(recipe_id)
    return render_template('kitchen/preparation_detail.html', recipe=recipe,
                           can_edit=current_user.has_permission('kitchen:sheet_create'),
                           can_delete=current_user.has_permission('kitchen:sheet_delete'))


@bp.route('/preparacoes/<int:recipe_id>/excluir', methods=['POST'])
@login_required
@require_permission('kitchen:sheet_delete')
def delete_recipe(recipe_id):
    recipe = _get_recipe_scoped(recipe_id)
    name = recipe.name
    # A ficha em cascata remove também a preparação (e o arquivo .docx).
    sheet = recipe.technical_sheet
    if sheet:
        file_path = _sheet_file_path(sheet)
        db.session.delete(sheet)
        db.session.commit()
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
            except OSError:
                pass
    else:
        db.session.delete(recipe)
        db.session.commit()
    flash(f'Preparação "{name}" excluída junto com a ficha técnica de origem.', 'info')
    return redirect(url_for('kitchen.preparations'))


@bp.route('/preparacoes/<int:recipe_id>/editar', methods=['GET', 'POST'])
@login_required
@require_permission('kitchen:sheet_create')
def edit_recipe(recipe_id):
    """Edita os campos da preparação (identificação, modo de preparo e notas) —
    os ingredientes são editados em outro formulário."""
    from app.blueprints.kitchen.parser import _STEP_NUMBER_RE

    recipe = _get_recipe_scoped(recipe_id)

    if request.method == 'POST':
        nome = (request.form.get('nome') or '').strip()
        if not nome:
            flash('Informe o nome da preparação.', 'warning')
            return redirect(url_for('kitchen.edit_recipe', recipe_id=recipe.id))
        recipe.name = nome
        recipe.equipments = (request.form.get('equipamentos') or '').strip() or None
        recipe.utensils = (request.form.get('utensilios') or '').strip() or None
        recipe.prep_time = (request.form.get('tempo_preparo') or '').strip()[:255] or None
        recipe.yield_info = (request.form.get('rendimento') or '').strip()[:255] or None
        recipe.steps_text = '\n'.join(
            _STEP_NUMBER_RE.sub('', s.strip()).strip()
            for s in (request.form.get('modo_preparo') or '').splitlines()
            if s.strip()) or None
        recipe.general_notes = (request.form.get('observacoes') or '').strip() or None
        recipe.allergens = (request.form.get('alergenicos') or '').strip() or None
        recipe.references = (request.form.get('referencias') or '').strip() or None
        db.session.commit()
        flash(f'Preparação "{recipe.name}" atualizada.', 'success')
        return redirect(url_for('kitchen.preparation_detail', recipe_id=recipe.id))

    return render_template('kitchen/recipe_form.html', recipe=recipe)


# ── Ingredientes (edição e ativação) ─────────────────────────────────────────

def _parse_form_quantity(raw):
    """Converte o texto do formulário em número ('400', '2,5', 'a gosto')."""
    from app.blueprints.kitchen.parser import _parse_quantity
    return _parse_quantity((raw or '').strip())


def _sheet_data_from_form():
    """Monta o dicionário no formato do parser a partir do formulário manual
    de ficha técnica. Retorna None quando o nome da preparação está vazio."""
    from app.blueprints.kitchen.parser import _STEP_NUMBER_RE

    nome = (request.form.get('nome') or '').strip()
    if not nome:
        return None

    preparations = []
    for index, name in enumerate(x.strip() for x in request.form.getlist('prep_nome[]')):
        preparations.append({'nome': name or f'Preparação {index + 1}',
                             'ingredientes': []})

    columns = ('ing_prep[]', 'ing_nome[]', 'ing_espec[]', 'ing_qtd[]', 'ing_unid[]')
    rows = zip(*(request.form.getlist(c) for c in columns))
    for prep_index, nome_ing, espec, qtd, unidade in rows:
        name = nome_ing.strip()
        if not name:
            continue
        try:
            prep_position = int(prep_index)
        except (TypeError, ValueError):
            continue
        if not 0 <= prep_position < len(preparations):
            continue
        preparations[prep_position]['ingredientes'].append({
            'nome': name,
            'especificacao': espec.strip(),
            'quantidade': _parse_form_quantity(qtd),
            'quantidade_raw': qtd.strip(),
            'unidade': unidade.strip(),
        })

    return {
        'nome': nome,
        'equipamentos': (request.form.get('equipamentos') or '').strip(),
        'utensilios': (request.form.get('utensilios') or '').strip(),
        'tempo_preparo': (request.form.get('tempo_preparo') or '').strip(),
        'rendimento': (request.form.get('rendimento') or '').strip(),
        'preparacoes': preparations,
        'modo_preparo': [_STEP_NUMBER_RE.sub('', s.strip()).strip()
                         for s in (request.form.get('modo_preparo') or '').splitlines()
                         if s.strip()],
        'observacoes': (request.form.get('observacoes') or '').strip() or None,
        'alergenicos': (request.form.get('alergenicos') or '').strip() or None,
        'referencias': (request.form.get('referencias') or '').strip() or None,
    }


@bp.route('/preparacoes/<int:recipe_id>/ingredientes/<int:prep_id>',
          methods=['GET', 'POST'])
@login_required
@require_permission('kitchen:sheet_create')
def edit_ingredients(recipe_id, prep_id):
    """Edita os ingredientes de uma preparação: campos, inclusão de novos
    itens, exclusão e ativação/desativação individual."""
    recipe = _get_recipe_scoped(recipe_id)
    preparation = db.session.get(KitchenPreparation, prep_id)
    if preparation is None or preparation.recipe_id != recipe.id:
        abort(404)

    if request.method == 'POST':
        _apply_ingredient_form(preparation)
        db.session.commit()
        flash(f'Ingredientes de "{preparation.name}" atualizados.', 'success')
        return redirect(url_for('kitchen.preparation_detail', recipe_id=recipe.id))

    return render_template('kitchen/ingredient_form.html',
                           recipe=recipe, preparation=preparation)


def _apply_ingredient_form(preparation):
    """Aplica o formulário de ingredientes: atualiza itens existentes, exclui
    os marcados e cria os novos (linhas com id 'new'). Checkboxes desmarcados
    não são enviados, por isso cada linha informa os índices marcados."""
    from app.blueprints.kitchen.parser import _parse_quantity

    columns = ('ing_id', 'ing_nome[]', 'ing_espec[]', 'ing_qtd[]', 'ing_unid[]')
    rows = list(zip(*(request.form.getlist(c) for c in columns)))
    # Os checkboxes enviam o índice da linha como valor; desmarcados não são
    # enviados. Converte para int porque a comparação é com enumerate().
    active_indexes = {int(v) for v in request.form.getlist('ing_ativo')
                      if str(v).isdigit()}
    delete_indexes = {int(v) for v in request.form.getlist('ing_excluir')
                      if str(v).isdigit()}
    existing = {ing.id: ing for ing in preparation.ingredients}

    position = 0
    for index, (raw_id, name, espec, qtd, unidade) in enumerate(rows):
        name = (name or '').strip()
        if index in delete_indexes:
            if raw_id and raw_id != 'new':
                ingredient = existing.get(int(raw_id))
                if ingredient and ingredient.preparation_id == preparation.id:
                    db.session.delete(ingredient)
            continue
        if not name:
            continue  # linha vazia adicionada e abandonada no formulário

        values = {
            'specification': (espec or '').strip() or None,
            'quantity': _parse_quantity((qtd or '').strip()),
            'quantity_raw': (qtd or '').strip()[:50] or None,
            'unit': (unidade or '').strip()[:30],
            'is_active': index in active_indexes,
            'position': position,
        }
        position += 1

        if raw_id and raw_id != 'new':
            ingredient = existing.get(int(raw_id))
            if ingredient is None or ingredient.preparation_id != preparation.id:
                continue
            ingredient.name = name
            for field, value in values.items():
                setattr(ingredient, field, value)
        else:
            preparation.ingredients.append(KitchenRecipeIngredient(
                name=name, preparation_id=preparation.id, **values))


@bp.route('/ingredientes/<int:ingredient_id>/alternar', methods=['POST'])
@login_required
@require_permission('kitchen:sheet_create')
def toggle_ingredient(ingredient_id):
    """Ativa/desativa um ingrediente. Desativado, ele deixa de aparecer na
    requisição de compra (Compras)."""
    ingredient = db.session.get(KitchenRecipeIngredient, ingredient_id)
    if ingredient is None:
        abort(404)
    recipe = ingredient.preparation.recipe
    if recipe.unity_id != current_unity_id():
        abort(404)
    ingredient.is_active = not ingredient.is_active
    db.session.commit()
    estado = 'ativado' if ingredient.is_active else 'desativado'
    flash(f'Ingrediente "{ingredient.name}" {estado}.', 'info')
    return redirect(request.referrer or
                    url_for('kitchen.preparation_detail', recipe_id=recipe.id))


# ── Compras ──────────────────────────────────────────────────────────────────

@bp.route('/compras')
@login_required
@require_permission('kitchen:read')
def shopping():
    recipes = KitchenRecipe.query.filter_by(unity_id=current_unity_id(),
                                            is_active=True) \
        .order_by(KitchenRecipe.name).all()
    return render_template('kitchen/shopping.html', recipes=recipes,
                           today=date.today(),
                           can_export=current_user.has_permission('kitchen:shopping_export'))


@bp.route('/compras/export', methods=['POST'])
@login_required
@require_permission('kitchen:shopping_export')
def shopping_export():
    from app.blueprints.kitchen.export import aggregate_ingredients, build_purchase_xlsx

    recipe_ids = request.form.getlist('recipe_ids')
    if not recipe_ids:
        flash('Selecione ao menos uma preparação para gerar a requisição.', 'warning')
        return redirect(url_for('kitchen.shopping'))

    try:
        ids = [int(i) for i in recipe_ids]
    except (TypeError, ValueError):
        flash('Seleção de preparações inválida.', 'danger')
        return redirect(url_for('kitchen.shopping'))

    recipes = KitchenRecipe.query.filter(
        KitchenRecipe.unity_id == current_unity_id(),
        KitchenRecipe.id.in_(ids)
    ).all()
    if not recipes:
        abort(404)

    class_date = request.form.get('class_date') or date.today().isoformat()
    try:
        class_date = datetime.strptime(class_date, '%Y-%m-%d').date()
    except ValueError:
        class_date = date.today()

    rows = aggregate_ingredients(recipes)
    try:
        content = build_purchase_xlsx(
            rows,
            professor=request.form.get('professor') or current_user.full_name,
            class_date=class_date,
            course=(request.form.get('course') or '').strip(),
            period=request.form.get('period') or '',
        )
    except FileNotFoundError:
        flash('Modelo do Excel não encontrado no servidor '
              '(base_planilha_compras.xlsx).', 'danger')
        return redirect(url_for('kitchen.shopping'))
    filename = f"Requisicao_Compra_{class_date:%Y-%m-%d}.xlsx"
    flash(f'Requisição gerada com {len(rows)} produto(s) a partir de '
          f'{len(recipes)} preparação(ões).', 'success')
    return send_file(io.BytesIO(content), as_attachment=True,
                     download_name=filename,
                     mimetype='application/vnd.openxmlformats-officedocument'
                              '.spreadsheetml.sheet')
