/* ==========================================================================
   graficos.js - Dashboard e Relatorios (Chart.js empacotado em vendor/chart.umd.js).
   - Le /api/dashboard e /api/relatorios/<aba>; o botao "Atualizar" refaz o fetch.
   - Cada grafico tem uma tabela equivalente (<details>) para leitores de tela.
   - Sem animacao quando o usuario pede "reduzir movimento".
   ========================================================================== */
(function () {
  'use strict';

  var $ = function (sel, raiz) { return (raiz || document).querySelector(sel); };
  var $$ = function (sel, raiz) { return Array.prototype.slice.call((raiz || document).querySelectorAll(sel)); };
  var reduzirMovimento = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var brl = new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' });
  var brl0 = new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL', notation: 'compact', maximumFractionDigits: 1 });
  var num = new Intl.NumberFormat('pt-BR', { maximumFractionDigits: 2 });

  function css(nome) { return getComputedStyle(document.documentElement).getPropertyValue(nome).trim(); }
  function normalizar(t) { return String(t || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase().trim(); }

  // cor de cada status (uma cor por entidade, sempre a mesma) - legenda e tabela repetem o texto
  var CORES_STATUS = { 'aberta': '--viz-1', 'aberto': '--viz-1', 'em andamento': '--viz-2', 'concluida': '--viz-3', 'concluido': '--viz-3', 'cancelada': '--viz-4', 'cancelado': '--viz-4' };

  function configurarChart() {
    if (!window.Chart || configurarChart.feito) { return !!window.Chart; }
    Chart.defaults.font.family = css('--fonte-texto');
    Chart.defaults.font.size = 12;
    Chart.defaults.color = css('--texto-suave');
    Chart.defaults.animation = reduzirMovimento ? false : { duration: 450 };
    Chart.defaults.maintainAspectRatio = false;
    configurarChart.feito = true;
    return true;
  }

  /* ---------- um grafico dentro de um cartao [data-grafico] ---------- */
  function desenhar(cartao, cfg) {
    var canvas = $('canvas', cartao);
    var msg = $('[data-grafico-msg]', cartao);
    var corpoTab = $('[data-grafico-tabela]', cartao);
    var rotulos = (cfg.rotulos || []).map(String);
    var valores = (cfg.valores || []).map(Number);
    var moeda = !!cfg.moeda;
    var fmt = function (v) { return moeda ? brl.format(v) : num.format(v); };
    var existente = window.Chart && Chart.getChart(canvas);
    if (existente) { existente.destroy(); }

    // tabela acessivel (sempre preenchida, com textContent para nao interpretar HTML)
    corpoTab.innerHTML = '';
    if (!rotulos.length) {
      var tr0 = document.createElement('tr'); var td0 = document.createElement('td');
      td0.colSpan = 2; td0.className = 'mudo'; td0.textContent = 'Sem dados para os filtros escolhidos.'; tr0.appendChild(td0); corpoTab.appendChild(tr0);
    }
    rotulos.forEach(function (r, i) {
      var tr = document.createElement('tr'); var a = document.createElement('td'); var b = document.createElement('td');
      a.textContent = r; b.className = 'col-num'; b.textContent = fmt(valores[i]); tr.appendChild(a); tr.appendChild(b); corpoTab.appendChild(tr);
    });
    var tudoZero = valores.every(function (v) { return !v; });
    canvas.setAttribute('aria-label', 'Gráfico: ' + (cfg.titulo || '') + '. ' + (rotulos.length ? rotulos.map(function (r, i) { return r + ': ' + fmt(valores[i]); }).join('; ') + '.' : 'Sem dados.'));
    if (!rotulos.length || tudoZero) {
      canvas.style.visibility = 'hidden'; msg.hidden = false; msg.textContent = 'Sem dados para os filtros escolhidos.';
      return;
    }
    canvas.style.visibility = ''; msg.hidden = true;
    if (!configurarChart()) { msg.hidden = false; msg.textContent = 'Não foi possível carregar a biblioteca de gráficos. Veja os dados na tabela abaixo.'; return; }

    var superficie = css('--superficie'), grade = css('--borda'), texto = css('--texto-suave');
    var cor1 = css('--viz-1');
    var tipo = normalizar(cfg.tipo || 'bar');
    var rosca = /pie|pizza|rosca|doughnut|donut/.test(tipo);
    var linha = /line|linha/.test(tipo);
    var horizontal = /barh|horizontal|^h/.test(tipo);
    var config;

    if (rosca) {
      var cores = rotulos.map(function (r, i) { return css(CORES_STATUS[normalizar(r)] || ['--viz-1', '--viz-2', '--viz-3', '--viz-4'][i % 4]); });
      config = {
        type: 'doughnut',
        data: { labels: rotulos, datasets: [{ data: valores, backgroundColor: cores, borderColor: superficie, borderWidth: 2 }] },
        options: {
          cutout: '58%',
          plugins: {
            legend: { position: 'bottom', labels: { color: texto, padding: 14, usePointStyle: true, pointStyle: 'rectRounded',
              generateLabels: function (chart) {
                var d = chart.data;
                return d.labels.map(function (l, i) { return { text: l + ' — ' + d.datasets[0].data[i], fillStyle: d.datasets[0].backgroundColor[i], strokeStyle: d.datasets[0].backgroundColor[i], fontColor: texto, index: i, hidden: !chart.getDataVisibility(i) }; });
              } } },
            tooltip: { callbacks: { label: function (c) { return ' ' + c.label + ': ' + fmt(c.parsed); } } }
          }
        }
      };
    } else {
      var eixoValor = { beginAtZero: true, grid: { color: grade }, border: { display: false }, ticks: { color: texto, maxTicksLimit: 6, maxRotation: 0, callback: function (v) { return moeda ? brl0.format(v) : num.format(v); } } };
      var eixoCat = { grid: { display: false }, border: { color: grade }, ticks: { color: texto, callback: function (v) { var t = String(this.getLabelForValue(v)); return t.length > 22 ? t.slice(0, 21) + '…' : t; } } };
      var ds = linha
        ? { data: valores, borderColor: cor1, backgroundColor: cor1, borderWidth: 2, tension: 0.35, pointRadius: 4.5, pointHoverRadius: 6, pointBackgroundColor: cor1, pointBorderColor: superficie, pointBorderWidth: 2, fill: false }
        : { data: valores, backgroundColor: cor1, maxBarThickness: 28, borderRadius: horizontal ? { topRight: 4, bottomRight: 4 } : { topLeft: 4, topRight: 4 }, borderSkipped: false };
      config = {
        type: linha ? 'line' : 'bar',
        data: { labels: rotulos, datasets: [ds] },
        options: {
          indexAxis: horizontal ? 'y' : 'x',
          interaction: { mode: linha ? 'index' : 'nearest', intersect: false },
          scales: { x: horizontal ? eixoValor : eixoCat, y: horizontal ? eixoCat : eixoValor },
          plugins: { legend: { display: false }, tooltip: { callbacks: { label: function (c) { return ' ' + fmt(horizontal ? c.parsed.x : c.parsed.y); } } } }
        }
      };
      // barras horizontais com muitos itens: aumenta a altura para nao espremer
      var area = $('.grafico', cartao);
      if (horizontal && area) { area.style.setProperty('--altura', Math.max(300, rotulos.length * 36 + 70) + 'px'); }
    }
    new Chart(canvas, config);
  }

  /* ---------- helpers de rede ---------- */
  function buscar(url) {
    return fetch(url, { headers: { 'Accept': 'application/json' }, credentials: 'same-origin' }).then(function (r) {
      if (!r.ok) { throw new Error('Erro ' + r.status); }
      return r.json();
    });
  }
  function parametros(form, extras) {
    var p = new URLSearchParams();
    new FormData(form).forEach(function (v, k) { if (v !== '' && k !== 'csrf_token' && k !== 'aba') { p.set(k, v); } });
    if (extras) { Object.keys(extras).forEach(function (k) { p.set(k, extras[k]); }); }
    return p;
  }
  function hora() { var d = new Date(); return ('0' + d.getHours()).slice(-2) + ':' + ('0' + d.getMinutes()).slice(-2); }
  function cartaoDe(id) { return $('[data-grafico="' + id + '"]'); }

  /* ==================== DASHBOARD ==================== */
  var formDash = $('form[data-dashboard]');
  if (formDash) {
    var statusDash = $('[data-status-dash]');
    var API_DASH = formDash.dataset.api;
    var CONF = {
      tempo_medio: { tipo: 'line' },
      custo_por_maquina: { tipo: 'barh', moeda: true },
      pecas_mais_usadas: { tipo: 'barh' },
      status_ordens: { tipo: 'doughnut' }
    };

    var aplicarKpis = function (kpis) {
      if (!kpis) { return; }
      var alias = { os_concluidas: ['os_concluidas', 'os_concluidas_mes', 'concluidas'], pedidos_abertos: ['pedidos_abertos', 'abertos'], os_andamento: ['os_andamento', 'em_andamento', 'andamento'], custo_total: ['custo_total', 'custo'] };
      var porChave = {};
      (Array.isArray(kpis.cards) ? kpis.cards : []).forEach(function (c) { if (c && c.chave) { porChave[c.chave] = c; } });
      $$('[data-kpi]').forEach(function (card) {
        var id = card.dataset.kpi, k;
        if (porChave[id]) {
          var c = porChave[id];
          $('[data-kpi-valor]', card).textContent = c.valor_fmt !== undefined && c.valor_fmt !== null ? c.valor_fmt : c.valor;
          if (c.detalhe !== undefined && c.detalhe !== null) { $('[data-kpi-detalhe]', card).textContent = c.detalhe; }
          return;
        }
        (alias[id] || [id]).some(function (nome) { if (kpis[nome] !== undefined) { k = kpis[nome]; return true; } return false; });
        if (k === undefined) { return; }
        var valor = k, detalhe;
        if (k !== null && typeof k === 'object') { valor = k.valor_fmt !== undefined ? k.valor_fmt : k.valor; detalhe = k.detalhe !== undefined ? k.detalhe : k.detalhe_fmt; }
        if (typeof valor === 'number') { valor = id === 'custo_total' ? brl0.format(valor) : num.format(valor); }
        $('[data-kpi-valor]', card).textContent = valor;
        if (detalhe !== undefined) { $('[data-kpi-detalhe]', card).textContent = detalhe; }
      });
    };

    var aplicarDash = function (dados) {
      Object.keys(CONF).forEach(function (chave) {
        var cartao = cartaoDe(chave);
        if (!cartao) { return; }
        var serie = dados[chave] || [];
        desenhar(cartao, {
          titulo: $('h2', cartao).textContent, tipo: CONF[chave].tipo, moeda: CONF[chave].moeda,
          rotulos: serie.map(function (x) { return x.rotulo; }), valores: serie.map(function (x) { return x.valor; })
        });
      });
      aplicarKpis(dados.kpis);
    };

    var atualizarLinks = function (qs) {
      $$('a[data-exportar]').forEach(function (a) { a.href = a.href.split('?')[0] + (qs ? '?' + qs : ''); });
    };
    var textoSelecionado = function (id, padrao) { var s = document.getElementById(id); return s && s.value ? s.options[s.selectedIndex].textContent : padrao; };

    var carregarDash = function (porUsuario) {
      var qs = parametros(formDash).toString();
      var botao = $('button[form="form-filtros-dash"]');
      if (botao) { botao.disabled = true; }
      if (statusDash) { statusDash.textContent = 'Atualizando indicadores…'; }
      buscar(API_DASH + (qs ? '?' + qs : '')).then(function (dados) {
        aplicarDash(dados);
        atualizarLinks(qs);
        try { history.replaceState(null, '', location.pathname + (qs ? '?' + qs : '')); } catch (e) { /* ignora */ }
        if (porUsuario) {
          var sub = $('.pagina-cab__sub');
          if (sub) { sub.textContent = textoSelecionado('periodo', '') + ' · ' + textoSelecionado('departamento_id', 'Todos os departamentos') + (document.getElementById('equipamento_id').value ? ' · ' + textoSelecionado('equipamento_id', '') : ''); }
        }
        if (statusDash) { statusDash.textContent = 'Indicadores atualizados às ' + hora() + '.'; }
      }).catch(function () {
        if (statusDash) { statusDash.textContent = 'Não foi possível atualizar os indicadores. Tente novamente.'; }
        $$('[data-grafico-msg]').forEach(function (m) { m.hidden = false; m.textContent = 'Não foi possível carregar os dados. Clique em Atualizar para tentar de novo.'; });
      }).then(function () { if (botao) { botao.disabled = false; } });
    };

    formDash.addEventListener('submit', function (e) { e.preventDefault(); carregarDash(true); });
    $$('select', formDash).forEach(function (s) { s.addEventListener('change', function () { carregarDash(true); }); });
    var iniciarDash = function () { carregarDash(false); };
    if (window.Chart) { iniciarDash(); } else { window.addEventListener('load', iniciarDash); }
  }

  /* ==================== RELATORIOS ==================== */
  var formRel = $('form[data-relatorios]');
  if (formRel) {
    var painel = $('[data-painel]');
    var abas = $('[data-abas]');
    var zonaGraficos = $('[data-graficos]');
    var zonaTabela = $('[data-tabela]');
    var statusRel = $('[data-status-rel]');
    var campoAba = $('input[name="aba"]', formRel);
    var abaAtual = campoAba.value;
    var TONS = { 'aberta': 'info', 'aberto': 'info', 'em andamento': 'aviso', 'concluida': 'ok', 'concluido': 'ok', 'cancelada': 'neutro', 'cancelado': 'neutro' };

    var cardGrafico = function (g) {
      var sec = document.createElement('section');
      sec.className = 'cartao grafico-cartao'; sec.dataset.grafico = g.id; sec.setAttribute('aria-labelledby', 'gt-' + g.id);
      var h = document.createElement('h2'); h.className = 'cartao__titulo'; h.id = 'gt-' + g.id; h.textContent = g.titulo;
      var area = document.createElement('div'); area.className = 'grafico';
      var cv = document.createElement('canvas'); cv.id = 'canvas-' + g.id; cv.setAttribute('role', 'img');
      var msg = document.createElement('p'); msg.className = 'grafico__msg'; msg.hidden = true; msg.setAttribute('data-grafico-msg', '');
      area.appendChild(cv); area.appendChild(msg);
      var det = document.createElement('details'); det.className = 'recolher';
      var sum = document.createElement('summary'); sum.textContent = 'Ver dados em tabela'; det.appendChild(sum);
      var wrap = document.createElement('div'); wrap.className = 'tabela-wrap'; wrap.tabIndex = 0; wrap.setAttribute('role', 'region'); wrap.setAttribute('aria-label', 'Dados do gráfico ' + g.titulo);
      var tb = document.createElement('table'); tb.className = 'tabela tabela--compacta';
      tb.innerHTML = '<thead><tr><th>Item</th><th class="col-num">Valor</th></tr></thead><tbody data-grafico-tabela></tbody>';
      wrap.appendChild(tb); det.appendChild(wrap);
      sec.appendChild(h); sec.appendChild(area); sec.appendChild(det);
      return sec;
    };

    var ehNumero = function (c) { return typeof c === 'number' || /^(R\$\s?)?-?[\d.,]+%?$/.test(String(c).trim()); };
    var celula = function (tag, valor, colNome, alinha) {
      var td = document.createElement(tag);
      var t = valor === null || valor === undefined || valor === '' ? '—' : String(valor);
      if (tag === 'td' && normalizar(colNome) === 'status' && TONS[normalizar(t)]) {
        var b = document.createElement('span'); b.className = 'badge badge--' + TONS[normalizar(t)]; b.textContent = t; td.appendChild(b);
      } else { td.textContent = t; }
      if (tag === 'td' && (alinha === 'dir' || (alinha !== 'esq' && ehNumero(valor) && t !== '—'))) { td.className = 'col-num nowrap'; }
      return td;
    };

    var desenharTabela = function (tabela) {
      zonaTabela.innerHTML = '';
      var colunas = (tabela && tabela.colunas) || [], linhas = (tabela && tabela.linhas) || [], alin = (tabela && tabela.alinhamentos) || [];
      var tituloTab = $('[data-titulo-tabela]');
      if (tituloTab && tabela && tabela.titulo) { tituloTab.textContent = tabela.titulo; }
      if (!linhas.length) {
        zonaTabela.innerHTML = '<div class="vazio"><p class="vazio__titulo">Sem dados para os filtros escolhidos</p><p class="vazio__texto">Tente outro período, departamento ou técnico.</p></div>';
        return;
      }
      var wrap = document.createElement('div'); wrap.className = 'tabela-wrap'; wrap.tabIndex = 0; wrap.setAttribute('role', 'region'); wrap.setAttribute('aria-label', 'Tabela do relatório');
      var t = document.createElement('table'); t.className = 'tabela';
      var nomes = colunas.map(function (c) { return typeof c === 'object' ? (c.rotulo || c.nome) : c; });
      var chaves = colunas.map(function (c, i) { return typeof c === 'object' ? (c.chave || c.rotulo) : i; });
      var thead = document.createElement('thead'), trh = document.createElement('tr');
      nomes.forEach(function (n, i) { var th = document.createElement('th'); th.textContent = n; if (alin[i] === 'dir') { th.className = 'col-num'; } trh.appendChild(th); });
      thead.appendChild(trh); t.appendChild(thead);
      var tbody = document.createElement('tbody');
      linhas.forEach(function (l) {
        var tr = document.createElement('tr');
        chaves.forEach(function (k, i) { tr.appendChild(celula('td', l[k], nomes[i], alin[i])); });
        tbody.appendChild(tr);
      });
      t.appendChild(tbody);
      if (tabela.rodape && tabela.rodape.length) {
        var tf = document.createElement('tfoot'), trf = document.createElement('tr');
        tabela.rodape.forEach(function (c, i) { var td = celula('td', c, '', alin[i]); trf.appendChild(td); });
        tf.appendChild(trf); t.appendChild(tf);
      }
      wrap.appendChild(t); zonaTabela.appendChild(wrap);
    };

    var desenharGraficos = function (graficos, reconstruir) {
      if (reconstruir) {
        $$('canvas', zonaGraficos).forEach(function (c) { var ch = window.Chart && Chart.getChart(c); if (ch) { ch.destroy(); } });
        zonaGraficos.innerHTML = '';
        (graficos || []).forEach(function (g) { zonaGraficos.appendChild(cardGrafico(g)); });
      }
      (graficos || []).forEach(function (g) {
        var cartao = cartaoDe(g.id);
        if (!cartao) { return; }
        var moeda = g.unidade !== undefined ? /R\$/.test(g.unidade) : /R\$|custo|valor/i.test(g.titulo || '');
        desenhar(cartao, { titulo: g.titulo, tipo: g.tipo, moeda: moeda, rotulos: g.rotulos, valores: g.valores });
      });
    };

    var linksExportacao = function (aba, qs) {
      $$('a[data-exportar]').forEach(function (a) {
        a.href = a.href.split('/relatorios/')[0] + '/relatorios/' + aba + '/exportar.' + a.dataset.exportar + '?aba=' + aba + (qs ? '&' + qs : '');
      });
    };

    var carregarRel = function (aba, empurrar) {
      var qs = parametros(formRel).toString();
      var url = formRel.dataset.api.replace(/[^/]+$/, aba) + (qs ? '?' + qs : '');
      if (statusRel) { statusRel.textContent = 'Atualizando relatório…'; }
      buscar(url).then(function (dados) {
        abaAtual = aba; campoAba.value = aba;
        $$('[role="tab"]', abas).forEach(function (t) {
          var sel = t.dataset.aba === aba;
          t.setAttribute('aria-selected', sel ? 'true' : 'false'); t.tabIndex = sel ? 0 : -1;
          t.href = formRel.dataset.urlBase + '?aba=' + t.dataset.aba + (qs ? '&' + qs : '');
        });
        painel.setAttribute('aria-labelledby', 'aba-' + aba);
        desenharGraficos(dados.graficos, true);
        desenharTabela(dados.tabela);
        linksExportacao(aba, qs);
        if (empurrar) { try { history.pushState({ aba: aba }, '', formRel.dataset.urlBase + '?aba=' + aba + (qs ? '&' + qs : '')); } catch (e) { /* ignora */ } }
        else { try { history.replaceState({ aba: aba }, '', location.pathname + '?aba=' + aba + (qs ? '&' + qs : '')); } catch (e) { /* ignora */ } }
        if (statusRel) { statusRel.textContent = 'Relatório atualizado às ' + hora() + '.'; }
      }).catch(function () {
        if (statusRel) { statusRel.textContent = 'Não foi possível atualizar o relatório. Tente novamente.'; }
        $$('[data-grafico-msg]').forEach(function (m) { m.hidden = false; m.textContent = 'Não foi possível carregar os dados. Clique em Atualizar para tentar de novo.'; });
      });
    };

    formRel.addEventListener('submit', function (e) { e.preventDefault(); carregarRel(abaAtual, false); });

    // abas: clique + setas/Home/End (padrao ARIA de abas com ativacao automatica)
    var listaAbas = $$('[role="tab"]', abas);
    listaAbas.forEach(function (t) {
      t.addEventListener('click', function (e) { e.preventDefault(); if (t.dataset.aba !== abaAtual) { carregarRel(t.dataset.aba, true); } });
      t.addEventListener('keydown', function (e) {
        var i = listaAbas.indexOf(t), alvo = null;
        if (e.key === 'ArrowRight') { alvo = listaAbas[(i + 1) % listaAbas.length]; }
        else if (e.key === 'ArrowLeft') { alvo = listaAbas[(i - 1 + listaAbas.length) % listaAbas.length]; }
        else if (e.key === 'Home') { alvo = listaAbas[0]; }
        else if (e.key === 'End') { alvo = listaAbas[listaAbas.length - 1]; }
        if (alvo) { e.preventDefault(); alvo.focus(); alvo.click(); }
      });
    });
    window.addEventListener('popstate', function (e) {
      var aba = (e.state && e.state.aba) || new URLSearchParams(location.search).get('aba') || 'os';
      carregarRel(aba, false);
    });

    // desenho inicial com os dados que o servidor ja embutiu na pagina
    var iniciarRel = function () {
      var bruto = $('#dados-relatorio'), dados = null;
      try { dados = bruto ? JSON.parse(bruto.textContent) : null; } catch (e) { dados = null; }
      if (dados) { desenharGraficos(dados.graficos, false); } else { carregarRel(abaAtual, false); }
    };
    if (window.Chart) { iniciarRel(); } else { window.addEventListener('load', iniciarRel); }
  }
})();
