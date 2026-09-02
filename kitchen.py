import os
import smtplib
import uuid
import unicodedata
from datetime import datetime, date, timedelta
from email.message import EmailMessage

from flask import (Blueprint, render_template, redirect, url_for, flash, abort,
                   request, current_app, make_response)
from flask_login import login_required, current_user
from sqlalchemy import func
from sqlalchemy.orm import joinedload, selectinload
from fpdf import FPDF
from extensions import db
from models import (Ingredient, IngredientCategory, StockMovement, StockBatch, Recipe, RecipeIngredient)
from forms import (IngredientForm, IngredientCategoryForm, StockMovementForm, StockBatchForm, RecipeForm)
from permissions import require_permission

bp = Blueprint('kitchen', __name__, url_prefix='/kitchen')

ALLOWED_PHOTO_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp', 'gif'}


def _fmt_qty(value):
    """Formata quantidades para pt-BR: 1500 -> '1500', 0.5 -> '0,5'."""
    if value is None:
        return '0'
    value = float(value)
    if value == int(value):
        return str(int(value))
    return ('%.2f' % value).rstrip('0').rstrip('.').replace('.', ',')


@bp.app_template_filter('qty')
def qty_filter(value):
    return _fmt_qty(value)


# ================= PHOTO UPLOAD HELPERS =================

def _photo_upload_dir():
    """Garante e retorna o diretório de fotos das receitas (static/uploads/recipes)."""
    path = os.path.join(current_app.static_folder, 'uploads', 'recipes')
    os.makedirs(path, exist_ok=True)
    return path


def _save_recipe_photo(file_storage):
    """Salva a imagem enviada com nome seguro gerado por UUID e retorna o nome do arquivo."""
    ext = os.path.splitext(file_storage.filename or '')[1].lower().lstrip('.')
    if ext not in ALLOWED_PHOTO_EXTENSIONS:
        return None
    new_name = f'receita_{uuid.uuid4().hex[:12]}.{ext}'
    file_storage.save(os.path.join(_photo_upload_dir(), new_name))
    return new_name


def _delete_recipe_photo(filename):
    """Remove do disco a foto antiga de uma receita (ignora arquivos inexistentes)."""
    if not filename:
        return
    path = os.path.join(current_app.static_folder, 'uploads', 'recipes', filename)
    if os.path.exists(path):
        try:
            os.remove(path)
        except OSError:
            pass


def _slugify(text, max_len=50):
    """Converte texto em slug ASCII para nomes de arquivo de exportação."""
    normalized = unicodedata.normalize('NFKD', text or '').encode('ascii', 'ignore').decode('ascii')
    slug = ''.join(c if c.isalnum() else '_' for c in normalized.lower())
    slug = '_'.join(s for s in slug.split('_') if s)
    return slug[:max_len] or 'receita'


def _fmt_brl(value):
    """Formata um valor em reais (R$ 1.234,56). Valores muito pequenos ganham 4 decimais."""
    if not value:
        return 'R$ 0,00'
    value = float(value)
    decimals = 4 if 0 < value < 0.10 else 2
    s = f'{value:,.{decimals}f}'
    return 'R$ ' + s.replace(',', 'X').replace('.', ',').replace('X', '.')


@bp.app_template_filter('brl')
def brl_filter(value):
    return _fmt_brl(value)


def _items_label(count):
    """Rótulo de contagem com plural correto: '1 item' / '3 itens'."""
    return f'{count} item' + ('s' if count != 1 else '')


# ================= LISTA DE COMPRAS (núcleo) =================

def _category_sort_key(category_name):
    category = IngredientCategory.query.filter_by(name=category_name).first()
    if category:
        return (0, category.display_order, category.name)
    return (1, 0, '')


def _group_items_by_category(items):
    """Agrupa uma lista de itens pela categoria do ingrediente, na ordem do mercado."""
    groups = {}
    for item in items:
        groups.setdefault(item['category'], []).append(item)
    ordered = sorted(groups.items(), key=lambda kv: _category_sort_key(kv[0]))
    return ordered


def _build_shopping_list(mode='restock', recipe_id=None):
    """Monta a lista de compras em dois modos.

    - 'recipe': itens faltantes de uma receita específica;
    - 'restock': todos os ingredientes ativos abaixo do estoque mínimo.
    Retorna dict com título, grupos por categoria, contagem e custo total.
    """
    items = []
    title = 'Lista de Compras'
    subtitle = ''

    if mode == 'recipe' and recipe_id:
        recipe = Recipe.query.get_or_404(recipe_id)
        title = f'Lista de Compras — {recipe.name}'
        subtitle = f'Receita: {recipe.name}'
        available, missing = recipe.check_stock()
        for m in missing:
            price = m['ingredient'].unit_price
            items.append({
                'name': m['ingredient'].name,
                'quantity': m['shortage'],
                'unit': m['ingredient'].unit_symbol,
                'cost': m['shortage'] * price if price else None,
                'inactive': m['reason'] == 'inactive',
                'category': m['ingredient'].category.name if m['ingredient'].category else 'Outros',
            })
    else:
        mode = 'restock'
        title = 'Lista de Compras — Reposição de Estoque'
        subtitle = 'Ingredientes abaixo do estoque mínimo'
        low = [i for i in Ingredient.query.filter_by(is_active=True).order_by(Ingredient.name).all()
               if i.is_low_stock]
        for ing in low:
            price = ing.unit_price
            items.append({
                'name': ing.name,
                'quantity': ing.restock_quantity,
                'unit': ing.unit_symbol,
                'cost': ing.estimated_cost if price else None,
                'inactive': False,
                'category': ing.category.name if ing.category else 'Outros',
            })

    groups = _group_items_by_category(items)
    costs = [i['cost'] for i in items if i['cost'] is not None]
    return {
        'mode': mode,
        'title': title,
        'subtitle': subtitle,
        'groups': groups,
        'items_count': len(items),
        'total_cost': sum(costs) if costs else None,
    }


def _shopping_list_as_text(data):
    """Gera o texto formatado da lista (para copiar ou enviar por e-mail)."""
    lines = [f'🛒 {data["title"]}', '']
    if data['subtitle']:
        lines.append(f'📌 {data["subtitle"]}')
    lines.append(f'🗓️ Gerada em {datetime.now().strftime("%d/%m/%Y %H:%M")}')
    lines.append('')

    for category_name, items in data['groups']:
        lines.append(category_name.upper())
        for item in items:
            line = f'• {item["name"]} — {_fmt_qty(item["quantity"])} {item["unit"]}'
            if item['inactive']:
                line += ' (ingrediente inativo: comprar quantidade total)'
            elif item['cost'] is not None:
                line += f' (~{_fmt_brl(item["cost"])})'
            lines.append(line)
        lines.append('')

    if data['total_cost'] is not None:
        lines.append(f'💰 Custo estimado total: {_fmt_brl(data["total_cost"])}')
        lines.append('')
    lines.append('— Enviado por SIGerE')
    return '\n'.join(lines)


# ================= INGREDIENTS =================

@bp.route('/ingredients')
@login_required
@require_permission('ingredient:read')
def list_ingredients():
    search = request.args.get('name', '')
    query = Ingredient.query
    if search:
        query = query.filter(Ingredient.name.ilike(f'%{search}%'))
    ingredients = query.order_by(Ingredient.name).all()

    # Agrupamento por seção, como corredores de supermercado
    categories = IngredientCategory.query.order_by(
        IngredientCategory.display_order, IngredientCategory.name).all()
    grouped = []
    used_ids = set()
    for category in categories:
        group_items = [i for i in ingredients if i.category_id == category.id]
        if group_items:
            grouped.append((category.name, group_items))
            used_ids.update(i.id for i in group_items)
    others = [i for i in ingredients if i.id not in used_ids]
    if others:
        grouped.append(('Outros', others))

    return render_template('kitchen/ingredients.html', grouped=grouped,
                           total=len(ingredients), search=search)


@bp.route('/ingredients/new', methods=['GET', 'POST'])
@login_required
@require_permission('ingredient:create')
def create_ingredient():
    form = IngredientForm()
    _fill_category_choices(form)
    if form.validate_on_submit():
        ingredient = Ingredient(
            name=form.name.data, unit=form.unit.data,
            category_id=form.category_id.data or None,
            unit_price=form.unit_price.data,
            minimum_stock=form.minimum_stock.data or 0.0,
            is_active=form.is_active.data
        )
        db.session.add(ingredient)
        db.session.commit()
        flash(f'Ingrediente "{ingredient.name}" cadastrado com sucesso.', 'success')
        return redirect(url_for('kitchen.list_ingredients'))
    return render_template('kitchen/ingredient_form.html', form=form, title='Cadastrar Ingrediente')


def _fill_category_choices(form):
    """Popula o select de categorias com a opção 'Sem categoria' (0)."""
    categories = IngredientCategory.query.filter_by(is_active=True).order_by(
        IngredientCategory.display_order, IngredientCategory.name).all()
    form.category_id.choices = [(0, '— Sem categoria —')] + [(c.id, c.name) for c in categories]


@bp.route('/ingredients/<int:ingredient_id>/edit', methods=['GET', 'POST'])
@login_required
@require_permission('ingredient:edit')
def edit_ingredient(ingredient_id):
    ingredient = Ingredient.query.get_or_404(ingredient_id)
    form = IngredientForm(obj=ingredient, obj_id=ingredient.id)
    _fill_category_choices(form)
    if form.validate_on_submit():
        ingredient.name = form.name.data
        ingredient.unit = form.unit.data
        ingredient.category_id = form.category_id.data or None
        ingredient.unit_price = form.unit_price.data
        ingredient.minimum_stock = form.minimum_stock.data or 0.0
        ingredient.is_active = form.is_active.data
        db.session.commit()
        flash(f'Ingrediente "{ingredient.name}" atualizado com sucesso.', 'success')
        return redirect(url_for('kitchen.list_ingredients'))
    return render_template('kitchen/ingredient_form.html', form=form, title='Editar Ingrediente')


@bp.route('/ingredients/<int:ingredient_id>/toggle', methods=['POST'])
@login_required
@require_permission('ingredient:toggle')
def toggle_ingredient(ingredient_id):
    ingredient = Ingredient.query.get_or_404(ingredient_id)
    ingredient.is_active = not ingredient.is_active
    db.session.commit()
    flash(f'Ingrediente {ingredient.name} {"ativado" if ingredient.is_active else "desativado"}.', 'success')
    return redirect(url_for('kitchen.list_ingredients'))


# ================= STOCK CONTROL =================

@bp.route('/stock')
@login_required
@require_permission('stock:read')
def stock():
    ingredients = Ingredient.query.order_by(Ingredient.name).all()
    active_ingredients = [i for i in ingredients if i.is_active]
    low_stock = [i for i in active_ingredients if i.is_low_stock]

    expired, expiring = [], []
    for ing in active_ingredients:
        expired.extend(ing.expired_batches())
        expiring.extend(ing.expiring_batches())

    movements = (StockMovement.query
                 .options(joinedload(StockMovement.ingredient), joinedload(StockMovement.user))
                 .order_by(StockMovement.created_at.desc(), StockMovement.id.desc())
                 .limit(10).all())

    entries_count = StockMovement.query.filter_by(movement_type='in').count()
    exits_count = StockMovement.query.filter_by(movement_type='out').count()
    movements_count = StockMovement.query.count()

    return render_template(
        'kitchen/stock.html',
        ingredients=ingredients,
        low_stock=low_stock,
        movements=movements,
        expired=expired,
        expiring=expiring,
        total_ingredients=len(ingredients),
        active_count=len(active_ingredients),
        entries_count=entries_count,
        exits_count=exits_count,
        movements_count=movements_count
    )


@bp.route('/stock/movements')
@login_required
@require_permission('stock:read')
def stock_movements_history():
    """Histórico completo de movimentações com filtros e paginação."""
    ingredient_id = request.args.get('ingredient', type=int)
    movement_type = request.args.get('type', '')
    page = request.args.get('page', 1, type=int)

    date_from = date_to = None
    try:
        if request.args.get('from'):
            date_from = datetime.strptime(request.args['from'], '%Y-%m-%d').date()
        if request.args.get('to'):
            date_to = datetime.strptime(request.args['to'], '%Y-%m-%d').date()
    except ValueError:
        flash('Período inválido. Use o seletor de datas.', 'warning')

    query = (StockMovement.query
             .options(joinedload(StockMovement.ingredient), joinedload(StockMovement.user)))
    if ingredient_id:
        query = query.filter(StockMovement.ingredient_id == ingredient_id)
    if movement_type in ('in', 'out'):
        query = query.filter(StockMovement.movement_type == movement_type)
    if date_from:
        query = query.filter(StockMovement.created_at >= datetime.combine(date_from, datetime.min.time()))
    if date_to:
        query = query.filter(StockMovement.created_at <= datetime.combine(date_to, datetime.max.time()))

    pagination = (query.order_by(StockMovement.created_at.desc(), StockMovement.id.desc())
                  .paginate(page=page, per_page=30, error_out=False))

    # Janela de páginas exibida na paginação (máx. 9 botões)
    pages_to_show = []
    if pagination.pages <= 9:
        pages_to_show = list(range(1, pagination.pages + 1))
    else:
        start = max(1, pagination.page - 3)
        end = min(pagination.pages, pagination.page + 3)
        pages_to_show = list(range(start, end + 1))

    filter_params = {}
    if ingredient_id:
        filter_params['ingredient'] = ingredient_id
    if movement_type in ('in', 'out'):
        filter_params['type'] = movement_type
    if date_from:
        filter_params['from'] = date_from.isoformat()
    if date_to:
        filter_params['to'] = date_to.isoformat()

    ingredients = Ingredient.query.order_by(Ingredient.name).all()
    return render_template(
        'kitchen/stock_movements.html',
        pagination=pagination,
        pages_to_show=pages_to_show,
        ingredients=ingredients,
        filter_params=filter_params,
        filter_ingredient=ingredient_id,
        filter_type=movement_type,
        filter_from=request.args.get('from', ''),
        filter_to=request.args.get('to', '')
    )


@bp.route('/stock/movement/new', methods=['GET', 'POST'])
@login_required
@require_permission('stock:movement')
def create_movement():
    form = StockMovementForm()
    # Apenas ingredientes ativos podem ser movimentados
    form.ingredient.choices = [
        (i.id, f'{i.name} ({i.unit_label})') for i in Ingredient.query.filter_by(is_active=True).order_by(Ingredient.name).all()
    ]

    preselect = request.args.get('ingredient', type=int)
    if request.method == 'GET' and preselect:
        form.ingredient.data = preselect

    if form.validate_on_submit():
        ingredient = Ingredient.query.get(form.ingredient.data)
        if not ingredient:
            abort(404)

        quantity = form.quantity.data
        if form.movement_type.data == 'out' and quantity > ingredient.stock_quantity:
            form.quantity.errors.append(
                f'Saída maior que o estoque atual ({_fmt_qty(ingredient.stock_quantity)} {ingredient.unit_symbol}).'
            )
        else:
            if form.movement_type.data == 'in':
                ingredient.stock_quantity += quantity
            else:
                ingredient.stock_quantity -= quantity

            movement = StockMovement(
                ingredient_id=ingredient.id,
                user_id=current_user.id,
                quantity=quantity,
                movement_type=form.movement_type.data,
                note=form.note.data
            )
            db.session.add(movement)
            db.session.commit()

            verb = 'Entrada' if form.movement_type.data == 'in' else 'Saída'
            flash(f'{verb} de {_fmt_qty(quantity)} {ingredient.unit_symbol} de "{ingredient.name}" registrada. '
                  f'Estoque atual: {_fmt_qty(ingredient.stock_quantity)} {ingredient.unit_symbol}.', 'success')
            return redirect(url_for('kitchen.stock'))

    return render_template('kitchen/stock_movement_form.html', form=form)


# ================= RECIPES =================

def _recipe_query():
    """Carrega receitas com ingredientes e estoque para evitar N+1 queries."""
    return (Recipe.query
            .options(selectinload(Recipe.ingredients).joinedload(RecipeIngredient.ingredient))
            .order_by(Recipe.name))


def _parse_recipe_items():
    """Lê as linhas dinâmicas (ingrediente + quantidade) do formulário de receita.

    Retorna (items, error). items é uma lista de dicts {ingredient, quantity};
    ingredientes repetidos têm as quantidades somadas.
    """
    ingredient_ids = request.form.getlist('ingredient_id')
    quantities = request.form.getlist('quantity')

    items, errors = [], []
    merged = {}
    order = []

    for ing_id, qty in zip(ingredient_ids, quantities):
        ing_id = (ing_id or '').strip()
        if not ing_id:
            errors.append('Selecione um ingrediente em todas as linhas da lista.')
            continue
        try:
            ing_id = int(ing_id)
        except ValueError:
            errors.append('Ingrediente inválido na lista.')
            continue

        try:
            qty = float((qty or '').replace(',', '.'))
        except ValueError:
            errors.append('Informe uma quantidade numérica válida para todos os ingredientes.')
            continue
        if qty <= 0:
            errors.append('As quantidades devem ser maiores que zero.')
            continue

        if ing_id in merged:
            merged[ing_id]['quantity'] += qty
        else:
            order.append(ing_id)
            merged[ing_id] = {'id': ing_id, 'quantity': qty}

    if not errors and not order:
        errors.append('Adicione pelo menos um ingrediente à receita.')

    if errors:
        return [], ' '.join(dict.fromkeys(errors))

    for entry in order:
        ingredient = Ingredient.query.get(entry)
        if not ingredient:
            return [], 'Um dos ingredientes selecionados não existe.'
        items.append({'ingredient': ingredient, 'quantity': merged[entry]['quantity']})

    return items, None


@bp.route('/recipes')
@login_required
@require_permission('recipe:read')
def list_recipes():
    recipes = _recipe_query().all()
    availability = {r.id: r.check_stock() for r in recipes}
    return render_template('kitchen/recipes.html', recipes=recipes, availability=availability)


@bp.route('/recipes/new', methods=['GET', 'POST'])
@login_required
@require_permission('recipe:create')
def create_recipe():
    form = RecipeForm()
    if form.validate_on_submit():
        items, error = _parse_recipe_items()
        if error:
            flash(error, 'danger')
        else:
            recipe = Recipe(
                name=form.name.data, description=form.description.data,
                servings=form.servings.data or 1,
                prep_time_minutes=form.prep_time_minutes.data,
                is_active=form.is_active.data, created_by=current_user.id
            )
            for item in items:
                recipe.ingredients.append(RecipeIngredient(
                    ingredient_id=item['ingredient'].id, quantity=item['quantity']
                ))
            photo_file = form.photo.data
            if photo_file and photo_file.filename:
                recipe.photo = _save_recipe_photo(photo_file)
            db.session.add(recipe)
            db.session.commit()
            flash(f'Receita "{recipe.name}" cadastrada com sucesso.', 'success')
            return redirect(url_for('kitchen.recipe_detail', recipe_id=recipe.id))

    ingredients = Ingredient.query.filter_by(is_active=True).order_by(Ingredient.name).all()
    return render_template('kitchen/recipe_form.html', form=form, ingredients=ingredients, links=[], title='Cadastrar Receita')


@bp.route('/recipes/<int:recipe_id>')
@login_required
@require_permission('recipe:read')
def recipe_detail(recipe_id):
    recipe = _recipe_query().filter_by(id=recipe_id).first_or_404()
    available, missing = recipe.check_stock()
    missing_map = {m['ingredient'].id: m for m in missing}
    return render_template(
        'kitchen/recipe_detail.html',
        recipe=recipe, available=available, missing=missing, missing_map=missing_map
    )


@bp.route('/recipes/<int:recipe_id>/edit', methods=['GET', 'POST'])
@login_required
@require_permission('recipe:edit')
def edit_recipe(recipe_id):
    recipe = Recipe.query.get_or_404(recipe_id)
    form = RecipeForm(obj=recipe, obj_id=recipe.id)

    if form.validate_on_submit():
        items, error = _parse_recipe_items()
        if error:
            flash(error, 'danger')
        else:
            recipe.name = form.name.data
            recipe.description = form.description.data
            recipe.servings = form.servings.data or 1
            recipe.prep_time_minutes = form.prep_time_minutes.data
            recipe.is_active = form.is_active.data
            recipe.ingredients.clear()
            # Emite os DELETEs dos vínculos antigos antes dos novos INSERTs — sem isso,
            # manter um ingrediente que já estava na receita viola o índice único.
            db.session.flush()
            for item in items:
                recipe.ingredients.append(RecipeIngredient(
                    ingredient_id=item['ingredient'].id, quantity=item['quantity']
                ))
            photo_file = form.photo.data
            if photo_file and photo_file.filename:
                new_photo = _save_recipe_photo(photo_file)
                if new_photo:
                    _delete_recipe_photo(recipe.photo)
                    recipe.photo = new_photo
            db.session.commit()
            flash(f'Receita "{recipe.name}" atualizada com sucesso.', 'success')
            return redirect(url_for('kitchen.recipe_detail', recipe_id=recipe.id))

    ingredients = Ingredient.query.filter_by(is_active=True).order_by(Ingredient.name).all()
    links = recipe.ingredients
    return render_template('kitchen/recipe_form.html', form=form, ingredients=ingredients, links=links,
                           title='Editar Receita', obj_id=recipe.id, recipe_photo=recipe.photo)


@bp.route('/recipes/<int:recipe_id>/toggle', methods=['POST'])
@login_required
@require_permission('recipe:toggle')
def toggle_recipe(recipe_id):
    recipe = Recipe.query.get_or_404(recipe_id)
    recipe.is_active = not recipe.is_active
    db.session.commit()
    flash(f'Receita {recipe.name} {"ativada" if recipe.is_active else "desativada"}.', 'success')
    return redirect(url_for('kitchen.list_recipes'))


@bp.route('/recipes/<int:recipe_id>/prepare', methods=['POST'])
@login_required
@require_permission('recipe:prepare')
def prepare_recipe(recipe_id):
    """Baixa do estoque os ingredientes usados pela receita (preparo)."""
    recipe = _recipe_query().filter_by(id=recipe_id).first_or_404()

    available, missing = recipe.check_stock()
    if not available:
        details = '; '.join(
            f"{m['ingredient'].name} (falta {_fmt_qty(m['shortage'])} {m['ingredient'].unit_symbol})"
            for m in missing
        )
        flash(f'Não foi possível preparar "{recipe.name}". Ingredientes insuficientes: {details}.', 'danger')
        return redirect(url_for('kitchen.recipe_detail', recipe_id=recipe.id))

    for link in recipe.ingredients:
        link.ingredient.stock_quantity -= link.quantity
        db.session.add(StockMovement(
            ingredient_id=link.ingredient.id,
            user_id=current_user.id,
            quantity=link.quantity,
            movement_type='out',
            note=f'Preparo da receita "{recipe.name}"',
            recipe_id=recipe.id
        ))

    db.session.commit()
    flash(f'Preparo da receita "{recipe.name}" registrado: {len(recipe.ingredients)} ingrediente(s) baixado(s) do estoque.', 'success')
    return redirect(url_for('kitchen.recipe_detail', recipe_id=recipe.id))


# ================= SHOPPING LIST EXPORT =================

def _pdf_safe(text):
    """Converte para latin-1 (fontes nativas do fpdf2), trocando caracteres fora do intervalo."""
    text = str(text).replace('\u2014', '-').replace('\u2013', '-')
    return text.encode('latin-1', errors='replace').decode('latin-1')


# ================= LISTA DE COMPRAS EM PDF =================

class _ShoppingListPDF(FPDF):
    """PDF da lista de compras com layout moderno.

    Faixa de cabeçalho na cor da marca, tabela zebrada, chip de total
    e rodapé com paginação.
    """
    NAVY = (0, 42, 72)        # cor da marca (sidebar)
    SLATE = (30, 41, 59)
    MUTED = (100, 116, 139)
    ZEBRA = (241, 245, 249)
    ACCENT = (5, 150, 105)
    AMBER_BG = (254, 249, 231)
    LINE = (226, 232, 240)

    def __init__(self, title, items_count, generated_at):
        super().__init__(orientation='P', unit='mm', format='A4')
        self._title = title
        self._items_count = items_count
        self._generated_at = generated_at
        self.alias_nb_pages()
        self.set_auto_page_break(auto=True, margin=22)
        self.set_margins(14, 14, 14)
        self.add_page()

    def header(self):
        self.set_fill_color(*self.NAVY)
        self.rect(0, 0, 210, 26, style='F')
        self.set_y(7)
        self.set_font('Helvetica', 'B', 17)
        self.set_text_color(255, 255, 255)
        self.cell(120, 10, 'Lista de Compras')
        self.set_font('Helvetica', '', 11)
        self.cell(0, 10, 'SIGerE', align='R')

        self.set_y(31)
        self.set_font('Helvetica', 'B', 13.5)
        self.set_text_color(*self.SLATE)
        self.cell(0, 8, _pdf_safe(self._title)[:70])

        self.set_y(38.5)
        self.set_font('Helvetica', '', 9)
        self.set_text_color(*self.MUTED)
        self.cell(0, 5, _pdf_safe(
            f'Gerada em {self._generated_at}   ·   {_items_label(self._items_count)} a comprar'
        ))
        self.set_y(48)

    def footer(self):
        self.set_y(-15)
        self.set_line_width(0.2)
        self.set_draw_color(*self.LINE)
        self.line(14, self.get_y(), 196, self.get_y())
        self.set_font('Helvetica', '', 8)
        self.set_text_color(148, 163, 184)
        self.cell(91, 7, 'Gerado por SIGerE', align='L')
        self.cell(91, 7, f'Página {self.page_no()} de {{nb}}', align='R')


def _shopping_list_pdf_response(data):
    """Gera o PDF moderno da lista de compras (por categoria, com custo estimado)."""
    pdf = _ShoppingListPDF(
        data['title'], data['items_count'], datetime.now().strftime('%d/%m/%Y %H:%M')
    )

    col_widths = [82, 42, 28, 30]

    # Cabeçalho da tabela
    pdf.set_fill_color(*_ShoppingListPDF.NAVY)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font('Helvetica', 'B', 9.5)
    for width, title in zip(col_widths, ['Ingrediente', 'Quantidade', 'Unidade', 'Custo Estimado']):
        pdf.cell(width, 9, _pdf_safe(title), align='C', fill=True)
    pdf.ln()

    for category_name, items in data['groups']:
        # faixa de seção (categoria)
        pdf.set_font('Helvetica', 'B', 9)
        pdf.set_fill_color(*_ShoppingListPDF.ZEBRA)
        pdf.set_text_color(*_ShoppingListPDF.SLATE)
        pdf.cell(182, 7, _pdf_safe(category_name.upper()), align='L', fill=True)
        pdf.ln()

        for index, item in enumerate(items):
            inactive = item['inactive']
            if inactive:
                pdf.set_fill_color(*_ShoppingListPDF.AMBER_BG)
            elif index % 2 == 0:
                pdf.set_fill_color(255, 255, 255)
            else:
                pdf.set_fill_color(248, 250, 252)

            name = _pdf_safe(item['name'] + ('  *' if inactive else ''))
            if len(name) > 46:
                name = name[:43].rstrip() + '...'

            pdf.set_font('Helvetica', '', 10)
            pdf.set_text_color(*_ShoppingListPDF.SLATE)
            pdf.cell(col_widths[0], 9, name, align='L', fill=True)
            pdf.set_font('Helvetica', 'B', 10)
            pdf.set_text_color(15, 23, 42)
            pdf.cell(col_widths[1], 9, _pdf_safe(_fmt_qty(item['quantity'])), align='C', fill=True)
            pdf.set_font('Helvetica', '', 10)
            pdf.set_text_color(*_ShoppingListPDF.MUTED)
            pdf.cell(col_widths[2], 9, _pdf_safe(item['unit']), align='C', fill=True)
            pdf.set_font('Helvetica', '', 10)
            pdf.cell(col_widths[3], 9, _pdf_safe(_fmt_brl(item['cost']) if item['cost'] is not None else '-'),
                     align='R', fill=True)
            pdf.ln()

    # Chip com o total de itens + custo estimado
    pdf.ln(4)
    chip_y = pdf.get_y()
    chip_text = _pdf_safe(f"{_items_label(data['items_count'])} para comprar")
    if data['total_cost'] is not None:
        chip_text += _pdf_safe(f"  ·  {_fmt_brl(data['total_cost'])}")
    pdf.set_fill_color(*_ShoppingListPDF.ACCENT)
    pdf.rect(14, chip_y, 78, 8.5, style='F', round_corners=True, corner_radius=4.25)
    pdf.set_xy(14, chip_y)
    pdf.set_font('Helvetica', 'B', 9)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(78, 8.5, chip_text, align='C')
    pdf.set_y(chip_y + 12)

    # Caixa de observações
    box_y = pdf.get_y()
    pdf.set_fill_color(248, 250, 252)
    pdf.set_draw_color(*_ShoppingListPDF.LINE)
    pdf.rect(14, box_y, 182, 17, style='DF', round_corners=True, corner_radius=3)
    pdf.set_xy(18, box_y + 3.5)
    pdf.set_font('Helvetica', 'I', 8.5)
    pdf.set_text_color(*_ShoppingListPDF.MUTED)
    pdf.multi_cell(174, 4.5, _pdf_safe(
        '* Ingrediente inativo no cadastro: compre a quantidade total usada pela receita. '
        'Modo reposição: itens abaixo do estoque mínimo, para recompor o nível desejado. '
        'Custos estimados com base no preço de compra cadastrado por unidade.'
    ))

    response = make_response(bytes(pdf.output()))
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f"attachment; filename=lista_compras_{_slugify(data['title'])}.pdf"
    return response


def _resolve_shopping_args():
    """Lê recipe_id/restock da query string e monta a lista (com validação)."""
    recipe_id = request.args.get('recipe_id', type=int)
    if recipe_id:
        recipe = Recipe.query.get(recipe_id)
        if not recipe:
            abort(404)
        data = _build_shopping_list('recipe', recipe_id)
        if not data['items_count']:
            flash('Todos os ingredientes desta receita estão em estoque — não há itens para comprar.', 'info')
            return None
        return data
    return _build_shopping_list('restock')


@bp.route('/shopping-list')
@login_required
@require_permission('stock:read')
def shopping_list():
    """Lista de compras consolidada: por receita ou reposição de estoque mínimo."""
    data = _resolve_shopping_args()
    if data is None:
        return redirect(url_for('kitchen.stock'))
    return render_template(
        'kitchen/shopping_list.html',
        data=data,
        recipe_id=request.args.get('recipe_id', type=int),
        text_preview=_shopping_list_as_text(data),
        email_enabled=bool(current_app.config.get('MAIL_HOST')),
    )


@bp.route('/shopping-list.pdf')
@login_required
@require_permission('stock:read')
def shopping_list_pdf():
    data = _resolve_shopping_args()
    if data is None:
        return redirect(url_for('kitchen.stock'))
    return _shopping_list_pdf_response(data)


@bp.route('/shopping-list/text')
@login_required
@require_permission('stock:read')
def shopping_list_text():
    data = _resolve_shopping_args()
    if data is None:
        return redirect(url_for('kitchen.stock'))
    return render_template(
        'kitchen/shopping_list_text.html',
        data=data,
        recipe_id=request.args.get('recipe_id', type=int),
        text=_shopping_list_as_text(data),
        email_enabled=bool(current_app.config.get('MAIL_HOST')),
    )


@bp.route('/shopping-list/email', methods=['POST'])
@login_required
@require_permission('stock:read')
def shopping_list_email():
    """Envia a lista de compras por e-mail usando o SMTP configurado no sistema."""
    recipients = [r.strip() for r in (request.form.get('recipients') or '').replace(';', ',').split(',') if r.strip()]
    subject = (request.form.get('subject') or '').strip() or 'Lista de Compras — SIGerE'

    if not recipients:
        flash('Informe pelo menos um e-mail de destino.', 'danger')
        return redirect(url_for('kitchen.shopping_list_text'))

    if not current_app.config.get('MAIL_HOST'):
        flash('Envio por e-mail não configurado: defina MAIL_HOST, MAIL_USER e MAIL_PASSWORD nas variáveis de ambiente.', 'danger')
        return redirect(url_for('kitchen.shopping_list_text'))

    data = _resolve_shopping_args()
    if data is None:
        return redirect(url_for('kitchen.stock'))

    try:
        message = EmailMessage()
        message['Subject'] = subject
        message['From'] = current_app.config.get('MAIL_FROM') or current_app.config.get('MAIL_USER')
        message['To'] = ', '.join(recipients)
        message.set_content(_shopping_list_as_text(data))

        with smtplib.SMTP(current_app.config['MAIL_HOST'], current_app.config['MAIL_PORT'], timeout=20) as server:
            if current_app.config.get('MAIL_USE_TLS'):
                server.starttls()
            if current_app.config.get('MAIL_USER'):
                server.login(current_app.config['MAIL_USER'], current_app.config['MAIL_PASSWORD'])
            server.send_message(message)

        flash(f'Lista enviada com sucesso para {", ".join(recipients)}.', 'success')
    except Exception as exc:
        flash(f'Falha ao enviar o e-mail: {exc}', 'danger')
    return redirect(url_for('kitchen.shopping_list_text'))


# ================= DASHBOARD DA COZINHA =================

@bp.route('/')
@login_required
@require_permission('stock:read')
def dashboard():
    since = datetime.now() - timedelta(days=30)

    ingredients = Ingredient.query.all()
    active = [i for i in ingredients if i.is_active]
    low = [i for i in active if i.is_low_stock]
    expiring, expired = [], []
    for ing in active:
        expired.extend(ing.expired_batches())
        expiring.extend(ing.expiring_batches())

    # Gráfico 1: valor do estoque por categoria (donut)
    value_by_category = {}
    for ing in active:
        value = (ing.stock_quantity or 0) * (ing.unit_price or 0)
        if value > 0:
            name = ing.category.name if ing.category else 'Outros'
            value_by_category[name] = value_by_category.get(name, 0) + value
    stock_value_labels = sorted(value_by_category, key=value_by_category.get, reverse=True)
    stock_value_data = [round(value_by_category[k], 2) for k in stock_value_labels]
    total_stock_value = round(sum(stock_value_data), 2)

    # Gráfico 2: evolução de entradas e saídas (últimos 30 dias)
    movements = StockMovement.query.filter(StockMovement.created_at >= since).all()
    days = [(datetime.now() - timedelta(days=i)).date() for i in range(29, -1, -1)]
    day_labels = [d.strftime('%d/%m') for d in days]
    entries_series, exits_series = [0.0] * 30, [0.0] * 30
    for m in movements:
        day = m.created_at.date()
        if day in days:
            idx = (datetime.now().date() - day).days
            series = entries_series if m.movement_type == 'in' else exits_series
            series[29 - idx] += m.quantity

    # Gráfico 3: top ingredientes consumidos (30 dias)
    consumption = {}
    for m in movements:
        if m.movement_type == 'out' and m.ingredient:
            consumption[m.ingredient] = consumption.get(m.ingredient, 0.0) + m.quantity
    top_consumed = sorted(consumption.items(), key=lambda kv: kv[1], reverse=True)[:8]
    consumed_labels = [i.name for i, _ in top_consumed]
    consumed_data = [round(q, 2) for _, q in top_consumed]

    # Gráfico 4: receitas mais preparadas (contagem de baixas vinculadas)
    prep_counts = dict(
        db.session.query(Recipe.name, func.count(StockMovement.id))
        .join(StockMovement, StockMovement.recipe_id == Recipe.id)
        .group_by(Recipe.id).order_by(func.count(StockMovement.id).desc()).limit(8).all()
    )
    prep_labels = list(prep_counts.keys())
    prep_data = list(prep_counts.values())

    return render_template(
        'kitchen/dashboard.html',
        total_ingredients=len(ingredients),
        active_count=len(active),
        low_stock=low,
        expiring=expiring,
        expired=expired,
        total_stock_value=total_stock_value,
        movements_30=len(movements),
        chart_stock_value_labels=stock_value_labels,
        chart_stock_value_data=stock_value_data,
        chart_day_labels=day_labels,
        chart_entries=entries_series,
        chart_exits=exits_series,
        chart_consumed_labels=consumed_labels,
        chart_consumed_data=consumed_data,
        chart_prep_labels=prep_labels,
        chart_prep_data=prep_data,
    )


# ================= CATEGORIAS DE INGREDIENTES =================

@bp.route('/categories')
@login_required
@require_permission('ingredient:read')
def list_categories():
    categories = IngredientCategory.query.order_by(
        IngredientCategory.display_order, IngredientCategory.name).all()
    counts = dict(db.session.query(Ingredient.category_id, func.count(Ingredient.id))
                  .group_by(Ingredient.category_id).all())
    return render_template('kitchen/categories.html', categories=categories, counts=counts)


@bp.route('/categories/create', methods=['GET', 'POST'])
@login_required
@require_permission('ingredient:create')
def create_category():
    form = IngredientCategoryForm()
    if form.validate_on_submit():
        category = IngredientCategory(name=form.name.data,
                                      display_order=form.display_order.data or 0,
                                      is_active=form.is_active.data)
        db.session.add(category)
        db.session.commit()
        flash(f'Categoria "{category.name}" criada com sucesso.', 'success')
        return redirect(url_for('kitchen.list_categories'))
    return render_template('kitchen/category_form.html', form=form, title='Nova Categoria')


@bp.route('/categories/<int:category_id>/edit', methods=['GET', 'POST'])
@login_required
@require_permission('ingredient:edit')
def edit_category(category_id):
    category = IngredientCategory.query.get_or_404(category_id)
    form = IngredientCategoryForm(obj=category, obj_id=category.id)
    if form.validate_on_submit():
        category.name = form.name.data
        category.display_order = form.display_order.data or 0
        category.is_active = form.is_active.data
        db.session.commit()
        flash(f'Categoria "{category.name}" atualizada com sucesso.', 'success')
        return redirect(url_for('kitchen.list_categories'))
    return render_template('kitchen/category_form.html', form=form, title='Editar Categoria')


@bp.route('/categories/<int:category_id>/toggle', methods=['POST'])
@login_required
@require_permission('ingredient:toggle')
def toggle_category(category_id):
    category = IngredientCategory.query.get_or_404(category_id)
    category.is_active = not category.is_active
    db.session.commit()
    flash(f'Categoria {category.name} {"ativada" if category.is_active else "desativada"}.', 'success')
    return redirect(url_for('kitchen.list_categories'))


# ================= LOTES E VALIDADE =================

@bp.route('/ingredients/<int:ingredient_id>/batches', methods=['GET', 'POST'])
@login_required
def ingredient_batches(ingredient_id):
    ingredient = Ingredient.query.get_or_404(ingredient_id)
    form = StockBatchForm()

    if request.method == 'POST':
        if not current_user.has_permission('stock:movement'):
            abort(403)
        if form.validate_on_submit():
            batch = StockBatch(ingredient_id=ingredient.id, quantity=form.quantity.data,
                               expiry_date=form.expiry_date.data, note=form.note.data)
            db.session.add(batch)
            db.session.commit()
            flash('Lote registrado com sucesso.', 'success')
            return redirect(url_for('kitchen.ingredient_batches', ingredient_id=ingredient.id))

    batches = StockBatch.query.filter_by(ingredient_id=ingredient.id).order_by(
        StockBatch.expiry_date.asc().nullslast(), StockBatch.created_at.desc()).all()
    today = date.today()
    for b in batches:
        if b.expiry_date:
            b.days_left = (b.expiry_date - today).days
    return render_template('kitchen/ingredient_batches.html', ingredient=ingredient,
                           batches=batches, form=form)


@bp.route('/batches/<int:batch_id>/delete', methods=['POST'])
@login_required
@require_permission('stock:movement')
def delete_batch(batch_id):
    batch = StockBatch.query.get_or_404(batch_id)
    ingredient_id = batch.ingredient_id
    db.session.delete(batch)
    db.session.commit()
    flash('Lote removido.', 'info')
    return redirect(url_for('kitchen.ingredient_batches', ingredient_id=ingredient_id))


# ================= RELATÓRIO DE CONSUMO =================

@bp.route('/reports/consumption')
@login_required
@require_permission('stock:read')
def consumption_report():
    try:
        date_from = datetime.strptime(request.args.get('from', ''), '%Y-%m-%d').date()
    except ValueError:
        date_from = (datetime.now() - timedelta(days=30)).date()
    try:
        date_to = datetime.strptime(request.args.get('to', ''), '%Y-%m-%d').date()
    except ValueError:
        date_to = datetime.now().date()
    if date_from > date_to:
        date_from, date_to = date_to, date_from

    start = datetime.combine(date_from, datetime.min.time())
    end = datetime.combine(date_to, datetime.max.time())

    movements = (StockMovement.query
                 .options(joinedload(StockMovement.ingredient))
                 .filter(StockMovement.movement_type == 'out',
                         StockMovement.created_at >= start,
                         StockMovement.created_at <= end).all())

    by_ingredient = {}
    cost_total = 0.0
    for m in movements:
        ing = m.ingredient
        if not ing:
            continue
        entry = by_ingredient.setdefault(ing, {'quantity': 0.0, 'cost': 0.0})
        entry['quantity'] += m.quantity
        if ing.unit_price:
            entry['cost'] += m.quantity * ing.unit_price
            cost_total += m.quantity * ing.unit_price

    ranked = sorted(by_ingredient.items(), key=lambda kv: kv[1]['quantity'], reverse=True)
    chart_labels = [ing.name for ing, _ in ranked[:10]]
    chart_data = [round(v['quantity'], 2) for _, v in ranked[:10]]

    # Tendência semanal de custo consumido
    weeks = {}
    for m in movements:
        ing = m.ingredient
        if not ing:
            continue
        week_start = m.created_at.date() - timedelta(days=m.created_at.weekday())
        value = m.quantity * (ing.unit_price or 0)
        weeks[week_start] = weeks.get(week_start, 0) + value
    week_labels = [w.strftime('%d/%m') for w in sorted(weeks)]
    week_costs = [round(weeks[w], 2) for w in sorted(weeks)]

    return render_template(
        'kitchen/consumption_report.html',
        date_from=date_from, date_to=date_to,
        ranked=ranked,
        cost_total=cost_total,
        chart_labels=chart_labels, chart_data=chart_data,
        week_labels=week_labels, week_costs=week_costs,
    )


# ================= VERSÃO PARA IMPRESSÃO =================

@bp.route('/recipes/<int:recipe_id>/print')
@login_required
@require_permission('recipe:read')
def print_recipe(recipe_id):
    recipe = _recipe_query().filter_by(id=recipe_id).first_or_404()
    available, missing = recipe.check_stock()
    return render_template('kitchen/recipe_print.html', recipe=recipe,
                           available=available, missing_count=len(missing))
