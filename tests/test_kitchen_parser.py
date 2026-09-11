"""Testes do parser de Fichas Técnicas (novo modelo em tabelas) e do fluxo
de fichas do módulo Cozinha: upload do .docx → "Salvar Ficha Técnica" e
criação manual pelo formulário (tabela única de insumos).

O DOCX de teste é montado em memória (zip + word/document.xml) seguindo o
modelo da Ficha Técnica Operacional: tabela principal com o nome na 1ª linha
mesclada, rótulos com valor na própria célula, cabeçalho de insumos
("Ingredientes | Especificações | Quantidade | Unidade"), parágrafos do modo
de preparo e tabela final de notas técnicas.
"""
import os
import tempfile
import unittest
import zipfile
from io import BytesIO

from app import create_app
from app.config import Config
from app.extensions import db
from app.blueprints.kitchen.parser import FichaParseError, parse_ficha_docx
from app.models import (KitchenRecipe, Permission, Role, TechnicalSheet,
                        Unity, User)

W_NS = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'

USERNAME = 'cozinha.teste'
PASSWORD = 'SenhaForte123'


# ── Montagem do DOCX de teste ────────────────────────────────────────────────

def _p(text):
    return (f'<w:p><w:r><w:t xml:space="preserve">{text}</w:t></w:r></w:p>')


def _cell(text):
    return (f'<w:tc><w:p><w:r><w:t xml:space="preserve">{text}</w:t></w:r>'
            f'</w:p></w:tc>')


def _row(*cells):
    return '<w:tr>' + ''.join(_cell(c) for c in cells) + '</w:tr>'


def _merged_row(text, span=4):
    return (f'<w:tr><w:tc><w:tcPr><w:gridSpan w:val="{span}"/></w:tcPr>'
            f'<w:p><w:r><w:t xml:space="preserve">{text}</w:t></w:r></w:p>'
            f'</w:tc></w:tr>')


def _table(*rows):
    return '<w:tbl>' + ''.join(rows) + '</w:tbl>'


def _docx(*parts):
    """DOCX mínimo em memória contendo apenas o word/document.xml.
    Aceita blocos soltos ou tuplas de blocos."""
    flat = []
    for part in parts:
        flat.extend(part) if isinstance(part, tuple) else flat.append(part)
    document = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                f'<w:document xmlns:w="{W_NS}"><w:body>{"".join(flat)}</w:body>'
                f'</w:document>')
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        archive.writestr('word/document.xml', document)
    buffer.seek(0)
    return buffer


def _ficha_marguerita():
    """Ficha completa no novo modelo, com valores nos campos e nos ingredientes."""
    return _docx(
        _table(
            _merged_row('Pizza Marguerita'),
            _merged_row('Equipamentos: Forno de lastro e amassadeira'),
            _merged_row('Utensílios:'),
            _row('Tempo de Preparo: 40 minutos', 'Rendimento: 4 porções'),
            _row('Ingredientes', 'Especificações', 'Quantidade', 'Unidade'),
            _row('Muçarela', 'Ralada', '130', 'g'),
            _row('Manjericão fresco', 'Em folhas', '5', 'g'),
            _row('Azeite de oliva', '', 'Q.B.', '-'),
            _row('Fermento biológico', 'Fresco', '', ''),
        ),
        _p('Modo de Preparo:'),
        _p('1. Preaquecer o forno a 300 °C.'),
        _p('2. Abrir a massa e distribuir os ingredientes.'),
        _table(
            _row('Observações técnicas: assar em forno bem quente'),
            _row(''),
            _row('Alergênicos'),
            _row('Contém derivados de leite'),
            _row('Referências'),
            _row('Apostila do curso Pizzaiolo'),
        ),
    )


class ParseFichaDocxTestCase(unittest.TestCase):
    def test_parse_full_ficha(self):
        data = parse_ficha_docx(_ficha_marguerita())
        self.assertEqual(data['nome'], 'Pizza Marguerita')
        self.assertEqual(data['equipamentos'], 'Forno de lastro e amassadeira')
        self.assertEqual(data['utensilios'], '')
        self.assertEqual(data['tempo_preparo'], '40 minutos')
        self.assertEqual(data['rendimento'], '4 porções')

        # Uma única tabela de insumos, com o nome da própria ficha.
        self.assertEqual(len(data['preparacoes']), 1)
        self.assertEqual(data['preparacoes'][0]['nome'], 'Pizza Marguerita')
        ingredientes = data['preparacoes'][0]['ingredientes']
        self.assertEqual([i['nome'] for i in ingredientes],
                         ['Muçarela', 'Manjericão fresco', 'Azeite de oliva',
                          'Fermento biológico'])
        self.assertEqual(ingredientes[0]['quantidade'], 130.0)
        self.assertEqual(ingredientes[0]['especificacao'], 'Ralada')
        self.assertEqual(ingredientes[0]['unidade'], 'g')
        # 'Q.B.' com unidade '-' → sem valor numérico e sem unidade (a gosto).
        self.assertIsNone(ingredientes[2]['quantidade'])
        self.assertEqual(ingredientes[2]['quantidade_raw'], 'Q.B.')
        self.assertEqual(ingredientes[2]['unidade'], '')
        # Linha com quantidade e unidade vazias é mantida.
        self.assertIsNone(ingredientes[3]['quantidade'])
        self.assertEqual(ingredientes[3]['especificacao'], 'Fresco')

        self.assertEqual(data['modo_preparo'],
                         ['Preaquecer o forno a 300 °C.',
                          'Abrir a massa e distribuir os ingredientes.'])
        self.assertEqual(data['observacoes'], 'assar em forno bem quente')
        self.assertEqual(data['alergenicos'], 'Contém derivados de leite')
        self.assertEqual(data['referencias'], 'Apostila do curso Pizzaiolo')

    def test_notes_value_in_row_below_label(self):
        body = (
            _table(
                _merged_row('Molho de tomate'),
                _row('Ingredientes', 'Especificações', 'Quantidade', 'Unidade'),
                _row('Tomate italiano', 'Maduro', '1500', 'g'),
            ),
            _table(
                _row('Observações técnicas:'),
                _row('Passar no passe-vites e não peneirar.'),
                _row('Alergênicos'),
                _row(''),
                _row('Referências'),
                _row(''),
            ),
        )
        data = parse_ficha_docx(_docx(body))
        self.assertEqual(data['observacoes'], 'Passar no passe-vites e não peneirar.')
        self.assertEqual(data['alergenicos'], '')
        self.assertEqual(data['referencias'], '')

    def test_rejects_document_without_ingredients_table(self):
        body = (_p('Receita solta'), _p('Nome da Preparação: Bolo'))
        with self.assertRaises(FichaParseError) as ctx:
            parse_ficha_docx(_docx(body))
        self.assertIn('tabela de insumos', str(ctx.exception))

    def test_rejects_invalid_zip(self):
        with self.assertRaises(FichaParseError):
            parse_ficha_docx(BytesIO(b'isto nao e um zip'))


class KitchenSheetFlowTestCase(unittest.TestCase):
    """Fluxo completo: upload → salvar e criação manual pelo formulário."""

    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix='.db')
        os.close(fd)
        TestConfig = type('TestConfig', (Config,), {
            'SECRET_KEY': 'chave-de-teste-nao-usar-o-valor-dev',
            'TESTING': True,
            'WTF_CSRF_ENABLED': False,
            'RATELIMIT_ENABLED': False,
            'SQLALCHEMY_DATABASE_URI': 'sqlite:///' + self.db_path.replace('\\', '/'),
        })

        self.app = create_app(TestConfig)
        self.app.config['SESSION_COOKIE_SECURE'] = False
        self.client = self.app.test_client()

        with self.app.app_context():
            db.create_all()
            self.unity = Unity(name='Unidade Teste', code='UT')
            db.session.add(self.unity)
            db.session.flush()

            perms = [Permission(code=code, module='kitchen', action=code.split(':')[1])
                     for code in ('kitchen:read', 'kitchen:sheet_create',
                                  'kitchen:sheet_delete')]
            db.session.add_all(perms)
            role = Role(name='cozinheiro-teste', label='Cozinha Teste', permissions=perms)
            db.session.add(role)
            db.session.flush()

            user = User(
                username=USERNAME, email='cozinha@escola.edu', full_name='Cozinheiro Teste',
                role='room', profile_type='employee', unity_id=self.unity.id,
                role_id=role.id, force_password_change=False, is_active_user=True,
            )
            user.set_password(PASSWORD)
            db.session.add(user)
            db.session.commit()

        response = self.client.post('/login',
                                    data={'username': USERNAME, 'password': PASSWORD},
                                    follow_redirects=True)
        self.assertEqual(response.status_code, 200)

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()
        for suffix in ('', '-wal', '-shm'):
            path = self.db_path + suffix
            if os.path.exists(path):
                os.remove(path)

    def test_upload_and_save_creates_preparation(self):
        response = self.client.post(
            '/kitchen/fichas/upload',
            data={'files': (_ficha_marguerita(), 'Pizza Marguerita.docx')},
            follow_redirects=True,
            content_type='multipart/form-data',
        )
        page = response.get_data(as_text=True)
        self.assertIn('1 ficha(s) lida(s) com sucesso', page)

        with self.app.app_context():
            sheet = TechnicalSheet.query.one()
            self.assertEqual(sheet.status, 'pending')
            self.assertEqual(sheet.parsed_data['nome'], 'Pizza Marguerita')
            sheet_id = sheet.id

        response = self.client.post(f'/kitchen/fichas/{sheet_id}/salvar',
                                    follow_redirects=True)
        page = response.get_data(as_text=True)
        self.assertIn('Ficha Técnica salva', page)
        self.assertIn('Muçarela', page)
        self.assertIn('Especificações', page)
        # Opção de ordem alfabética dos ingredientes com o nome na linha
        self.assertIn('btn-sort-alpha', page)
        self.assertIn('data-name="Muçarela"', page)

        with self.app.app_context():
            recipe = KitchenRecipe.query.one()
            self.assertEqual(recipe.name, 'Pizza Marguerita')
            self.assertEqual(recipe.equipments, 'Forno de lastro e amassadeira')
            self.assertEqual(recipe.yield_info, '4 porções')
            self.assertEqual(len(recipe.preparations), 1)
            self.assertEqual(len(recipe.preparations[0].ingredients), 4)

    def test_manual_sheet_with_single_ingredients_table(self):
        response = self.client.post('/kitchen/fichas/criar', data={
            'nome': 'Crostini',
            'equipamentos': 'Forno',
            'utensilios': 'Faca serrilhada',
            'tempo_preparo': '20 minutos',
            'rendimento': '2 porções',
            'ing_nome[]': ['Massa de pizza', 'Queijo parmesão'],
            'ing_espec[]': ['', 'Ralado'],
            'ing_qtd[]': ['300', '100'],
            'ing_unid[]': ['g', 'g'],
            'modo_preparo': '1. Cortar o pão.\n2. Gratinar.',
            'alergenicos': 'Contém glúten',
        }, follow_redirects=True)
        page = response.get_data(as_text=True)
        self.assertIn('Ficha Técnica criada', page)
        self.assertIn('Queijo parmesão', page)

        with self.app.app_context():
            recipe = KitchenRecipe.query.one()
            self.assertEqual(recipe.name, 'Crostini')
            self.assertIsNone(recipe.technical_sheet)
            self.assertEqual(len(recipe.preparations), 1)
            preparation = recipe.preparations[0]
            self.assertEqual(preparation.name, 'Crostini')
            self.assertEqual([i.name for i in preparation.ingredients],
                             ['Massa de pizza', 'Queijo parmesão'])
            self.assertEqual(preparation.ingredients[0].quantity, 300.0)
            self.assertEqual(preparation.ingredients[1].specification, 'Ralado')
            self.assertEqual(recipe.step_list,
                             ['Cortar o pão.', 'Gratinar.'])
            self.assertEqual(recipe.allergens, 'Contém glúten')

    def test_delete_all_saved_sheets_removes_recipes_and_files(self):
        for name in ('Pizza Marguerita.docx', 'Cópia Pizza Marguerita.docx'):
            self.client.post(
                '/kitchen/fichas/upload',
                data={'files': (_ficha_marguerita(), name)},
                content_type='multipart/form-data',
                follow_redirects=True,
            )
        self.client.post('/kitchen/fichas/salvar-todas', follow_redirects=True)

        with self.app.app_context():
            self.assertEqual(TechnicalSheet.query.count(), 2)
            self.assertEqual(KitchenRecipe.query.count(), 2)
            folder = os.path.join(self.app.instance_path, 'uploads',
                                  'technical_sheets')
            stored = [s.stored_filename for s in TechnicalSheet.query.all()]
        for filename in stored:
            self.assertTrue(os.path.exists(os.path.join(folder, filename)))

        response = self.client.post('/kitchen/fichas/excluir-todas',
                                    follow_redirects=True)
        self.assertIn('2 ficha(s) salva(s) excluída(s)',
                      response.get_data(as_text=True))

        with self.app.app_context():
            self.assertEqual(TechnicalSheet.query.count(), 0)
            self.assertEqual(KitchenRecipe.query.count(), 0)
        # Os arquivos enviados ("downloads") também são removidos do disco.
        for filename in stored:
            self.assertFalse(os.path.exists(os.path.join(folder, filename)))


if __name__ == '__main__':
    unittest.main()
