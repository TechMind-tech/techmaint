"""
Seguranca: CSRF, metodos HTTP, erros amigaveis, IDOR, injecao, arquivos expostos, cookies e cabecalhos.

Rastreabilidade: SPEC §1 ("Seguranca basica obrigatoria": SQL parametrizado, hash, sessao assinada, CSRF em todo POST,
escaping, validacao no servidor, POST/Redirect/GET, exclusao so por POST), SPEC §6 (CSRF 400/403, injecao, 500 sem stack trace),
RNF Seguranca (restricao de acesso, criptografia, LGPD).
"""

import re

import pytest

from helpers import (PAYLOADS_HOSTIS, consulta, contar, html_de, obter_csrf, post, snapshot, texto_visivel, um, e_redirect_login)

TABELAS = ["usuarios", "equipamentos", "pecas", "fornecedores", "prestadores_servico", "departamentos", "pedidos_manutencao",
           "ordens_servico", "itens_os", "servicos_os", "apontamentos_os", "movimentacao_estoque_pecas"]

# (url, corpo valido o bastante para ser aceito se o CSRF nao existisse)
ROTAS_POST = [
    "/usuarios", "/usuarios/{u}/editar", "/usuarios/{u}/excluir",
    "/equipamentos", "/equipamentos/{e}/editar", "/equipamentos/{e}/excluir",
    "/pecas", "/pecas/{p}/editar", "/pecas/{p}/excluir", "/pecas/{p}/estoque",
    "/fornecedores/novo", "/fornecedores/{f}/editar", "/fornecedores/{f}/excluir",
    "/prestadores/novo", "/prestadores/{pr}/editar", "/prestadores/{pr}/excluir",
    "/departamentos", "/departamentos/{d}/editar", "/departamentos/{d}/excluir",
    "/pedidos/novo", "/pedidos/1624/editar", "/pedidos/1624/cancelar", "/pedidos/1624/aprovar", "/pedidos/1624/abrir-os",
    "/os/nova", "/os/10232/editar", "/os/10234/pecas", "/os/10234/servicos", "/os/10234/apontamentos", "/os/10234/fechar",
    "/os/10232/excluir", "/estoque", "/estoque/{m}/excluir", "/configuracoes", "/logout",
]


@pytest.fixture()
def ids():
    return {"u": um("SELECT id FROM usuarios WHERE login='plima'"), "e": um("SELECT MIN(id) FROM equipamentos"),
            "p": um("SELECT MIN(id) FROM pecas"), "f": um("SELECT MIN(id) FROM fornecedores"),
            "pr": um("SELECT MIN(id) FROM prestadores_servico"), "d": um("SELECT id FROM departamentos WHERE nome='Logística'"),
            "m": um("SELECT MIN(id) FROM movimentacao_estoque_pecas")}


# --------------------------------------------------------------------------------------------- CSRF

@pytest.mark.parametrize("rota", ROTAS_POST)
def test_post_sem_token_csrf_e_rejeitado(admin, ids, rota):
    antes = snapshot(TABELAS)
    r = admin.post(rota.format(**ids), data={"nome": "x", "descricao": "x", "quantidade": "1"})
    assert r.status_code in (400, 403), f"POST {rota} SEM csrf_token deveria ser 400/403 (SPEC §6). Veio {r.status_code}"
    assert snapshot(TABELAS) == antes, "POST sem CSRF alterou o banco"


@pytest.mark.parametrize("rota", ROTAS_POST)
def test_post_com_token_csrf_falso_e_rejeitado(admin, ids, rota):
    r = admin.post(rota.format(**ids), data={"csrf_token": "token-forjado-123", "nome": "x"})
    assert r.status_code in (400, 403), f"POST {rota} com csrf_token falso: {r.status_code}"


def test_token_csrf_de_outra_sessao_nao_vale(app, admin, tecnico, ids):
    tok_admin = obter_csrf(admin)
    antes = snapshot(TABELAS)
    r = tecnico.post("/equipamentos", data={"csrf_token": tok_admin, "codigo": "ZZ.CSRF", "descricao": "x"})
    assert r.status_code in (400, 403)
    assert snapshot(TABELAS) == antes


def test_token_csrf_esta_em_todo_formulario_post_das_paginas(admin):
    from helpers import formularios
    paginas = ["/usuarios", "/equipamentos", "/pecas", "/fornecedores/novo", "/prestadores/novo", "/departamentos", "/pedidos/novo",
               "/os/nova", "/os/10234", "/estoque", "/configuracoes", "/pedidos/1624", "/menu"]
    faltando = []
    for p in paginas:
        r = admin.get(p)
        assert r.status_code == 200, f"{p} -> {r.status_code}"
        for f in formularios(html_de(r)):
            if f.method == "post" and "csrf_token" not in f.nomes:
                faltando.append((p, f.action))
    assert not faltando, f"<form method=post> sem csrf_token (SPEC §4): {faltando}"


def test_csrf_no_login_e_recuperar_senha(anonimo):
    from helpers import formularios
    for p in ("/login", "/recuperar-senha"):
        fs = [f for f in formularios(html_de(anonimo.get(p))) if f.method == "post"]
        assert fs and all("csrf_token" in f.nomes for f in fs), p


# --------------------------------------------------------------------------------------------- metodos HTTP

@pytest.mark.parametrize("rota", ["/usuarios/{u}/excluir", "/equipamentos/{e}/excluir", "/pecas/{p}/excluir", "/fornecedores/{f}/excluir",
                                  "/prestadores/{pr}/excluir", "/departamentos/{d}/excluir", "/pedidos/1624/cancelar",
                                  "/pedidos/1624/aprovar", "/os/10232/fechar", "/os/10232/excluir",
                                  "/estoque/{m}/excluir", "/logout", "/os/10234/pecas", "/os/10234/servicos", "/os/10234/apontamentos"])
def test_acoes_destrutivas_nao_funcionam_por_get(admin, ids, rota):
    antes = snapshot(TABELAS)
    r = admin.get(rota.format(**ids))
    assert r.status_code == 405, f"GET {rota} deveria ser 405 (acoes so por POST - SPEC §1). Veio {r.status_code}"
    assert snapshot(TABELAS) == antes


def test_get_abrir_os_nao_altera_nada(admin):
    """SPEC §6: /pedidos/<id>/abrir-os aceita GET (leva ao formulario de nova OS) mas nao pode criar OS por GET."""
    antes = snapshot(TABELAS)
    r = admin.get("/pedidos/1624/abrir-os")
    assert r.status_code in (200, 302, 303)
    assert snapshot(TABELAS) == antes


@pytest.mark.parametrize("metodo", ["put", "delete", "patch"])
@pytest.mark.parametrize("rota", ["/usuarios", "/equipamentos/1/excluir", "/os/10234", "/pedidos/1623", "/estoque", "/login"])
def test_metodos_inesperados(admin, rota, metodo):
    r = getattr(admin, metodo)(rota)
    assert r.status_code in (400, 403, 405), f"{metodo.upper()} {rota} -> {r.status_code}"


def test_head_e_options_nao_quebram(admin):
    assert admin.head("/dashboard").status_code < 500
    assert admin.options("/dashboard").status_code < 500


# --------------------------------------------------------------------------------------------- erros amigaveis

def test_404_amigavel_em_pt_br(admin):
    r = admin.get("/pagina-que-nao-existe")
    assert r.status_code == 404
    t = texto_visivel(html_de(r)).lower()
    assert "não encontrad" in t or "nao encontrad" in t or "404" in t
    assert "traceback" not in t and "werkzeug" not in t


def test_404_para_anonimo_nao_vaza_nada(anonimo):
    r = anonimo.get("/pagina-que-nao-existe")
    assert r.status_code in (302, 404)


def test_404_nao_reflete_o_caminho_sem_escape(admin):
    r = admin.get("/<script>alert(1)</script>")
    assert "<script>alert(1)</script>" not in html_de(r)


def test_405_nao_vaza_stack(admin):
    r = admin.get("/usuarios/1/excluir")
    assert "Traceback" not in html_de(r)


@pytest.mark.parametrize("caminho", ["/pedidos/abc", "/pedidos/-1", "/pedidos/0", "/pedidos/99999999999999999999", "/pedidos/1%20OR%201=1",
                                     "/os/abc", "/os/-1", "/os/0", "/os/99999999999999999999", "/usuarios/abc/editar", "/usuarios/-1/editar",
                                     "/equipamentos/0/editar", "/pecas/9999999999999999999999/editar", "/os/10234/pecas/abc/editar",
                                     "/estoque/abc/excluir", "/pedidos/1;DROP TABLE usuarios/editar"])
def test_ids_invalidos_viram_404_nunca_500(admin, caminho):
    r = admin.get(caminho)
    assert r.status_code in (404, 405), f"GET {caminho} -> {r.status_code}"
    r = post(admin, caminho, {})
    assert r.status_code in (404, 405), f"POST {caminho} -> {r.status_code}"
    assert contar("usuarios") >= 5


def test_500_nao_mostra_stack_trace(app):
    """Forca uma excecao nao tratada e confere a pagina amigavel (SPEC §6)."""
    @app.route("/__qa_explode")
    def _explode():
        raise RuntimeError("segredo-interno-123")
    app.config["PROPAGATE_EXCEPTIONS"] = False
    c = app.test_client()
    from helpers import logar_como
    logar_como(c, "admin")
    r = c.get("/__qa_explode")
    assert r.status_code == 500
    h = html_de(r)
    assert "segredo-interno-123" not in h and "Traceback" not in h, "Stack trace/mensagem interna vazou na pagina de erro 500"
    assert "erro" in texto_visivel(h).lower()


def test_debug_desligado(app):
    assert app.debug is False
    assert app.config.get("DEBUG") in (False, None)


# --------------------------------------------------------------------------------------------- arquivos expostos / traversal

@pytest.mark.parametrize("caminho", ["/app.py", "/database.py", "/schema.sql", "/seed.py", "/requirements.txt", "/README.md", "/techmaint.db",
                                     "/.git/config", "/.env", "/tests/conftest.py", "/modulos/auth.py", "/servicos/validacoes.py",
                                     "/templates/base.html", "/static/../app.py", "/static/%2e%2e/app.py", "/static/..%2fapp.py",
                                     "/static/../../etc/passwd", "/static//etc/passwd"])
def test_arquivos_sensiveis_nao_sao_servidos(anonimo, caminho):
    r = anonimo.get(caminho)
    assert r.status_code in (302, 400, 404), f"{caminho} -> {r.status_code}"
    if r.status_code == 200:
        pytest.fail(f"{caminho} exposto")
    assert b"SECRET_KEY" not in r.get_data() and b"root:" not in r.get_data()


def test_static_nao_lista_diretorio(anonimo):
    r = anonimo.get("/static/")
    assert r.status_code in (404, 308, 301)
    assert b"Index of" not in r.get_data()


# --------------------------------------------------------------------------------------------- injecao generica

@pytest.mark.parametrize("payload", PAYLOADS_HOSTIS + ["1 OR 1=1", "1; DROP TABLE usuarios", "' UNION SELECT login, senha_hash FROM usuarios--"])
@pytest.mark.parametrize("pagina,param", [("/usuarios", "busca"), ("/equipamentos", "busca"), ("/pecas", "busca"), ("/fornecedores", "busca"),
                                          ("/prestadores", "busca"), ("/pedidos", "busca"), ("/os", "busca"), ("/estoque", "busca"),
                                          ("/pedidos", "status"), ("/os", "status"), ("/equipamentos", "grupo"), ("/pecas", "equipamento"),
                                          ("/relatorios", "periodo"), ("/dashboard", "periodo"), ("/estoque", "tipo")])
def test_parametros_de_url_hostis_nao_quebram_nem_refletem(admin, pagina, param, payload):
    r = admin.get(pagina, query_string={param: payload})
    assert r.status_code < 500, f"{pagina}?{param}={payload!r} -> {r.status_code}"
    if "<" in payload:
        assert payload not in html_de(r), "Parametro refletido sem escape (XSS refletido)"
    h = html_de(r)
    # o proprio texto digitado volta (escapado) no campo de busca; o que nao pode aparecer e um HASH real do banco
    hashes = [r["senha_hash"] for r in consulta("SELECT senha_hash FROM usuarios")]
    assert not any(x in h for x in hashes) and "pbkdf2:" not in h and "scrypt:" not in h, "UNION SELECT vazou hash de senha"
    assert contar("usuarios") >= 5


def test_hash_de_senha_nunca_aparece_em_nenhuma_pagina(admin):
    for p in ("/usuarios", "/usuarios/1/editar", "/configuracoes", "/menu", "/dashboard"):
        h = html_de(admin.get(p))
        assert "pbkdf2:" not in h and "scrypt:" not in h and "senha_hash" not in h, f"hash de senha exposto em {p}"


def test_formulario_de_edicao_de_usuario_nao_pre_preenche_senha(admin):
    from helpers import formularios
    uid = um("SELECT id FROM usuarios WHERE login='plima'")
    for f in formularios(html_de(admin.get(f"/usuarios/{uid}/editar"))):
        for c in f.campos:
            if c.nome and "senha" in c.nome:
                assert not c.valor, "Campo senha da edicao vem preenchido"
                assert c.tipo == "password"


# --------------------------------------------------------------------------------------------- IDOR / escalada

def test_idor_comum_nao_acessa_ids_de_outros_pelos_endpoints_de_acao(comum):
    n = contar("ordens_servico", "status='Concluída'")
    for rota in ("/os/10233/fechar", "/os/10233/pecas", "/os/10233/excluir", "/pedidos/1625/cancelar", "/pedidos/1625/editar"):
        r = post(comum, rota, {})
        assert r.status_code in (403, 404), f"Comum POST {rota} -> {r.status_code}"
    assert contar("ordens_servico", "status='Concluída'") == n


def test_usuario_nao_vira_admin_por_parametro_forjado_no_login(anonimo):
    from helpers import enviar, ALIASES_LOGIN
    r = enviar(anonimo, "/login", {"usuario": "solicitante", "senha": "solicitante123"}, ALIASES_LOGIN,
               extras={"perfil": "Administrador", "is_admin": "1"}, estrito=False)
    assert anonimo.get("/usuarios").status_code == 403


def test_cookie_de_sessao_adulterado_e_rejeitado(admin, app):
    c = app.test_client()
    from helpers import logar_como
    logar_como(c, "comum")
    cookie = c.get_cookie("session")
    assert cookie is not None
    c.set_cookie("session", cookie.value[:-3] + ("AAA" if not cookie.value.endswith("AAA") else "BBB"))
    r = c.get("/menu")
    assert e_redirect_login(r), "Cookie de sessao com assinatura invalida deveria ser tratado como nao logado"


def test_cookie_de_sessao_tem_httponly_e_samesite(app):
    from helpers import fazer_login
    c = app.test_client()
    r = fazer_login(c, "admin", "admin123")
    sc = " ".join(r.headers.getlist("Set-Cookie")).lower()
    assert "httponly" in sc
    assert "samesite" in sc, "Recomendado: SameSite=Lax no cookie de sessao (defesa extra contra CSRF)"


def test_cabecalhos_de_seguranca_basicos(admin):
    r = admin.get("/menu")
    h = {k.lower(): v for k, v in r.headers.items()}
    assert h.get("x-content-type-options", "").lower() == "nosniff", "Recomendado: X-Content-Type-Options: nosniff"
    assert "x-frame-options" in h or "frame-ancestors" in h.get("content-security-policy", ""), \
        "Recomendado: X-Frame-Options/CSP frame-ancestors (clickjacking)"


# --------------------------------------------------------------------------------------------- BUG-010: CSP

CSP_PAGINAS = ["/login", "/menu", "/dashboard", "/pecas", "/os/10234", "/relatorios", "/configuracoes", "/pagina-que-nao-existe"]


@pytest.mark.parametrize("pagina", CSP_PAGINAS)
def test_csp_presente_e_restritiva(admin, pagina):
    csp = admin.get(pagina).headers.get("Content-Security-Policy", "")
    assert csp, f"{pagina}: sem Content-Security-Policy"
    d = {p.split()[0]: p.split()[1:] for p in csp.split(";") if p.strip()}
    assert d.get("default-src") == ["'self'"], csp
    assert "'unsafe-eval'" not in csp and "*" not in csp.replace("*/", ""), f"CSP permissiva: {csp}"
    assert "http:" not in csp and "https:" not in csp, "CSP nao deve liberar origens externas"
    assert d.get("script-src") == ["'self'"], "scripts so do proprio dominio (sem inline, sem CDN)"
    assert d.get("object-src") == ["'none'"] and d.get("frame-ancestors") == ["'none'"]
    assert d.get("base-uri") == ["'self'"] and d.get("form-action") == ["'self'"]


def test_csp_tambem_nas_respostas_de_erro_e_exportacao(admin, anonimo):
    for r in (anonimo.get("/login"), admin.get("/dashboard/exportar.pdf"), admin.get("/api/dashboard"), admin.get("/os/99999999")):
        assert r.headers.get("Content-Security-Policy"), f"{r.request.path}: sem CSP"


def test_templates_nao_tem_script_inline_nem_handler_inline_incompativeis_com_a_csp():
    """script-src 'self' bloqueia <script> inline e onclick=...; qualquer um quebraria em silencio no navegador."""
    import pathlib
    ruins = []
    for t in (pathlib.Path(__file__).resolve().parent.parent / "templates").glob("*.html"):
        txt = t.read_text(encoding="utf-8")
        for m in re.finditer(r"<script\b([^>]*)>", txt, re.I):
            if "src=" not in m.group(1) and "application/json" not in m.group(1):
                ruins.append(f"{t.name}: <script> inline")
        for m in re.finditer(r"\son(click|change|submit|load|input|focus|blur)\s*=", txt, re.I):
            ruins.append(f"{t.name}: handler on{m.group(1)}=")
    assert not ruins, f"Incompativel com a CSP (script-src 'self'): {ruins[:8]}"
