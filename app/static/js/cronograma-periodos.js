// Cronograma público: atalhos de período (barra fixa no celular).
//
// - Ao abrir o dia de hoje, rola direto para o cartão do período em curso —
//   antes era preciso deslizar manualmente pelos períodos anteriores para
//   chegar à Tarde/Noite;
// - Enquanto o usuário rola a página, o atalho do período visível fica
//   marcado (scrollspy simples por IntersectionObserver);
// - O toque num atalho desliza suavemente até o cartão do período.
(function () {
    var nav = document.querySelector('.periodo-nav');
    if (!nav) return;

    var links = Array.prototype.slice.call(nav.querySelectorAll('[data-periodo]'));
    var secoes = links
        .map(function (l) { return document.getElementById('periodo-' + l.dataset.periodo); })
        .filter(Boolean);

    function ativar(chave) {
        links.forEach(function (l) {
            var emFoco = l.dataset.periodo === chave;
            l.classList.toggle('ativo', emFoco);
            if (emFoco) l.setAttribute('aria-current', 'true');
            else l.removeAttribute('aria-current');
        });
    }

    // Toque no atalho: desliza até o cartão (o recuo fica por conta do
    // scroll-margin-top das âncoras).
    links.forEach(function (l) {
        l.addEventListener('click', function (evento) {
            var alvo = document.getElementById('periodo-' + l.dataset.periodo);
            if (!alvo) return;
            evento.preventDefault();
            ativar(l.dataset.periodo);
            alvo.scrollIntoView({ behavior: movimentoSuave() ? 'auto' : 'smooth', block: 'start' });
        });
    });

    // Scrollspy: ativo é o cartão cruzando a faixa central da tela. No fim
    // da página (dias com pouco conteúdo, em que o último cartão já aparece
    // inteiro sem rolar até o topo dele), o último período é o marcado — a
    // proporção na faixa ainda favoreceria o penúltimo.
    if ('IntersectionObserver' in window && secoes.length) {
        var visibilidade = {};
        var observador = new IntersectionObserver(function (entradas) {
            entradas.forEach(function (e) {
                visibilidade[e.target.id] = e.isIntersecting ? e.intersectionRatio : 0;
            });
            var fimDaPagina = window.innerHeight + window.scrollY >=
                              document.documentElement.scrollHeight - 4;
            if (fimDaPagina) {
                ativar(secoes[secoes.length - 1].id.replace('periodo-', ''));
                return;
            }
            var melhor = null, maior = 0;
            secoes.forEach(function (s) {
                if ((visibilidade[s.id] || 0) > maior) { maior = visibilidade[s.id]; melhor = s.id; }
            });
            if (melhor) ativar(melhor.replace('periodo-', ''));
        }, { rootMargin: '-20% 0px -45% 0px', threshold: [0, 0.2, 0.4, 0.6, 0.8, 1] });
        secoes.forEach(function (s) { observador.observe(s); });
    }

    // Hoje: começa já no período em curso. Pequena espera para o layout
    // assentar (fontes/CDN) antes de medir a posição do cartão.
    var periodoAtual = nav.dataset.periodoAtual;
    if (periodoAtual) {
        var card = document.getElementById('periodo-' + periodoAtual);
        if (card) {
            window.setTimeout(function () {
                card.scrollIntoView({ behavior: movimentoSuave() ? 'auto' : 'smooth', block: 'start' });
            }, 150);
        }
    }

    function movimentoSuave() {
        return window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    }
})();
