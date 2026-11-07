/* Tabelas ordenáveis no cliente.
   Uso: marque a tabela com data-ordenavel e inclua este script. Os <th>
   do cabeçalho ficam clicáveis e alternam ascendente/descendente; colunas
   com data-nao-ordenavel (ex.: Ações) ficam de fora e linhas com
   data-nao-ordenar (ex.: faixas de grupo ou linha de "nenhum registro")
   não se movem. Reconhece datas pt-BR (dd/mm/aaaa[ hh:mm]) e números
   pt-BR (1.234,56, R$, %); vazio vai sempre para o fim.
   Faixas de grupo (data-nao-ordenar ou td[colspan], como as de
   "Professores e cursos" do relatório geral) abrem um segmento: a
   ordenação reorganiza as linhas DENTRO de cada grupo — o grupo nunca se
   separa das suas linhas nem muda de posição. */
(function () {
    'use strict';

    var ICONE = {
        nenhuma: 'bi-arrow-down-up',
        asc: 'bi-caret-up-fill',
        desc: 'bi-caret-down-fill'
    };

    function chaveTexto(texto) {
        texto = (texto || '').trim();
        if (!texto || texto === '—' || texto === '-') return null;
        var data = texto.match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})(?:\s+(\d{1,2}):(\d{2}))?$/);
        if (data) {
            return { tipo: 'n', valor: (+data[3]) * 10000 + (+data[2]) * 100 + (+data[1]) +
                (((+data[4]) || 0) * 60 + ((+data[5]) || 0)) / 1440 };
        }
        // Duração "Xh" ou "XhMM" (coluna Horas dos relatórios).
        var duracao = texto.match(/^(\d+)h(\d{1,2})?$/);
        if (duracao) {
            return { tipo: 'n', valor: (+duracao[1]) + ((+duracao[2]) || 0) / 60 };
        }
        var num = texto.replace(/R\$/gi, '').replace(/%/g, '').replace(/\s/g, '');
        if (/^-?(\d{1,3}(\.\d{3})*|\d+)(,\d+)?$/.test(num)) {
            return { tipo: 'n', valor: parseFloat(num.replace(/\./g, '').replace(',', '.')) };
        }
        if (/^-?\d+(\.\d+)?$/.test(num)) {
            return { tipo: 'n', valor: parseFloat(num) };
        }
        return { tipo: 't', valor: texto.toLowerCase() };
    }

    function chaveCelula(linha, indice) {
        var celula = linha.cells[indice];
        return chaveTexto(celula ? celula.textContent : '');
    }

    function ordenarTabela(tabela, th, indice, direcao) {
        tabela.querySelectorAll('thead th').forEach(function (outro) {
            if (outro !== th) definirIcone(outro, 'nenhuma');
        });
        definirIcone(th, direcao);
        tabela.setAttribute('data-direcao', direcao);
        tabela.setAttribute('data-coluna', String(indice));

        tabela.querySelectorAll('tbody').forEach(function (tbody) {
            // Segmenta o tbody: cada faixa de grupo abre um segmento com as
            // linhas que a seguem; linhas antes da primeira faixa formam um
            // segmento sem faixa (tabelas planas ficam como eram).
            var segmentos = [];
            var atual = null;
            Array.prototype.forEach.call(tbody.rows, function (linha) {
                var eFaixa = linha.hasAttribute('data-nao-ordenar') ||
                    linha.querySelector('td[colspan]');
                if (eFaixa || !atual) {
                    atual = { faixa: eFaixa ? linha : null, linhas: [] };
                    segmentos.push(atual);
                }
                if (!eFaixa) atual.linhas.push(linha);
            });
            var comparador = function (a, b) {
                var ka = chaveCelula(a, indice);
                var kb = chaveCelula(b, indice);
                if (ka === null && kb === null) return 0;
                if (ka === null) return 1;
                if (kb === null) return -1;
                if (ka.tipo !== kb.tipo) return ka.tipo === 'n' ? -1 : 1;
                var cmp = ka.tipo === 'n'
                    ? ka.valor - kb.valor
                    : ka.valor.localeCompare(kb.valor, 'pt-BR');
                return direcao === 'asc' ? cmp : -cmp;
            };
            segmentos.forEach(function (segmento) {
                segmento.linhas.sort(comparador);
                if (segmento.faixa) tbody.appendChild(segmento.faixa);
                segmento.linhas.forEach(function (linha) { tbody.appendChild(linha); });
            });
        });
    }

    function definirIcone(th, estado) {
        var icone = th.querySelector('.icone-ordenar');
        if (!icone) {
            icone = document.createElement('i');
            icone.className = 'bi icone-ordenar small text-muted ms-1';
            th.appendChild(icone);
        }
        icone.classList.remove(ICONE.nenhuma, ICONE.asc, ICONE.desc);
        icone.classList.add(ICONE[estado]);
        icone.classList.toggle('opacity-50', estado === 'nenhuma');
        th.setAttribute('aria-sort',
            estado === 'asc' ? 'ascending' : estado === 'desc' ? 'descending' : 'none');
    }

    function prepararTabela(tabela) {
        var cabecalho = tabela.querySelector('thead');
        if (!cabecalho) return;
        var ths = cabecalho.querySelectorAll('th');
        ths.forEach(function (th) {
            if (th.hasAttribute('data-nao-ordenavel') || th.classList.contains('th-ordenavel')) return;
            th.classList.add('th-ordenavel');
            definirIcone(th, 'nenhuma');
            th.addEventListener('click', function () {
                var indice = Array.prototype.indexOf.call(ths, th);
                var atual = tabela.getAttribute('data-coluna') === String(indice)
                    ? tabela.getAttribute('data-direcao') : null;
                ordenarTabela(tabela, th, indice, atual === 'asc' ? 'desc' : 'asc');
            });
        });
    }

    document.querySelectorAll('table[data-ordenavel]').forEach(prepararTabela);
})();
