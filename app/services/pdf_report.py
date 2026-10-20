"""Motor visual dos relatórios PDF do SIGerE (fpdf2).

Centraliza a identidade visual dos PDFs de exportação — faixa de marca,
título/meta do relatório, cartões de indicadores, tabela zebrada com faixas
de agrupamento e rodapé paginado — para que as rotas de exportação só
descrevam o conteúdo. O desenho visa leitura à distância (parede, telão,
murais): tipografia grande, alto contraste e uma página que se identifica
sozinha mesmo quando o relatório tem várias folhas.

A fonte Helvetica core cobre apenas latin-1: todo texto passa por
`_texto()`, que troca travessões, aspas curvas e outros glifos fora da
tabela de caracteres (ver nota em classrooms.export_availability).
"""
from datetime import datetime

from fpdf import FPDF
from fpdf.fonts import FontFace

# Paleta espelhada em app/static/css/style.css (:root)
AZUL_SENAC = (0, 75, 141)      # --bs-primary #004b8d
AZUL_ACENTO = (44, 123, 229)   # realce claro sobre a faixa de marca
TINTA = (30, 41, 59)           # texto principal (slate-800)
CINZA = (100, 116, 139)        # texto secundário (slate-500)
LINHA = (203, 213, 225)        # separadores (slate-300)
ZEBRA = (241, 245, 249)        # linhas alternadas (slate-100)
FAIXA_DIA = (224, 236, 248)    # fundo da faixa de data (tinta do azul)
CINZA_PASSADO = (148, 163, 184)  # reservas que já ocorreram
FUNDO_PASSADO = (235, 238, 242)  # faixa de data de dias passados

FONTE = "helvetica"

_SUBSTITUICOES = {
    "\u2013": "-", "\u2014": "-", "\u2212": "-",
    "\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"',
    "\u2022": "\u00b7", "\u2026": "...", "\u00a0": " ",
}


def _texto(valor):
    """Sanitiza para latin-1 (fontes core do fpdf2): troca glifos fora da
    tabela de caracteres em vez de falhar a geração do PDF."""
    if valor is None:
        return ""
    valor = str(valor)
    for de, para in _SUBSTITUICOES.items():
        valor = valor.replace(de, para)
    return valor.encode("latin-1", "replace").decode("latin-1")


def _elipse(texto, largura_max, pdf):
    """Corta o texto com reticências quando excede a largura (mm)."""
    if pdf.get_string_width(texto) <= largura_max:
        return texto
    while texto and pdf.get_string_width(texto + "...") > largura_max:
        texto = texto[:-1]
    return texto + "..."


class RelatorioPDF(FPDF):
    """A4 paisagem com faixa de marca, título, rodapé paginado e helpers
    de conteúdo (cartões de indicadores, tabela e mensagem vazia)."""

    def __init__(self, titulo, unidade=None):
        super().__init__(orientation="L", unit="mm", format="A4")
        self.titulo = _texto(titulo)
        self.unidade = _texto(unidade) if unidade else None
        self.emitido_em = datetime.now()
        self.meta = None

        self.set_margins(left=12, top=46, right=12)
        self.set_auto_page_break(auto=True, margin=17)
        self.set_title(f"SIGerE - {self.titulo}")
        self.set_author("SIGerE")
        self.set_creator("SIGerE")
        self.set_subject(self.titulo)
        self.alias_nb_pages()
        self.add_page()

    # -- identidade visual -------------------------------------------------

    def header(self):
        # Faixa de marca (sangrando até as bordas da folha)
        self.set_fill_color(*AZUL_SENAC)
        self.rect(0, 0, self.w, 24, style="F")
        self.set_fill_color(*AZUL_ACENTO)
        self.rect(0, 24, self.w, 1.1, style="F")

        self.set_text_color(255, 255, 255)
        self.set_y(4.6)
        self.set_x(12)
        self.set_font(FONTE, "B", 15.5)
        self.cell(0, 7.5, "SIGerE", new_x="LMARGIN", new_y="NEXT")
        self.set_x(12)
        self.set_font(FONTE, "", 6.6)
        self.cell(0, 3.4, "Sistema Integrado de Gerenciamento Educacional",
                  new_x="LMARGIN", new_y="NEXT")

        if self.unidade:
            self.set_y(5.6)
            self.set_x(-12)
            self.set_font(FONTE, "B", 11)
            nome = _elipse(self.unidade, 90, self)
            self.cell(0, 6, nome, align="R")
        self.set_y(13.8)
        self.set_x(-12)
        self.set_font(FONTE, "", 7.2)
        self.cell(0, 4, f"Emitido em {self.emitido_em:%d/%m/%Y às %H:%M}",
                  align="R")

        # Bloco de título: repete em todas as páginas para que qualquer folha
        # avulsa (mural, telão) identifique o relatório sozinha
        self.set_y(29.5)
        self.set_x(12)
        self.set_text_color(*AZUL_SENAC)
        self.set_font(FONTE, "B", 15)
        self.cell(0, 7.5, self.titulo, new_x="LMARGIN", new_y="NEXT")
        if self.meta:
            self._desenhar_meta()
        # Páginas de continuação (quebra dentro da tabela) retomam abaixo do
        # bloco de título, sem depender de onde o header parou
        self.set_y(self.t_margin)

    def _desenhar_meta(self):
        self.set_y(37.6)
        self.set_x(12)
        self.set_text_color(*CINZA)
        self.set_font(FONTE, "", 9.5)
        self.cell(0, 5, _elipse(self.meta, self.epw, self),
                  new_x="LMARGIN", new_y="NEXT")
        self.linha_divisoria(44)

    def linha_meta(self, texto):
        """Linha descritiva sob o título (sala, período, filtros aplicados),
        repetida em todas as páginas pelo header."""
        self.meta = _texto(texto)
        self._desenhar_meta()

    def linha_divisoria(self, y):
        self.set_draw_color(*LINHA)
        self.set_line_width(0.35)
        self.line(12, y, self.w - 12, y)

    def footer(self):
        self.set_y(-11)
        self.set_draw_color(*LINHA)
        self.set_line_width(0.3)
        self.line(12, self.get_y(), self.w - 12, self.get_y())
        self.set_y(-9.5)
        self.set_font(FONTE, "", 7.2)
        self.set_text_color(*CINZA)
        rodape = "SIGerE"
        if self.unidade:
            rodape += f" \u00b7 {self.unidade}"
        self.cell(0, 4, rodape, align="L")
        self.set_y(-9.5)
        self.set_x(-12)
        self.cell(0, 4, f"Página {self.page_no()}/{{nb}}", align="R")

    # -- conteúdo ----------------------------------------------------------

    def cartoes_kpi(self, indicadores, y=None):
        """Cartões de indicadores [(valor, rótulo), ...] lado a lado."""
        y = self.get_y() + 5 if y is None else y
        n = len(indicadores)
        largura = (self.epw - (n - 1) * 4) / n
        altura = 17
        for i, (valor, rotulo) in enumerate(indicadores):
            x = self.l_margin + i * (largura + 4)
            self.set_fill_color(*ZEBRA)
            self.rect(x, y, largura, altura, style="F",
                      round_corners=True, corner_radius=2.2)
            self.set_xy(x, y + 2.6)
            self.set_font(FONTE, "B", 15)
            self.set_text_color(*AZUL_SENAC)
            self.cell(largura, 7.5, _texto(valor), align="C")
            self.set_xy(x, y + 11)
            self.set_font(FONTE, "B", 6.4)
            self.set_text_color(*CINZA)
            self.cell(largura, 4, _texto(rotulo).upper(), align="C")
        self.set_y(y + altura)

    FAIXA = "faixa"      # linha de agrupamento (ex.: data) ocupando a tabela
    LINHA = "linha"      # linha comum de células
    PASSADO = "passado"  # estilo de conteúdo que já ocorreu

    def tabela(self, colunas, linhas, larguras, alinhos, altura_linha=5.8):
        """Tabela zebrada com cabeçalho azul, repetido a cada página.

        `linhas` aceita dois formatos: {"faixa": "texto"} para uma faixa de
        agrupamento ocupando toda a largura (combinável com "estilo") e
        {"celulas": [...]} para uma linha comum (idem). Estilo PASSADO
        exibe o conteúdo em cinza riscado — reservas que já ocorreram.
        """
        self.set_y(max(self.get_y() + 4, self.t_margin))
        self.set_font(FONTE, "", 9)
        self.set_text_color(*TINTA)
        self.set_draw_color(*LINHA)
        self.set_line_width(0.25)

        cabecalho = FontFace(family=FONTE, emphasis="B", size_pt=9.5,
                             color=(255, 255, 255), fill_color=AZUL_SENAC)
        conteudo = FontFace(family=FONTE, emphasis="IS", color=CINZA_PASSADO)
        faixa_estilo = FontFace(family=FONTE, emphasis="B", size_pt=9.5,
                                color=AZUL_SENAC, fill_color=FAIXA_DIA)
        faixa_passada = FontFace(family=FONTE, emphasis="B", size_pt=9.5,
                                 color=CINZA_PASSADO, fill_color=FUNDO_PASSADO)

        with self.table(
            col_widths=larguras,
            text_align=alinhos,
            line_height=altura_linha,
            padding=1.8,
            headings_style=cabecalho,
            cell_fill_color=ZEBRA,
            cell_fill_mode="EVEN_ROWS",
            borders_layout="HORIZONTAL_LINES",
        ) as tabela:
            topo = tabela.row()
            for coluna in colunas:
                topo.cell(_texto(coluna))

            for linha in linhas:
                estilo_passado = linha.get("estilo") == self.PASSADO
                linha_tabela = tabela.row()
                if "faixa" in linha:
                    linha_tabela.cell(
                        _texto(linha["faixa"]), colspan=len(colunas),
                        style=faixa_passada if estilo_passado else faixa_estilo,
                    )
                else:
                    for celula in linha["celulas"]:
                        linha_tabela.cell(
                            _texto(celula),
                            style=conteudo if estilo_passado else None,
                        )

    def mensagem_vazia(self, titulo, subtitulo=None, y=None):
        """Quadro de destaque usado quando o relatório não tem registros."""
        y = self.get_y() + 8 if y is None else y
        largura, altura = 170, 26
        x = self.l_margin + (self.epw - largura) / 2
        self.set_fill_color(*ZEBRA)
        self.rect(x, y, largura, altura, style="F",
                  round_corners=True, corner_radius=2.5)
        self.set_xy(x, y + 5)
        self.set_font(FONTE, "B", 12)
        self.set_text_color(*AZUL_SENAC)
        self.cell(largura, 7, _texto(titulo), align="C", new_x="LMARGIN",
                  new_y="NEXT")
        if subtitulo:
            self.set_x(x)
            self.set_font(FONTE, "", 9)
            self.set_text_color(*CINZA)
            self.cell(largura, 5.5, _texto(subtitulo), align="C")
        self.set_y(y + altura)

    def nota(self, texto):
        """Anotação discreta abaixo da tabela (legendas, observações)."""
        self.set_y(max(self.get_y() + 2.5, self.t_margin))
        self.set_font(FONTE, "", 7.8)
        self.set_text_color(*CINZA)
        self.set_x(12)
        self.cell(0, 4.5, _texto(texto), new_x="LMARGIN", new_y="NEXT")
