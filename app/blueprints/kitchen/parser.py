"""Parser de Fichas Técnicas Operacionais (DOCX) para o módulo de Cozinha.

Extrai, sem dependências externas (zipfile + XML), a estrutura padrão dos
documentos enviados:

    Ficha Técnica Operacional
    Nome da Preparação: ... | Equipamentos: ... | Utensílios: ...
    Tempo de Preparo: ... | Rendimento: ...
    1. Insumos            → tabelas "Ingrediente/Especificação/Quantidade/
                             Unidade", uma por preparação ("Para os Bolinhos…")
    2. Modo de Preparo    → passos numerados (modo de preparo geral)
    3. Finalização e Notas Técnicas → observações, alergênicos, referências

Os rótulos do cabeçalho são localizados por regex dentro do texto corrido,
portanto funcionem em parágrafos únicos ou com quebras de linha.
"""
import re
import unicodedata
import zipfile

from defusedxml.ElementTree import fromstring

W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'

# Rótulos do cabeçalho, na ordem em que aparecem no documento.
HEADER_LABELS = (
    ('nome', r'Nome\s+da\s+Prepara[çc][ãa]o'),
    ('equipamentos', r'Equipamentos'),
    ('utensilios', r'Utens[íi]lios'),
    ('tempo_preparo', r'Tempo\s+de\s+Preparo'),
    ('rendimento', r'Rendimento'),
)
_HEADER_RE = re.compile(
    r'(?:' + '|'.join(fr'({pat})' for _, pat in HEADER_LABELS) + r')\s*:',
    re.IGNORECASE,
)

_SECTION_PATTERNS = (
    ('insumos', re.compile(r'^\s*1\s*[\.\)\-–]?\s*(?:\w+\s+){0,2}?insumos', re.IGNORECASE)),
    ('modo', re.compile(r'^\s*2\s*[\.\)\-–]?\s*modo\s+de\s+preparo', re.IGNORECASE)),
    ('notas', re.compile(r'^\s*3\s*[\.\)\-–]?\s*(?:finaliza|nota)', re.IGNORECASE)),
)

_NOTA_PREFIXES = (
    ('observacoes', re.compile(r'^\s*observa[çc][õo]es\s*t[ée]cnicas?\s*:?\s*', re.IGNORECASE)),
    ('alergenicos', re.compile(r'^\s*alerg[êe]nicos?\s*:?\s*', re.IGNORECASE)),
    ('referencias', re.compile(r'^\s*refer[êe]ncias?\s*(bibliogr[áa]ficas?)?\s*:?\s*', re.IGNORECASE)),
)

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
    cells = []
    for cell in row.findall(W + 'tc'):
        text = ' '.join(
            re.sub(r'\s+', ' ', _paragraph_text(p)).strip()
            for p in cell.findall(W + 'p')
        ).strip()
        cells.append(text)
    return cells


def _read_blocks(doc_xml):
    """Retorna os blocos do corpo do documento na ordem original:
    ('p', texto) para parágrafos e ('table', linhas) para tabelas."""
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
    """Colapsa quebras de linha/espaços de um valor de cabeçalho."""
    return re.sub(r'\s+', ' ', value).strip(' .;')


def _extract_header(paragraph_texts):
    """Localiza os rótulos do cabeçalho no texto corrido (antes da 1ª tabela)
    e devolve um dicionário com os valores entre um rótulo e o próximo."""
    haystack = '\n'.join(paragraph_texts)
    matches = list(_HEADER_RE.finditer(haystack))
    fields = {}
    for index, match in enumerate(matches):
        # Índice do grupo alternado que casou → chave canônica do rótulo.
        group_index = next(i for i, g in enumerate(match.groups()) if g is not None)
        key = HEADER_LABELS[group_index][0]
        end = matches[index + 1].start() if index + 1 < len(matches) else len(haystack)
        value = _clean_inline(haystack[match.end():end])
        if value:
            fields.setdefault(key, value)
    return fields


def _match_section(text):
    normalized = _strip_accents(text).lower()
    for name, pattern in _SECTION_PATTERNS:
        if pattern.match(normalized):
            return name
    return None


def _parse_quantity(raw):
    """Primeiro número do texto da quantidade ('400', '15 e 3', '2,5')."""
    match = re.search(r'\d+(?:[.,]\d+)?', raw or '')
    if not match:
        return None
    return float(match.group().replace(',', '.'))


def _parse_ingredient_row(cells):
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


def _clean_preparation_name(text):
    """'Para os Bolinhos de Carne Seca' → 'Bolinhos de Carne Seca'."""
    prefix = re.match(r'^\s*para\s+(?:os|as|o|a|um|uma|uns|umas)?\s+', text, flags=re.IGNORECASE)
    name = text[prefix.end():] if prefix else text
    return name.strip(':. ')


def _is_header_row(row):
    return any('ingred' in _strip_accents(c).lower() for c in row)


def parse_ficha_docx(file_stream):
    """Lê um arquivo DOCX de Ficha Técnica e retorna um dicionário com o
    conteúdo estruturado. Levanta FichaParseError quando o arquivo não segue
    o formato esperado."""
    try:
        with zipfile.ZipFile(file_stream) as archive:
            doc_xml = archive.read('word/document.xml')
    except zipfile.BadZipFile:
        raise FichaParseError('O arquivo não é um documento Word (.docx) válido.')
    except KeyError:
        raise FichaParseError('DOCX sem conteúdo de texto (word/document.xml ausente).')

    blocks = _read_blocks(doc_xml)

    # ── Cabeçalho: parágrafos antes da primeira tabela/seção de insumos ──
    intro_texts = []
    for kind, content in blocks:
        if kind == 'table' or _match_section(content):
            break
        intro_texts.append(content)
    header = _extract_header(intro_texts)
    if not header.get('nome'):
        raise FichaParseError(
            'Não foi possível localizar o rótulo "Nome da Preparação:" no documento.')

    # ── Corpo: seções de insumos, modo de preparo e notas ──
    section = None
    preparations = []      # [{'nome', 'ingredientes': [...]}]
    current_prep = None
    steps = []
    notes = {'observacoes': [], 'alergenicos': [], 'referencias': []}

    for kind, content in blocks:
        if kind == 'p':
            matched = _match_section(content)
            if matched:
                section = matched
                continue

        if section == 'insumos':
            if kind == 'p':
                if content.lower().startswith('para '):
                    current_prep = {
                        'nome': _clean_preparation_name(content),
                        'ingredientes': [],
                    }
                    preparations.append(current_prep)
            elif kind == 'table':
                if current_prep is None:
                    current_prep = {'nome': 'Ingredientes', 'ingredientes': []}
                    preparations.append(current_prep)
                data_rows = content[1:] if _is_header_row(content[0]) else content
                for row in data_rows:
                    ingredient = _parse_ingredient_row(row)
                    if ingredient:
                        current_prep['ingredientes'].append(ingredient)

        elif section == 'modo':
            if kind == 'p':
                step = _STEP_NUMBER_RE.sub('', content).strip()
                if step:
                    steps.append(step)

        elif section == 'notas':
            if kind == 'p':
                for key, pattern in _NOTA_PREFIXES:
                    if pattern.match(content):
                        notes[key].append(pattern.sub('', content).strip())
                        break
                else:
                    notes['observacoes'].append(content)

    return {
        'nome': header.get('nome'),
        'equipamentos': header.get('equipamentos', ''),
        'utensilios': header.get('utensilios', ''),
        'tempo_preparo': header.get('tempo_preparo', ''),
        'rendimento': header.get('rendimento', ''),
        'preparacoes': preparations,
        'modo_preparo': steps,
        'observacoes': '\n'.join(notes['observacoes']) or None,
        'alergenicos': '\n'.join(notes['alergenicos']) or None,
        'referencias': '\n'.join(notes['referencias']) or None,
    }
