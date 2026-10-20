/* Detecção da unidade pública mais próxima pela geolocalização do visitante.
 *
 * Usada no portal público (cronograma e busca de aula): o botão
 * [data-unity-detect] pede a posição do visitante, encontra a unidade mais
 * próxima entre as cadastradas em window.SIGERE_UNIDADES_PUBLICAS (somente as
 * que têm coordenadas) e recarrega a página com ?unity=<id>, preservando os
 * demais parâmetros da URL (data, q...). Sem o pedido de permissão do
 * navegador, nada acontece — a escolha manual pela lista segue funcionando.
 */
(function () {
    'use strict';

    var unidades = window.SIGERE_UNIDADES_PUBLICAS || [];
    var RAIO_TERRA_KM = 6371;

    function distanciaKm(lat1, lng1, lat2, lng2) {
        var rad = Math.PI / 180;
        var dLat = (lat2 - lat1) * rad;
        var dLng = (lng2 - lng1) * rad;
        var a = Math.sin(dLat / 2) * Math.sin(dLat / 2) +
                Math.cos(lat1 * rad) * Math.cos(lat2 * rad) *
                Math.sin(dLng / 2) * Math.sin(dLng / 2);
        return RAIO_TERRA_KM * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
    }

    function maisProxima(lat, lng) {
        var melhor = null;
        var menor = Infinity;
        unidades.forEach(function (u) {
            if (u.lat === null || u.lng === null) return;
            var d = distanciaKm(lat, lng, u.lat, u.lng);
            if (d < menor) { menor = d; melhor = u; }
        });
        return melhor;
    }

    function urlComUnidade(id) {
        var url = new URL(window.location.href);
        url.searchParams.set('unity', String(id));
        return url.toString();
    }

    function aviso(mensagem) {
        var container = document.querySelector('.toast-container');
        if (!container) {
            container = document.createElement('div');
            container.className = 'toast-container position-fixed bottom-0 start-50 translate-middle-x p-3';
            document.body.appendChild(container);
        }
        var toastEl = document.createElement('div');
        toastEl.className = 'toast align-items-center text-bg-danger border-0';
        toastEl.setAttribute('role', 'alert');
        toastEl.innerHTML = '<div class="d-flex"><div class="toast-body">' + mensagem +
            '</div><button type="button" class="btn-close btn-close-white me-2 m-auto" ' +
            'data-bs-dismiss="toast" aria-label="Fechar"></button></div>';
        container.appendChild(toastEl);
        toastEl.addEventListener('hidden.bs.toast', function () { toastEl.remove(); });
        bootstrap.Toast.getOrCreateInstance(toastEl).show();
    }

    function detectar(botao) {
        if (!('geolocation' in navigator)) {
            aviso('Seu navegador não permite detectar sua localização. Escolha a unidade na lista.');
            return;
        }
        var rotulo = botao.innerHTML;
        function restaurar(mensagem) {
            botao.disabled = false;
            botao.innerHTML = rotulo;
            aviso(mensagem);
        }
        botao.disabled = true;
        botao.innerHTML = '<span class="spinner-border spinner-border-sm me-1" aria-hidden="true"></span>Detectando...';
        navigator.geolocation.getCurrentPosition(function (posicao) {
            var alvo = maisProxima(posicao.coords.latitude, posicao.coords.longitude);
            if (!alvo) {
                restaurar('Nenhuma unidade possui coordenadas cadastradas.');
                return;
            }
            // replace: a página com a unidade escolhida substitui a atual no
            // histórico, para o botão "voltar" não reabrir a página sem a
            // unidade detectada.
            window.location.replace(urlComUnidade(alvo.id));
        }, function (erro) {
            restaurar({
                1: 'Permissão de localização negada. Escolha a unidade na lista.',
                2: 'Não foi possível obter sua localização agora. Tente novamente.',
                3: 'Tempo esgotado ao obter sua localização. Tente novamente.'
            }[erro.code] || 'Falha ao detectar sua localização.');
        }, { enableHighAccuracy: false, timeout: 10000, maximumAge: 300000 });
    }

    // Delegação no document: o menu dropdown é reaberto/recriado pelo Bootstrap.
    document.addEventListener('click', function (evento) {
        var botao = evento.target.closest('[data-unity-detect]');
        if (botao) detectar(botao);
    });
})();
