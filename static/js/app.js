/* ==========================================================================
   app.js - comportamentos comuns a todas as telas (JavaScript puro).
   Tudo aqui e "melhoria progressiva": sem JS as telas continuam funcionando.
   ========================================================================== */
(function () {
  'use strict';

  var $ = function (sel, raiz) { return (raiz || document).querySelector(sel); };
  var $$ = function (sel, raiz) { return Array.prototype.slice.call((raiz || document).querySelectorAll(sel)); };

  // localStorage pode falhar (modo privado, bloqueio): sempre dentro de try/catch
  function guardar(chave, valor) { try { window.localStorage.setItem(chave, valor); } catch (e) { /* ignora */ } }
  function ler(chave) { try { return window.localStorage.getItem(chave); } catch (e) { return null; } }

  // remove acentos e caixa para comparar textos ("Pecas" = "Peças")
  function normalizar(t) {
    return String(t || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
  }

  /* ---------- menu lateral (hamburguer) ---------- */
  var corpo = document.body;
  var botaoMenu = $('[data-menu-botao]');
  var sidebar = $('#sidebar');
  var principal = $('.app__main');
  var telaPequena = window.matchMedia('(max-width: 900px)');

  function menuAberto() { return telaPequena.matches ? corpo.classList.contains('menu-aberto') : !corpo.classList.contains('sidebar-recolhida'); }
  function sincronizarMenu() {
    if (!botaoMenu) { return; }
    var aberto = menuAberto();
    botaoMenu.setAttribute('aria-expanded', aberto ? 'true' : 'false');
    // com o painel aberto no celular, o resto da pagina fica inerte (teclado e leitor de tela)
    if (principal) { if (telaPequena.matches && corpo.classList.contains('menu-aberto')) { principal.setAttribute('inert', ''); } else { principal.removeAttribute('inert'); } }
  }
  function alternarMenu(abrir) {
    if (telaPequena.matches) {
      corpo.classList.toggle('menu-aberto', abrir);
      sincronizarMenu();
      if (abrir) { var primeiro = $('.sidebar__link', sidebar); if (primeiro) { primeiro.focus(); } }
      else if (botaoMenu) { botaoMenu.focus(); }
    } else {
      corpo.classList.toggle('sidebar-recolhida', !abrir);
      guardar('tm-sidebar', abrir ? 'aberta' : 'recolhida');
      sincronizarMenu();
    }
  }
  if (botaoMenu && sidebar) {
    if (ler('tm-sidebar') === 'recolhida') { corpo.classList.add('sidebar-recolhida'); }
    sincronizarMenu();
    botaoMenu.addEventListener('click', function () { alternarMenu(!menuAberto()); });
    $$('[data-menu-fechar]').forEach(function (el) { el.addEventListener('click', function () { alternarMenu(false); }); });
    telaPequena.addEventListener('change', function () { corpo.classList.remove('menu-aberto'); sincronizarMenu(); });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && telaPequena.matches && corpo.classList.contains('menu-aberto')) { alternarMenu(false); }
      // prende o foco dentro do painel enquanto ele esta aberto (celular)
      if (e.key === 'Tab' && telaPequena.matches && corpo.classList.contains('menu-aberto')) {
        var foco = $$('a[href], button:not([disabled])', sidebar).filter(function (el) { return el.offsetParent !== null; });
        if (!foco.length) { return; }
        var primeiro = foco[0], ultimo = foco[foco.length - 1];
        if (e.shiftKey && document.activeElement === primeiro) { e.preventDefault(); ultimo.focus(); }
        else if (!e.shiftKey && document.activeElement === ultimo) { e.preventDefault(); primeiro.focus(); }
      }
    });
  }

  /* ---------- menus suspensos (alertas / usuario) ---------- */
  var suspensos = $$('details[data-suspenso]');
  suspensos.forEach(function (d) {
    d.addEventListener('toggle', function () {
      if (d.open) { suspensos.forEach(function (o) { if (o !== d) { o.open = false; } }); }
    });
  });
  document.addEventListener('click', function (e) {
    suspensos.forEach(function (d) { if (d.open && !d.contains(e.target)) { d.open = false; } });
  });
  document.addEventListener('keydown', function (e) {
    if (e.key !== 'Escape') { return; }
    suspensos.forEach(function (d) { if (d.open) { d.open = false; var s = $('summary', d); if (s) { s.focus(); } } });
  });

  /* ---------- avisos (flash) dispensaveis ---------- */
  document.addEventListener('click', function (e) {
    var b = e.target.closest('[data-fechar-aviso]');
    if (b) { var aviso = b.closest('.aviso'); if (aviso) { aviso.remove(); } }
  });

  /* ---------- dialogo de confirmacao (excluir, cancelar, fechar OS) ---------- */
  var dialogo = $('#dialogo-confirmar');
  var formPendente = null;
  if (dialogo && typeof dialogo.showModal === 'function') {
    document.addEventListener('submit', function (e) {
      var f = e.target;
      if (!f || !f.matches || !f.matches('form[data-confirmar]') || f.dataset.confirmado === '1') { return; }
      e.preventDefault();
      formPendente = f;
      $('[data-dialogo-titulo]', dialogo).textContent = f.dataset.confirmarTitulo || 'Confirmar';
      $('[data-dialogo-texto]', dialogo).textContent = f.dataset.confirmar;
      var ok = $('[data-dialogo-ok]', dialogo);
      ok.textContent = f.dataset.confirmarBotao || 'Confirmar';
      var perigo = (f.dataset.confirmarTom || 'perigo') === 'perigo';
      ok.className = 'btn ' + (perigo ? 'btn--perigo-solido' : 'btn--verde');
      dialogo.returnValue = '';
      dialogo.showModal();
    }, true);
    // os dois botoes sao type="button": o envio so acontece quando o usuario clica em confirmar
    $('[data-dialogo-voltar]', dialogo).addEventListener('click', function () { dialogo.close('cancelar'); });
    $('[data-dialogo-ok]', dialogo).addEventListener('click', function () {
      var f = formPendente; formPendente = null;
      dialogo.close('confirmar');
      if (f) { f.dataset.confirmado = '1'; if (f.requestSubmit) { f.requestSubmit(); } else { f.submit(); } }
    });
    dialogo.addEventListener('close', function () { formPendente = null; });
    // clicar fora da caixa fecha (sem confirmar)
    dialogo.addEventListener('click', function (e) { if (e.target === dialogo) { dialogo.close('cancelar'); } });
  }

  /* ---------- filtros: selects enviam sozinhos; busca filtra as linhas ja carregadas ---------- */
  $$('select[data-auto-enviar]').forEach(function (s) {
    s.addEventListener('change', function () { var f = s.form; if (f) { if (f.requestSubmit) { f.requestSubmit(); } else { f.submit(); } } });
  });

  $$('input[data-filtrar-tabela], input[data-filtrar-lista]').forEach(function (campo) {
    var seletor = campo.dataset.filtrarTabela || campo.dataset.filtrarLista;
    var alvo = $(seletor);
    if (!alvo) { return; }
    var linhas = campo.dataset.filtrarTabela ? $$('tbody tr', alvo) : $$('li', alvo);
    var cartao = campo.closest('.cartao');
    var contagem = cartao ? $('[data-contagem]', cartao) : null;
    var textoOriginal = contagem ? contagem.textContent : '';
    var sufixo = textoOriginal.replace(/^\s*\d+\s*/, '');
    var aviso = document.createElement('p');
    aviso.className = 'vazio__texto centro'; aviso.hidden = true; aviso.style.padding = '16px';
    aviso.textContent = 'Nenhum resultado entre os itens carregados. Use Pesquisar para buscar em todo o cadastro.';
    alvo.parentNode.insertBefore(aviso, alvo.nextSibling);
    campo.addEventListener('input', function () {
      var termo = normalizar(campo.value).trim();
      var visiveis = 0;
      linhas.forEach(function (l) {
        var bate = !termo || normalizar(l.textContent).indexOf(termo) !== -1;
        l.hidden = !bate;
        if (bate) { visiveis += 1; }
      });
      aviso.hidden = visiveis !== 0;
      if (contagem) { contagem.textContent = visiveis + ' ' + sufixo; }
    });
    // Enter envia o formulario (busca no servidor); o filtro local so ajuda enquanto digita
  });

  /* ---------- select dependente Grupo -> Subgrupo (/api/subgrupos) ---------- */
  $$('select[data-grupo-select]').forEach(function (grupo) {
    var alvo = document.getElementById(grupo.dataset.grupoSelect);
    var url = grupo.dataset.subgruposUrl;
    if (!alvo || !url) { return; }
    function montar(lista, escolhido) {
      alvo.innerHTML = '';
      var vazio = document.createElement('option'); vazio.value = ''; vazio.textContent = 'Selecione o subgrupo'; alvo.appendChild(vazio);
      lista.forEach(function (s) {
        var o = document.createElement('option'); o.value = s.id; o.textContent = s.nome;
        if (String(s.id) === String(escolhido)) { o.selected = true; }
        alvo.appendChild(o);
      });
    }
    grupo.addEventListener('change', function () {
      var anterior = alvo.value;
      if (!grupo.value) { montar([], ''); return; }
      alvo.disabled = true;
      alvo.innerHTML = '<option value="">Carregando…</option>';
      fetch(url + '?grupo_id=' + encodeURIComponent(grupo.value), { headers: { 'Accept': 'application/json' }, credentials: 'same-origin' })
        .then(function (r) { if (!r.ok) { throw new Error('http ' + r.status); } return r.json(); })
        .then(function (lista) { montar(lista, anterior); })
        .catch(function () { alvo.innerHTML = '<option value="">Não foi possível carregar os subgrupos</option>'; })
        .then(function () { alvo.disabled = false; });
    });
  });

  /* ---------- mascaras (CNPJ, CEP, telefone) - so visual; o servidor valida ---------- */
  var mascaras = {
    cnpj: function (d) { d = d.slice(0, 14); return d.replace(/^(\d{2})(\d)/, '$1.$2').replace(/^(\d{2})\.(\d{3})(\d)/, '$1.$2.$3').replace(/\.(\d{3})(\d)/, '.$1/$2').replace(/(\d{4})(\d)/, '$1-$2'); },
    cep: function (d) { d = d.slice(0, 8); return d.replace(/^(\d{5})(\d)/, '$1-$2'); },
    telefone: function (d) {
      d = d.slice(0, 11);
      if (d.length <= 2) { return d ? '(' + d : ''; }
      if (d.length <= 6) { return '(' + d.slice(0, 2) + ') ' + d.slice(2); }
      if (d.length <= 10) { return '(' + d.slice(0, 2) + ') ' + d.slice(2, 6) + '-' + d.slice(6); }
      return '(' + d.slice(0, 2) + ') ' + d.slice(2, 7) + '-' + d.slice(7);
    }
  };
  $$('input[data-mascara]').forEach(function (inp) {
    var f = mascaras[inp.dataset.mascara];
    if (!f) { return; }
    inp.addEventListener('input', function () { inp.value = f(inp.value.replace(/\D/g, '')); });
  });

  /* ---------- usuarios: texto de ajuda do perfil escolhido ---------- */
  var descricoesPerfil = {
    'administrador': 'Acesso total ao sistema, inclusive usuários e perfis.',
    'tecnico': 'Acesso a equipamentos, peças, OS e movimentação de estoque.',
    'gestor': 'Acompanha indicadores, aprova pedidos e consulta relatórios.',
    'usuario comum': 'Abre pedidos de manutenção e acompanha o status das próprias OS.'
  };
  $$('select[data-perfil-select]').forEach(function (sel) {
    var ajuda = $('[data-perfil-ajuda]');
    if (!ajuda) { return; }
    function atualizar() {
      var op = sel.options[sel.selectedIndex];
      var t = descricoesPerfil[normalizar(op ? op.textContent : '')];
      if (t) { ajuda.textContent = t; }
    }
    sel.addEventListener('change', atualizar);
    atualizar();
  });

  /* ---------- pecas: ajuste rapido de estoque ---------- */
  var dlgEstoque = $('#dialogo-estoque');
  if (dlgEstoque && typeof dlgEstoque.showModal === 'function') {
    $$('[data-atualizar-estoque]').forEach(function (a) {
      a.addEventListener('click', function (e) {
        e.preventDefault();
        $('[data-form-estoque]', dlgEstoque).action = a.dataset.acao;
        $('[data-estoque-nome]', dlgEstoque).textContent = a.dataset.nome + ' — estoque atual: ' + a.dataset.atual;
        var campo = $('#dlg-qtde', dlgEstoque);
        campo.value = a.dataset.atual;
        dlgEstoque.showModal();
        campo.focus(); campo.select();
      });
    });
    $$('[data-fechar-dialogo]', dlgEstoque).forEach(function (b) { b.addEventListener('click', function () { dlgEstoque.close(); }); });
    dlgEstoque.addEventListener('click', function (e) { if (e.target === dlgEstoque) { dlgEstoque.close(); } });
  }

  /* ---------- estoque: codigo do item <-> descricao (peca) ---------- */
  var selPeca = $('select[data-peca-select]');
  var campoCodigo = $('input[data-codigo-item]');
  if (selPeca && campoCodigo) {
    var valor = $('#valor_unitario');
    selPeca.addEventListener('change', function () {
      var op = selPeca.options[selPeca.selectedIndex];
      campoCodigo.value = op && op.dataset.codigo ? op.dataset.codigo : '';
      if (valor && op && op.dataset.valor && (!valor.value || Number(valor.value) === 0)) { valor.value = op.dataset.valor; }
    });
    campoCodigo.addEventListener('input', function () {
      var q = normalizar(campoCodigo.value).trim();
      if (!q) { return; }
      for (var i = 0; i < selPeca.options.length; i++) {
        if (normalizar(selPeca.options[i].dataset.codigo || '') === q) { selPeca.selectedIndex = i; break; }
      }
    });
    if (selPeca.value) { var o = selPeca.options[selPeca.selectedIndex]; if (o && o.dataset.codigo && !campoCodigo.value) { campoCodigo.value = o.dataset.codigo; } }
  }

  /* ---------- configuracoes: pre-visualiza o tema na hora ---------- */
  $$('input[data-tema-opcao]').forEach(function (r) {
    r.addEventListener('change', function () { if (r.checked) { document.documentElement.setAttribute('data-theme', r.value === 'escuro' ? 'escuro' : 'claro'); } });
  });
})();
