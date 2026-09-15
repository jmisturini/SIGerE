"""Testes do relatório de ingredientes da página de Compras (módulo Cozinha).

O botão "Relatório de Ingredientes" abre uma página em tela com as mesmas
linhas agregadas da requisição de compra; cada linha tem um botão "Detalhes"
que abre um modal com a quantidade individual de cada preparação ("Receita"
ou "Receita — Sub-preparação" quando a receita tem sub-preparações com nome
próprio). Na página de Compras o botão só fica ativo com ao menos uma
preparação selecionada.
"""
import json
import os
import re
import tempfile
import unittest

from app import create_app
from app.config import Config
from app.extensions import db
from app.models import (KitchenPreparation, KitchenRecipe, KitchenRecipeIngredient,
                        Permission, Role, Unity, User)

EMAIL = 'cozinha@escola.edu'
READER_EMAIL = 'leitor@escola.edu'
PASSWORD = 'SenhaForte123'


class TestConfig(Config):
    SECRET_KEY = 'chave-de-teste-nao-usar-o-valor-dev'
    TESTING = True
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False


class KitchenReportTestCase(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix='.db')
        os.close(fd)
        TestConfig.SQLALCHEMY_DATABASE_URI = 'sqlite:///' + self.db_path.replace('\\', '/')

        self.app = create_app(TestConfig)
        self.app.config['SESSION_COOKIE_SECURE'] = False
        self.client = self.app.test_client()

        with self.app.app_context():
            db.create_all()
            self.unity = Unity(name='Unidade Teste', code='UT')
            db.session.add(self.unity)
            db.session.flush()

            perms = [Permission(code=code, module='kitchen', action=code.split(':')[1])
                     for code in ('kitchen:read', 'kitchen:shopping_export')]
            db.session.add_all(perms)
            manager = Role(name='cozinheiro-teste', label='Cozinha Teste', permissions=perms)
            db.session.add(manager)
            reader_role = Role(name='leitor-teste', label='Leitor Cozinha',
                               permissions=[p for p in perms if p.code == 'kitchen:read'])
            db.session.add(reader_role)
            db.session.flush()

            user = User(
                email='cozinha@escola.edu', full_name='Cozinheiro Teste',
                role='room', profile_type='employee', unity_id=self.unity.id,
                role_id=manager.id, force_password_change=False, is_active_user=True,
            )
            user.set_password(PASSWORD)
            db.session.add(user)

            reader = User(
                email='leitor@escola.edu', full_name='Leitor Teste',
                role='room', profile_type='employee', unity_id=self.unity.id,
                role_id=reader_role.id, force_password_change=False, is_active_user=True,
            )
            reader.set_password(PASSWORD)
            db.session.add(reader)

            # Receita com uma única tabela de insumos (sub-preparação com o
            # mesmo nome da receita) e itens de todos os casos: soma, "a gosto"
            # e ingrediente excluído (água).
            bolo = KitchenRecipe(name='Bolo de Carne', unity_id=self.unity.id,
                                 yield_info='4 porções')
            massa_bolo = KitchenPreparation(name='Bolo de Carne', position=0, recipe=bolo)
            massa_bolo.ingredients.append(KitchenRecipeIngredient(
                name='Farinha de Trigo', quantity=400.0, unit='g', position=0))
            massa_bolo.ingredients.append(KitchenRecipeIngredient(
                name='Ovo', quantity=3.0, unit='un', position=1))
            massa_bolo.ingredients.append(KitchenRecipeIngredient(
                name='Sal', quantity=None, quantity_raw='a gosto', unit='', position=2))
            massa_bolo.ingredients.append(KitchenRecipeIngredient(
                name='Água', quantity=500.0, unit='ml', position=3))
            db.session.add(bolo)

            # Receita com duas sub-preparações usando o mesmo ingrediente: o
            # relatório deve mostrar as duas origens ("Lasanha — Massa" e
            # "Lasanha — Molho Branco").
            lasanha = KitchenRecipe(name='Lasanha', unity_id=self.unity.id,
                                    yield_info='6 porções')
            massa = KitchenPreparation(name='Massa', position=0, recipe=lasanha)
            massa.ingredients.append(KitchenRecipeIngredient(
                name='Farinha de Trigo', quantity=100.0, unit='g', position=0))
            massa.ingredients.append(KitchenRecipeIngredient(
                name='Ovo', quantity=2.0, unit='un', position=1))
            molho = KitchenPreparation(name='Molho Branco', position=1, recipe=lasanha)
            molho.ingredients.append(KitchenRecipeIngredient(
                name='Farinha de Trigo', quantity=100.0, unit='g', position=0))
            db.session.add(lasanha)
            db.session.commit()
            self.bolo_id = bolo.id
            self.lasanha_id = lasanha.id
            self.unity_id = self.unity.id

        self._login()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()
        for suffix in ('', '-wal', '-shm'):
            path = self.db_path + suffix
            if os.path.exists(path):
                os.remove(path)

    def _login(self, email=EMAIL):
        response = self.client.post('/login',
                                    data={'email': email, 'password': PASSWORD},
                                    follow_redirects=True)
        self.assertEqual(response.status_code, 200)

    def _post_report(self, **extra):
        follow = extra.pop('follow_redirects', False)
        data = {
            'recipe_ids': [str(self.bolo_id), str(self.lasanha_id)],
            'professor': 'Prof Teste',
            'class_date': '2026-09-12',
            'course': 'GASTRONOMIA',
            'period': 'Noturno',
        }
        data.update(extra)
        return self.client.post('/kitchen/compras/relatorio', data=data,
                                follow_redirects=follow)

    def test_report_page_lists_exported_ingredients_with_preparations(self):
        response = self._post_report()
        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)

        # Cabeçalho com os dados do formulário e as preparações escolhidas
        # (agora em campos editáveis, de onde a requisição é exportada).
        self.assertIn('Relatório de Ingredientes', page)
        self.assertIn('name="professor"', page)
        self.assertIn('Prof Teste', page)
        self.assertIn('value="2026-09-12"', page)
        self.assertIn('GASTRONOMIA', page)
        self.assertIn('Noturno', page)
        self.assertIn('Bolo de Carne', page)
        self.assertIn('Lasanha', page)

        # A exportação da requisição mora na página do relatório: formulário
        # com os ids das preparações selecionadas e o botão de exportar.
        self.assertIn('action="/kitchen/compras/export"', page)
        self.assertIn('<input type="hidden" name="recipe_ids" '
                      f'value="{self.bolo_id}">', page)
        self.assertIn('<input type="hidden" name="recipe_ids" '
                      f'value="{self.lasanha_id}">', page)
        self.assertIn('Exportar Requisição (.xlsx)', page)

        # Farinha de Trigo: 400 g + 100 g + 100 g = 600 g → 0,6 KG, com a
        # quebra individual de cada preparação nos dados do modal de detalhes
        # (o tojson escapa o travessão, por isso o JSON é lido e parseado).
        self.assertIn('Farinha de Trigo', page)
        self.assertIn('0,6', page)
        dados = json.loads(re.search(
            r'<script id="ingredientes-data" type="application/json">(.*?)</script>',
            page, re.DOTALL).group(1))
        farinha = next(linha for linha in dados if linha['nome'] == 'Farinha de Trigo')
        self.assertEqual([(f['nome'], round(f['quantidade'], 3), f['unidade'])
                          for f in farinha['fontes']],
                         [('Bolo de Carne', 0.4, 'KG'),
                          ('Lasanha — Massa', 0.1, 'KG'),
                          ('Lasanha — Molho Branco', 0.1, 'KG')])

        # Ovo: 3 + 2 un → 5 UN, sem a origem "Molho Branco" na linha.
        self.assertIn('Ovo', page)
        self.assertIn('<td class="text-center">5</td>', page)

        # Sem quantidade definida: quantidade em branco e unidade '—'.
        self.assertIn('<td class="text-center">—</td>', page)

        # Água nunca entra na requisição (nem nos dados do relatório — a
        # palavra pode aparecer no texto informativo do card de exportação).
        self.assertFalse(any(linha['nome'] == 'Água' for linha in dados))

        # Botão de detalhes por linha e modal (a coluna de preparações
        # vinculadas saiu da tabela).
        self.assertIn('DETALHES', page)
        self.assertEqual(page.count('btn-outline-primary detalhes-btn'), 3)
        self.assertIn('id="detalhesModal"', page)
        self.assertNotIn('PREPARAÇÕES VINCULADAS', page)

    def test_aggregate_rows_carry_per_preparation_quantities(self):
        from app.blueprints.kitchen.export import aggregate_ingredients

        with self.app.app_context():
            recipes = KitchenRecipe.query.filter(
                KitchenRecipe.unity_id == self.unity_id,
                KitchenRecipe.id.in_([self.bolo_id, self.lasanha_id]),
            ).order_by(KitchenRecipe.name).all()
            rows = {row['nome']: row for row in aggregate_ingredients(recipes)}

        # Farinha: a quebra soma exatamente o total da linha (0,6 KG).
        self.assertEqual([(f['nome'], round(f['quantidade'], 3), f['unidade'])
                          for f in rows['Farinha de Trigo']['fontes']],
                         [('Bolo de Carne', 0.4, 'KG'),
                          ('Lasanha — Massa', 0.1, 'KG'),
                          ('Lasanha — Molho Branco', 0.1, 'KG')])

        # Ovo: só as duas preparações que o usam.
        self.assertEqual([(f['nome'], f['quantidade'], f['unidade'])
                          for f in rows['Ovo']['fontes']],
                         [('Bolo de Carne', 3.0, 'UN'),
                          ('Lasanha — Massa', 2.0, 'UN')])

        # "A gosto": fontes com quantidade em branco e unidade '—'.
        self.assertEqual(rows['Sal']['fontes'],
                         [{'nome': 'Bolo de Carne', 'quantidade': None,
                           'unidade': '—'}])

    def test_report_without_selection_redirects_with_warning(self):
        response = self._post_report(recipe_ids=[], follow_redirects=True)
        self.assertIn('Selecione ao menos uma preparação para ver o relatório',
                      response.get_data(as_text=True))

    def test_report_requires_export_permission(self):
        # A view de login redireciona sem trocar de usuário quando já há uma
        # sessão ativa, por isso o logout antes de entrar como leitor.
        self.client.get('/logout')
        self._login(READER_EMAIL)
        response = self._post_report()
        self.assertEqual(response.status_code, 403)

    def test_shopping_page_shows_report_button(self):
        response = self.client.get('/kitchen/compras')
        page = response.get_data(as_text=True)
        self.assertIn('Relatório de Ingredientes', page)
        self.assertIn('/kitchen/compras/relatorio', page)
        # O botão nasce desabilitado: fica ativo via JavaScript quando o
        # usuário seleciona ao menos uma preparação.
        botao = re.search(r'<button[^>]*id="report-btn"[^>]*>', page).group(0)
        self.assertIn('disabled', botao)
        # A exportação saiu da página de Compras: virou ação da página do
        # relatório, que recebe os campos de dados da requisição.
        self.assertNotIn('/kitchen/compras/export', page)
        self.assertNotIn('Exportar Requisição', page)


if __name__ == '__main__':
    unittest.main()
