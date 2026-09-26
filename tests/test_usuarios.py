"""SB-102: CRUD de usuarios (tela e API)."""

import database
from tests.conftest import logar, postar


def id_de(login):
    return database.consultar_um("SELECT id FROM usuarios WHERE login = ?", (login,))["id"]


def novo_usuario(**mudancas):
    dados = {"nome": "Ana Souza", "login": "ana", "email": "ana@techmaint.local",
             "senha": "senhaforte", "perfis": ["TECNICO"]}
    dados.update(mudancas)
    return dados


def test_admin_cria_usuario_que_consegue_logar(admin, app):
    resposta = postar(admin, "/usuarios/novo", novo_usuario(perfis=["TECNICO", "GESTOR"]))
    assert resposta.status_code == 302
    outro = app.test_client()
    assert logar(outro, "ana", "senhaforte").status_code == 302
    eu = outro.get("/api/eu").get_json()
    assert sorted(eu["perfis"]) == ["GESTOR", "TECNICO"]


def test_login_repetido_e_recusado(admin):
    resposta = postar(admin, "/usuarios/novo", novo_usuario(login="GESTOR"))
    assert resposta.status_code == 422
    assert "ja esta em uso" in resposta.text


def test_senha_curta_e_perfil_vazio_sao_recusados(admin):
    resposta = postar(admin, "/usuarios/novo", novo_usuario(senha="123", perfis=[]))
    assert resposta.status_code == 422
    assert "pelo menos 8" in resposta.text
    assert "pelo menos um perfil" in resposta.text


def test_perfil_inventado_e_recusado(admin):
    resposta = postar(admin, "/usuarios/novo", novo_usuario(perfis=["SUPERUSUARIO"]))
    assert resposta.status_code == 422


def test_editar_sem_senha_mantem_a_senha(admin, app):
    id_tecnico = id_de("tecnico")
    antes = database.consultar_um("SELECT senha_hash FROM usuarios WHERE id = ?", (id_tecnico,))
    resposta = postar(admin, f"/usuarios/editar/{id_tecnico}", {
        "nome": "Tiago T.", "login": "tecnico", "email": "", "senha": "", "perfis": ["TECNICO"]})
    assert resposta.status_code == 302
    depois = database.consultar_um("SELECT nome, senha_hash FROM usuarios WHERE id = ?", (id_tecnico,))
    assert depois["nome"] == "Tiago T."
    assert depois["senha_hash"] == antes["senha_hash"]


def test_nao_pode_desativar_a_si_mesmo(admin):
    postar(admin, f"/usuarios/desativar/{id_de('admin')}")
    assert database.consultar_um("SELECT ativo FROM usuarios WHERE login = 'admin'")["ativo"] == 1


def test_nao_pode_tirar_o_perfil_do_ultimo_administrador(admin):
    resposta = postar(admin, f"/usuarios/editar/{id_de('admin')}", {
        "nome": "Administrador", "login": "admin", "perfis": ["GESTOR"]})
    assert resposta.status_code == 422
    assert "unico administrador" in resposta.text


def test_desativar_e_reativar(admin):
    id_cliente = id_de("cliente")
    postar(admin, f"/usuarios/desativar/{id_cliente}")
    assert "cliente@techmaint.local" not in admin.get("/usuarios/").text
    assert "cliente@techmaint.local" in admin.get("/usuarios/?inativos=1").text
    postar(admin, f"/usuarios/reativar/{id_cliente}")
    assert database.consultar_um("SELECT ativo FROM usuarios WHERE id = ?", (id_cliente,))["ativo"] == 1


# --- API --------------------------------------------------------------------

def test_api_crud_de_usuario(admin):
    resposta = admin.post("/api/usuarios", json=novo_usuario(perfis=["CLIENTE"]))
    assert resposta.status_code == 201
    corpo = resposta.get_json()
    assert "senha_hash" not in corpo and "senha" not in corpo
    assert corpo["perfis"] == ["CLIENTE"]

    resposta = admin.put(f"/api/usuarios/{corpo['id']}", json={
        "nome": "Ana S.", "login": "ana", "perfis": "GESTOR"})
    assert resposta.status_code == 200
    assert resposta.get_json()["perfis"] == ["GESTOR"]

    resposta = admin.delete(f"/api/usuarios/{corpo['id']}")
    assert resposta.status_code == 200
    assert resposta.get_json()["ativo"] is False


def test_api_validacao_devolve_422_com_os_campos(admin):
    resposta = admin.post("/api/usuarios", json={"nome": ""})
    assert resposta.status_code == 422
    assert {"nome", "login", "senha", "perfis"} <= set(resposta.get_json()["campos"])


def test_api_nao_desativa_a_si_mesmo(admin):
    resposta = admin.delete(f"/api/usuarios/{id_de('admin')}")
    assert resposta.status_code == 409
