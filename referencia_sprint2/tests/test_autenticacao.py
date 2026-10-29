"""SB-102: login, logout, senha com hash e protecao CSRF."""

import database
from tests.conftest import logar, postar, token


def test_pagina_protegida_manda_para_o_login_com_next(cliente):
    resposta = cliente.get("/maquinas/?status=PARADO")
    assert resposta.status_code == 302
    assert resposta.headers["Location"] == "/login?next=/maquinas/?status%3DPARADO"


def test_senha_errada_nao_entra(cliente):
    resposta = logar(cliente, "admin", "senha-errada")
    assert resposta.status_code == 401
    assert "Login ou senha incorretos" in resposta.text
    assert cliente.get("/").status_code == 302  # continua deslogado


def test_login_inexistente_da_a_mesma_mensagem(cliente):
    resposta = logar(cliente, "ninguem", "qualquer")
    assert "Login ou senha incorretos" in resposta.text


def test_senha_certa_entra_e_volta_para_o_next(cliente):
    resposta = cliente.post("/login?next=/pecas/", data={
        "login": "admin", "senha": "admin123", "csrf_token": token(cliente)})
    assert resposta.status_code == 302
    assert resposta.headers["Location"] == "/pecas/"


def test_login_ignora_maiusculas(cliente):
    assert logar(cliente, "ADMIN", "admin123").status_code == 302


def test_next_para_outro_site_e_ignorado(cliente):
    for destino in ["https://site-falso.com", "//site-falso.com", "javascript:alert(1)"]:
        resposta = cliente.post(f"/login?next={destino}", data={
            "login": "admin", "senha": "admin123", "csrf_token": token(cliente)})
        assert resposta.headers["Location"] == "/"


def test_senha_guardada_como_hash(app):
    linha = database.consultar_um("SELECT senha_hash FROM usuarios WHERE login = 'admin'")
    assert linha["senha_hash"] != "admin123"
    assert "admin123" not in linha["senha_hash"]
    assert linha["senha_hash"].startswith(("scrypt:", "pbkdf2:"))


def test_formulario_sem_token_csrf_e_recusado(cliente):
    resposta = cliente.post("/login", data={"login": "admin", "senha": "admin123"})
    assert resposta.status_code == 400
    assert "Formulario expirado" in resposta.text


def test_formulario_com_token_errado_e_recusado(admin):
    token(admin)
    resposta = admin.post("/departamentos/novo", data={"nome": "X", "csrf_token": "falso"})
    assert resposta.status_code == 400
    assert database.consultar_um("SELECT 1 FROM departamentos WHERE nome = 'X'") is None


def test_logout_exige_post_e_encerra_a_sessao(admin):
    assert admin.get("/logout").status_code == 405
    postar(admin, "/logout")
    assert admin.get("/").status_code == 302


def test_usuario_desativado_nao_entra(admin):
    id_tecnico = database.consultar_um("SELECT id FROM usuarios WHERE login = 'tecnico'")["id"]
    postar(admin, f"/usuarios/desativar/{id_tecnico}")
    postar(admin, "/logout")
    assert logar(admin, "tecnico").status_code == 401


def test_usuario_desativado_perde_a_sessao_aberta(app):
    tecnico = app.test_client()
    logar(tecnico, "tecnico")
    assert tecnico.get("/maquinas/").status_code == 200
    database.executar("UPDATE usuarios SET ativo = 0 WHERE login = 'tecnico'")
    assert tecnico.get("/maquinas/").status_code == 302


# --- API --------------------------------------------------------------------

def test_api_sem_login_devolve_401_em_json(cliente):
    resposta = cliente.get("/api/maquinas")
    assert resposta.status_code == 401
    assert "login" in resposta.get_json()["erro"].lower()


def test_api_login_e_eu(cliente):
    resposta = cliente.post("/api/login", json={"login": "gestor", "senha": "senha123"})
    assert resposta.status_code == 200
    assert "senha_hash" not in resposta.get_json()
    eu = cliente.get("/api/eu").get_json()
    assert eu["perfis"] == ["GESTOR"]
    assert "maquinas:editar" in eu["permissoes"]
    assert "usuarios:editar" not in eu["permissoes"]


def test_api_login_errado(cliente):
    resposta = cliente.post("/api/login", json={"login": "gestor", "senha": "x"})
    assert resposta.status_code == 401


def test_api_post_sem_json_e_recusado(cliente):
    # Um formulario de outro site so consegue mandar "form", nunca JSON.
    resposta = cliente.post("/api/login", data={"login": "admin", "senha": "admin123"})
    assert resposta.status_code == 415
