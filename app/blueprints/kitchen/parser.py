"""Parser de Fichas Técnicas Operacionais (DOCX) para o módulo de Cozinha.

Extrai, sem dependências externas (zipfile + XML), a estrutura padrão dos
documentos enviados — o modelo em tabelas da Ficha Técnica Operacional:

    ┌─────────────────────────────────────────────────────────┐
    │ Nome da preparação                                      │ ← 1ª linha mesclada
    │ Equipamentos: <valor na mesma célula>                   │
    │ Utensílios: <valor na mesma célula>                     │
    │ Tempo de Preparo: <valor>  │  Rendimento: <valor>       │
    │ Ingredientes │ Especificações │ Quantidade │ Unidade    │ ← cabeçalho de insumos
    │ ... linhas de insumos (linhas vazias separam grupos) ...│
    └─────────────────────────────────────────────────────────┘
    Modo de Preparo:
    <passos em parágrafos, numerados ou não>
    ┌─────────────────────────────────────────────────────────┐
    │ Observações técnicas: <valor>                           │
    │ Alergênicos           <valor>                           │
    │ Referências           <valor>                           │
    └─────────────────────────────────────────────────────────┘

No cabeçalho, o valor vem logo após o rótulo na própria célula. Nas notas
técnicas, o valor pode vir após o rótulo ou na linha seguinte da tabela.
"""
import re
import unicodedata
import zipfile

from defusedxml.ElementTree import fromstring

W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'

# Rótulos do cabeçalho da tabela principal: "Rótulo: valor" na mesma célula.
_HEADER_LABEL_RE = re.compile(
    r'^\s*(equipamentos|utens[íi]lios|tempo\s+de\s+preparo|rendimento)\s*:?\s*(.*)$',
    re.IGNORECASE,
)
_HEADER_KEYS = {
    'equipamentos': 'equipamentos',
    'utensilios': 'utensilios',
    'tempo de preparo': 'tempo_preparo',
    'rendimento': 'rendimento',
}

# Rótulos da tabela de notas técnicas (valor após o rótulo ou na linha seguinte).
_NOTA_LABEL_RE = re.compile(
    r'^\s*(observa[çc][õo]es\s*t[ée]cnicas?|alerg[êe]nicos?|'
    r'refer[êe]ncias?(?:\s*bibliogr[áa]ficas?)?)\s*:?\s*(.*)$',
    re.IGNORECASE,
)

_MODO_LABEL_RE = re.compile(r'^\s*modo\s+de\s+preparo\s*:?\s*(.*)$', re.IGNORECASE)

_STEP_NUMBER_RE = re.compile(r'^\s*\d+\s*[\.\)\-–]\s*')


class FichaParseError(Exception):
    """Arquivo enviado não é uma Ficha Técnica Operacional válida."""


def _strip_accents(text):
    return ''.join(c for c in unicodedata.normalize('NFD', text)
                   if unicodedata.category(c) != 'Mn')


def _paragraph_text(par):
    """Texto do parágrafo preservando <w:br/> como quebra de linha."""
    parts = []
    for node in par.iter():
        if node.tag == W + 't':
            parts.append(node.text or '')
        elif node.tag in (W + 'br', W + 'cr'):
            parts.append('\n')
        elif node.tag == W + 'tab':
            parts.append(' ')
    return ''.join(parts)


def _cell_texts(row):
    """Textos das células da linha, com os parágrafos de cada célula unidos."""
    cells = []
    for cell in row.findall(W + 'tc'):
        text = ' '.join(
            re.sub(r'\s+', ' ', _paragraph_text(p)).strip()
            for p in cell.findall(W + 'p')
        ).strip()
        cells.append(text)
    return cells


def _read_blocks(doc_xml):
    """Blocos do corpo do documento na ordem original: ('p', texto) para
    parágrafos e ('table', linhas) para tabelas. Linhas de tabela sem nenhum
    conteúdo são descartadas."""
    try:
        root = fromstring(doc_xml)
    except Exception as exc:
        raise FichaParseError(f'XML do DOCX inválido: {exc}')
    body = root.find(W + 'body')
    if body is None:
        raise FichaParseError('Documento DOCX sem corpo de texto.')

    blocks = []
    for el in body:
        if el.tag == W + 'p':
            text = re.sub(r'[ \t]+', ' ', _paragraph_text(el)).strip()
            if text:
                blocks.append(('p', text))
        elif el.tag == W + 'tbl':
            rows = [_cell_texts(row) for row in el.findall(W + 'tr')]
            rows = [r for r in rows if any(c for c in r)]
            if rows:
                blocks.append(('table', rows))
    return blocks


def _clean_inline(value):
    """Colapsa espaços de um valor extraído do documento."""
    return re.sub(r'\s+', ' ', value or '').strip()


def _is_ingredients_header(row):
    """True na linha de cabeçalho da tabela de insumos ('Ingredientes...')."""
    return bool(row) and _strip_accents(row[0]).strip().lower() == 'ingredientes'


def _parse_quantity(raw):
    """Primeiro número do texto da quantidade ('400', '15 e 3', '2,5')."""
    match = re.search(r'\d+(?:[.,]\d+)?', raw or '')
    if not match:
        return None
    return float(match.group().replace(',', '.'))


def _parse_ingredient_row(cells):
    """Linha da tabela de insumos → dicionário do ingrediente ('Q.B.' e
    quantidade vazia ficam sem valor numérico; unidade '-' significa 'a gosto')."""
    cells = (cells + ['', '', '', ''])[:4]
    name, specification, quantity_raw, unit = (c.strip() for c in cells)
    if not name:
        return None
    return {
        'nome': name,
        'especificacao': specification,
        'quantidade': _parse_quantity(quantity_raw),
        'quantidade_raw': quantity_raw,
        'unidade': '' if unit in ('-', '—') else unit,
    }


def parse_ficha_docx(file_stream):
    """Lê um arquivo DOCX de Ficha Técnica e retorna um dicionário com o
    conteúdo estruturado. Levanta FichaParseError quando o arquivo não segue
    o formato esperado (modelo em tabelas da Ficha Técnica Operacional)."""
    try:
        with zipfile.ZipFile(file_stream) as archive:
            doc_xml = archive.read('word/document.xml')
    except zipfile.BadZipFile:
        raise FichaParseError('O arquivo não é um documento Word (.docx) válido.')
    except KeyError:
        raise FichaParseError('DOCX sem conteúdo de texto (word/document.xml ausente).')

    blocks = _read_blocks(doc_xml)
    tables = [content for kind, content in blocks if kind == 'table']

    # ── Tabela principal: a que contém o cabeçalho de insumos ──
    main_table = next(
        (t for t in tables if any(_is_ingredients_header(r) for r in t)), None)
    if main_table is None:
        raise FichaParseError(
            'Não foi possível localizar a tabela de insumos da Ficha Técnica '
            '(linha "Ingredientes | Especificações | Quantidade | Unidade").')

    fields = {}
    preparation = {'nome': '', 'ingredientes': []}
    in_ingredients = False
    for row in main_table:
        if _is_ingredients_header(row):
            in_ingredients = True
            continue
        if in_ingredients:
            ingredient = _parse_ingredient_row(row)
            if ingredient:
                preparation['ingredientes'].append(ingredient)
            continue
        # Identificação: rótulos com o valor na própria célula; a 1ª linha
        # (sem rótulo) é o nome da preparação.
        labeled = False
        for cell in row:
            match = _HEADER_LABEL_RE.match(cell)
            if not match:
                continue
            labeled = True
            key = _HEADER_KEYS[_strip_accents(match.group(1)).lower()]
            value = _clean_inline(match.group(2))
            if value:
                fields.setdefault(key, value)
        if not labeled and not fields.get('nome'):
            name = _clean_inline(row[0]) if row else ''
            if name:
                fields['nome'] = name
                preparation['nome'] = name
    if not fields.get('nome'):
        raise FichaParseError(
            'Não foi possível localizar o nome da preparação na 1ª linha da ficha.')

    # ── Tabela de notas técnicas e modo de preparo entre as tabelas ──
    main_index = notes_index = None
    notes_table = None
    for index, (kind, content) in enumerate(blocks):
        if kind != 'table':
            continue
        if content is main_table:
            main_index = index
        elif notes_table is None and any(_NOTA_LABEL_RE.match(r[0]) for r in content):
            notes_table = content
            notes_index = index

    steps = []
    for kind, content in blocks[main_index + 1:notes_index if notes_index is not None
                                else len(blocks)]:
        if kind != 'p':
            continue
        match = _MODO_LABEL_RE.match(content)
        step = match.group(1) if match else content
        step = _STEP_NUMBER_RE.sub('', step).strip()
        if step:
            steps.append(step)

    notes = {'observacoes': [], 'alergenicos': [], 'referencias': []}
    if notes_table is not None:
        current = None
        for row in notes_table:
            match = _NOTA_LABEL_RE.match(row[0] if row else '')
            if match:
                label = _strip_accents(match.group(1)).lower()
                if label.startswith('observa'):
                    current = 'observacoes'
                elif label.startswith('alerg'):
                    current = 'alergenicos'
                else:
                    current = 'referencias'
                value = _clean_inline(match.group(2))
                if value:
                    notes[current].append(value)
            elif current:
                value = _clean_inline(' '.join(c for c in row if c))
                if value:
                    notes[current].append(value)

    return {
        'nome': fields.get('nome'),
        'equipamentos': fields.get('equipamentos', ''),
        'utensilios': fields.get('utensilios', ''),
        'tempo_preparo': fields.get('tempo_preparo', ''),
        'rendimento': fields.get('rendimento', ''),
        'preparacoes': [preparation],
        'modo_preparo': steps,
        'observacoes': '\n'.join(notes['observacoes']),
        'alergenicos': '\n'.join(notes['alergenicos']),
        'referencias': '\n'.join(notes['referencias']),
    }
