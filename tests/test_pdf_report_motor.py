"""Testes do motor visual dos relatórios PDF (app/services/pdf_report.py):
sanitização latin-1, geração multi-página com grupos e a regressão do
vazamento de fill_color nas linhas da tabela.
"""
import unittest

from app.services.pdf_report import (AZUL_ACENTO, FAIXA_DIA, RelatorioPDF,
                                     _texto)


def _rg(cor):
    """Comando de preenchimento que o fpdf2 emite para a cor RGB dada.

    O fpdf2 formata cada componente com 4 casas e remove zeros à direita
    (229/255 sai como "0.898", não "0.8980"; 0 sai como "0", não "0.0000").
    """
    componentes = []
    for valor in cor:
        texto = f"{valor / 255:.4f}".rstrip("0").rstrip(".")
        componentes.append(texto or "0")
    return f"{' '.join(componentes)} rg".encode()


def _conteudos(pdf):
    """Streams de conteúdo por página, lidos antes de output() (que os
    compacta em objetos PDFContentStream)."""
    return {indice: bytes(pagina.contents) for indice, pagina in pdf.pages.items()}


class TextoSanitizadoTest(unittest.TestCase):
    def test_glifos_fora_do_latin1_sao_trocados(self):
        self.assertEqual(_texto("A – B"), "A - B")
        self.assertEqual(_texto("“aspas”"), '"aspas"')
        self.assertEqual(_texto("item • x"), "item \u00b7 x")
        self.assertEqual(_texto(None), "")

    def test_caractere_desconhecido_nao_explode(self):
        # Emoji não existe em latin-1: vira "?" em vez de levantar exceção
        self.assertEqual(_texto("Reserva \U0001f3eb ok"), "Reserva ? ok")


class MotorPdfTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # 30 grupos de 4 linhas: força várias páginas com faixas de dia
        cls.linhas = []
        for g in range(30):
            cls.linhas.append({"faixa": f"Dia {g + 1}/11/2026"})
            for i in range(4):
                cls.linhas.append({"celulas": [f"0{g}:00", f"S{i + 1}",
                                               "Curso", "Professor",
                                               "Evento"]})

    def _pdf_completo(self):
        pdf = RelatorioPDF("Aulas do Calendário", unidade="Unidade Centro")
        pdf.linha_meta("46 aulas \u00b7 Período: 01/11/2026 a 30/11/2026")
        pdf.cartoes_kpi([("46", "Aulas"), ("92h", "Horas"),
                         ("30", "Dias"), ("4", "Salas")])
        pdf.tabela(["Horário", "Sala", "Curso", "Professor", "Evento"],
                   self.linhas, [28, 20, 62, 55, 108],
                   ("CENTER", "CENTER", "LEFT", "LEFT", "LEFT"))
        pdf.nota("Em cinza riscado: aulas que já ocorreram.")
        return pdf

    def test_gera_pdf_multipaginas(self):
        pdf = self._pdf_completo()
        saida = bytes(pdf.output())
        self.assertTrue(saida.startswith(b"%PDF"))
        self.assertGreater(len(pdf.pages), 1)

    def test_toda_pagina_da_tabela_tem_faixa_de_dia(self):
        """Com grupos que cabem numa folha, nenhuma página exibe linhas de
        continuação soltas: todas as páginas da tabela têm faixa de dia."""
        pdf = self._pdf_completo()
        conteudos = _conteudos(pdf)
        pdf.output()
        faixa = _rg(FAIXA_DIA)
        self.assertGreater(len(conteudos), 1)
        for indice, conteudo in conteudos.items():
            self.assertIn(faixa, conteudo,
                          f"Página {indice} sem faixa de dia (linhas órfãs?)")

    def test_fill_color_dos_cartoes_nao_vaza_para_a_tabela(self):
        """fpdf2 captura o fill_color vigente como estilo inicial da tabela;
        o motor precisa resetá-lo, senão as linhas herdam o realce dos
        cartões de indicadores (regressão de 2026-10-25)."""
        pdf = self._pdf_completo()
        conteudos = _conteudos(pdf)
        pdf.output()
        realce = _rg(AZUL_ACENTO)
        faixa = _rg(FAIXA_DIA)
        for indice, conteudo in conteudos.items():
            # O header desenha a linha de realce da marca em toda página, à
            # esquerda do conteúdo: a caça ao realce começa onde a tabela
            # começa (primeira faixa de dia)
            tabela = conteudo[conteudo.find(faixa):]
            if indice == 1:
                # Antes da tabela: marca do header + as 4 barras dos cartões
                antes = conteudo[:conteudo.find(faixa)]
                self.assertGreater(
                    antes.count(realce), 4,
                    "Esperava marca do header + 4 barras de cartões KPI "
                    "antes da tabela")
                self.assertLess(conteudo.find(realce),
                                conteudo.find(faixa),
                                "Realce dos cartões precisa preceder a tabela")
                self.assertNotIn(realce, tabela,
                                 "Realce dos cartões apareceu dentro da tabela")
            else:
                self.assertNotIn(realce, tabela,
                                 f"Página {indice} com realce dos cartões "
                                 "vazando nas linhas da tabela")

    def test_grupo_com_cabecalho_nao_separa_faixa_da_primeira_linha(self):
        """No limite de espaço, um grupo que abre com cabeçalho precisa levar
        cabeçalho + faixa + 1ª linha juntos: a faixa nunca pode ficar sozinha
        no pé da folha com os dados na página seguinte. Varremos tamanhos do
        primeiro grupo para atravessar a janela crítica de posição."""
        for preenchimento in range(1, 17):
            linhas = []
            # Grupo 1 pequeno (tamanho varrido) só para deslocar a posição
            # onde o grupo grande inicia
            linhas.append({"faixa": "Dia 1/11/2026"})
            for i in range(preenchimento):
                linhas.append({"celulas": ["08:00", "S1", "C", "P",
                                           "RV1"]})
            # Grupo 2 maior que uma folha inteira: abre com cabeçalho
            linhas.append({"faixa": "Dia 2/11/2026"})
            for i in range(16):
                linhas.append({"celulas": ["09:00", "S2", "C", "P",
                                           "RV2"]})
            linhas.append({"faixa": "Dia 3/11/2026"})
            for i in range(3):
                linhas.append({"celulas": ["10:00", "S3", "C", "P",
                                           "RV3"]})

            pdf = RelatorioPDF("Aulas do Calendário", unidade="U")
            pdf.linha_meta("Varredura de limite de paginação")
            pdf.tabela(["Horário", "Sala", "Curso", "Professor", "Evento"],
                       linhas, [28, 20, 62, 55, 108],
                       ("CENTER", "CENTER", "LEFT", "LEFT", "LEFT"))
            conteudos = _conteudos(pdf)
            pdf.output()

            for numero_pagina, conteudo in conteudos.items():
                for g in ("1", "2", "3"):
                    faixa = f"Dia {g}/11/2026".encode()
                    if faixa in conteudo:
                        self.assertIn(f"RV{g}".encode(), conteudo,
                                      f"preenchimento={preenchimento}, "
                                      f"página {numero_pagina}: faixa do dia "
                                      f"{g} sem nenhuma linha de dados na "
                                      "mesma folha")

    def test_primeiro_grupo_nao_vaza_sem_faixa_apos_cartoes(self):
        """Com cartões de indicadores consumindo a primeira folha, um primeiro
        dia que caiba numa página inteira mas não no espaço restante deve ir
        inteiro para a folha seguinte: as páginas de cada faixa e de suas
        linhas precisam coincidir, sem continuação sem faixa de data.
        12 linhas é o limite: a altura efetiva (142,8mm) cabe nos 147mm
        úteis, mas a estimativa com folga (154,2mm) não caberia."""
        linhas = [{"faixa": "Dia 1/11/2026"}]
        for i in range(12):
            linhas.append({"celulas": ["08:00", "S1", "Curso", "Professor",
                                       f"RV1L{i}"]})
        linhas.append({"faixa": "Dia 2/11/2026"})
        for i in range(4):
            linhas.append({"celulas": ["09:00", "S2", "Curso", "Professor",
                                       f"RV2L{i}"]})

        pdf = RelatorioPDF("Aulas do Calendário", unidade="U")
        pdf.linha_meta("Primeiro dia cheio depois dos cartões")
        pdf.cartoes_kpi([("12", "Aulas"), ("24h", "Horas"),
                         ("1", "Dia"), ("1", "Sala")])
        pdf.tabela(["Horário", "Sala", "Curso", "Professor", "Evento"],
                   linhas, [28, 20, 62, 55, 108],
                   ("CENTER", "CENTER", "LEFT", "LEFT", "LEFT"))
        conteudos = _conteudos(pdf)
        pdf.output()

        self.assertGreater(len(conteudos), 1)
        for g in ("1", "2"):
            faixa = f"Dia {g}/11/2026".encode()
            paginas_faixa = {n for n, c in conteudos.items() if faixa in c}
            marcador = f"RV{g}L".encode()
            paginas_dados = {n for n, c in conteudos.items()
                             if marcador in c}
            self.assertTrue(paginas_faixa,
                            f"Faixa do dia {g} não foi renderizada")
            self.assertEqual(paginas_faixa, paginas_dados,
                             f"Dia {g}: faixa e dados em folhas distintas "
                             "(continuação sem faixa de data)")

    def test_mensagem_vazia_e_elision_nao_explode(self):
        pdf = RelatorioPDF("Agenda de Reservas", unidade="U" * 120)
        pdf.linha_meta("Sala muito comprida " * 12)
        pdf.mensagem_vazia("Nenhuma reserva aprovada no período",
                           "As reservas confirmadas aparecem nesta agenda.")
        saida = bytes(pdf.output())
        self.assertTrue(saida.startswith(b"%PDF"))
        self.assertEqual(len(pdf.pages), 1)


if __name__ == "__main__":
    unittest.main()
