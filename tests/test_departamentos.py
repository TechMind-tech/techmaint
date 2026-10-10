"""
CRUD de Departamentos (Manual §1.5, Figma 15, SPEC §3, §4 /departamentos).

Rastreabilidade: RF Cadastro de Departamentos (Projeto §15b), Manual 1.5 (Nome do departamento, Responsavel;
Salvar/Editar/Excluir; listagem), apoio §4 (Responsavel = lista de usuarios cadastrados), SPEC §3 (nome UNIQUE; vinculos).
"""

import pytest

from helpers import (Bruto, PAYLOADS_HOSTIS, assert_exibido_com_seguranca, assert_rejeitado, assert_sucesso_post,
                     contar, enviar, formularios, html_de, linha, post, texto_visivel, unico, um)

ALIASES = {"nome": ["nome", "nome_departamento"], "responsavel": ["responsavel_id", "responsavel"]}


def payload(**kw):
    n = unico("D")
    base = dict(nome=f"Depto QA {n}", responsavel="João Administrador")
    base.update(kw)
    return base


def criar(c, **kw):
    return enviar(c, "/departamentos", payload(**kw), ALIASES, estrito=False)


def depto(nome):
    return linha("SELECT * FROM departamentos WHERE nome=?", nome)


def test_tela_de_departamentos(admin):
    t = texto_visivel(html_de(admin.get("/departamentos")))
    for trecho in ("Cadastro de Departamentos", "Novo Departamento", "Departamentos Cadastrados", "Produção",
                   "Roberto Alves", "Manutenção", "Logística", "Utilidades", "Administração", "Editar", "Excluir"):
        assert trecho.lower() in t.lower(), f"Figma 15: {trecho!r} ausente"


def test_responsavel_e_lista_de_usuarios_cadastrados(admin):
    forms = [f for f in formularios(html_de(admin.get("/departamentos"))) if f.method == "post" and "csrf_token" in f.nomes]
    f = max(forms, key=lambda x: len(x.campos))
    c = next(c for c in f.campos if c.nome and "responsavel" in c.nome)
    assert c.tag == "select", "Responsavel deve ser lista de usuarios (apoio §4; SPEC §3)"
    rotulos = " | ".join(o["rotulo"] for o in c.opcoes)
    for nome in ("João Administrador", "Maria Técnica", "Carlos Gestor"):
        assert nome in rotulos


def test_criar_departamento(admin):
    d = payload()
    assert_sucesso_post(enviar(admin, "/departamentos", d, ALIASES, estrito=False), "criar departamento")
    r = depto(d["nome"])
    assert r
    assert r["responsavel_id"] == um("SELECT id FROM usuarios WHERE login='admin'") or "João" in (r["responsavel_nome"] or "")


def test_departamento_novo_na_lista_e_nos_selects_de_outras_telas(admin):
    d = payload()
    criar(admin, **d)
    assert d["nome"] in html_de(admin.get("/departamentos"))
    assert d["nome"] in html_de(admin.get("/equipamentos")), "Departamento novo deve aparecer no select de Equipamentos"
    assert d["nome"] in html_de(admin.get("/pedidos/novo")), "... e no de Pedido de Manutencao"


@pytest.mark.parametrize("nome,mudanca", [
    ("nome_vazio", dict(nome="")),
    ("nome_so_espacos", dict(nome="   ")),
    ("nome_duplicado", dict(nome="Produção")),
    ("nome_duplicado_com_espacos", dict(nome=" Produção ")),
    ("responsavel_inexistente", dict(responsavel=Bruto("99999"))),
    ("nome_gigante", dict(nome="D" * 101)),
])
def test_validacoes(admin, nome, mudanca):
    antes = contar("departamentos")
    r = enviar(admin, "/departamentos", {**payload(), **mudanca}, ALIASES, estrito=False)
    assert_rejeitado(r, f"departamento invalido ({nome})")
    assert contar("departamentos") == antes


def test_editar_departamento(admin):
    d = payload()
    criar(admin, **d)
    r0 = depto(d["nome"])
    r = enviar(admin, f"/departamentos/{r0['id']}/editar", {"nome": "Nome Novo QA", "responsavel": "Carlos Gestor"}, ALIASES, estrito=False)
    assert_sucesso_post(r, "editar departamento")
    r1 = linha("SELECT * FROM departamentos WHERE id=?", r0["id"])
    assert r1["nome"] == "Nome Novo QA"


def test_editar_para_nome_existente_rejeitado(admin):
    d = payload()
    criar(admin, **d)
    r0 = depto(d["nome"])
    r = enviar(admin, f"/departamentos/{r0['id']}/editar", {"nome": "Logística"}, ALIASES, estrito=False)
    assert_rejeitado(r, "duplicar nome na edicao")


def test_formulario_de_edicao_preenchido(admin):
    did = um("SELECT id FROM departamentos WHERE nome='Logística'")
    h = html_de(admin.get(f"/departamentos/{did}/editar"))
    assert "Logística" in h


def test_excluir_departamento_sem_vinculos(admin):
    d = payload()
    criar(admin, **d)
    r0 = depto(d["nome"])
    assert_sucesso_post(post(admin, f"/departamentos/{r0['id']}/excluir"), "excluir")
    assert depto(d["nome"]) is None


@pytest.mark.parametrize("nome", ["Produção", "Utilidades", "Logística"])
def test_excluir_departamento_com_equipamentos_ou_pedidos_e_bloqueado(admin, nome):
    did = um("SELECT id FROM departamentos WHERE nome=?", nome)
    r = post(admin, f"/departamentos/{did}/excluir", seguir=True)
    assert r.status_code == 200, f"HTTP {r.status_code}: excluir com vinculos deve avisar, nao dar erro"
    assert depto(nome), f"Departamento {nome} (com equipamentos/pedidos) foi excluido"
    t = texto_visivel(html_de(r)).lower()
    assert "vínculo" in t or "vinculo" in t or "não é possível" in t or "nao e possivel" in t


def test_excluir_so_por_post(admin):
    did = um("SELECT id FROM departamentos LIMIT 1")
    assert admin.get(f"/departamentos/{did}/excluir").status_code == 405


def test_inexistente(admin):
    assert admin.get("/departamentos/999999/editar").status_code == 404
    assert post(admin, "/departamentos/999999/excluir").status_code in (404, 302, 303)


@pytest.mark.parametrize("bruto", PAYLOADS_HOSTIS)
def test_nome_hostil(admin, bruto):
    r = criar(admin, nome=bruto)
    assert r.status_code < 500
    if depto(bruto):
        assert_exibido_com_seguranca(html_de(admin.get("/departamentos")), bruto, "lista de departamentos")


@pytest.mark.parametrize("perfil", ["gestor", "tecnico"])
def test_somente_leitura_para_gestor_e_tecnico(cliente_de, perfil):
    c = cliente_de(perfil)
    r = c.get("/departamentos")
    assert r.status_code == 200
    h = html_de(r)
    assert "Novo Departamento" not in texto_visivel(h), f"{perfil} so pode ver (SPEC §2): o formulario de cadastro nao deveria aparecer"
    assert "/excluir" not in h, f"{perfil}: botoes de excluir nao deveriam aparecer"
    assert "Produção" in h


def test_auditoria(admin):
    from helpers import consulta
    d = payload()
    criar(admin, **d)
    r0 = depto(d["nome"])
    post(admin, f"/departamentos/{r0['id']}/excluir")
    assert contar("historico_alteracoes", "lower(entidade) LIKE 'depart%' AND id_entidade=?", r0["id"]) >= 2
