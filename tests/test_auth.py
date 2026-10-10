"""
Autenticacao: login, validacoes, usuario inativo, bloqueio por forca bruta, logout, `proximo`, recuperacao de senha.

Rastreabilidade: RF "Cadastro de Usuarios: login seguro, recuperacao de senha" (Projeto §15b),
Manual §6.2 (Login), SPEC §2 (mensagens, 302 com proximo, bloqueio 5 falhas/5 min), SPEC §4 (/login, /logout, /recuperar-senha).
Obs.: logins "descartaveis" unicos evitam que o contador de falhas (que pode ser em memoria) contamine outros testes.
"""

import re
from urllib.parse import parse_qs, unquote, urlparse

import pytest

from helpers import (ALIASES_LOGIN, MSG_CAMPOS_VAZIOS, MSG_LOGIN_INVALIDO, USUARIOS_DEMO, ContratoAusente,
                     contem, criar_usuario_db, e_redirect_login, enviar, extrair_csrf, fazer_login, formularios,
                     html_de, local, obter_csrf, post, texto_visivel, unico, um, executa, normalizar)


# ----------------------------------------------------------------------------- tela de login

def test_tela_de_login_tem_os_elementos_do_figma_e_do_manual(anonimo):
    r = anonimo.get("/login")
    assert r.status_code == 200
    h = html_de(r)
    for trecho in ("TechMaint", "Faça login para continuar", "ENTRAR", "Esqueceu a senha?", "Lembrar-me",
                   "Desenvolvido em Python"):
        assert trecho.lower() in texto_visivel(h).lower(), f"Login deveria exibir {trecho!r} (Figma 01-login / SPEC §5)"
    forms = [f for f in formularios(h) if f.method == "post"]
    assert forms, "Login precisa de <form method=post>"
    nomes = forms[0].nomes
    assert "csrf_token" in nomes, f"Form de login sem csrf_token (SPEC §1). Campos: {nomes}"
    assert any(n in nomes for n in ("usuario", "login", "username")), f"Campo de usuario ausente: {nomes}"
    assert any(n in nomes for n in ("senha", "password")), f"Campo de senha ausente: {nomes}"
    tipos = {c.nome: c.tipo for c in forms[0].campos}
    assert tipos.get("senha", tipos.get("password")) == "password", "Campo senha deve ser type=password"
    assert '<html' in h.lower() and 'lang="pt' in h.lower(), "html lang pt-BR esperado"


def test_link_esqueceu_a_senha_aponta_para_recuperar(anonimo):
    h = html_de(anonimo.get("/login"))
    assert "/recuperar-senha" in h


def test_raiz_sem_login_redireciona_para_login(anonimo):
    r = anonimo.get("/")
    assert e_redirect_login(r) or (r.status_code in (301, 302) and "/dashboard" in local(r)), \
        f"'/' deveria redirecionar (para /dashboard e dali para /login). Veio {r.status_code} {local(r)}"


# ----------------------------------------------------------------------------- login valido

@pytest.mark.parametrize("chave", list(USUARIOS_DEMO))
def test_login_valido_de_cada_usuario_demo(anonimo, chave):
    login, senha, perfil = USUARIOS_DEMO[chave]
    r = fazer_login(anonimo, login, senha)
    assert r.status_code in (302, 303), f"Login valido deveria redirecionar (PRG). Veio {r.status_code}"
    destino = urlparse(local(r)).path
    assert destino in ("/menu", "/dashboard", "/", "/menu/"), f"Apos login, destino inesperado: {destino}"
    pag = anonimo.get(local(r), follow_redirects=True)
    assert pag.status_code == 200, f"Pagina inicial pos-login do perfil {perfil} deveria ser 200, veio {pag.status_code}"
    t = texto_visivel(html_de(pag))
    nome = um("SELECT nome FROM usuarios WHERE login=?", login)
    assert nome in t, f"Nome do usuario ({nome}) deveria aparecer no cabecalho (Figma)"


def test_login_nao_diferencia_maiusculas_do_login(anonimo):
    r = fazer_login(anonimo, "ADMIN", "admin123")
    assert r.status_code in (302, 303), "Login case-insensitive (SPEC §3.6: login unico case-insensitive)"


def test_sessao_autentica_acesso_a_area_restrita(anonimo):
    fazer_login(anonimo, "admin", "admin123")
    assert anonimo.get("/dashboard", follow_redirects=True).status_code == 200


def test_cookie_de_sessao_httponly(anonimo):
    r = fazer_login(anonimo, "admin", "admin123")
    cookies = r.headers.getlist("Set-Cookie")
    assert cookies, "Login deveria abrir uma sessao (Set-Cookie)"
    assert all("httponly" in c.lower() for c in cookies if c.lower().startswith("session")), \
        f"Cookie de sessao sem HttpOnly: {cookies}"


# ----------------------------------------------------------------------------- login invalido

def test_senha_errada_mensagem_generica(anonimo):
    login = unico("u")
    criar_usuario_db(login, "senhaCerta1")
    r = fazer_login(anonimo, login, "senhaErrada")
    assert r.status_code in (200, 400, 401)
    assert MSG_LOGIN_INVALIDO in texto_visivel(html_de(r)), f"Esperado {MSG_LOGIN_INVALIDO!r} (SPEC §2)"
    assert anonimo.get("/dashboard").status_code == 302, "Nao deveria estar logado"


def test_usuario_inexistente_mesma_mensagem_que_senha_errada(anonimo, app):
    """Nao revelar se o usuario existe (SPEC §2)."""
    login = unico("v")
    criar_usuario_db(login, "senhaCerta1")
    r1 = fazer_login(anonimo, login, "errada")
    r2 = fazer_login(app.test_client(), unico("naoexiste"), "errada")
    t1, t2 = texto_visivel(html_de(r1)), texto_visivel(html_de(r2))
    assert MSG_LOGIN_INVALIDO in t1 and MSG_LOGIN_INVALIDO in t2
    assert r1.status_code == r2.status_code


@pytest.mark.parametrize("usuario,senha", [("", ""), ("admin", ""), ("", "admin123"), ("   ", "   ")])
def test_campos_vazios(anonimo, usuario, senha):
    r = fazer_login(anonimo, usuario, senha)
    assert r.status_code in (200, 400, 401), f"HTTP {r.status_code}"
    assert MSG_CAMPOS_VAZIOS in texto_visivel(html_de(r)), f"Esperado {MSG_CAMPOS_VAZIOS!r} (SPEC §2, Figma 02)"


def test_erro_de_login_mantem_usuario_digitado(anonimo):
    r = fazer_login(anonimo, "alguem.digitado", "xxxxxxxx")
    h = html_de(r)
    assert "alguem.digitado" in h, "O valor digitado no usuario deve ser preservado (SPEC §4 valores.usuario)"
    assert "xxxxxxxx" not in h, "A senha digitada NUNCA deve voltar no HTML"


def test_login_com_injecao_sql_nao_autentica_nem_quebra(anonimo):
    for payload in ("' OR '1'='1", "admin'--", "'; DROP TABLE usuarios; --", '" OR ""="'):
        r = fazer_login(anonimo, payload, payload)
        assert r.status_code in (200, 400, 401), f"{payload!r} -> HTTP {r.status_code}"
    assert um("SELECT COUNT(*) FROM usuarios") >= 5, "Tabela usuarios foi afetada!"
    assert anonimo.get("/dashboard").status_code == 302


def test_login_com_valores_gigantes_e_unicode(anonimo):
    r = fazer_login(anonimo, "x" * 5000, "y" * 5000)
    assert r.status_code < 500
    r = fazer_login(anonimo, "usuário-ção-🙂-‮", "sénha-🙂")
    assert r.status_code < 500


def test_login_sem_csrf_e_rejeitado(anonimo):
    anonimo.get("/login")
    r = anonimo.post("/login", data={"usuario": "admin", "senha": "admin123"})
    assert r.status_code in (400, 403), f"POST /login sem csrf_token deveria ser 400/403, veio {r.status_code}"
    assert anonimo.get("/dashboard").status_code == 302


def test_login_com_csrf_invalido_e_rejeitado(anonimo):
    anonimo.get("/login")
    r = anonimo.post("/login", data={"usuario": "admin", "senha": "admin123", "csrf_token": "forjado"})
    assert r.status_code in (400, 403)


# ----------------------------------------------------------------------------- inativo

def test_usuario_inativo_nao_loga(anonimo):
    login = unico("ina")
    criar_usuario_db(login, "senhaCerta1", ativo=0)
    r = fazer_login(anonimo, login, "senhaCerta1")
    assert r.status_code in (200, 400, 401, 403), f"Usuario inativo recebeu HTTP {r.status_code} (deveria negar)"
    assert anonimo.get("/dashboard").status_code == 302, "Usuario inativo conseguiu abrir sessao (SPEC §2)"


def test_usuario_desativado_com_sessao_aberta_perde_acesso(app, admin):
    """Se o admin inativa um usuario logado, o proximo acesso dele deve ser barrado."""
    login = unico("des")
    uid = criar_usuario_db(login, "senhaCerta1", "Técnico")
    c = app.test_client()
    assert fazer_login(c, login, "senhaCerta1").status_code in (302, 303)
    assert c.get("/menu").status_code == 200
    executa("UPDATE usuarios SET ativo = 0 WHERE id = ?", uid)
    r = c.get("/menu")
    assert r.status_code in (302, 401, 403), "Usuario inativado continuou com acesso na sessao aberta"


# ----------------------------------------------------------------------------- bloqueio

MSG_BLOQUEIO = ("bloque", "tentativas", "minuto", "aguarde", "muitas")


def test_bloqueio_apos_5_falhas_seguidas(anonimo):
    login = unico("blq")
    criar_usuario_db(login, "senhaCerta1")
    for i in range(5):
        r = fazer_login(anonimo, login, f"errada{i}")
        assert r.status_code in (200, 400, 401, 429)
    # 6a tentativa com a senha CORRETA continua barrada
    r = fazer_login(anonimo, login, "senhaCerta1")
    assert r.status_code in (200, 400, 401, 403, 429), f"Login deveria estar bloqueado, veio {r.status_code}"
    assert anonimo.get("/dashboard").status_code == 302, "Apos 5 falhas a conta deveria estar bloqueada por 5 min (SPEC §2)"
    t = normalizar(texto_visivel(html_de(r)))
    assert any(normalizar(m) in t for m in MSG_BLOQUEIO), \
        f"A mensagem de bloqueio deve ser clara (SPEC §2). Texto: {texto_visivel(html_de(r))[:200]!r}"


def test_quarta_falha_ainda_nao_bloqueia(anonimo):
    login = unico("q4")
    criar_usuario_db(login, "senhaCerta1")
    for i in range(4):
        fazer_login(anonimo, login, f"errada{i}")
    r = fazer_login(anonimo, login, "senhaCerta1")
    assert r.status_code in (302, 303), "Com 4 falhas ainda nao deveria bloquear (limite e 5)"


def test_bloqueio_e_por_login_nao_global(app):
    a, b = unico("ba"), unico("bb")
    criar_usuario_db(a, "senhaCerta1")
    criar_usuario_db(b, "senhaCerta1")
    c1, c2 = app.test_client(), app.test_client()
    for i in range(6):
        fazer_login(c1, a, f"x{i}")
    r = fazer_login(c2, b, "senhaCerta1")
    assert r.status_code in (302, 303), "O bloqueio de um login nao deve afetar outro login"


def test_sucesso_zera_contador_de_falhas(app):
    login = unico("zr")
    criar_usuario_db(login, "senhaCerta1")
    c = app.test_client()
    for _ in range(3):
        fazer_login(c, login, "errada")
    assert fazer_login(c, login, "senhaCerta1").status_code in (302, 303)
    c2 = app.test_client()
    for _ in range(3):
        fazer_login(c2, login, "errada")
    r = fazer_login(c2, login, "senhaCerta1")
    assert r.status_code in (302, 303), "'5 falhas SEGUIDAS': um sucesso no meio deve zerar o contador (SPEC §2)"


def test_bloqueio_vale_mesmo_trocando_de_cliente(app):
    login = unico("bc")
    criar_usuario_db(login, "senhaCerta1")
    for i in range(5):
        fazer_login(app.test_client(), login, f"errada{i}")
    r = fazer_login(app.test_client(), login, "senhaCerta1")
    assert r.status_code not in (302, 303), "Bloqueio contornado abrindo nova sessao/cookie"


# ----------------------------------------------------------------------------- logout

def test_logout_encerra_sessao(admin):
    assert admin.get("/dashboard").status_code == 200
    r = post(admin, "/logout")
    assert r.status_code in (302, 303)
    assert urlparse(local(r)).path.startswith("/login")
    assert e_redirect_login(admin.get("/dashboard")), "Depois do logout, /dashboard deve redirecionar ao login"


def test_logout_so_aceita_post(admin):
    assert admin.get("/logout").status_code == 405
    assert admin.get("/dashboard").status_code == 200, "GET /logout nao pode derrubar a sessao (CSRF de logout)"


def test_logout_sem_csrf_rejeitado(admin):
    r = admin.post("/logout")
    assert r.status_code in (400, 403)
    assert admin.get("/dashboard").status_code == 200


def test_botao_sair_existe_no_cabecalho_ou_menu(admin):
    h = html_de(admin.get("/menu"))
    assert any(f.method == "post" and f.action.rstrip("/").endswith("/logout") for f in formularios(h)), \
        "Esperado <form method=post action=/logout> acessivel na tela (Manual 6.2: Sair do sistema)"


def test_botao_voltar_do_navegador_apos_logout_nao_mostra_dado_em_cache(admin):
    r = admin.get("/dashboard")
    cc = (r.headers.get("Cache-Control") or "").lower()
    assert "no-store" in cc or "no-cache" in cc or "private" in cc, \
        f"Paginas autenticadas deveriam evitar cache compartilhado/persistente. Cache-Control={cc!r}"


# ----------------------------------------------------------------------------- proximo

def test_redirect_para_login_preserva_proximo(anonimo):
    r = anonimo.get("/usuarios")
    assert r.status_code == 302
    loc = urlparse(local(r))
    assert loc.path == "/login"
    assert parse_qs(loc.query).get("proximo") == ["/usuarios"], f"Location={local(r)!r} (SPEC §2: /login?proximo=<url>)"


def test_proximo_com_query_string_e_preservado(anonimo):
    r = anonimo.get("/pedidos?status=Aberto&busca=bomba")
    q = parse_qs(urlparse(local(r)).query)
    assert q.get("proximo") and q["proximo"][0].startswith("/pedidos") and "status=Aberto" in unquote(q["proximo"][0])


def test_login_com_proximo_volta_para_a_pagina_pedida(anonimo):
    r = fazer_login(anonimo, "admin", "admin123", proximo="/usuarios")
    assert r.status_code in (302, 303)
    assert urlparse(local(r)).path == "/usuarios"


@pytest.mark.parametrize("externo", ["https://evil.example.com/x", "//evil.example.com", "http://evil.example.com",
                                     "javascript:alert(1)", "\\\\evil.example.com", "/\\evil.example.com"])
def test_proximo_nao_permite_open_redirect(anonimo, externo):
    r = fazer_login(anonimo, "admin", "admin123", proximo=externo)
    assert r.status_code in (302, 303, 200)
    if r.status_code in (302, 303):
        u = urlparse(local(r))
        assert not u.netloc and not local(r).startswith(("//", "\\", "javascript")), f"Open redirect para {local(r)!r}"


def test_proximo_para_pagina_sem_permissao_nao_vaza(app):
    """Usuario Comum com proximo=/usuarios entra e recebe 403 (nao erro 500 nem vazamento)."""
    c = app.test_client()
    r = fazer_login(c, "solicitante", "solicitante123", proximo="/usuarios")
    assert r.status_code in (302, 303)
    assert c.get(local(r), follow_redirects=True).status_code in (403, 200)  # 200 se o app preferir cair no menu
    h = html_de(c.get("/usuarios"))
    assert "admin123" not in h


# ----------------------------------------------------------------------------- recuperar senha

ALIASES_RECUP = {"usuario": ["usuario", "login", "email", "identificador"], "senha": ["senha", "nova_senha", "password"],
                 "confirmar": ["confirmar_senha", "confirmar", "confirmacao", "senha2", "repetir_senha"]}


HOOK_LINKS = "techmaint_links_reset"   # app.extensions[...] = {login: link}; so existe com app.testing=True (modulos/auth.py)
HOOK_ULTIMO = "techmaint_ultimo_link_reset"


def _token(app, login):
    """Token de redefinicao pelo gancho de teste (o link nao aparece mais na tela: BUG-003)."""
    link = app.extensions.get(HOOK_LINKS, {}).get(login) or app.extensions.get(HOOK_ULTIMO)
    m = re.search(r"redefinir-senha/([A-Za-z0-9_\-\.=]+)", link or "")
    return m.group(1) if m else None


def test_recuperar_senha_pagina(anonimo):
    r = anonimo.get("/recuperar-senha")
    assert r.status_code == 200
    forms = [f for f in formularios(html_de(r)) if f.method == "post"]
    assert forms and "csrf_token" in forms[0].nomes


def _recuperar(app, usuario):
    c = app.test_client()
    return enviar(c, "/recuperar-senha", {"usuario": usuario}, ALIASES_RECUP, seguir=True, estrito=False)


def test_recuperar_senha_nao_revela_se_usuario_existe(app):
    """BUG-003 (verificado): resposta identica para login existente e inexistente, sem link/token na tela."""
    r1, r2 = _recuperar(app, "admin"), _recuperar(app, unico("naoexiste"))
    assert r1.status_code == r2.status_code < 500
    t1, t2 = texto_visivel(html_de(r1)), texto_visivel(html_de(r2))
    assert t1 == t2, "A resposta difere entre usuario existente e inexistente (enumeracao)"
    for h in (html_de(r1), html_de(r2)):
        assert "redefinir-senha/" not in h, "Link/token de redefinicao nao pode aparecer na tela"
        assert "(simulado) Link de redefinição" not in texto_visivel(h)
    assert "admin" in app.extensions.get(HOOK_LINKS, {}), "O link deveria ter sido gerado e so exposto ao gancho de teste"
    assert unico("naoexiste") not in app.extensions.get(HOOK_LINKS, {})


def test_recuperar_senha_sem_link_na_tela_nem_em_cabecalhos(app):
    r = _recuperar(app, "admin")
    link = app.extensions[HOOK_LINKS]["admin"]
    tok = link.rsplit("/", 1)[-1]
    assert tok not in html_de(r) and tok not in str(r.headers)
    assert tok not in str(app.test_client().get("/recuperar-senha").data)


def test_recuperar_senha_fluxo_completo(app):
    login = unico("rec")
    criar_usuario_db(login, "senhaAntiga1")
    c = app.test_client()
    r = enviar(c, "/recuperar-senha", {"usuario": login}, ALIASES_RECUP, seguir=True, estrito=False)
    assert r.status_code == 200
    tok = _token(app, login)
    assert tok, "O gancho de teste nao recebeu o link de redefinicao (modulos/auth.py: HOOK_LINKS)"
    pag = c.get(f"/redefinir-senha/{tok}")
    assert pag.status_code == 200, f"GET /redefinir-senha/<token> -> {pag.status_code}"
    r2 = enviar(c, f"/redefinir-senha/{tok}", {"senha": "novaSenha99", "confirmar": "novaSenha99"}, ALIASES_RECUP,
                seguir=True, estrito=False)
    assert r2.status_code == 200
    assert fazer_login(app.test_client(), login, "novaSenha99").status_code in (302, 303), "Nova senha deveria funcionar"
    assert fazer_login(app.test_client(), login, "senhaAntiga1").status_code not in (302, 303), "Senha antiga ainda funciona"


def test_token_de_recuperacao_e_de_uso_unico(app):
    login = unico("rc2")
    criar_usuario_db(login, "senhaAntiga1")
    c = app.test_client()
    r = enviar(c, "/recuperar-senha", {"usuario": login}, ALIASES_RECUP, seguir=True, estrito=False)
    tok = _token(app, login)
    assert tok, "gancho de teste sem link de redefinicao"
    enviar(c, f"/redefinir-senha/{tok}", {"senha": "novaSenha99", "confirmar": "novaSenha99"}, ALIASES_RECUP, seguir=True, estrito=False)
    r = c.post(f"/redefinir-senha/{tok}", data={"senha": "outraSenha88", "confirmar": "outraSenha88",
                                                "csrf_token": obter_csrf(c)})
    assert r.status_code in (200, 400, 404, 410, 302)
    assert fazer_login(app.test_client(), login, "outraSenha88").status_code not in (302, 303), "Token foi reutilizado"


@pytest.mark.parametrize("token", ["token-invalido", "0" * 64, "../../etc/passwd", "<script>", "' OR 1=1 --"])
def test_token_invalido_de_redefinicao(anonimo, token):
    r = anonimo.get(f"/redefinir-senha/{token}")
    assert r.status_code in (200, 302, 400, 404, 410), f"HTTP {r.status_code}"
    assert r.status_code != 500


def test_redefinir_senha_rejeita_senha_curta(app):
    login = unico("rc3")
    criar_usuario_db(login, "senhaAntiga1")
    c = app.test_client()
    r = enviar(c, "/recuperar-senha", {"usuario": login}, ALIASES_RECUP, seguir=True, estrito=False)
    tok = _token(app, login)
    assert tok, "gancho de teste sem link de redefinicao"
    enviar(c, f"/redefinir-senha/{tok}", {"senha": "123", "confirmar": "123"}, ALIASES_RECUP, seguir=True, estrito=False)
    assert fazer_login(app.test_client(), login, "123").status_code not in (302, 303), "Aceitou senha de 3 caracteres (min 8)"
    assert fazer_login(app.test_client(), login, "senhaAntiga1").status_code in (302, 303), "A senha antiga deveria seguir valendo"
