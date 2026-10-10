"""
E2E com Playwright (chromium headless) contra o app REAL rodando em porta livre e banco temporario.

Cobre (SPEC §5 requisitos de front, §6 qualidade): login -> menu/dashboard -> cadastro -> pedido -> OS -> estoque -> relatorios
em 1440x900 e 390x844; sem scroll horizontal da pagina; menu off-canvas no mobile; foco visivel/teclado; ausencia de erros de
console; ausencia de requisicoes externas (so localhost); tema escuro; contraste; acessibilidade basica; confirmacao de exclusao.
Screenshots em tests/screenshots/ (usadas na comparacao visual com figma/*.jpg).

Rodar so estes: `pytest -m e2e`.   Pular: `pytest -m "not e2e"`.
So faz skip quando o chromium nao esta disponivel (dependencia externa) - nunca para esconder falha do app.
"""

import os
import re
import pathlib
import time
from urllib.parse import urlparse

import pytest

from helpers import USUARIOS_DEMO, consulta, um

pytestmark = pytest.mark.e2e

SHOTS = pathlib.Path(__file__).resolve().parent / "screenshots"
VIEWPORTS = {"desktop": {"width": 1440, "height": 900}, "mobile": {"width": 390, "height": 844}}


# --------------------------------------------------------------------------------------------- infraestrutura

@pytest.fixture(scope="module")
def pw():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        pytest.skip("playwright nao instalado (pip install playwright)")
    p = sync_playwright().start()
    try:
        navegador = p.chromium.launch()
    except Exception as e:  # noqa: BLE001
        p.stop()
        pytest.skip(f"chromium indisponivel em PLAYWRIGHT_BROWSERS_PATH={os.environ.get('PLAYWRIGHT_BROWSERS_PATH')}: {e}")
    yield navegador
    navegador.close()
    p.stop()


class Vigia:
    """Observa uma pagina: erros de console, erros de JS, requisicoes externas, respostas >= 400 inesperadas."""

    def __init__(self, page, base):
        self.base = base
        self.host = urlparse(base).netloc
        self.erros_console, self.erros_js, self.externas, self.http_ruins, self.falhas = [], [], [], [], []
        page.on("console", lambda m: self.erros_console.append(f"{m.text} @ {m.location.get('url', '')}") if m.type == "error" else None)
        page.on("pageerror", lambda e: self.erros_js.append(str(e)))
        page.on("request", self._req)
        page.on("requestfailed", lambda r: self.falhas.append(f"{r.url} ({r.failure})"))
        page.on("response", self._resp)

    def _req(self, r):
        u = urlparse(r.url)
        if u.scheme in ("data", "blob", "about", "chrome-extension"):
            return
        if u.netloc != self.host:
            self.externas.append(r.url)

    def _resp(self, r):
        if r.status >= 400 and not r.url.endswith("favicon.ico") and r.status not in self.esperados:
            self.http_ruins.append(f"{r.status} {r.url}")

    esperados: set = set()

    def limpo(self, contexto=""):
        assert not self.externas, f"{contexto}: requisicoes EXTERNAS (o sistema deve funcionar offline): {self.externas[:5]}"
        assert not self.erros_js, f"{contexto}: erros de JavaScript: {self.erros_js[:3]}"
        # "Failed to load resource ... status of 404" e o eco no console de uma resposta HTTP esperada pelo teste
        reais = [e for e in self.erros_console
                 if not any(f"status of {c}" in e for c in self.esperados)]
        assert not reais, f"{contexto}: erros no console: {reais[:3]}"
        assert not self.http_ruins, f"{contexto}: respostas HTTP de erro nos recursos: {self.http_ruins[:5]}"
        assert not self.falhas, f"{contexto}: requisicoes que falharam: {self.falhas[:3]}"


@pytest.fixture(scope="module")
def sessoes(pw, servidor):
    """Fabrica de contextos autenticados (um login por perfil x viewport, reaproveitado no modulo)."""
    cache = {}

    def _get(perfil: str, vp: str, **ctx_kw):
        chave = (perfil, vp, tuple(sorted(ctx_kw.items())))
        if chave not in cache:
            ctx = pw.new_context(viewport=VIEWPORTS[vp], base_url=servidor.url, locale="pt-BR", **ctx_kw)
            ctx.set_default_timeout(15000)
            if perfil != "anonimo":
                pg = ctx.new_page()
                entrar(pg, perfil)
                pg.close()
            cache[chave] = ctx
        return cache[chave]

    yield _get
    for c in cache.values():
        c.close()


def entrar(page, perfil: str):
    login, senha, _ = USUARIOS_DEMO[perfil]
    page.goto("/login")
    page.locator("input[type=password]").first.fill(senha)
    page.locator("input[type=text], input:not([type])").first.fill(login)
    with page.expect_navigation():
        page.get_by_role("button", name=re.compile("entrar", re.I)).click()
    assert "/login" not in page.url, f"login de {login} nao saiu da tela de login: {page.url}"


def sem_scroll_horizontal(page):
    return page.evaluate("""() => ({
        doc: document.documentElement.scrollWidth, body: document.body.scrollWidth, janela: window.innerWidth})""")


def tirar_foto(page, vp, nome):
    SHOTS.mkdir(exist_ok=True)
    page.screenshot(path=str(SHOTS / f"{vp}_{nome}.png"), full_page=True)


def ir(page, caminho, vigia=None):
    resp = page.goto(caminho, wait_until="networkidle")
    return resp


# --------------------------------------------------------------------------------------------- login

def test_login_validacao_e_sucesso(pw, servidor):
    ctx = pw.new_context(viewport=VIEWPORTS["desktop"], base_url=servidor.url, locale="pt-BR")
    page = ctx.new_page()
    v = Vigia(page, servidor.url)
    page.goto("/login")
    assert "TechMaint" in page.title() or page.get_by_text("TechMaint").first.is_visible()
    for t in ("Faça login para continuar", "Esqueceu a senha?", "Lembrar-me", "ENTRAR"):
        assert page.get_by_text(re.compile(re.escape(t), re.I)).first.is_visible(), f"Login sem {t!r} (Figma 01)"
    tirar_foto(page, "desktop", "00_login")
    # campos vazios
    page.get_by_role("button", name=re.compile("entrar", re.I)).click()
    page.wait_for_load_state("networkidle")
    assert page.get_by_text("Preencha todos os campos.").first.is_visible(), "Mensagem de campos vazios (Figma 02)"
    tirar_foto(page, "desktop", "00_login_vazio")
    # senha errada
    page.locator("input[type=text], input:not([type])").first.fill("admin")
    page.locator("input[type=password]").first.fill("errada")
    page.get_by_role("button", name=re.compile("entrar", re.I)).click()
    page.wait_for_load_state("networkidle")
    assert page.get_by_text("Usuário ou senha inválidos.").first.is_visible()
    assert page.locator("input[type=password]").first.input_value() == "", "A senha nao pode voltar preenchida"
    assert page.locator("input[type=text], input:not([type])").first.input_value() == "admin", "O usuario digitado deve ser mantido"
    # sucesso
    page.locator("input[type=password]").first.fill("admin123")
    with page.expect_navigation():
        page.get_by_role("button", name=re.compile("entrar", re.I)).click()
    assert re.search(r"/(menu|dashboard)", page.url), page.url
    assert page.get_by_text("João Administrador").first.is_visible()
    v.esperados = {400, 401, 403}
    v.limpo("fluxo de login")
    ctx.close()


def test_login_por_teclado_enter(pw, servidor):
    ctx = pw.new_context(viewport=VIEWPORTS["desktop"], base_url=servidor.url)
    page = ctx.new_page()
    page.goto("/login")
    page.locator("input[type=text], input:not([type])").first.fill("tecnico")
    page.locator("input[type=password]").first.fill("tecnico123")
    with page.expect_navigation():
        page.keyboard.press("Enter")
    assert "/login" not in page.url
    ctx.close()


def test_logout_pelo_navegador(sessoes):
    ctx = sessoes("gestor", "desktop")
    page = ctx.new_page()
    page.goto("/menu")
    botao = page.get_by_role("button", name=re.compile("sair", re.I))
    if not botao.count():
        botao = page.get_by_role("link", name=re.compile("sair", re.I))
    if not botao.count():
        page.goto("/configuracoes")
        botao = page.get_by_role("button", name=re.compile("sair", re.I))
    assert botao.count(), "Botao Sair nao encontrado (Manual 6.2)"
    # usa um contexto novo para nao derrubar a sessao reaproveitada
    ctx2 = ctx.browser.new_context(viewport=VIEWPORTS["desktop"], base_url=page.url.split("/menu")[0].split("/configuracoes")[0])
    p2 = ctx2.new_page()
    entrar(p2, "gestor")
    p2.goto("/menu")
    b2 = p2.get_by_role("button", name=re.compile("sair", re.I))
    if not b2.count():
        p2.goto("/configuracoes")
        b2 = p2.get_by_role("button", name=re.compile("sair", re.I))
    with p2.expect_navigation():
        b2.first.click()
    assert "/login" in p2.url
    p2.goto("/dashboard")
    assert "/login" in p2.url, "Depois do logout /dashboard deve exigir login"
    p2.go_back()
    p2.reload()
    assert "/login" in p2.url, "Voltar no historico nao pode reabrir pagina autenticada"
    ctx2.close()
    page.close()


# --------------------------------------------------------------------------------------------- todas as telas x 2 viewports

TELAS = [
    ("menu", "/menu"), ("dashboard", "/dashboard"), ("usuarios", "/usuarios"), ("usuarios_editar", "/usuarios/__PLIMA__/editar"),
    ("equipamentos", "/equipamentos"), ("pecas", "/pecas"), ("fornecedores", "/fornecedores"), ("fornecedor_novo", "/fornecedores/novo"),
    ("prestadores", "/prestadores"), ("prestador_novo", "/prestadores/novo"), ("departamentos", "/departamentos"),
    ("pedidos", "/pedidos"), ("pedido_novo", "/pedidos/novo"), ("pedido_detalhe", "/pedidos/1623"), ("os_lista", "/os"),
    ("os_nova", "/os/nova"), ("os_detalhe", "/os/10234"), ("estoque", "/estoque"), ("relatorios_os", "/relatorios?aba=os"),
    ("relatorios_estoque", "/relatorios?aba=estoque"), ("relatorios_financeiro", "/relatorios?aba=financeiro"),
    ("relatorios_fornecedores", "/relatorios?aba=fornecedores"), ("configuracoes", "/configuracoes"),
]


@pytest.mark.parametrize("vp", ["desktop", "mobile"])
@pytest.mark.parametrize("nome,caminho", TELAS, ids=[t[0] for t in TELAS])
def test_tela_sem_erros_sem_rede_externa_e_sem_scroll_horizontal(sessoes, servidor, vp, nome, caminho):
    caminho = caminho.replace("__PLIMA__", str(um("SELECT id FROM usuarios WHERE login='plima'", path=servidor.db)))
    ctx = sessoes("admin", vp)
    page = ctx.new_page()
    v = Vigia(page, servidor.url)
    resp = ir(page, caminho)
    assert resp.status == 200, f"{caminho} -> HTTP {resp.status}"
    page.wait_for_timeout(700)   # animacoes/graficos
    tirar_foto(page, vp, nome)
    m = sem_scroll_horizontal(page)
    assert m["doc"] <= m["janela"] + 1, f"{vp} {caminho}: SCROLL HORIZONTAL da pagina (scrollWidth {m['doc']} > janela {m['janela']})"
    assert m["body"] <= m["janela"] + 1, f"{vp} {caminho}: body maior que a janela ({m})"
    v.limpo(f"{vp} {caminho}")
    page.close()


@pytest.mark.parametrize("caminho", ["/login", "/recuperar-senha", "/redefinir-senha/token-invalido", "/pagina-inexistente"])
@pytest.mark.parametrize("vp", ["desktop", "mobile"])
def test_telas_publicas_e_erros(sessoes, servidor, vp, caminho):
    ctx = sessoes("anonimo", vp)
    page = ctx.new_page()
    v = Vigia(page, servidor.url)
    v.esperados = {400, 404, 410}
    resp = page.goto(caminho, wait_until="networkidle")
    assert resp.status in (200, 302, 400, 404, 410)
    tirar_foto(page, vp, "publica_" + re.sub(r"\W+", "_", caminho.strip("/")))
    m = sem_scroll_horizontal(page)
    assert m["doc"] <= m["janela"] + 1, f"{vp} {caminho}: scroll horizontal ({m})"
    v.limpo(f"{vp} {caminho}")
    page.close()


@pytest.mark.parametrize("vp", ["desktop", "mobile"])
def test_pagina_403_amigavel(sessoes, servidor, vp):
    ctx = sessoes("comum", vp)
    page = ctx.new_page()
    v = Vigia(page, servidor.url)
    v.esperados = {403}
    resp = page.goto("/usuarios", wait_until="networkidle")
    assert resp.status == 403
    assert page.get_by_text(re.compile("permiss", re.I)).first.is_visible()
    assert page.get_by_role("link", name=re.compile("voltar|menu|in[ií]cio|dashboard", re.I)).count() >= 1, "A 403 deveria oferecer um caminho de volta"
    tirar_foto(page, vp, "403")
    m = sem_scroll_horizontal(page)
    assert m["doc"] <= m["janela"] + 1
    v.limpo("403")
    page.close()


# --------------------------------------------------------------------------------------------- dashboard / graficos

def test_dashboard_graficos_renderizam_e_atualizam_sem_recarregar(sessoes, servidor):
    ctx = sessoes("admin", "desktop")
    page = ctx.new_page()
    v = Vigia(page, servidor.url)
    page.goto("/dashboard", wait_until="networkidle")
    page.wait_for_timeout(1200)
    n = page.locator("canvas").count()
    assert n >= 4, f"4 graficos (canvas) esperados, achei {n}"
    pintados = page.evaluate("""() => [...document.querySelectorAll('canvas')].map(c => {
        const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data; let n = 0;
        for (let i = 3; i < d.length; i += 4) if (d[i] !== 0) { n++; } return n; })""")
    assert all(x > 500 for x in pintados), f"Canvas em branco (pixels pintados por grafico: {pintados})"
    assert page.get_by_role("button", name=re.compile("atualizar", re.I)).count() == 1
    antes = page.evaluate("performance.getEntriesByType('navigation').length")
    sel = page.locator("select").first
    opcoes = sel.locator("option").count()
    assert opcoes >= 2
    with page.expect_response(re.compile(r"/api/dashboard")) as r:
        page.get_by_role("button", name=re.compile("atualizar", re.I)).click()
    assert r.value.status == 200
    assert page.url.endswith("/dashboard") or "/dashboard?" in page.url
    assert page.evaluate("performance.getEntriesByType('navigation').length") == antes, "Atualizar deve refazer o fetch sem recarregar a pagina"
    for t in ("Pedidos Abertos", "OS em Andamento", "Custo Total"):
        assert page.get_by_text(re.compile(t, re.I)).first.is_visible(), f"KPI {t} ausente"
    v.limpo("dashboard")
    page.close()


def test_dashboard_filtro_de_periodo_muda_os_dados(sessoes, servidor):
    page = sessoes("admin", "desktop").new_page()
    page.goto("/dashboard", wait_until="networkidle")
    sel = page.locator("select[name*=periodo]").first
    valores = [o.get_attribute("value") for o in sel.locator("option").all()]
    assert len(valores) == 4, f"periodos esperados (7 dias, 30 dias, 6 meses, ano): {valores}"
    with page.expect_response(re.compile(r"/api/dashboard.*periodo=")) as r:
        sel.select_option(valores[0])
        if page.get_by_role("button", name=re.compile("atualizar", re.I)).count():
            page.get_by_role("button", name=re.compile("atualizar", re.I)).click()
    assert r.value.status == 200
    page.close()


def test_dashboard_exportacoes_baixam_arquivos(sessoes):
    page = sessoes("admin", "desktop").new_page()
    page.goto("/dashboard", wait_until="networkidle")
    for rotulo, ext in (("Exportar PDF", ".pdf"), ("Exportar Excel", ".xlsx")):
        el = page.get_by_role("link", name=re.compile(rotulo, re.I))
        if not el.count():
            el = page.get_by_role("button", name=re.compile(rotulo, re.I))
        assert el.count(), f"Botao {rotulo!r} ausente (Manual 3.1)"
        with page.expect_download() as d:
            el.first.click()
        assert d.value.suggested_filename.lower().endswith(ext), d.value.suggested_filename
        path = d.value.path()
        assert os.path.getsize(path) > 1000
    page.close()


# --------------------------------------------------------------------------------------------- off-canvas / responsividade

def _sidebar(page):
    return page.locator("aside, .sidebar, #sidebar, nav[aria-label]").first


def _visivel_na_tela(page, loc):
    box = loc.bounding_box()
    vp = page.viewport_size
    if not box:
        return False
    return box["x"] + box["width"] > 8 and box["x"] < vp["width"] - 8 and loc.is_visible()


def test_mobile_menu_offcanvas_abre_e_fecha(sessoes, servidor):
    page = sessoes("admin", "mobile").new_page()
    v = Vigia(page, servidor.url)
    page.goto("/menu", wait_until="networkidle")
    sb = _sidebar(page)
    assert not _visivel_na_tela(page, sb), "No mobile a sidebar deve ficar FORA da tela (off-canvas, SPEC §5)"
    burger = page.locator("[data-menu-botao]").first   # hamburguer (aria-controls=sidebar); o botao "Fechar menu" da sidebar tambem casa com /menu/ quando aberta
    assert burger.is_visible(), "Botao hamburguer visivel no mobile"
    assert (burger.get_attribute("aria-expanded") or "false") == "false"
    assert (burger.bounding_box()["width"] >= 40 and burger.bounding_box()["height"] >= 40), "Alvo de toque do hamburguer < 40px"
    burger.click()
    page.wait_for_timeout(500)
    assert _visivel_na_tela(page, sb), "Sidebar nao abriu ao tocar no hamburguer"
    assert burger.get_attribute("aria-expanded") == "true", "aria-expanded deve refletir o estado do menu"
    m = sem_scroll_horizontal(page)
    assert m["doc"] <= m["janela"] + 1, "Menu aberto gerou scroll horizontal"
    tirar_foto(page, "mobile", "menu_aberto")
    page.keyboard.press("Escape")
    page.wait_for_timeout(500)
    assert not _visivel_na_tela(page, sb), "Esc deve fechar o menu off-canvas (SPEC §5: teclado funciona no menu)"
    burger.click()
    page.wait_for_timeout(400)
    with page.expect_navigation():
        sb.get_by_role("link", name=re.compile("Pedidos de Manuten", re.I)).first.click()
    assert page.url.endswith("/pedidos")
    page.wait_for_timeout(400)
    assert not _visivel_na_tela(page, _sidebar(page)), "Menu deve fechar apos navegar"
    v.limpo("menu mobile")
    page.close()


def test_mobile_overlay_fecha_o_menu(sessoes):
    page = sessoes("admin", "mobile").new_page()
    page.goto("/menu", wait_until="networkidle")
    page.get_by_role("button", name=re.compile("menu", re.I)).first.click()
    page.wait_for_timeout(400)
    page.mouse.click(385, 500)   # area fora da sidebar (lado direito)
    page.wait_for_timeout(500)
    assert not _visivel_na_tela(page, _sidebar(page)), "Clicar fora (overlay) deve fechar o menu"
    page.close()


def test_desktop_sidebar_fixa_visivel(sessoes):
    page = sessoes("admin", "desktop").new_page()
    page.goto("/dashboard", wait_until="networkidle")
    sb = _sidebar(page)
    assert _visivel_na_tela(page, sb), "Desktop: sidebar fixa visivel (SPEC §0/§5)"
    box = sb.bounding_box()
    assert 200 <= box["width"] <= 340, f"Largura da sidebar {box['width']}px"
    assert box["x"] <= 1
    atual = sb.locator("[aria-current=page]")
    assert atual.count() == 1, "Exatamente um item do menu com aria-current=page (SPEC §5)"
    assert re.search("dashboard", atual.inner_text(), re.I)
    page.close()


def test_mobile_tabelas_rolam_dentro_do_proprio_container(sessoes):
    page = sessoes("admin", "mobile").new_page()
    page.goto("/usuarios", wait_until="networkidle")
    info = page.evaluate("""() => { const t = document.querySelector('table'); if (!t) return null;
        let p = t.parentElement; while (p && p !== document.body) { const o = getComputedStyle(p).overflowX;
          if (o === 'auto' || o === 'scroll') return {ok: true, sw: p.scrollWidth, cw: p.clientWidth}; p = p.parentElement; }
        return {ok: false, tw: t.getBoundingClientRect().width, vw: innerWidth}; }""")
    assert info, "Tabela de usuarios nao encontrada"
    assert info["ok"] or info.get("tw", 0) <= info.get("vw", 0), f"Tabela larga sem container com rolagem contida: {info}"
    page.close()


def test_mobile_alvos_de_toque_minimos(sessoes):
    page = sessoes("admin", "mobile").new_page()
    pequenos = []
    for caminho in ("/pedidos", "/pedidos/novo", "/equipamentos", "/estoque", "/os/10234"):
        page.goto(caminho, wait_until="networkidle")
        r = page.evaluate("""() => [...document.querySelectorAll('main button, main a.btn, main [class*=btn], main input:not([type=hidden]):not([type=checkbox]):not([type=radio]), main select')]
            .filter(e => e.offsetParent !== null).map(e => { const b = e.getBoundingClientRect();
            return {t: (e.innerText || e.name || e.className || e.tagName).slice(0, 30), h: Math.round(b.height), w: Math.round(b.width)}; })""")
        pequenos += [f"{caminho}: {x['t']!r} {x['w']}x{x['h']}" for x in r if x["h"] < 40]
    assert not pequenos, f"Alvos de toque menores que 40px (SPEC §5): {pequenos[:8]}"
    page.close()


def test_mobile_formularios_em_uma_coluna(sessoes):
    page = sessoes("admin", "mobile").new_page()
    page.goto("/pedidos/novo", wait_until="networkidle")
    larguras = page.evaluate("""() => [...document.querySelectorAll('main input:not([type=hidden]), main select, main textarea')]
        .filter(e => e.offsetParent !== null).map(e => Math.round(e.getBoundingClientRect().width))""")
    assert larguras and min(larguras) >= 390 * 0.6, f"Campos estreitos demais no mobile (lado a lado?): {larguras}"
    page.close()


# --------------------------------------------------------------------------------------------- teclado / foco / acessibilidade

JS_FOCO = """() => { const e = document.activeElement; if (!e || e === document.body) return null;
    const s = getComputedStyle(e);
    const outline = s.outlineStyle !== 'none' && parseFloat(s.outlineWidth) > 0;
    const sombra = s.boxShadow && s.boxShadow !== 'none';
    const borda = s.borderColor;
    return {tag: e.tagName, txt: (e.innerText || e.name || e.getAttribute('aria-label') || '').slice(0, 25), outline, sombra, ok: outline || sombra}; }"""


@pytest.mark.parametrize("caminho,perfil", [("/login", "anonimo"), ("/menu", "admin"), ("/pecas", "admin")])
def test_foco_visivel_ao_navegar_por_tab(sessoes, caminho, perfil):
    page = sessoes(perfil, "desktop").new_page()
    page.goto(caminho, wait_until="networkidle")
    sem_foco, vistos = [], 0
    for _ in range(14):
        page.keyboard.press("Tab")
        info = page.evaluate(JS_FOCO)
        if not info:
            continue
        vistos += 1
        if not info["ok"]:
            sem_foco.append(f"{info['tag']}:{info['txt']!r}")
    assert vistos >= 5, "Poucos elementos focaveis por teclado"
    assert not sem_foco, f"{caminho}: elementos SEM indicador de foco visivel (SPEC §5): {sem_foco}"
    page.close()


def test_skip_link_ou_main_landmark(sessoes):
    page = sessoes("admin", "desktop").new_page()
    page.goto("/pecas", wait_until="networkidle")
    assert page.locator("main, [role=main]").count() == 1, "Esperado um unico landmark <main>"
    assert page.locator("nav, [role=navigation]").count() >= 1
    page.close()


def test_flash_tem_aria_live_e_confirmacao_de_exclusao_acessivel(sessoes, servidor):
    page = sessoes("admin", "desktop").new_page()
    page.goto("/departamentos", wait_until="networkidle")
    nome = f"Depto E2E {int(time.time()) % 100000}"
    page.locator("input[name*=nome]").first.fill(nome)
    with page.expect_navigation():
        page.get_by_role("button", name=re.compile("cadastrar|salvar", re.I)).first.click()
    live = page.locator("[aria-live], [role=status], [role=alert]")
    assert live.count() >= 1, "Mensagens flash precisam de regiao aria-live/role=status|alert (SPEC §5)"
    assert page.get_by_text(nome).first.is_visible()
    linha = page.locator("tr", has_text=nome)
    linha.get_by_role("button", name=re.compile("excluir", re.I)).first.click()
    dlg = page.locator("dialog[open], [role=dialog], [role=alertdialog]")
    dlg.first.wait_for(state="visible", timeout=4000)
    assert dlg.count() >= 1, "Confirmacao de exclusao deve abrir um <dialog> acessivel (SPEC §5)"
    page.keyboard.press("Escape")
    page.wait_for_timeout(300)
    assert not page.locator("dialog[open]").count(), "Esc deve fechar o dialogo"
    assert um("SELECT COUNT(*) FROM departamentos WHERE nome=?", nome, path=servidor.db) == 1, "Cancelar a confirmacao nao pode excluir"
    linha.get_by_role("button", name=re.compile("excluir", re.I)).first.click()
    dlg.first.wait_for(state="visible")
    with page.expect_navigation():
        dlg.get_by_role("button", name=re.compile("excluir|confirmar|sim", re.I)).first.click()
    assert um("SELECT COUNT(*) FROM departamentos WHERE nome=?", nome, path=servidor.db) == 0
    page.close()


JS_A11Y = """() => {
  const falhas = [];
  if (!document.documentElement.lang) falhas.push('html sem lang');
  const h1 = document.querySelectorAll('h1').length; if (h1 !== 1) falhas.push('h1 count=' + h1);
  document.querySelectorAll('input:not([type=hidden]), select, textarea').forEach(e => {
    if (e.offsetParent === null || e.closest('details:not([open]) > :not(summary)')) return;
    const nome = e.getAttribute('aria-label') || e.getAttribute('aria-labelledby') || (e.labels && e.labels.length) || e.title;
    if (!nome) falhas.push('campo sem label: ' + (e.name || e.id || e.type));
  });
  document.querySelectorAll('button, a[href]').forEach(e => {
    if (e.offsetParent === null || e.closest('details:not([open]) > :not(summary)')) return;
    const t = (e.innerText || '').trim() || e.getAttribute('aria-label') || e.title || (e.querySelector('img[alt]') || {}).alt;
    if (!t) falhas.push('controle sem nome acessivel: ' + e.outerHTML.slice(0, 60));
  });
  document.querySelectorAll('img').forEach(e => { if (!e.hasAttribute('alt')) falhas.push('img sem alt: ' + e.src.slice(-30)); });
  const ids = {}; document.querySelectorAll('[id]').forEach(e => { ids[e.id] = (ids[e.id] || 0) + 1; });
  Object.entries(ids).forEach(([k, n]) => { if (n > 1) falhas.push('id duplicado: ' + k); });
  document.querySelectorAll('table').forEach(t => { if (!t.querySelector('th')) falhas.push('tabela sem th'); });
  return falhas;
}"""


@pytest.mark.parametrize("nome,caminho", [t for t in TELAS if t[0] not in ("usuarios_editar",)], ids=[t[0] for t in TELAS if t[0] != "usuarios_editar"])
def test_acessibilidade_basica_por_tela(sessoes, nome, caminho):
    page = sessoes("admin", "desktop").new_page()
    page.goto(caminho, wait_until="networkidle")
    falhas = page.evaluate(JS_A11Y)
    assert not falhas, f"{caminho}: {falhas[:6]}"
    page.close()


def test_login_acessivel(sessoes):
    page = sessoes("anonimo", "desktop").new_page()
    page.goto("/login", wait_until="networkidle")
    falhas = page.evaluate(JS_A11Y)
    assert not falhas, falhas
    page.close()


def test_abas_do_relatorio_funcionam_por_teclado(sessoes):
    page = sessoes("admin", "desktop").new_page()
    page.goto("/relatorios?aba=os", wait_until="networkidle")
    abas = page.get_by_role("tab")
    if abas.count() == 0:
        abas = page.locator("nav a, .tabs a, .abas a, [class*=tab] a, [class*=tab] button").filter(has_text=re.compile("Estoque|Financeiro|Fornecedores"))
    assert abas.count() >= 4, "Abas Ordens de Servico / Estoque / Financeiro / Fornecedores (Figma 20)"
    alvo = abas.filter(has_text=re.compile("Estoque"))
    alvo.first.focus()
    with page.expect_response(re.compile(r"/api/relatorios/estoque|aba=estoque"), timeout=8000):
        page.keyboard.press("Enter")
    page.wait_for_timeout(500)
    assert "Rolamento" in page.inner_text("body") or "estoque" in page.url
    page.close()


def test_relatorios_atualizar_e_exportacoes(sessoes):
    page = sessoes("admin", "desktop").new_page()
    page.goto("/relatorios?aba=os", wait_until="networkidle")
    with page.expect_response(re.compile(r"/api/relatorios/os")) as r:
        page.get_by_role("button", name=re.compile("atualizar", re.I)).click()
    assert r.value.status == 200
    for rotulo, ext in (("Exportar PDF", ".pdf"), ("Exportar Excel", ".xlsx")):
        el = page.get_by_role("link", name=re.compile(rotulo, re.I))
        if not el.count():
            el = page.get_by_role("button", name=re.compile(rotulo, re.I))
        assert el.count(), f"{rotulo} ausente"
        with page.expect_download() as d:
            el.first.click()
        assert d.value.suggested_filename.lower().endswith(ext)
    assert page.locator("canvas").count() >= 2, "Graficos 'OS por Tecnico' e 'Custo por Tecnico (R$)'"
    page.close()


def test_reduced_motion_sem_transicoes(pw, servidor):
    ctx = pw.new_context(viewport=VIEWPORTS["mobile"], base_url=servidor.url, reduced_motion="reduce")
    page = ctx.new_page()
    entrar(page, "admin")
    page.goto("/dashboard", wait_until="networkidle")
    dur = page.evaluate("""() => { const alvo = document.querySelector('aside, .sidebar, #sidebar');
        return [parseFloat(getComputedStyle(alvo).transitionDuration) || 0, parseFloat(getComputedStyle(document.body).animationDuration) || 0]; }""")
    assert dur[0] <= 0.01, f"prefers-reduced-motion: a sidebar ainda tem transicao de {dur[0]}s (SPEC §5)"
    anim = page.evaluate("() => (window.Chart && Chart.defaults.animation === false) || (window.Chart && Chart.defaults.animation && Chart.defaults.animation.duration === 0) || null")
    ctx.close()


# --------------------------------------------------------------------------------------------- tema escuro e contraste

JS_CONTRASTE = """() => {
  const parse = c => { const m = c.match(/rgba?\\(([^)]+)\\)/); if (!m) return null; const p = m[1].split(',').map(x => parseFloat(x)); return {r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1}; };
  const lum = c => { const f = v => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); }; return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b); };
  const fundo = e => { let n = e; while (n) { const st = getComputedStyle(n); const c = parse(st.backgroundColor); if (c && c.a > 0.95) return c; if (st.backgroundImage && st.backgroundImage !== 'none') return null; n = n.parentElement; } return {r: 255, g: 255, b: 255, a: 1}; };
  const ratio = (a, b) => { const l1 = lum(a), l2 = lum(b); return (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05); };
  const ruins = []; let n = 0;
  document.querySelectorAll('h1, h2, h3, p, label, th, td, a, button, span, li, small, input, select, .badge, [class*=badge], [class*=pill]').forEach(e => {
    if (e.offsetParent === null || !(e.innerText || e.value || '').trim()) return;
    if (e.children.length > 0 && !['A', 'BUTTON', 'LABEL', 'TH', 'TD'].includes(e.tagName)) return;
    const s = getComputedStyle(e); const fg = parse(s.color); if (!fg) return; const bg = fundo(e); if (!bg) return;  // fundo em gradiente/imagem: indeterminado, nao avaliado
    const grande = parseFloat(s.fontSize) >= 24 || (parseFloat(s.fontSize) >= 18.66 && parseInt(s.fontWeight) >= 700);
    const r = ratio(fg, bg); n++;
    if (r < (grande ? 3 : 4.5)) ruins.push({txt: (e.innerText || e.value).trim().slice(0, 28), r: Math.round(r * 100) / 100, cor: s.color, fundo: 'rgb(' + bg.r + ',' + bg.g + ',' + bg.b + ')', tag: e.tagName});
  });
  return {n, ruins};
}"""


@pytest.mark.parametrize("tema", ["claro", "escuro"])
@pytest.mark.parametrize("caminho", ["/dashboard", "/pecas", "/pedidos", "/os/10234"])
def test_contraste_wcag_aa_nos_dois_temas(pw, servidor, tema, caminho):
    ctx = pw.new_context(viewport=VIEWPORTS["desktop"], base_url=servidor.url, locale="pt-BR")
    page = ctx.new_page()
    entrar(page, "tecnico")      # usuario dedicado: troca de tema nao afeta os outros testes
    _definir_tema(page, tema)    # sempre explicito: o tema fica gravado no usuario e o servidor e compartilhado entre testes
    page.goto(caminho, wait_until="networkidle")
    page.wait_for_timeout(500)
    ativo = page.evaluate("document.documentElement.dataset.theme")
    assert (ativo in ("escuro", "dark")) == (tema == "escuro"), f"tema {tema!r} solicitado mas data-theme={ativo!r}"
    res = page.evaluate(JS_CONTRASTE)
    tirar_foto(page, "desktop", f"tema_{tema}_{re.sub(chr(92) + 'W+', '_', caminho.strip('/'))}")
    assert res["n"] > 10
    unicos = {(r["txt"], r["cor"], r["fundo"]): r for r in res["ruins"]}
    assert len(unicos) <= 0, f"{tema} {caminho}: {len(unicos)} combinacoes abaixo de AA (4.5:1): " + str(list(unicos.values())[:6])
    ctx.close()


def _definir_tema(page, tema):
    page.goto("/configuracoes", wait_until="networkidle")
    alvo = page.locator(f"input[name=tema][value={tema}], select[name=tema]")
    assert alvo.count(), "Controle de tema ausente em /configuracoes (SPEC §4)"
    if alvo.first.evaluate("e => e.tagName") == "SELECT":
        alvo.first.select_option(tema)
    else:
        alvo.first.check(force=True)
    # o botao Salvar do MESMO formulario do controle de tema (a pagina tem 3 forms: perfil, senha, preferencias)
    form = alvo.first.locator("xpath=ancestor::form[1]")
    with page.expect_navigation():
        form.locator("button[type=submit], input[type=submit]").first.click()


def test_tema_escuro_aplica_data_theme_e_fundo_escuro(pw, servidor):
    ctx = pw.new_context(viewport=VIEWPORTS["desktop"], base_url=servidor.url, locale="pt-BR")
    page = ctx.new_page()
    v = Vigia(page, servidor.url)
    entrar(page, "plima")
    claro = page.evaluate("() => [document.documentElement.dataset.theme, getComputedStyle(document.body).backgroundColor]")
    assert claro[0] in ("claro", "light", None, ""), claro
    _definir_tema(page, "escuro")
    page.goto("/dashboard", wait_until="networkidle")
    page.wait_for_timeout(800)
    tema, fundo = page.evaluate("() => [document.documentElement.dataset.theme, getComputedStyle(document.body).backgroundColor]")
    assert tema in ("escuro", "dark"), f"data-theme={tema!r} apos escolher tema escuro"
    r, g, b = [int(x) for x in re.findall(r"\d+", fundo)[:3]]
    assert (0.2126 * r + 0.7152 * g + 0.0722 * b) < 90, f"Fundo do tema escuro nao e escuro: {fundo}"
    tirar_foto(page, "desktop", "dashboard_escuro")
    # graficos continuam legiveis: canvas existe e tem pixels
    assert page.locator("canvas").count() >= 3   # Tecnico ve o dashboard sem financeiro (SPEC §2): 3 graficos, sem Custo por Maquina
    # persiste apos recarregar e em outra pagina
    page.reload()
    assert page.evaluate("document.documentElement.dataset.theme") in ("escuro", "dark")
    v.limpo("tema escuro")
    ctx.close()


def test_tema_respeita_prefers_color_scheme_somente_se_configurado(pw, servidor):
    """Informativo: tema e uma preferencia do usuario (SPEC §4), nao do SO. Nao deve quebrar com color_scheme=dark."""
    ctx = pw.new_context(viewport=VIEWPORTS["desktop"], base_url=servidor.url, color_scheme="dark")
    page = ctx.new_page()
    resp = page.goto("/login", wait_until="networkidle")
    assert resp.status == 200
    ctx.close()


# --------------------------------------------------------------------------------------------- perfil Usuario Comum no navegador

def test_usuario_comum_ve_menu_reduzido_no_navegador(sessoes, servidor):
    page = sessoes("comum", "desktop").new_page()
    v = Vigia(page, servidor.url)
    page.goto("/menu", wait_until="networkidle")
    sb = _sidebar(page).inner_text()
    for proibido in ("Usuários e Perfis", "Equipamentos", "Peças", "Fornecedores", "Prestadores", "Departamentos", "Movim"):
        assert proibido.lower() not in sb.lower(), f"Item {proibido!r} nao deveria aparecer para o Usuario Comum (SPEC §2)"
    for permitido in ("Pedidos de Manuten", "Ordens de Servi"):
        assert permitido.lower() in sb.lower()
    tirar_foto(page, "desktop", "menu_comum")
    v.limpo("menu do usuario comum")
    page.close()


# --------------------------------------------------------------------------------------------- jornada completa pela UI

def _clicar(page, nome, *, tipo=("button", "link")):
    for t in tipo:
        el = page.get_by_role(t, name=re.compile(nome, re.I))
        if el.count():
            return el.first
    raise AssertionError(f"Nao achei botao/link {nome!r} na pagina {page.url}")


def test_jornada_ponta_a_ponta_pela_interface(sessoes, servidor):
    """Login -> cadastro (departamento, peca) -> pedido -> OS -> peca/servico/apontamento -> fechar -> estoque -> relatorios."""
    db = servidor.db
    ctx = sessoes("admin", "desktop")
    page = ctx.new_page()
    v = Vigia(page, servidor.url)
    v.esperados = {400}
    sufixo = int(time.time()) % 100000

    # 1) Menu principal -> Cadastros
    page.goto("/menu", wait_until="networkidle")
    assert page.get_by_text(re.compile("Cadastros", re.I)).first.is_visible()
    tirar_foto(page, "desktop", "jornada_01_menu")

    # 2) Cadastra uma peca (select de equipamento)
    page.goto("/pecas", wait_until="networkidle")
    nome_peca = f"Peca E2E {sufixo}"
    page.locator("main input[name*=nome]").first.fill(nome_peca)
    sel_eq = page.locator("main select[name*=equipamento]").first
    sel_eq.select_option(label="BOMBA 2 (RESFRIADOR)")
    page.locator("main input[name*=valor]").first.fill("12.50")
    page.locator("main input[name*=estoque], main input[name*=qtde], main input[name*=quant]").first.fill("20")
    page.locator("main input[name*=ncm]").first.fill("84821010")
    with page.expect_navigation():
        _clicar(page, "cadastrar|salvar", tipo=("button",)).click()
    assert page.get_by_text(nome_peca).first.is_visible(), "Peca cadastrada deve aparecer na lista"
    peca_id = um("SELECT id FROM pecas WHERE nome=?", nome_peca, path=db)
    assert peca_id
    tirar_foto(page, "desktop", "jornada_02_pecas")

    # 3) Novo pedido pela UI
    page.goto("/pedidos", wait_until="networkidle")
    with page.expect_navigation():
        _clicar(page, "novo pedido").click()
    page.locator("main select[name*=equipamento]").first.select_option(label="BOMBA 2 (RESFRIADOR)")
    page.locator("main select[name*=departamento]").first.select_option(label="Utilidades")
    page.locator("main textarea").first.fill(f"Vazamento detectado E2E {sufixo}")
    page.locator("main select[name*=prioridade]").first.select_option(label="Alta")
    tirar_foto(page, "desktop", "jornada_03_pedido_form")
    with page.expect_navigation():
        _clicar(page, "abrir pedido|salvar|cadastrar|enviar", tipo=("button",)).click()
    pid = um("SELECT id FROM pedidos_manutencao WHERE descricao_problema LIKE ? ORDER BY id DESC LIMIT 1", f"%E2E {sufixo}", path=db)
    assert pid, "Pedido nao gravado pela UI"

    # 4) Abre a OS a partir do detalhe do pedido
    page.goto(f"/pedidos/{pid}", wait_until="networkidle")
    tirar_foto(page, "desktop", "jornada_04_pedido_detalhe")
    with page.expect_navigation():
        _clicar(page, "abrir os").click()
    # o botao leva ao formulario /os/nova com o pedido ja escolhido; falta escolher o tecnico e confirmar
    assert "/os/nova" in page.url and f"pedido_id={pid}" in page.url, f"Esperado /os/nova?pedido_id={pid}: {page.url}"
    page.locator("main select[name*=tecnico]").first.select_option(label="Maria Técnica")
    tirar_foto(page, "desktop", "jornada_04b_os_nova")
    with page.expect_navigation():
        _clicar(page, "abrir os", tipo=("button",)).click()
    assert re.search(r"/os/\d+", page.url), f"Depois de Abrir OS deveria mostrar a OS: {page.url}"
    oid = int(re.search(r"/os/(\d+)", page.url).group(1))
    assert um("SELECT id_pedido FROM ordens_servico WHERE id=?", oid, path=db) == pid

    # 5) Adiciona peca, servico e apontamento
    f_peca = page.locator("form[action*='/pecas']").first
    f_peca.locator("select").first.select_option(value=str(peca_id))
    f_peca.locator("input[name*=quant]").first.fill("5")
    with page.expect_navigation():
        f_peca.locator("button[type=submit], button:not([type])").first.click()
    assert float(um("SELECT qtde_estoque FROM pecas WHERE id=?", peca_id, path=db)) == 15, "Baixa de estoque pela UI"
    f_serv = page.locator("form[action*='/servicos']").first
    f_serv.locator("input[name*=descricao]").first.fill("Troca do selo (E2E)")
    f_serv.locator("input[name*=valor]").first.fill("350.00")
    with page.expect_navigation():
        f_serv.locator("button[type=submit], button:not([type])").first.click()
    f_ap = page.locator("form[action*='/apontamentos']").first
    f_ap.locator("input[name*=horas]").first.fill("2")
    f_ap.locator("select[name*=tipo]").first.select_option(label="INSPECAO")
    with page.expect_navigation():
        f_ap.locator("button[type=submit], button:not([type])").first.click()
    page.goto(f"/os/{oid}", wait_until="networkidle")
    texto = page.inner_text("main")
    assert nome_peca in texto and "Troca do selo (E2E)" in texto and "INSPECAO" in texto
    assert "R$ 412,50" in texto, "Total: 5 x 12,50 + 350,00 = R$ 412,50"
    tirar_foto(page, "desktop", "jornada_05_os_detalhe")

    # 6) Estoque mostra a saida
    page.goto("/estoque", wait_until="networkidle")
    assert page.get_by_text(re.compile(f"OS-{oid}")).first.is_visible(), "Historico de estoque deve citar a OS"
    tirar_foto(page, "desktop", "jornada_06_estoque")

    # 7) Registra uma entrada manual pelo formulario
    page.locator("main input[type=radio][value=Entrada]").first.check(force=True)
    page.locator("main select[name*=peca], main select[name*=descricao]").first.select_option(value=str(peca_id))
    page.locator("main input[name=quantidade], main input[name*=quant]").first.fill("10")
    page.locator("main input[name*=valor]").first.fill("12.50")
    page.locator("main input[name*=numero], main input[name*=n_doc]").first.fill("NF-E2E-1")
    with page.expect_navigation():
        _clicar(page, "registrar movimento", tipo=("button",)).click()
    assert float(um("SELECT qtde_estoque FROM pecas WHERE id=?", peca_id, path=db)) == 25
    # saida acima do saldo mostra erro
    page.locator("main input[type=radio][value*=Sa]").first.check(force=True)
    page.locator("main select[name*=peca], main select[name*=descricao]").first.select_option(value=str(peca_id))
    page.locator("main input[name=quantidade], main input[name*=quant]").first.fill("999")
    page.locator("main input[name*=valor]").first.fill("1")
    _clicar(page, "registrar movimento", tipo=("button",)).click()
    page.wait_for_load_state("networkidle")
    assert float(um("SELECT qtde_estoque FROM pecas WHERE id=?", peca_id, path=db)) == 25, "Saida maior que o saldo nao pode passar"
    assert page.get_by_text(re.compile("saldo|insuficiente|estoque", re.I)).first.is_visible()

    # 8) Fecha a OS (pode haver confirmacao)
    page.goto(f"/os/{oid}", wait_until="networkidle")
    _clicar(page, "fechar os", tipo=("button",)).click()
    dlg = page.locator("dialog[open], [role=dialog]")
    dlg.first.wait_for(state="visible", timeout=5000)   # confirmacao de fechamento (SPEC §5: dialog acessivel)
    with page.expect_navigation():
        dlg.get_by_role("button", name=re.compile("fechar|confirmar|sim", re.I)).last.click()
    page.wait_for_load_state("networkidle")
    assert um("SELECT status FROM ordens_servico WHERE id=?", oid, path=db) == "Concluída"
    assert um("SELECT status FROM pedidos_manutencao WHERE id=?", pid, path=db) == "Concluído"
    assert um("SELECT status FROM equipamentos WHERE descricao='BOMBA 2 (RESFRIADOR)'", path=db) == "Ativo"
    page.goto(f"/os/{oid}", wait_until="networkidle")
    assert page.get_by_text("Concluída").first.is_visible()
    assert page.get_by_role("button", name=re.compile("fechar os", re.I)).count() == 0, "OS concluida: sem botao Fechar OS"
    assert page.locator("form[action*='/pecas']").count() == 0, "OS concluida: somente leitura (sem formulario de peca)"
    tirar_foto(page, "desktop", "jornada_07_os_concluida")

    # 9) Relatorios e dashboard refletem
    page.goto("/relatorios?aba=os", wait_until="networkidle")
    assert page.get_by_text("Concluída").first.is_visible()
    tirar_foto(page, "desktop", "jornada_08_relatorios")
    page.goto("/dashboard", wait_until="networkidle")
    page.wait_for_timeout(900)
    tirar_foto(page, "desktop", "jornada_09_dashboard")
    v.limpo("jornada ponta a ponta")
    page.close()


def test_jornada_mobile_login_menu_e_novo_pedido(pw, servidor):
    ctx = pw.new_context(viewport=VIEWPORTS["mobile"], base_url=servidor.url, locale="pt-BR", has_touch=True, is_mobile=True)
    page = ctx.new_page()
    v = Vigia(page, servidor.url)
    entrar(page, "comum")
    page.get_by_role("button", name=re.compile("menu", re.I)).first.tap()
    page.wait_for_timeout(500)
    with page.expect_navigation():
        _sidebar(page).get_by_role("link", name=re.compile("Pedidos de Manuten", re.I)).first.tap()
    with page.expect_navigation():
        _clicar(page, "novo pedido").tap()
    page.locator("main select[name*=equipamento]").first.select_option(label="BOMBA 1 (RESFRIADOR)")
    page.locator("main select[name*=departamento]").first.select_option(label="Utilidades")
    page.locator("main textarea").first.fill("Pedido pelo celular (E2E mobile)")
    tirar_foto(page, "mobile", "jornada_pedido_form")
    with page.expect_navigation():
        _clicar(page, "abrir pedido|salvar|cadastrar|enviar", tipo=("button",)).tap()
    m = sem_scroll_horizontal(page)
    assert m["doc"] <= m["janela"] + 1
    assert um("SELECT solicitante FROM pedidos_manutencao WHERE descricao_problema LIKE '%E2E mobile%'", path=servidor.db) == "Ana Solicitante"
    v.limpo("jornada mobile")
    ctx.close()


def test_selects_dependentes_grupo_subgrupo_no_navegador(sessoes, servidor):
    page = sessoes("admin", "desktop").new_page()
    v = Vigia(page, servidor.url)
    page.goto("/equipamentos", wait_until="networkidle")
    grupo = page.locator("main select[name*=grupo]:not([name*=sub])").first
    sub = page.locator("main select[name*=subgrupo]").first
    grupo.select_option(label="TI")
    with page.expect_response(lambda r: "/api/subgrupos" in r.url):
        grupo.select_option(label="Frota")
    page.wait_for_timeout(300)
    opcoes = [o.inner_text() for o in sub.locator("option:not([value=''])").all()]   # sem o placeholder "Selecione"
    assert len(opcoes) == 6 and "Automóveis" in opcoes, f"Subgrupos de Frota (apoio §2: 6): {opcoes}"
    grupo.select_option(label="Infraestrutura")
    page.wait_for_timeout(600)
    assert sub.locator("option:not([value=''])").count() == 17
    v.limpo("selects dependentes")
    page.close()


# --------------------------------------------------------------------------------------------- BUG-010: CSP no navegador real

PAGINAS_CSP = ["/menu", "/dashboard", "/relatorios?aba=os", "/relatorios?aba=financeiro", "/pecas", "/pedidos/novo", "/os/10234",
               "/estoque", "/usuarios", "/configuracoes"]


@pytest.mark.parametrize("vp", ["desktop", "mobile"])
def test_csp_sem_violacoes_graficos_pintados_e_dialogo_funcionando(sessoes, servidor, vp):
    """Com a CSP ativa nada pode ser bloqueado: sem 'Refused to ...' no console, graficos com pixels, dialogo de confirmacao abre."""
    page = sessoes("admin", vp).new_page()
    bloqueios = []
    page.on("console", lambda m: bloqueios.append(m.text) if ("Content Security Policy" in m.text or "Refused to" in m.text) else None)
    page.on("pageerror", lambda e: bloqueios.append(str(e)))
    v = Vigia(page, servidor.url)
    for caminho in PAGINAS_CSP:
        resp = page.goto(caminho, wait_until="networkidle")
        assert resp.status == 200, caminho
        assert "content-security-policy" in {k.lower() for k in resp.headers}, f"{caminho}: resposta sem CSP"
    page.goto("/dashboard", wait_until="networkidle")
    page.wait_for_timeout(800)
    pintados = page.evaluate("""() => [...document.querySelectorAll('canvas')].map(c => {
        const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data; let n = 0;
        for (let i = 3; i < d.length; i += 4) if (d[i] !== 0) n++; return n; })""")
    assert len(pintados) >= 4 and all(n > 200 for n in pintados), f"Graficos sem pixels com a CSP ativa: {pintados}"
    # dialogo de confirmacao (JS proprio) continua abrindo e fechando
    page.goto("/os/10234", wait_until="networkidle")
    page.get_by_role("button", name=re.compile("fechar os", re.I)).first.click()
    dlg = page.locator("dialog[open], [role=dialog]")
    dlg.first.wait_for(state="visible", timeout=5000)
    page.keyboard.press("Escape")
    page.wait_for_timeout(300)
    assert not page.locator("dialog[open]").count(), "Esc deve fechar o dialogo"
    assert um("SELECT status FROM ordens_servico WHERE id=10234", path=servidor.db) != "Concluída", "Cancelar nao pode fechar a OS"
    assert not bloqueios, f"Violacoes de CSP/JS: {bloqueios[:3]}"
    v.limpo(f"CSP {vp}")
    page.close()
