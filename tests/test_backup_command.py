"""Testes do comando `flask backup` (snapshot do banco + retenção + upload S3).

Cobre:
- geração de snapshot SQLite válido (integridade e conteúdo) com a CLI;
- política de retenção avô/pai/filho (7 diárias + 4 semanais, com teto de
  idade) local e na nuvem, e preservação de arquivos estranhos à pasta;
- upload e retenção na nuvem com cliente S3 falso (sem rede, sem boto3);
- interpretação das DATABASE_URL SQLite e PostgreSQL.
"""
import gzip
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from app import create_app
from app import backup as modulo_backup
from app.config import Config
from app.extensions import db
from app.models import User


class TestConfig(Config):
    SECRET_KEY = 'chave-de-teste-nao-usar-o-valor-dev'
    TESTING = True
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False


def _arquivo_antigo(pasta, nome, dias_atras):
    """Cria um arquivo de backup falso com mtime envelhecido."""
    caminho = os.path.join(pasta, nome)
    with open(caminho, 'wb') as fh:
        fh.write(b'x')
    passado = datetime.now() - timedelta(days=dias_atras)
    os.utime(caminho, (passado.timestamp(), passado.timestamp()))
    return caminho


class BackupCommandTestCase(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix='.db')
        os.close(fd)
        TestConfig.SQLALCHEMY_DATABASE_URI = 'sqlite:///' + self.db_path.replace('\\', '/')
        self.app = create_app(TestConfig)
        self.app.config['SESSION_COOKIE_SECURE'] = False

        self.pasta_backup = tempfile.mkdtemp(prefix='sigere-backup-test-')

        with self.app.app_context():
            db.create_all()
            user = User(email='gestor@escola.edu', full_name='Gestor Teste',
                        role='room', profile_type='employee',
                        force_password_change=False)
            user.set_password('SenhaForte123')
            db.session.add(user)
            db.session.commit()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()
        for suffix in ('', '-wal', '-shm'):
            path = self.db_path + suffix
            if os.path.exists(path):
                os.remove(path)
        for nome in os.listdir(self.pasta_backup):
            os.remove(os.path.join(self.pasta_backup, nome))
        os.rmdir(self.pasta_backup)

    def _rodar(self, *args):
        return self.app.test_cli_runner().invoke(args=['backup', *args])

    # ── Geração do snapshot ────────────────────────────────────────────────

    def test_backup_sqlite_gera_snapshot_valido(self):
        resultado = self._rodar('--no-upload', '--dir', self.pasta_backup)
        self.assertEqual(resultado.exit_code, 0, resultado.output)
        self.assertIn('Backup', resultado.output)

        arquivos = os.listdir(self.pasta_backup)
        self.assertEqual(len(arquivos), 1)
        self.assertRegex(arquivos[0], r'^sigere-\d{8}-\d{6}-sqlite\.sqlite\.gz$')

        caminho = os.path.join(self.pasta_backup, arquivos[0])
        snapshot = caminho[:-3] + '.aberto'
        with gzip.open(caminho, 'rb') as gz, open(snapshot, 'wb') as bruto:
            bruto.write(gz.read())
        conexao = sqlite3.connect(snapshot)
        try:
            self.assertEqual(
                conexao.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
            self.assertEqual(
                conexao.execute('SELECT COUNT(*) FROM users').fetchone()[0], 1)
        finally:
            conexao.close()
            os.remove(snapshot)

    def test_backup_sem_bucket_avisa_que_ficou_local(self):
        with mock.patch.dict(os.environ, {'BACKUP_S3_BUCKET': ''}):
            resultado = self._rodar('--dir', self.pasta_backup)
        self.assertEqual(resultado.exit_code, 0, resultado.output)
        self.assertIn('apenas local', resultado.output)

    def test_variavel_de_retencao_invalida_erro_claro(self):
        # BACKUP_DAILY_KEEP com lixo no .env: mensagem apresentável, sem
        # ValueError cru.
        with mock.patch.dict(os.environ, {'BACKUP_DAILY_KEEP': 'sete'}):
            resultado = self._rodar('--dir', self.pasta_backup)
        self.assertNotEqual(resultado.exit_code, 0)
        self.assertIn('BACKUP_DAILY_KEEP', resultado.output)
        self.assertIn('não é um número inteiro', resultado.output)
        self.assertNotIn('Traceback', resultado.output)

    def test_variavel_de_retencao_negativa_erro_claro(self):
        # Negativo é erro de digitação: sem o aviso, desativaria o nível em
        # silêncio e sobraria só o "mais recente" da rede de segurança.
        with mock.patch.dict(os.environ, {'BACKUP_DAILY_KEEP': '-3'}):
            resultado = self._rodar('--dir', self.pasta_backup)
        self.assertNotEqual(resultado.exit_code, 0)
        self.assertIn('é negativo — precisa ser >= 0', resultado.output)
        self.assertNotIn('Traceback', resultado.output)

    def test_keep_days_negativo_e_rejeitado(self):
        # Na CLI vale o mesmo contrato: --keep-days negativo cairia no teto
        # <= 0 e desligaria toda a retenção em silêncio — o click reprova
        # antes de qualquer efeito.
        resultado = self._rodar('--keep-days', '-1', '--dir', self.pasta_backup)
        self.assertNotEqual(resultado.exit_code, 0)
        self.assertIn('--keep-days', resultado.output)

    def test_falha_inesperada_no_dump_vira_mensagem(self):
        # Bug do comando ou ambiente fora do previsto: mensagem para o
        # operador + código 1 — não traceback cru sem rótulo.
        with mock.patch.object(modulo_backup, '_dump_sqlite',
                               side_effect=RuntimeError('bug do comando')):
            resultado = self._rodar('--no-upload', '--dir', self.pasta_backup)
        self.assertNotEqual(resultado.exit_code, 0)
        self.assertIn('Falha inesperada no backup', resultado.output)
        self.assertIn('bug do comando', resultado.output)

    # ── Retenção local ─────────────────────────────────────────────────────

    def test_retencao_remove_apenas_backups_antigos(self):
        antigo = _arquivo_antigo(self.pasta_backup,
                                 'sigere-20200101-000000-sqlite.sqlite.gz', 30)
        recente = _arquivo_antigo(self.pasta_backup,
                                  'sigere-20990101-000000-sqlite.sqlite.gz', 1)
        estranho = os.path.join(self.pasta_backup, 'nao-e-backup.gz')
        with open(estranho, 'wb') as fh:
            fh.write(b'x')

        resultado = self._rodar('--no-upload', '--dir', self.pasta_backup)
        self.assertEqual(resultado.exit_code, 0, resultado.output)
        self.assertFalse(os.path.exists(antigo))
        self.assertTrue(os.path.exists(recente))
        self.assertTrue(os.path.exists(estranho))
        # Mantidos: o recém-gerado e o de 2099; apagado: o de 2020.
        self.assertIn('Retenção local: 2 mantido(s), 1 apagado(s)', resultado.output)

    # ── Política de retenção (7 diárias + 4 semanais + teto) ───────────────

    def test_selecao_guarda_sete_diarias_e_quatro_semanais(self):
        # 18/11/2026 é uma quarta-feira (semana ISO 47: dom 15 termina a semana 46).
        agora = datetime(2026, 11, 18, 3, 20)
        registros = []
        for dias_atras in range(30, -1, -1):
            momento = agora - timedelta(days=dias_atras)
            registros.append((momento, momento.strftime('sigere-%Y%m%d-%H%M%S')))

        manter = modulo_backup._selecionar_manter(
            registros, agora, diarias=7, semanais=4, teto_dias=45)

        # Diárias: tudo de 12 a 18/11 — inclusive o domingo 15/11, que também
        # é o "mais novo" da semana 46 (contado uma só vez) → 7 + 3 = 10.
        esperados = {f'sigere-202611{dia:02d}-032000' for dia in range(12, 19)}
        esperados |= {'sigere-20261025-032000', 'sigere-20261101-032000',
                      'sigere-20261108-032000'}
        self.assertEqual(manter, esperados)
        # Um dia dentro da semana 46, mas fora das janelas, não sobrevive.
        self.assertNotIn('sigere-20261111-032000', manter)

    def test_teto_de_idade_apaga_ate_semanal(self):
        agora = datetime(2026, 11, 18, 3, 20)
        velho = (agora - timedelta(days=60), 'sigere-20260919-032000')

        self.assertEqual(
            modulo_backup._selecionar_manter([velho], agora, 7, 4, 45), set())
        # Teto 0 desliga a retenção inteira — contrato antigo do
        # `--keep-days 0` preservado: até velhos de 100 dias permanecem.
        antigos = []
        for dias in (60, 100):
            momento = agora - timedelta(days=dias)
            antigos.append((momento, momento.strftime('sigere-%Y%m%d-032000')))
        self.assertEqual(
            modulo_backup._selecionar_manter(
                antigos, agora, diarias=7, semanais=4, teto_dias=0),
            {nome for _, nome in antigos})

    def test_rede_de_seguranca_mantem_o_mais_recente_sem_politica(self):
        # Diárias e semanais zeradas sob teto ativo nunca apagam tudo —
        # inclusive o backup recém-gerado, que já está na pasta.
        agora = datetime(2026, 11, 18, 3, 20)
        registros = []
        for dias in range(3):
            momento = agora - timedelta(days=dias)
            registros.append((momento, momento.strftime('sigere-%Y%m%d-032000')))

        self.assertEqual(
            modulo_backup._selecionar_manter(
                registros, agora, diarias=0, semanais=0, teto_dias=45),
            {'sigere-20261118-032000'})

    def test_caminho_sqlite_relativo_resolve_na_instance(self):
        # Mesma resolução do Flask-SQLAlchemy: relativo cai na pasta
        # instance/ — backup e verificação leem o arquivo que o app escreve.
        with self.app.app_context():
            self.assertEqual(
                modulo_backup._caminho_sqlite('/absoluto/x.db'), '/absoluto/x.db')
            relativo = modulo_backup._caminho_sqlite('relativo.db')
        self.assertTrue(os.path.isabs(relativo))
        self.assertTrue(relativo.endswith(
            os.path.join('instance', 'relativo.db')))

    def test_momento_vem_do_carimbo_do_nome(self):
        self.assertEqual(
            modulo_backup._momento_de('sigere-20260117-032033-postgres.sql.gz',
                                      datetime(2000, 1, 1)),
            datetime(2026, 1, 17, 3, 20, 33))
        # Sem carimbo no nome, cai no mtime informado.
        self.assertEqual(
            modulo_backup._momento_de('outro.gz', datetime(2000, 1, 1)),
            datetime(2000, 1, 1))
        # Carimbo impossível (30 de fevereiro) não derruba o comando —
        # cai no mtime em vez de ValueError.
        self.assertEqual(
            modulo_backup._momento_de('sigere-20260230-032033-postgres.sql.gz',
                                      datetime(2000, 1, 1)),
            datetime(2000, 1, 1))

    def test_momento_nuvem_devolve_naive_no_calendario_local(self):
        consciente = datetime(2026, 11, 15, 23, 30, tzinfo=timezone.utc)
        resultado = modulo_backup._momento_nuvem('outro.gz', consciente)
        self.assertIsNone(resultado.tzinfo)
        self.assertEqual(resultado, consciente.astimezone().replace(tzinfo=None))
        # Carimbo do nome vence e já é local — janelas idênticas às da pasta.
        self.assertEqual(
            modulo_backup._momento_nuvem('sigere-20260117-032033-postgres.sql.gz',
                                         consciente),
            datetime(2026, 1, 17, 3, 20, 33))

    def test_selecao_semanal_sozinha_mantem_o_recem_gerado(self):
        # BACKUP_DAILY_KEEP=0: a seleção semanal pula a semana corrente —
        # sem a proteção do "mais recente", o snapshot recém-gerado seria
        # apagado antes do upload e o comando terminaria sem backup novo.
        agora = datetime(2026, 11, 18, 3, 20)  # quarta-feira, semana ISO 47
        semana_passada = datetime(2026, 11, 11, 3, 20)
        manter = modulo_backup._selecionar_manter(
            [(semana_passada, 'sigere-20261111-032000'),
             (agora, 'sigere-20261118-032000')],
            agora, diarias=0, semanais=4, teto_dias=45)
        self.assertEqual(manter,
                         {'sigere-20261111-032000', 'sigere-20261118-032000'})

    def test_relogio_regressado_protege_o_snapshot_atual(self):
        # Follow-up do CodeRabbit (#243): BACKUP_DAILY_KEEP=0 + correção
        # regressiva de relógio — um backup antigo com carimbo NO FUTURO
        # (25/11) vence o fallback "mais recente" e o snapshot de hoje
        # (22/11, semana corrente que a semanal pula) sai da seleção. Sem a
        # proteção do atual, a retenção apagaria o backup recém-gerado
        # (local e, pós-upload, também o objeto do bucket) e o comando
        # ainda reportaria sucesso.
        agora = datetime(2026, 11, 22, 3, 20)
        registros = [(datetime(2026, 11, 25, 3, 20), 'sigere-20261125-032000'),
                     (agora, 'sigere-20261122-032000')]
        manter = modulo_backup._selecionar_manter(
            registros, agora, diarias=0, semanais=4, teto_dias=45)
        self.assertEqual(manter, {'sigere-20261125-032000'})  # fallback fica com o futuro

        # A proteção do snapshot atual é quem o salva da limpeza:
        futuro = _arquivo_antigo(self.pasta_backup,
                                 'sigere-20261125-032000-sqlite.sqlite.gz', 0)
        os.utime(futuro, (agora.timestamp(), agora.timestamp()))  # mtime é o que importa menos: o carimbo do NOME vence
        atual = os.path.join(self.pasta_backup,
                             'sigere-20261122-032000-sqlite.sqlite.gz')
        with open(atual, 'wb') as fh:
            fh.write(b'x')

        removidos, mantidos, falhas = modulo_backup._limpar_locais(
            self.pasta_backup, diarias=0, semanais=4, teto_dias=45,
            agora=agora, proteger='sigere-20261122-032000-sqlite.sqlite.gz')
        self.assertEqual(removidos, [])   # nem o futuro (semanal) nem o atual (protegido)
        self.assertTrue(os.path.exists(futuro))
        self.assertTrue(os.path.exists(atual))

    def test_semanal_nao_vaza_para_semanas_vazias_intermediarias(self):
        # Semanas 43-46 sem nenhum backup e um órfão da semana 41 (38 dias
        # atrás, dentro do teto de 45): não é semanal — o alcance real é o
        # intervalo das 4 semanas ISO anteriores, não "4 semanas preenchidas".
        agora = datetime(2026, 11, 18, 3, 20)  # quarta-feira, semana ISO 47
        registros = [(datetime(2026, 11, dia, 3, 20),
                      f'sigere-202611{dia:02d}-032000') for dia in range(12, 19)]
        registros.append((datetime(2026, 10, 11, 3, 20), 'sigere-20261011-032000'))

        manter = modulo_backup._selecionar_manter(
            registros, agora, diarias=7, semanais=4, teto_dias=45)
        self.assertEqual(manter,
                         {f'sigere-202611{dia:02d}-032000' for dia in range(12, 19)})

    # ── Upload e retenção na nuvem (cliente S3 falso) ──────────────────────

    def test_upload_e_retencao_nuvem_com_cliente_falso(self):
        antigo_nuvem = {
            'Key': 'sigere/sigere-20200101-000000-postgres.sql.gz',
            'LastModified': datetime.now(timezone.utc) - timedelta(days=90),
        }
        recente_nuvem = {
            'Key': 'sigere/sigere-20990101-000000-postgres.sql.gz',
            'LastModified': datetime.now(timezone.utc) - timedelta(days=1),
        }
        falso_cliente = mock.Mock()
        falso_cliente.delete_objects.return_value = {'Errors': []}
        paginador = mock.Mock()
        paginador.paginate.return_value = [{'Contents': [antigo_nuvem, recente_nuvem]}]
        falso_cliente.get_paginator.return_value = paginador

        ambiente = {'BACKUP_S3_BUCKET': 'bucket-sigere',
                    'BACKUP_S3_PREFIX': 'sigere'}
        with mock.patch.dict(os.environ, ambiente), \
                mock.patch.object(modulo_backup, '_criar_cliente_s3',
                                  return_value=falso_cliente):
            resultado = self._rodar('--dir', self.pasta_backup)

        self.assertEqual(resultado.exit_code, 0, resultado.output)
        self.assertIn('s3://bucket-sigere/sigere/', resultado.output)

        # O snapshot recém-gerado foi o objeto enviado…
        enviados = falso_cliente.upload_file.call_args_list
        self.assertEqual(len(enviados), 1)
        self.assertEqual(enviados[0].args[1], 'bucket-sigere')
        self.assertRegex(enviados[0].args[2], r'^sigere/sigere-\d{8}-\d{6}-sqlite\.')
        # …e só o objeto vencido saiu do bucket.
        excluidos = falso_cliente.delete_objects.call_args_list
        self.assertEqual(len(excluidos), 1)
        self.assertEqual(excluidos[0].kwargs['Delete']['Objects'],
                         [{'Key': antigo_nuvem['Key']}])

    def test_upload_sem_boto3_falha_com_mensagem_clara(self):
        ambiente = {'BACKUP_S3_BUCKET': 'bucket-sigere'}
        with mock.patch.dict(os.environ, ambiente), \
                mock.patch.dict('sys.modules', {'boto3': None}):
            resultado = self._rodar('--dir', self.pasta_backup)
        self.assertNotEqual(resultado.exit_code, 0)
        self.assertIn('boto3', resultado.output)
        # O arquivo local continua intacto — o upload falhou, o backup não.
        self.assertEqual(len(os.listdir(self.pasta_backup)), 1)

    def test_retencao_nuvem_so_toca_filhos_diretos_do_prefixo(self):
        # Cópia manual em subpasta (mesmo com basename de backup e vencida)
        # NÃO entra na política — espelho do comportamento da pasta local,
        # que não desce em subpastas. Vencido de verdade é o filho direto.
        # agora naive local — mesmo calendário dos momentos normalizados
        agora = datetime(2026, 11, 18, 12, 0)
        conteudo = [
            {'Key': 'sigere/sigere-20261118-032000-postgres.sql.gz',
             'LastModified': agora},
            {'Key': 'sigere/2025/sigere-20250101-032000-postgres.sql.gz',
             'LastModified': agora - timedelta(days=300)},
            {'Key': 'sigere/sigere-20250101-032000-postgres.sql.gz',
             'LastModified': agora - timedelta(days=300)},
        ]
        falso_cliente = mock.Mock()
        falso_cliente.delete_objects.return_value = {'Errors': []}
        paginador = mock.Mock()
        paginador.paginate.return_value = [{'Contents': conteudo}]
        falso_cliente.get_paginator.return_value = paginador
        cfg = {'bucket': 'bucket-sigere', 'prefixo': 'sigere', 'diarias': 7,
               'semanais': 4, 'dias_retencao': 45}

        removidos = modulo_backup._limpar_nuvem(cfg, cliente=falso_cliente,
                                                agora=agora)
        self.assertEqual(removidos,
                         ['sigere/sigere-20250101-032000-postgres.sql.gz'])

    def test_retencao_nuvem_nao_conta_falha_como_removida(self):
        # Object lock/permissão recusam a exclusão: a chave volta em Errors
        # mesmo com Quiet — não pode entrar nos removidos nem passar calada.
        agora = datetime(2026, 11, 18, 12, 0)
        chave_vencida = 'sigere/sigere-20250101-032000-postgres.sql.gz'
        falso_cliente = mock.Mock()
        paginador = mock.Mock()
        paginador.paginate.return_value = [{'Contents': [
            {'Key': chave_vencida, 'LastModified': agora - timedelta(days=300)}]}]
        falso_cliente.get_paginator.return_value = paginador
        falso_cliente.delete_objects.return_value = {
            'Errors': [{'Key': chave_vencida, 'Code': 'AccessDenied',
                        'Message': 'Access Denied'}]}
        cfg = {'bucket': 'bucket-sigere', 'prefixo': 'sigere', 'diarias': 7,
               'semanais': 4, 'dias_retencao': 45}

        with mock.patch.object(modulo_backup.click, 'echo') as eco:
            removidos = modulo_backup._limpar_nuvem(cfg, cliente=falso_cliente,
                                                    agora=agora)
        self.assertEqual(removidos, [])
        avisos = [str(chamada.args[0]) for chamada in eco.call_args_list
                  if chamada.args]
        self.assertTrue(any('não foram apagados no bucket' in aviso
                            for aviso in avisos))

    # ── Interpretação da DATABASE_URL ──────────────────────────────────────

    def test_interpretar_uri_sqlite(self):
        motor, caminho = modulo_backup._interpretar_uri('sqlite:///reservation.db')
        self.assertEqual(motor, 'sqlite')
        self.assertEqual(caminho, 'reservation.db')

        motor, caminho = modulo_backup._interpretar_uri('sqlite:////var/lib/sigere/db.sqlite')
        self.assertEqual(motor, 'sqlite')
        self.assertEqual(caminho, '/var/lib/sigere/db.sqlite')

    def test_interpretar_uri_postgresql(self):
        motor, p = modulo_backup._interpretar_uri(
            'postgresql://sigere:senha%20forte@db.local:5433/sigeredb?sslmode=require')
        self.assertEqual(motor, 'postgresql')
        self.assertEqual(p['host'], 'db.local')
        self.assertEqual(p['port'], 5433)
        self.assertEqual(p['user'], 'sigere')
        self.assertEqual(p['password'], 'senha forte')
        self.assertEqual(p['database'], 'sigeredb')
        self.assertEqual(p['sslmode'], 'require')

    def test_interpretar_uri_nao_suportada(self):
        with self.assertRaises(modulo_backup.BackupError):
            modulo_backup._interpretar_uri('mysql://root@localhost/antigo')


if __name__ == '__main__':
    unittest.main()
