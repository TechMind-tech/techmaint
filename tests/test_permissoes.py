"""SB-102: perfis e permissoes (RBAC)."""

import pytest

import database
from seguranca import MATRIZ, PERFIS
from tests.conftest import postar


def test_os_quatro_perfis_existem_com_permissoes_distintas(app):
    conjuntos = {}
    for perfil in PERFIS:
        linhas = database.consultar(
            """SELECT pm.codigo FROM perfis pf
                 JOIN perfis_permissoes pp ON pp.id_perfil = pf.id
                 JOIN permissoes pm ON pm.id = pp.id_permissao
                WHERE pf.nome = ?""", (perfil,))
        conjuntos[perfil] = frozenset(l["codigo"] for l in linhas)
        assert conjuntos[perfil] == frozenset(MATRIZ[perfil])
    assert len(set(conjuntos.values())) == 4  # nenhum perfil igual ao outro


@pytest.mark.parametrize("url", ["/maquinas/novo", "/departamentos/novo", "/pecas/novo",
                                 "/fornecedores/novo", "/prestadores/novo", "/usuarios/novo"])
def test_tecnico_recebe_403_ao_tentar_cadastrar(tecnico, url):
    resposta = tecnico.get(url)
    assert resposta.status_code == 403
    assert "permissao" in resposta.text
    assert "Traceback" not in resposta.text  # pagina amigavel, sem stack trace


def test_403_vale_no_servidor_mesmo_com_post_direto(tecnico):
    resposta = postar(tecnico, "/departamentos/novo", {"nome": "Invasao"})
    assert resposta.status_code == 403
    assert database.consultar_um("SELECT 1 FROM departamentos WHERE nome = 'Invasao'") is None


def test_cliente_ve_maquinas_mas_nao_pecas(cliente_perfil):
    assert cliente_perfil.get("/maquinas/").status_code == 200
    assert cliente_perfil.get("/pecas/").status_code == 403
    assert cliente_perfil.get("/fornecedores/").status_code == 403


def test_menu_esconde_o_que_o_perfil_nao_pode(cliente_perfil):
    html = cliente_perfil.get("/").text
    assert 'href="/maquinas/"' in html
    assert 'href="/pecas/"' not in html
    assert 'href="/usuarios/"' not in html


def test_botoes_de_editar_somem_para_quem_so_ve(tecnico):
    html = tecnico.get("/maquinas/").text
    assert "+ Nova" not in html
    assert "Apagar" not in html


def test_gestor_ve_usuarios_mas_nao_edita(gestor):
    assert gestor.get("/usuarios/").status_code == 200
    assert gestor.get("/usuarios/novo").status_code == 403
    assert "+ Novo" not in gestor.get("/usuarios/").text


def test_gestor_cadastra_maquina(gestor):
    resposta = postar(gestor, "/maquinas/novo", {
        "nome": "Prensa", "id_departamento": "1", "status": "OPERANDO"})
    assert resposta.status_code == 302


def test_api_403_em_json(tecnico):
    resposta = tecnico.post("/api/departamentos", json={"nome": "X"})
    assert resposta.status_code == 403
    assert "erro" in resposta.get_json()
