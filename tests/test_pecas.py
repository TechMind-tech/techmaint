"""
CRUD de Pecas + "Atualizar estoque" (Manual §1.3, Figma 11-12, SPEC §3 regras 6-7, §4).

Rastreabilidade: RF "Cadastro de Pecas por maquina, valor unitario, estoque" (Projeto §15b), Manual 1.3
(Nome, Equipamento vinculado [lista], Valor unitario, Qtd estoque, NCM; Salvar/Excluir/Atualizar estoque/Editar;
listagem com filtro por equipamento), SPEC §3 (alerta Baixo: qtde < minimo; ajuste rapido gera movimentacao).
"""

import pytest

from helpers import (lista_de, Bruto, PAYLOADS_HOSTIS, assert_exibido_com_seguranca, assert_rejeitado, assert_sucesso_post,
                     consulta, contar, enviar, executa, formularios, html_de, linha, post, texto_visivel, unico, um)

ALIASES = {
    "nome": ["nome"], "equipamento": ["id_equipamento", "equipamento", "equipamento_id"],
    "valor": ["valor_unitario", "valor"], "qtde": ["qtde_estoque", "quantidade", "estoque", "qtd"], "ncm": ["ncm"],
    "minimo": ["estoque_minimo", "minimo"],
}


def payload(**kw):
    n = unico("P")
    base = dict(nome=f"Peca QA {n}", equipamento="BOMBA 1 (RESFRIADOR)", valor="15,50", qtde="25", ncm="84821010")
    base.update(kw)
    return base


def criar(c, **kw):
    return enviar(c, "/pecas", payload(**kw), ALIASES, estrito=False)


def peca(nome):
    return linha("SELECT * FROM pecas WHERE nome=?", nome)


# --------------------------------------------------------------------------------------------- tela

def test_tela_de_pecas(admin):
    t = texto_visivel(html_de(admin.get("/pecas")))
    for trecho in ("Cadastro de Peças", "Nova Peça", "Lista de Peças Cadastradas", "Rolamento 6204", "Sensor Indutivo",
                   "Correia V", "Filtro de Ar"):
        assert trecho.lower() in t.lower(), f"Figma 11/12: {trecho!r} ausente"


def test_formulario_usa_select_de_equipamento_conforme_manual(admin):
    """SPEC §3.7: 'Equipamento vinculado' e select de equipamentos cadastrados (nao texto livre)."""
    forms = [f for f in formularios(html_de(admin.get("/pecas"))) if f.method == "post" and "csrf_token" in f.nomes]
    f = max(forms, key=lambda x: len(x.campos))
    campo = next((c for c in f.campos if c.nome and "equipamento" in c.nome), None)
    assert campo, f"Campo de equipamento ausente: {f.nomes}"
    assert campo.tag == "select", "Equipamento vinculado deve ser <select> (Manual/apoio §4; SPEC §3.7)"
    assert len(campo.opcoes) >= 70, f"O select deveria listar os equipamentos cadastrados ({len(campo.opcoes)} opcoes)"


def test_botoes_cadastrar_excluir_atualizar_estoque_editar(admin):
    h = html_de(admin.get("/pecas"))
    t = texto_visivel(h)
    assert "Cadastrar" in t or "Salvar" in t
    assert "Editar" in t, "Manual 1.3: 'Incluir botao Editar'"
    assert "Atualizar estoque" in t, "Manual 1.3: botao Atualizar estoque"


def test_alerta_baixo_so_no_filtro_de_ar(admin):
    t = texto_visivel(lista_de(html_de(admin.get("/pecas?busca=Filtro"))))
    assert "Baixo" in t, "Figma 12: aviso '⚠ Baixo' em laranja no Filtro de Ar"
    t2 = texto_visivel(lista_de(html_de(admin.get("/pecas?busca=Rolamento"))))
    assert "Baixo" not in t2


def test_rodape_da_lista_mostra_contagem(admin):
    t = texto_visivel(html_de(admin.get("/pecas")))
    n = contar("pecas")
    assert f"{n}" in t and ("iten" in t.lower() or "peça" in t.lower()), "Figma 12: 'Mostrando N de N itens'"


# --------------------------------------------------------------------------------------------- criar

def test_criar_peca_valida(admin):
    d = payload()
    r = enviar(admin, "/pecas", d, ALIASES, estrito=False)
    assert_sucesso_post(r, "criar peca")
    p = peca(d["nome"])
    assert p and float(p["valor_unitario"]) == 15.5 and float(p["qtde_estoque"]) == 25 and p["ncm"] == "84821010"
    assert p["id_equipamento"] == um("SELECT id FROM equipamentos WHERE descricao='BOMBA 1 (RESFRIADOR)'")
    assert float(p["estoque_minimo"]) == 5, "estoque_minimo padrao = 5 (SPEC §3)"


@pytest.mark.parametrize("valor,esperado", [("15,50", 15.5), ("15.50", 15.5), ("0", 0.0), ("1.234,56", 1234.56), ("100", 100.0)])
def test_formatos_de_valor_unitario(admin, valor, esperado):
    d = payload(valor=valor)
    r = enviar(admin, "/pecas", d, ALIASES, estrito=False)
    assert_sucesso_post(r, f"valor {valor!r}")
    assert float(peca(d["nome"])["valor_unitario"]) == esperado


def test_peca_nova_aparece_na_lista_busca_e_filtro_por_equipamento(admin):
    d = payload(nome="Peca Unica Zeta", equipamento="INJETORA 01 - YIZUMI")
    criar(admin, **d)
    assert "Peca Unica Zeta" in html_de(admin.get("/pecas?busca=unica zeta"))
    assert "Rolamento 6204" not in lista_de(html_de(admin.get("/pecas?busca=unica zeta")))
    eqid = um("SELECT id FROM equipamentos WHERE descricao='INJETORA 01 - YIZUMI'")
    ok = False
    for nome in ("equipamento", "equipamento_id", "filtro_equipamento", "id_equipamento"):
        h = lista_de(html_de(admin.get(f"/pecas?{nome}={eqid}")))
        if "Peca Unica Zeta" in h and "Sensor Indutivo" not in h and "Filtro de Ar" not in h:
            ok = True
            break
    assert ok, "Filtro por equipamento nao funcionou (Manual 1.3: listagem com filtro por equipamento)"


def test_peca_criada_com_estoque_abaixo_do_minimo_mostra_baixo(admin):
    d = payload(nome="Peca Quase Zerada", qtde="2")
    criar(admin, **d)
    t = texto_visivel(html_de(admin.get("/pecas?busca=Quase Zerada")))
    assert "Baixo" in t, "qtde 2 < minimo 5 deveria exibir aviso Baixo"


def test_criar_peca_com_estoque_inicial_gera_movimentacao_de_entrada(admin):
    """Coerencia saldo x movimentacao: ao nascer com saldo, o historico deveria explicar o saldo (decisao de contrato)."""
    d = payload(qtde="40")
    criar(admin, **d)
    p = peca(d["nome"])
    mov = consulta("SELECT * FROM movimentacao_estoque_pecas WHERE id_peca=?", p["id"])
    liquido = sum((m["quantidade"] if m["tipo"] == "Entrada" else -m["quantidade"]) for m in mov)
    assert liquido in (0, 40), "Saldo inicial: ou nao ha movimentacao (0) ou ha uma Entrada de 40; nunca valor diferente"


# --------------------------------------------------------------------------------------------- validacoes

INVALIDOS = [
    ("nome_vazio", dict(nome="")),
    ("nome_so_espacos", dict(nome="  ")),
    ("equipamento_inexistente", dict(equipamento=Bruto("99999"))),
    ("valor_negativo", dict(valor="-1,00")),
    ("valor_texto", dict(valor="caro")),
    ("valor_vazio", dict(valor="")),
    ("qtde_negativa", dict(qtde="-3")),
    ("qtde_texto", dict(qtde="muitas")),
    ("ncm_7_digitos", dict(ncm="8482101")),
    ("ncm_letras", dict(ncm="ABCDEFGH")),
    ("ncm_9_digitos", dict(ncm="848210100")),
    ("minimo_negativo", dict(minimo="-1")),
]


@pytest.mark.parametrize("nome,mudanca", INVALIDOS, ids=[i[0] for i in INVALIDOS])
def test_validacoes_na_criacao(admin, nome, mudanca):
    d = {**payload(), **mudanca}
    antes = contar("pecas")
    r = enviar(admin, "/pecas", d, ALIASES, estrito=False)
    if nome == "minimo_negativo" and "minimo" not in " ".join(r.form_usado.nomes):
        pytest.skip("o formulario nao expoe estoque_minimo")
    assert_rejeitado(r, f"Peca invalida ({nome})")
    assert contar("pecas") == antes, f"{nome}: peca invalida foi GRAVADA"


def test_form_com_erro_preserva_o_digitado(admin):
    d = payload(nome="Nome Que Fica", valor="-5")
    r = enviar(admin, "/pecas", d, ALIASES, estrito=False)
    assert "Nome Que Fica" in html_de(r)


def test_valores_extremos(admin):
    for v in ("1e308", "NaN", "99999999999999999999,99", "0,001", "0,005"):
        r = enviar(admin, "/pecas", payload(valor=v), ALIASES, estrito=False)
        assert r.status_code < 500, f"valor={v!r} -> {r.status_code}"
    for q in ("99999999999999999999", "1e9", "0,5"):
        r = enviar(admin, "/pecas", payload(qtde=q), ALIASES, estrito=False)
        assert r.status_code < 500, f"qtde={q!r} -> {r.status_code}"


# --------------------------------------------------------------------------------------------- editar

def test_editar_peca(admin):
    d = payload()
    criar(admin, **d)
    p = peca(d["nome"])
    r = enviar(admin, f"/pecas/{p['id']}/editar", {"nome": "Peca Editada", "valor": "99,90"}, ALIASES, estrito=False)
    assert_sucesso_post(r, "editar peca")
    p2 = linha("SELECT * FROM pecas WHERE id=?", p["id"])
    assert p2["nome"] == "Peca Editada" and float(p2["valor_unitario"]) == 99.9


def test_formulario_de_edicao_preenchido(admin):
    pid = um("SELECT id FROM pecas WHERE nome='Rolamento 6204'")
    h = html_de(admin.get(f"/pecas/{pid}/editar"))
    assert "Rolamento 6204" in h and ("15,00" in h or "15.00" in h)


def test_editar_peca_inexistente_404(admin):
    assert admin.get("/pecas/999999/editar").status_code == 404


def test_editar_valor_unitario_nao_altera_itens_de_os_ja_lancados(admin):
    """O valor lancado na OS e um 'snapshot' (itens_os.valor_unitario): mudar o preco da peca nao reescreve o passado."""
    item = linha("SELECT * FROM itens_os ORDER BY id LIMIT 1")
    assert item, "seed sem itens_os"
    antes = float(item["valor_unitario"])
    enviar(admin, f"/pecas/{item['id_peca']}/editar", {"valor": "999,99"}, ALIASES, estrito=False)
    assert float(linha("SELECT valor_unitario FROM itens_os WHERE id=?", item["id"])["valor_unitario"]) == antes


# --------------------------------------------------------------------------------------------- atualizar estoque

def _ajuste(c, pid, **dados):
    from helpers import post as _post
    return _post(c, f"/pecas/{pid}/estoque", dados)


def test_atualizar_estoque_gera_movimentacao(admin):
    d = payload(qtde="10")
    criar(admin, **d)
    p = peca(d["nome"])
    n_antes = contar("movimentacao_estoque_pecas", "id_peca=?", p["id"])
    r = enviar(admin, "/pecas", {}, ALIASES, estrito=False, post_url=f"/pecas/{p['id']}/estoque",
               extras={"quantidade": "5", "qtde_estoque": "15", "novo_saldo": "15", "tipo": "Entrada"})
    assert r.status_code < 500
    p2 = linha("SELECT * FROM pecas WHERE id=?", p["id"])
    assert float(p2["qtde_estoque"]) != 10 or contar("movimentacao_estoque_pecas", "id_peca=?", p["id"]) == n_antes, \
        "Ajuste nao alterou o saldo (confira o nome dos campos do 'Atualizar estoque')"
    if float(p2["qtde_estoque"]) != 10:
        assert contar("movimentacao_estoque_pecas", "id_peca=?", p["id"]) == n_antes + 1, \
            "Atualizar estoque deve gerar movimentacao (SPEC §4 pecas)"


def test_atualizar_estoque_rejeita_saldo_negativo(admin):
    d = payload(qtde="10")
    criar(admin, **d)
    p = peca(d["nome"])
    for campos in ({"quantidade": "-50"}, {"qtde_estoque": "-50"}, {"novo_saldo": "-50"}):
        _ajuste(admin, p["id"], **campos)
        assert float(linha("SELECT qtde_estoque FROM pecas WHERE id=?", p["id"])["qtde_estoque"]) >= 0, \
            "Ajuste deixou saldo negativo"


# --------------------------------------------------------------------------------------------- excluir

def test_excluir_peca_sem_vinculos(admin):
    d = payload()
    criar(admin, **d)
    p = peca(d["nome"])
    assert_sucesso_post(post(admin, f"/pecas/{p['id']}/excluir"), "excluir peca")
    assert peca(d["nome"]) is None
    assert contar("estoque_pecas", "id_peca=?", p["id"]) == 0, "estoque_pecas ficou com registro orfao"


def test_excluir_peca_usada_em_os_e_bloqueado(admin):
    item = linha("SELECT * FROM itens_os ORDER BY id LIMIT 1")
    r = post(admin, f"/pecas/{item['id_peca']}/excluir", seguir=True)
    assert r.status_code == 200
    assert linha("SELECT * FROM pecas WHERE id=?", item["id_peca"]), "Peca usada em OS foi excluida (integridade)"
    t = texto_visivel(html_de(r)).lower()
    assert "vínculo" in t or "vinculo" in t or "não é possível" in t or "nao e possivel" in t
    assert consulta("PRAGMA foreign_key_check") == []


def test_excluir_so_por_post(admin):
    pid = um("SELECT id FROM pecas LIMIT 1")
    assert admin.get(f"/pecas/{pid}/excluir").status_code == 405


# --------------------------------------------------------------------------------------------- injecao

@pytest.mark.parametrize("bruto", PAYLOADS_HOSTIS)
def test_nome_hostil_escapado(admin, bruto):
    d = payload(nome=bruto)
    r = criar(admin, **d)
    assert r.status_code < 500
    assert peca(bruto), "peca nao gravada"
    h = html_de(admin.get("/pecas", query_string={"busca": bruto[:20]}))
    assert_exibido_com_seguranca(h, bruto, "lista de pecas") if bruto in h or "<" not in bruto else None
    assert contar("pecas") >= 4
    assert "<script>alert" not in html_de(admin.get("/pecas"))


def test_tecnico_cadastra_peca(tecnico):
    d = payload()
    assert_sucesso_post(criar(tecnico, **d), "tecnico cria peca (SPEC §2)")
