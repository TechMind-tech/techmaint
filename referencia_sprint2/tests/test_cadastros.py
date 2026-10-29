"""SB-103 a SB-110: departamentos, maquinas, pecas + estoque, fornecedores
e prestadores. Cada teste roda num banco novo, com os dados do seed."""

import sqlite3

import pytest

import database
from tests.conftest import postar


def um(sql, parametros=()):
    return database.consultar_um(sql, parametros)


# --- Departamentos (SB-103 / SB-104) ---------------------------------------

def test_departamento_crud_completo(admin):
    assert postar(admin, "/departamentos/novo", {"nome": "Utilidades", "responsavel": ""}).status_code == 302
    assert "Departamento criado" in admin.get("/departamentos/").text
    novo = um("SELECT * FROM departamentos WHERE nome = 'Utilidades'")
    assert novo["responsavel"] is None  # vazio vira NULL

    postar(admin, f"/departamentos/editar/{novo['id']}", {"nome": "Utilidades", "responsavel": "Jose"})
    assert um("SELECT responsavel FROM departamentos WHERE id = ?", (novo["id"],))["responsavel"] == "Jose"

    postar(admin, f"/departamentos/apagar/{novo['id']}")
    assert um("SELECT 1 FROM departamentos WHERE id = ?", (novo["id"],)) is None


def test_departamento_sem_nome_mostra_erro_e_nao_salva(admin):
    antes = um("SELECT COUNT(*) AS n FROM departamentos")["n"]
    resposta = postar(admin, "/departamentos/novo", {"nome": "  "})
    assert resposta.status_code == 422
    assert "Preencha o nome" in resposta.text
    assert um("SELECT COUNT(*) AS n FROM departamentos")["n"] == antes


def test_departamento_nome_repetido_ignora_maiusculas(admin):
    resposta = postar(admin, "/departamentos/novo", {"nome": "PRODUCAO"})
    assert resposta.status_code == 422
    assert "Ja existe" in resposta.text


def test_nao_apaga_departamento_com_maquinas(admin):
    producao = um("SELECT id FROM departamentos WHERE nome = 'Producao'")["id"]
    postar(admin, f"/departamentos/apagar/{producao}")
    assert um("SELECT 1 FROM departamentos WHERE id = ?", (producao,)) is not None
    assert admin.delete(f"/api/departamentos/{producao}").status_code == 409


def test_api_departamentos(admin):
    resposta = admin.post("/api/departamentos", json={"nome": "Qualidade"})
    assert resposta.status_code == 201
    novo_id = resposta.get_json()["id"]
    assert admin.get(f"/api/departamentos/{novo_id}").get_json()["nome"] == "Qualidade"
    assert admin.put(f"/api/departamentos/{novo_id}", json={"nome": ""}).status_code == 422
    assert admin.delete(f"/api/departamentos/{novo_id}").status_code == 204
    assert admin.get(f"/api/departamentos/{novo_id}").status_code == 404


# --- Maquinas (SB-103 / SB-104) --------------------------------------------

def test_maquina_precisa_de_departamento_existente(admin):
    resposta = postar(admin, "/maquinas/novo", {"nome": "Prensa", "id_departamento": "999", "status": "OPERANDO"})
    assert resposta.status_code == 422
    assert "Departamento nao encontrado" in resposta.text


def test_maquina_status_invalido_e_patrimonio_repetido(admin):
    resposta = postar(admin, "/maquinas/novo", {
        "nome": "Prensa", "patrimonio": "pat-0001", "id_departamento": "1", "status": "QUEBRADA"})
    assert resposta.status_code == 422
    assert "patrimonio" in resposta.text and "status valido" in resposta.text


def test_filtros_de_maquinas(admin):
    paradas = admin.get("/api/maquinas?status=PARADO").get_json()
    assert [m["nome"] for m in paradas] == ["Empilhadeira eletrica"]
    producao = um("SELECT id FROM departamentos WHERE nome = 'Producao'")["id"]
    assert len(admin.get(f"/api/maquinas?departamento={producao}").get_json()) == 2


def test_nao_apaga_maquina_com_pecas(admin):
    torno = um("SELECT id FROM maquinas WHERE patrimonio = 'PAT-0001'")["id"]
    postar(admin, f"/maquinas/apagar/{torno}")
    assert um("SELECT 1 FROM maquinas WHERE id = ?", (torno,)) is not None


def test_status_aparece_como_etiqueta(admin):
    assert "etiqueta--em-manutencao" in admin.get("/maquinas/").text


# --- Pecas + estoque (SB-105 / SB-106) -------------------------------------

def nova_peca(**mudancas):
    dados = {"nome": "Mancal", "codigo": "MAN-01", "ncm": "8483.30.90", "valor": "1.234,56",
             "id_maquina": "1", "qtde_atual": "3", "qtde_minima": "2", "qtde_maxima": "10",
             "local": "A-9"}
    dados.update(mudancas)
    return dados


def test_peca_e_estoque_sao_criados_juntos(admin):
    assert postar(admin, "/pecas/novo", nova_peca()).status_code == 302
    peca = um("""SELECT p.*, e.qtde_atual, e.qtde_minima, e.qtde_maxima
                   FROM pecas p JOIN estoque_pecas e ON e.id_peca = p.id
                  WHERE p.codigo = 'MAN-01'""")
    assert peca["valor_centavos"] == 123456   # dinheiro em centavos
    assert peca["ncm"] == "84833090"          # so digitos
    assert (peca["qtde_atual"], peca["qtde_minima"], peca["qtde_maxima"]) == (3, 2, 10)
    assert "R$ 1.234,56" in admin.get("/pecas/").text


@pytest.mark.parametrize("mudanca, trecho", [
    ({"valor": "-5"}, "nao pode ser negativo"),
    ({"valor": "abc"}, "invalido"),
    ({"qtde_minima": "10", "qtde_maxima": "5"}, "maximo nao pode ser menor"),
    ({"qtde_minima": "-1"}, "nao pode ser menor que 0"),
    ({"ncm": "123"}, "8 digitos"),
    ({"id_maquina": "999"}, "Maquina nao encontrada"),
    ({"codigo": "rol-6205"}, "Ja existe uma peca"),
])
def test_peca_invalida(admin, mudanca, trecho):
    resposta = postar(admin, "/pecas/novo", nova_peca(**mudanca))
    assert resposta.status_code == 422
    assert trecho in resposta.text


def test_editar_peca_nao_muda_o_saldo(admin):
    rolamento = um("SELECT id FROM pecas WHERE codigo = 'ROL-6205'")["id"]
    resposta = postar(admin, f"/pecas/editar/{rolamento}", nova_peca(
        nome="Rolamento 6205", codigo="ROL-6205", qtde_atual="999", qtde_minima="1", qtde_maxima="30"))
    assert resposta.status_code == 302
    estoque = um("SELECT * FROM estoque_pecas WHERE id_peca = ?", (rolamento,))
    assert estoque["qtde_atual"] == 12        # saldo so muda por movimentacao
    assert estoque["qtde_maxima"] == 30


def test_alerta_de_estoque_baixo(admin):
    em_alerta = admin.get("/api/pecas?alerta=1").get_json()
    # Filtro de ar (0 de 2) e Correia (2 de 5) estao abaixo do minimo;
    # o mais critico (proporcionalmente mais longe do minimo) vem primeiro.
    assert [p["codigo"] for p in em_alerta] == ["FIL-SRP", "COR-A42"]
    assert em_alerta[0]["estoque"]["sugestao_compra"] == 6

    html = admin.get("/pecas/").text
    assert html.count('class="linha--alerta"') == 2
    assert html.count("Repor") >= 2           # cor E texto
    assert "2 peca(s) abaixo do estoque minimo" in admin.get("/").text


def test_apagar_peca_leva_o_estoque_junto(admin):
    filtro = um("SELECT id FROM pecas WHERE codigo = 'FIL-SRP'")["id"]
    postar(admin, f"/pecas/apagar/{filtro}")
    assert um("SELECT 1 FROM estoque_pecas WHERE id_peca = ?", (filtro,)) is None


def test_api_pecas(admin):
    resposta = admin.post("/api/pecas", json={
        "nome": "Sensor", "valor_centavos": 9990, "id_maquina": 1,
        "estoque": {"atual": 1, "minimo": 2, "maximo": 4}})
    assert resposta.status_code == 201, resposta.get_json()
    peca = resposta.get_json()
    assert peca["valor_centavos"] == 9990
    assert peca["estoque"]["situacao"] == "REPOR"
    resposta = admin.put(f"/api/pecas/{peca['id']}", json={
        "nome": "Sensor", "valor_centavos": 12.5, "id_maquina": 1,
        "estoque": {"minimo": 2, "maximo": 4}})
    assert resposta.status_code == 422      # centavos precisa ser inteiro
    assert admin.delete(f"/api/pecas/{peca['id']}").status_code == 204


# --- Fornecedores (SB-107 / SB-108) ----------------------------------------

def novo_fornecedor(**mudancas):
    dados = {"razao_social": "Pecas Unidas Ltda", "cnpj": "90.908.080/0001-70",
             "email": "vendas@unidas.exemplo"}
    dados.update(mudancas)
    return dados


def test_fornecedor_cnpj_salvo_sem_mascara_e_exibido_com(admin):
    assert postar(admin, "/fornecedores/novo", novo_fornecedor()).status_code == 302
    assert um("SELECT cnpj FROM fornecedores WHERE razao_social = 'Pecas Unidas Ltda'")["cnpj"] == "90908080000170"
    assert "90.908.080/0001-70" in admin.get("/fornecedores/").text


def test_fornecedor_cnpj_invalido(admin):
    resposta = postar(admin, "/fornecedores/novo", novo_fornecedor(cnpj="11.111.111/1111-11"))
    assert resposta.status_code == 422
    assert "CNPJ invalido" in resposta.text


def test_fornecedor_cnpj_repetido_mostra_aviso_e_nao_erro_500(admin):
    resposta = postar(admin, "/fornecedores/novo", novo_fornecedor(cnpj="11222333000181"))
    assert resposta.status_code == 422
    assert "Ja existe um fornecedor com este CNPJ" in resposta.text


def test_fornecedor_exclusao_logica(admin):
    id_forn = um("SELECT id FROM fornecedores WHERE cnpj = '11222333000181'")["id"]
    postar(admin, f"/fornecedores/desativar/{id_forn}")
    assert um("SELECT ativo FROM fornecedores WHERE id = ?", (id_forn,))["ativo"] == 0  # continua no banco
    assert "Rolamentos Paulista" not in admin.get("/fornecedores/").text
    assert "Rolamentos Paulista" in admin.get("/fornecedores/?inativos=1").text
    postar(admin, f"/fornecedores/reativar/{id_forn}")
    assert um("SELECT ativo FROM fornecedores WHERE id = ?", (id_forn,))["ativo"] == 1


def test_fornecedor_busca_por_cnpj_com_mascara(admin):
    assert "Rolamentos Paulista" in admin.get("/fornecedores/?busca=11.222.333").text


def test_api_fornecedores(admin):
    resposta = admin.post("/api/fornecedores", json=novo_fornecedor())
    assert resposta.status_code == 201
    corpo = resposta.get_json()
    assert corpo["cnpj"] == "90908080000170" and corpo["cnpj_formatado"] == "90.908.080/0001-70"
    assert admin.post("/api/fornecedores", json=novo_fornecedor()).status_code == 422  # repetido
    resposta = admin.delete(f"/api/fornecedores/{corpo['id']}")
    assert resposta.status_code == 200 and resposta.get_json()["ativo"] is False


# --- Prestadores (SB-109 / SB-110) -----------------------------------------

def test_prestador_crud_e_exclusao_logica(admin):
    resposta = postar(admin, "/prestadores/novo", {
        "razao_social": "Hidro Servicos", "cnpj": "32132132000163", "especialidade": "Hidraulica"})
    assert resposta.status_code == 302
    novo = um("SELECT * FROM prestadores WHERE cnpj = '32132132000163'")
    assert novo["especialidade"] == "Hidraulica"
    postar(admin, f"/prestadores/desativar/{novo['id']}")
    assert um("SELECT ativo FROM prestadores WHERE id = ?", (novo["id"],))["ativo"] == 0
    assert "Hidro Servicos" not in admin.get("/prestadores/").text


def test_prestador_usa_a_mesma_validacao_de_cnpj(admin):
    resposta = postar(admin, "/prestadores/novo", {"razao_social": "X", "cnpj": "12345678000100"})
    assert resposta.status_code == 422
    assert "CNPJ invalido" in resposta.text


def test_mesmo_cnpj_pode_ser_fornecedor_e_prestador(admin):
    # Uma empresa pode vender peca E prestar servico: tabelas diferentes.
    resposta = postar(admin, "/prestadores/novo", {"razao_social": "RolaSP Servicos", "cnpj": "11222333000181"})
    assert resposta.status_code == 302


# --- O banco se protege sozinho, mesmo se o Python falhar ------------------

def test_banco_recusa_chave_estrangeira_invalida(app):
    with pytest.raises(sqlite3.IntegrityError):
        database.executar("INSERT INTO maquinas (nome, id_departamento) VALUES ('X', 999)")


def test_banco_recusa_estoque_negativo_e_minimo_maior_que_maximo(app):
    with pytest.raises(sqlite3.IntegrityError):
        database.executar("UPDATE estoque_pecas SET qtde_atual = -1")
    with pytest.raises(sqlite3.IntegrityError):
        database.executar("UPDATE estoque_pecas SET qtde_minima = 10, qtde_maxima = 5")


def test_banco_recusa_cnpj_com_tamanho_errado(app):
    with pytest.raises(sqlite3.IntegrityError):
        database.executar("INSERT INTO fornecedores (razao_social, cnpj) VALUES ('X', '123')")


def test_seed_pode_rodar_duas_vezes_sem_duplicar(app):
    import seed
    antes = um("SELECT (SELECT COUNT(*) FROM usuarios) + (SELECT COUNT(*) FROM pecas) AS n")["n"]
    seed.garantir_acesso_inicial()
    seed.carregar_exemplos()
    assert um("SELECT (SELECT COUNT(*) FROM usuarios) + (SELECT COUNT(*) FROM pecas) AS n")["n"] == antes
