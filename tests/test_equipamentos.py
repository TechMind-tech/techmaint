"""
CRUD de Equipamentos + API de subgrupos (Manual §1.2, Figma 09-10, SPEC §3 regras 6-7, §4).

Rastreabilidade: RF "Cadastro de Entidades: Maquinas" (Projeto §15b), Manual 1.2 (Codigo, Descricao, Grupo, Subgrupo,
Departamento, Vida util, Valor residual; Novo/Salvar/Editar/Excluir/Pesquisar; listagem com status ativo/manutencao),
SPEC §3.6 (NCM 8 digitos, codigo unico, valores >= 0), §3.7 (Subgrupo depende do Grupo), apoio §2-§4.
"""

import pytest

from dados_apoio import SUBGRUPOS_POR_GRUPO
from helpers import (Bruto, PAYLOADS_HOSTIS, assert_exibido_com_seguranca, assert_rejeitado, assert_sucesso_post,
                     consulta, contar, enviar, formularios, html_de, linha, post, texto_visivel, unico, um)

ALIASES = {
    "codigo": ["codigo"], "descricao": ["descricao"], "grupo": ["id_grupo", "grupo", "grupo_id"],
    "subgrupo": ["id_subgrupo", "subgrupo", "subgrupo_id"], "departamento": ["id_departamento", "departamento", "depto"],
    "status": ["status"], "vida_util": ["vida_util_meses", "vida_util"], "valor_residual": ["valor_residual_padrao", "valor_residual"],
    "ncm": ["ncm"], "depreciacao": ["controla_depreciacao", "depreciacao"], "patrimoniado": ["patrimoniado"],
}


def payload(**kw):
    n = unico("EQ")
    base = dict(codigo=f"QA.{n}", descricao=f"EQUIPAMENTO DE TESTE {n}", grupo="Produção", subgrupo="Injetoras",
                departamento="Produção", status="Ativo", ncm="84771000", vida_util="120", valor_residual="1500,50")
    base.update(kw)
    return base


def criar(c, **kw):
    return enviar(c, "/equipamentos", payload(**kw), ALIASES, estrito=False)


def eq(codigo):
    return linha("SELECT * FROM equipamentos WHERE codigo=?", codigo)


# --------------------------------------------------------------------------------------------- tela

def test_tela_de_equipamentos(admin):
    r = admin.get("/equipamentos")
    assert r.status_code == 200
    t = texto_visivel(html_de(r))
    for trecho in ("Cadastro de Equipamentos", "Novo Equipamento", "Equipamentos Cadastrados", "equipamentos cadastrados"):
        assert trecho.lower() in t.lower(), f"Figma 09/10: texto {trecho!r} ausente"
    assert "07.000.0066" in html_de(admin.get("/equipamentos?busca=BOMBA 1"))


def test_formulario_tem_os_campos_do_manual_e_status_em_radios(admin):
    forms = [f for f in formularios(html_de(admin.get("/equipamentos"))) if f.method == "post" and "csrf_token" in f.nomes]
    f = max(forms, key=lambda x: len(x.campos))
    nomes = " ".join(f.nomes).lower()
    for campo in ("codigo", "descricao", "grupo", "subgrupo", "departamento", "status", "vida_util", "valor_residual", "ncm"):
        assert campo in nomes, f"Campo {campo!r} ausente do form de equipamento (Manual 1.2). Campos: {f.nomes}"
    status = next(c for c in f.campos if c.nome == "status")
    assert status.tipo == "radio", "Status deve ser grupo de radios (Figma 09: bolinhas coloridas)"
    assert [o["rotulo"] for o in status.opcoes][:3] == ["Ativo", "Em manutenção", "Baixado"]
    assert next(o for o in status.opcoes if o["selecionado"])["rotulo"] == "Ativo", "Status padrao: Ativo"
    grupo = next(c for c in f.campos if c.nome and "grupo" in c.nome and "sub" not in c.nome)
    assert len(grupo.opcoes) >= 15


def test_lista_mostra_todos_os_equipamentos_do_seed_ou_pagina(admin):
    n = contar("equipamentos")
    t = texto_visivel(html_de(admin.get("/equipamentos")))
    assert str(n) in t, f"O contador 'N equipamentos cadastrados' deveria mostrar {n} (total do banco)"


# --------------------------------------------------------------------------------------------- criar / listar / buscar

def test_criar_equipamento_valido(admin):
    d = payload()
    r = enviar(admin, "/equipamentos", d, ALIASES, estrito=False)
    assert_sucesso_post(r, "criar equipamento")
    e = eq(d["codigo"])
    assert e, "Equipamento nao gravado"
    assert e["descricao"] == d["descricao"] and e["ncm"] == "84771000" and e["status"] == "Ativo"
    assert e["id_grupo"] == um("SELECT id FROM grupos WHERE nome='Produção'")
    assert e["id_subgrupo"] == um("SELECT id FROM subgrupos WHERE nome='Injetoras'")
    assert e["vida_util_meses"] == 120 and float(e["valor_residual_padrao"]) == 1500.50


def test_criar_com_checkboxes_depreciacao_e_patrimoniado(admin):
    d = payload(depreciacao=True, patrimoniado=True)
    criar(admin, **d)
    e = eq(d["codigo"])
    assert e["controla_depreciacao"] in (1, True) and e["patrimoniado"] in (1, True)
    d2 = payload(depreciacao=False, patrimoniado=False)
    criar(admin, **d2)
    e2 = eq(d2["codigo"])
    assert e2["controla_depreciacao"] in (0, None, False) and e2["patrimoniado"] in (0, None, False)


def test_equipamento_novo_aparece_na_lista_e_na_busca_por_codigo_e_descricao(admin):
    d = payload(descricao="TORNO CNC ZETA UNICO")
    criar(admin, **d)
    h = html_de(admin.get("/equipamentos?busca=" + d["codigo"]))
    assert d["codigo"] in h and "TORNO CNC ZETA UNICO" in h
    h2 = html_de(admin.get("/equipamentos?busca=cnc zeta"))
    assert d["codigo"] in h2
    assert "07.000.0066" not in h2


def test_busca_sem_resultado_mostra_estado_vazio(admin):
    t = texto_visivel(html_de(admin.get("/equipamentos?busca=zzzz_nao_existe_999")))
    assert "nenhum" in t.lower(), "Estado vazio amigavel esperado (SPEC §5: 'Nenhum ... encontrado')"


def _filtra(c, base, variantes, presente, ausente):
    tent = []
    for nome, val in variantes:
        h = html_de(c.get(f"{base}?{nome}={val}"))
        tent.append(f"{nome}={val}")
        if presente in h and ausente not in h:
            return True, tent
    return False, tent


def test_filtro_por_grupo(admin):
    gid = um("SELECT id FROM grupos WHERE nome='TI'")
    ok, tent = _filtra(admin, "/equipamentos", [(n, v) for n in ("grupo", "filtro_grupo", "grupo_id", "id_grupo") for v in (gid, "TI")],
                       "NOTEBOOK DELL 1", "BOMBA 1 (RESFRIADOR)")
    assert ok, f"Filtro por grupo nao funcionou (tentei {tent}); SPEC §4: filtro_grupo"


def test_filtro_por_status(admin):
    from helpers import executa
    executa("UPDATE equipamentos SET status='Baixado' WHERE descricao='NOTEBOOK DELL 2'")
    ok, tent = _filtra(admin, "/equipamentos", [("status", "Baixado"), ("filtro_status", "Baixado")], "NOTEBOOK DELL 2", "NOTEBOOK DELL 1")
    assert ok, f"Filtro por status nao funcionou (tentei {tent})"


def test_filtros_combinados_grupo_e_busca(admin):
    gid = um("SELECT id FROM grupos WHERE nome='Produção'")
    for nome in ("grupo", "filtro_grupo", "grupo_id"):
        h = html_de(admin.get(f"/equipamentos?{nome}={gid}&busca=INJETORA"))
        if "INJETORA 01" in h and "NOTEBOOK" not in h:
            return
    pytest.fail("Filtro de grupo + busca combinados nao funcionou")


# --------------------------------------------------------------------------------------------- validacoes

INVALIDOS = [
    ("codigo_vazio", dict(codigo="")),
    ("codigo_duplicado", dict(codigo="07.000.0066")),
    ("descricao_vazia", dict(descricao="")),
    ("descricao_so_espacos", dict(descricao="   ")),
    ("grupo_inexistente", dict(grupo=Bruto("99999"))),
    ("subgrupo_inexistente", dict(subgrupo=Bruto("99999"))),
    ("subgrupo_de_outro_grupo", dict(grupo="Produção", subgrupo="Bombas")),       # Bombas pertence a Infraestrutura
    ("departamento_inexistente", dict(departamento=Bruto("99999"))),
    ("status_invalido", dict(status=Bruto("Quebrado"))),
    ("ncm_7_digitos", dict(ncm="8477100")),
    ("ncm_9_digitos", dict(ncm="847710000")),
    ("ncm_com_letras", dict(ncm="ABCD1234")),
    ("vida_util_negativa", dict(vida_util="-5")),
    ("vida_util_texto", dict(vida_util="abc")),
    ("valor_residual_negativo", dict(valor_residual="-10,00")),
    ("valor_residual_texto", dict(valor_residual="muito")),
]


@pytest.mark.parametrize("nome,mudanca", INVALIDOS, ids=[i[0] for i in INVALIDOS])
def test_validacoes_na_criacao(admin, nome, mudanca):
    d = {**payload(), **mudanca}
    antes = contar("equipamentos")
    r = enviar(admin, "/equipamentos", d, ALIASES, estrito=False)
    assert_rejeitado(r, f"Equipamento invalido ({nome})")
    assert contar("equipamentos") == antes, f"{nome}: equipamento invalido foi GRAVADO"


def test_codigo_duplicado_mostra_mensagem(admin):
    r = enviar(admin, "/equipamentos", payload(codigo="07.000.0066"), ALIASES, estrito=False)
    t = texto_visivel(html_de(r)).lower()
    assert "já" in t or "existe" in t or "duplic" in t or "único" in t or "unico" in t, "Mensagem de codigo duplicado esperada"


def test_codigo_duplicado_ignora_espacos_nas_pontas(admin):
    antes = contar("equipamentos")
    r = enviar(admin, "/equipamentos", payload(codigo=" 07.000.0066 "), ALIASES, estrito=False)
    assert_rejeitado(r, "codigo duplicado com espacos")
    assert contar("equipamentos") == antes


def test_form_com_erro_preserva_valores_digitados(admin):
    d = payload(descricao="DESCRICAO QUE NAO PODE SUMIR", ncm="123")
    r = enviar(admin, "/equipamentos", d, ALIASES, estrito=False)
    assert "DESCRICAO QUE NAO PODE SUMIR" in html_de(r) and d["codigo"] in html_de(r)


@pytest.mark.parametrize("ncm", ["84771000", "00000000"])
def test_ncm_8_digitos_valido(admin, ncm):
    assert_sucesso_post(criar(admin, ncm=ncm), f"ncm {ncm}")


def test_ncm_vazio_e_permitido_ou_rejeitado_sem_500(admin):
    r = criar(admin, ncm="")
    assert r.status_code < 500   # Projeto: NCM nao e NOT NULL


def test_valor_residual_com_ponto_decimal(admin):
    d = payload(valor_residual="2000.75")
    assert_sucesso_post(enviar(admin, "/equipamentos", d, ALIASES, estrito=False), "valor com ponto")
    assert float(eq(d["codigo"])["valor_residual_padrao"]) == 2000.75


def test_valor_residual_zero_e_aceito(admin):
    d = payload(valor_residual="0")
    assert_sucesso_post(enviar(admin, "/equipamentos", d, ALIASES, estrito=False), "valor 0")


def test_valores_extremos_nao_quebram(admin):
    for v in ("99999999999999999999", "1e308", "NaN", "Infinity", "-0"):
        r = enviar(admin, "/equipamentos", payload(valor_residual=v), ALIASES, estrito=False)
        assert r.status_code < 500, f"valor_residual={v!r} -> HTTP {r.status_code}"
    for v in ("99999999999", "32768", "2147483648", "1e5"):
        r = enviar(admin, "/equipamentos", payload(vida_util=v), ALIASES, estrito=False)
        assert r.status_code < 500, f"vida_util={v!r} -> HTTP {r.status_code}"


# --------------------------------------------------------------------------------------------- editar

def test_editar_equipamento(admin):
    d = payload()
    criar(admin, **d)
    e = eq(d["codigo"])
    r = enviar(admin, f"/equipamentos/{e['id']}/editar",
               {"descricao": "DESCRICAO EDITADA", "status": "Em manutenção", "ncm": "12345678"}, ALIASES, estrito=False)
    assert_sucesso_post(r, "editar")
    e2 = eq(d["codigo"])
    assert e2["descricao"] == "DESCRICAO EDITADA" and e2["status"] == "Em manutenção" and e2["ncm"] == "12345678"


def test_formulario_de_edicao_preenchido_com_o_item(admin):
    e = linha("SELECT * FROM equipamentos WHERE codigo='07.000.0066'")
    h = html_de(admin.get(f"/equipamentos/{e['id']}/editar"))
    assert "07.000.0066" in h and "BOMBA 1 (RESFRIADOR)" in h


def test_editar_para_codigo_de_outro_equipamento_e_rejeitado(admin):
    d = payload()
    criar(admin, **d)
    e = eq(d["codigo"])
    r = enviar(admin, f"/equipamentos/{e['id']}/editar", {"codigo": "07.000.0067"}, ALIASES, estrito=False)
    assert_rejeitado(r, "codigo duplicado na edicao")
    assert eq(d["codigo"])


def test_editar_mantendo_o_mesmo_codigo_funciona(admin):
    d = payload()
    criar(admin, **d)
    e = eq(d["codigo"])
    r = enviar(admin, f"/equipamentos/{e['id']}/editar", {"descricao": "NOVA"}, ALIASES, estrito=False)
    assert_sucesso_post(r, "editar mantendo codigo")


def test_editar_grupo_exige_subgrupo_compativel(admin):
    d = payload()
    criar(admin, **d)
    e = eq(d["codigo"])
    r = enviar(admin, f"/equipamentos/{e['id']}/editar", {"grupo": "TI", "subgrupo": Bruto(str(um("SELECT id FROM subgrupos WHERE nome='Injetoras'")))},
               ALIASES, estrito=False)
    assert_rejeitado(r, "subgrupo de outro grupo na edicao")


def test_equipamento_inexistente_404(admin):
    assert admin.get("/equipamentos/999999/editar").status_code == 404
    assert post(admin, "/equipamentos/999999/editar", {"codigo": "x"}).status_code == 404


def test_tecnico_tambem_pode_cadastrar(tecnico):
    d = payload()
    assert_sucesso_post(criar(tecnico, **d), "tecnico cria equipamento (SPEC §2: CRUD)")
    assert eq(d["codigo"])


# --------------------------------------------------------------------------------------------- excluir

def test_excluir_equipamento_sem_vinculos(admin):
    d = payload()
    criar(admin, **d)
    e = eq(d["codigo"])
    assert_sucesso_post(post(admin, f"/equipamentos/{e['id']}/excluir"), "excluir")
    assert eq(d["codigo"]) is None


def test_excluir_equipamento_com_pedidos_e_bloqueado_com_mensagem(admin):
    e = linha("SELECT * FROM equipamentos WHERE codigo='07.000.0066'")  # BOMBA 1: pedido #1623 + pecas
    r = post(admin, f"/equipamentos/{e['id']}/excluir", seguir=True)
    assert r.status_code == 200, f"Excluir com vinculo deve voltar a lista com aviso (HTTP {r.status_code}), nunca 500"
    assert eq("07.000.0066"), "Equipamento com pedidos/pecas foi excluido (SPEC §3: mensagem amigavel, nao apagar)"
    t = texto_visivel(html_de(r)).lower()
    assert "vínculo" in t or "vinculo" in t or "não é possível" in t or "nao e possivel" in t, f"Mensagem amigavel esperada: {t[:300]!r}"
    assert consulta("PRAGMA foreign_key_check") == []


def test_excluir_equipamento_com_peca_vinculada_e_bloqueado(admin):
    d = payload()
    criar(admin, **d)
    e = eq(d["codigo"])
    from helpers import executa
    executa("INSERT INTO pecas (id_equipamento, nome, ncm, valor_unitario, qtde_estoque, estoque_minimo) VALUES (?, 'Peca QA', '12345678', 1, 10, 5)", e["id"])
    r = post(admin, f"/equipamentos/{e['id']}/excluir")
    assert r.status_code < 500
    assert eq(d["codigo"]), "Excluiu equipamento que tem peca vinculada"
    assert contar("pecas", "nome='Peca QA'") == 1


def test_excluir_so_aceita_post(admin):
    e = eq("07.000.0066")
    assert admin.get(f"/equipamentos/{e['id']}/excluir").status_code == 405


def test_excluir_inexistente(admin):
    assert post(admin, "/equipamentos/999999/excluir").status_code in (404, 302, 303)


def test_auditoria_de_equipamento(admin):
    d = payload()
    criar(admin, **d)
    e = eq(d["codigo"])
    enviar(admin, f"/equipamentos/{e['id']}/editar", {"descricao": "AUD"}, ALIASES, estrito=False)
    post(admin, f"/equipamentos/{e['id']}/excluir")
    n = contar("historico_alteracoes", "lower(entidade) LIKE 'equip%' AND id_entidade=?", e["id"])
    assert n >= 3, f"historico_alteracoes deveria registrar criar/editar/excluir de equipamento (achei {n})"


# --------------------------------------------------------------------------------------------- injecao

@pytest.mark.parametrize("bruto", PAYLOADS_HOSTIS)
def test_descricao_hostil_e_escapada(admin, bruto):
    d = payload(descricao=bruto)
    r = criar(admin, **d)
    assert r.status_code < 500
    e = eq(d["codigo"])
    assert e and e["descricao"] == bruto
    assert_exibido_com_seguranca(html_de(admin.get("/equipamentos?busca=" + d["codigo"])), bruto, "lista de equipamentos")
    assert contar("equipamentos") > 70


@pytest.mark.parametrize("busca", PAYLOADS_HOSTIS + ["%", "_", "\\", "%%%", "\x00", "a" * 3000])
def test_busca_com_caracteres_especiais_nao_quebra(admin, busca):
    r = admin.get("/equipamentos", query_string={"busca": busca})
    assert r.status_code < 500
    if "<" in busca:
        assert busca not in html_de(r), "Busca refletida sem escape (XSS refletido)"


def test_curinga_percent_na_busca_nao_retorna_tudo_como_se_fosse_curinga(admin):
    """'%' literal: aceitavel retornar tudo OU nada, desde que sem erro. Documenta o comportamento."""
    r = admin.get("/equipamentos", query_string={"busca": "%"})
    assert r.status_code == 200


# --------------------------------------------------------------------------------------------- API de subgrupos

def test_api_subgrupos_shape(admin):
    gid = um("SELECT id FROM grupos WHERE nome='Produção'")
    r = admin.get(f"/api/subgrupos?grupo_id={gid}")
    assert r.status_code == 200 and r.mimetype == "application/json"
    j = r.get_json()
    assert isinstance(j, list) and j, "esperada lista [{id, nome}]"
    assert all(set(x) >= {"id", "nome"} for x in j), f"cada item deve ter id e nome: {j[:2]}"
    assert all(isinstance(x["id"], int) and isinstance(x["nome"], str) for x in j)


@pytest.mark.parametrize("grupo,qtd", sorted(SUBGRUPOS_POR_GRUPO.items()))
def test_api_subgrupos_por_grupo(admin, grupo, qtd):
    gid = um("SELECT id FROM grupos WHERE nome=?", grupo)
    j = admin.get(f"/api/subgrupos?grupo_id={gid}").get_json()
    assert len(j) == qtd, f"Grupo {grupo}: {len(j)} subgrupos (apoio §2: {qtd})"
    ids = {x["id"] for x in j}
    assert ids == {r["id"] for r in consulta("SELECT id FROM subgrupos WHERE id_grupo=?", gid)}


@pytest.mark.parametrize("valor", ["99999", "0", "-1", "abc", "", "1 OR 1=1", "1;DROP TABLE grupos", "9" * 40])
def test_api_subgrupos_entrada_invalida(admin, valor):
    r = admin.get("/api/subgrupos", query_string={"grupo_id": valor})
    assert r.status_code in (200, 400), f"HTTP {r.status_code}"
    if r.status_code == 200:
        assert r.get_json() == [], f"grupo_id={valor!r} deveria devolver []"
    assert contar("grupos") == 15


def test_api_subgrupos_sem_parametro(admin):
    r = admin.get("/api/subgrupos")
    assert r.status_code in (200, 400)


def test_api_subgrupos_exige_login(anonimo):
    r = anonimo.get("/api/subgrupos?grupo_id=1")
    assert r.status_code in (302, 401)


def test_select_de_subgrupo_do_formulario_vem_do_grupo_inicial(admin):
    forms = [f for f in formularios(html_de(admin.get("/equipamentos"))) if f.method == "post" and "csrf_token" in f.nomes]
    f = max(forms, key=lambda x: len(x.campos))
    sub = next(c for c in f.campos if c.nome and "subgrupo" in c.nome)
    grupo = next(c for c in f.campos if c.nome and "grupo" in c.nome and "sub" not in c.nome)
    selecionado = next((o for o in grupo.opcoes if o["selecionado"]), grupo.opcoes[0])
    esperado = um("SELECT COUNT(*) FROM subgrupos WHERE id_grupo=?", int(selecionado["valor"])) if selecionado["valor"].isdigit() else None
    if esperado is not None:
        assert len(sub.opcoes) == esperado, f"Subgrupos iniciais ({len(sub.opcoes)}) devem ser do grupo selecionado ({esperado}) - SPEC §4"
