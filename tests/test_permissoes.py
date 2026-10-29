"""
Autorizacao: matriz perfil x rota da SPEC §2 (302 nao logado / 403 sem permissao / 200 com permissao).

Rastreabilidade: SPEC §2 (matriz de permissoes), Projeto §15e (casos de uso por ator), RNF Seguranca (restricao de acesso).
Convencoes: onde a SPEC e ambigua o conjunto aceito e uma tupla (ex.: (200, 403)) e o caso esta marcado "AMBIGUO"
no QA_PLANO.md. Escritas (POST) sao verificadas de forma estrita: negado => 403 e NADA muda no banco.
"""

import pytest

from helpers import (PERFIS, STATUS_REDIRECT, consulta, contar, e_redirect_login, html_de, linha, local, obter_csrf,
                     post, snapshot, texto_visivel, um)

A, G, T, C = "admin", "gestor", "tecnico", "comum"


def so(*perfis, negado=403, **excecoes):
    d = {p: (200 if p in perfis else negado) for p in PERFIS}
    d.update(excecoes)
    return d


# rota (com placeholders resolvidos por `ids`) -> {perfil: status aceito (int ou tupla)}
MATRIZ_GET = [
    ("/menu", so(A, G, T, C)),
    ("/dashboard", so(A, G, T, **{C: (200, 403)})),                      # AMBIGUO p/ Usuario Comum
    ("/api/dashboard", so(A, G, T, **{C: (200, 403)})),
    ("/dashboard/exportar.pdf", so(A, G)),
    ("/dashboard/exportar.xlsx", so(A, G)),
    ("/relatorios", so(A, G, T, C)),
    ("/relatorios?aba=os", so(A, G, T, C)),
    ("/relatorios?aba=estoque", so(A, G, T, **{C: (302, 403)})),
    ("/relatorios?aba=fornecedores", so(A, G, T, **{C: (302, 403)})),
    ("/relatorios?aba=financeiro", so(A, G, **{T: (302, 403), C: (302, 403)})),
    ("/api/relatorios/os", so(A, G, T, C)),
    ("/api/relatorios/estoque", so(A, G, T, **{C: (302, 403)})),
    ("/api/relatorios/financeiro", so(A, G, **{T: 403, C: 403})),
    ("/api/relatorios/fornecedores", so(A, G, T, **{C: 403})),
    ("/relatorios/os/exportar.pdf", so(A, G)),
    ("/relatorios/os/exportar.xlsx", so(A, G)),
    ("/relatorios/os/exportar.csv", so(A, G)),
    ("/relatorios/financeiro/exportar.xlsx", so(A, G)),
    ("/usuarios", so(A)),
    ("/usuarios/{usuario}/editar", so(A)),
    ("/equipamentos", so(A, G, T)),
    ("/equipamentos/{equipamento}/editar", so(A, T, **{G: (200, 403)})),   # AMBIGUO: Gestor "ver"
    ("/api/subgrupos?grupo_id=1", so(A, G, T, **{C: (200, 403)})),
    ("/pecas", so(A, G, T)),
    ("/pecas/{peca}/editar", so(A, T, **{G: (200, 403)})),
    ("/fornecedores", so(A, G, T)),
    ("/fornecedores/novo", so(A, **{G: (200, 403), T: (200, 403)})),       # AMBIGUO: so "ver"
    ("/fornecedores/{fornecedor}/editar", so(A, **{G: (200, 403), T: (200, 403)})),
    ("/prestadores", so(A, G, T)),
    ("/prestadores/novo", so(A, **{G: (200, 403), T: (200, 403)})),
    ("/prestadores/{prestador}/editar", so(A, **{G: (200, 403), T: (200, 403)})),
    ("/departamentos", so(A, G, T)),
    ("/departamentos/{departamento}/editar", so(A, **{G: (200, 403), T: (200, 403)})),
    ("/pedidos", so(A, G, T, C)),
    ("/pedidos/novo", so(A, G, T, C)),
    ("/pedidos/{pedido_ana}", so(A, G, T, C)),
    ("/pedidos/{pedido_ana}/editar", so(A, G, T, **{C: (200, 403)})),
    ("/os", so(A, G, T, C)),
    ("/os/nova", so(A, T, **{G: 403, C: 403})),
    ("/os/{os_ana}", so(A, G, T, C)),
    ("/os/{os_ana}/editar", so(A, T, **{G: (200, 403), C: 403})),
    ("/estoque", so(A, G, T)),
    ("/configuracoes", so(A, G, T, C)),
]


@pytest.fixture()
def ids(app):
    """IDs reais do seed para montar as rotas."""
    from helpers import um as _um
    return {
        "usuario": _um("SELECT id FROM usuarios WHERE login='plima'"),
        "equipamento": _um("SELECT id FROM equipamentos ORDER BY id LIMIT 1"),
        "peca": _um("SELECT id FROM pecas ORDER BY id LIMIT 1"),
        "fornecedor": _um("SELECT id FROM fornecedores ORDER BY id LIMIT 1"),
        "prestador": _um("SELECT id FROM prestadores_servico ORDER BY id LIMIT 1"),
        "departamento": _um("SELECT id FROM departamentos WHERE nome='Logística'"),
        "pedido_ana": 1623,       # solicitante Ana (Usuario Comum) -> "proprio" do perfil Comum
        "pedido_outro": 1625,     # solicitante Carlos Gestor
        "os_ana": 10234,          # OS do pedido #1623
        "os_outra": 10233,        # OS do pedido #1625 (Carlos)
        "movimento": _um("SELECT id FROM movimentacao_estoque_pecas ORDER BY id LIMIT 1"),
    }


def _url(tpl, ids):
    return tpl.format(**ids)


def _ok(status, aceito):
    return status in (aceito if isinstance(aceito, tuple) else (aceito,))


# ---------------------------------------------------------------------------------------------- nao logado

@pytest.mark.parametrize("rota", [r for r, _ in MATRIZ_GET], ids=[r for r, _ in MATRIZ_GET])
def test_anonimo_e_redirecionado_ao_login(anonimo, ids, rota):
    r = anonimo.get(_url(rota, ids))
    if r.status_code == 401 and rota.startswith("/api/"):
        return  # APIs podem responder 401; HTML deve redirecionar
    assert e_redirect_login(r), f"{rota}: nao logado deveria dar 302 -> /login?proximo=... (SPEC §2). Veio {r.status_code} {local(r)}"
    assert "proximo=" in local(r)


@pytest.mark.parametrize("rota", ["/login", "/recuperar-senha"])
def test_rotas_publicas(anonimo, rota):
    assert anonimo.get(rota).status_code == 200


def test_arquivos_estaticos_sao_publicos(anonimo):
    import pathlib
    css = next(pathlib.Path(__file__).resolve().parent.parent.joinpath("static").rglob("*.css"), None)
    assert css, "nenhum CSS em static/"
    assert anonimo.get("/static/" + "/".join(css.parts[css.parts.index("static") + 1:])).status_code == 200


# ---------------------------------------------------------------------------------------------- GET: matriz

CASOS_GET = [(rota, perfil, esperado) for rota, m in MATRIZ_GET for perfil, esperado in m.items()]


@pytest.mark.parametrize("rota,perfil,esperado", CASOS_GET,
                         ids=[f"{p}:{r}" for r, p, _ in CASOS_GET])
def test_matriz_get(cliente_de, ids, rota, perfil, esperado):
    c = cliente_de(perfil)
    r = c.get(_url(rota, ids))
    assert _ok(r.status_code, esperado), (
        f"{perfil} GET {rota}: esperado {esperado} (SPEC §2) mas veio {r.status_code} (Location={local(r)!r})"
    )
    if r.status_code == 403:
        assert "403" in texto_visivel(html_de(r)) or "permiss" in texto_visivel(html_de(r)).lower(), \
            "A pagina 403 deveria explicar a falta de permissao (403.html, SPEC §2)"


# ---------------------------------------------------------------------------------------------- Comum: so os proprios

def test_usuario_comum_nao_ve_pedido_de_outro_usuario(comum, ids):
    r = comum.get(f"/pedidos/{ids['pedido_outro']}")
    assert r.status_code in (403, 404), f"Usuario Comum so consulta os PROPRIOS pedidos (SPEC §2). Veio {r.status_code}"


def test_usuario_comum_nao_ve_os_de_pedido_alheio(comum, ids):
    r = comum.get(f"/os/{ids['os_outra']}")
    assert r.status_code in (403, 404), f"Usuario Comum so consulta status das PROPRIAS OS (SPEC §2). Veio {r.status_code}"


def test_lista_de_pedidos_do_comum_so_tem_os_proprios(comum):
    h = html_de(comum.get("/pedidos"))
    t = texto_visivel(h)
    assert "#1623" in t, "Pedido #1623 (Ana) deveria aparecer para Ana"
    assert "#1625" not in t, "Pedido #1625 (Carlos Gestor) nao deveria aparecer para o Usuario Comum"
    assert "Carlos Gestor" not in t


def test_lista_de_os_do_comum_so_tem_as_proprias(comum):
    t = texto_visivel(html_de(comum.get("/os")))
    assert "OS-10234" in t
    assert "OS-10233" not in t, "OS-10233 e do pedido #1625 (de outro usuario)"


def test_busca_nao_vaza_pedidos_alheios_para_o_comum(comum):
    t = texto_visivel(html_de(comum.get("/pedidos?busca=EMPILHADEIRA")))
    assert "#1625" not in t


def test_comum_nao_ve_aba_financeiro_do_relatorio(comum):
    r = comum.get("/relatorios?aba=financeiro")
    if r.status_code == 200:
        t = texto_visivel(html_de(r)).lower()
        assert "custo total" not in t and "financeiro" not in t, "Usuario Comum so tem 'relatorios de atendimento' (aba Ordens)"
    else:
        assert r.status_code in (302, 403)


def test_comum_so_ve_aba_ordens_nos_relatorios(comum):
    t = texto_visivel(html_de(comum.get("/relatorios")))
    for aba in ("Estoque", "Financeiro", "Fornecedores"):
        assert aba not in t, f"A aba {aba!r} nao deveria aparecer para o Usuario Comum (SPEC §2)"


def test_tecnico_nao_ve_valores_financeiros_no_dashboard(tecnico):
    h = html_de(tecnico.get("/dashboard"))
    t = texto_visivel(h)
    assert "Custo Total" not in t and "R$" not in t.replace("R$ 0", ""), \
        "Tecnico 've' dashboard sem financeiro (SPEC §2): nada de R$/Custo no HTML"


def test_tecnico_api_dashboard_sem_dados_financeiros(tecnico):
    r = tecnico.get("/api/dashboard")
    assert r.status_code == 200
    j = r.get_json()
    custo = j.get("custo_por_maquina")
    assert not custo, f"Tecnico nao deveria receber custo_por_maquina (financeiro): {custo!r}"
    kp = {str(k).lower(): v for k, v in (j.get("kpis") or {}).items()}
    assert not any("custo" in k and v not in (None, 0, "", []) for k, v in kp.items()), f"KPI financeiro vazou: {kp}"


# ---------------------------------------------------------------------------------------------- menu por perfil

ITENS_MENU = {
    "usuarios": "/usuarios", "equipamentos": "/equipamentos", "pecas": "/pecas", "fornecedores": "/fornecedores",
    "prestadores": "/prestadores", "departamentos": "/departamentos", "pedidos": "/pedidos", "os": "/os",
    "estoque": "/estoque", "relatorios": "/relatorios", "dashboard": "/dashboard",
}
VISIVEL = {  # item -> perfis que devem ver o link no menu lateral
    "usuarios": {A}, "equipamentos": {A, G, T}, "pecas": {A, G, T}, "fornecedores": {A, G, T},
    "prestadores": {A, G, T}, "departamentos": {A, G, T}, "pedidos": {A, G, T, C}, "os": {A, G, T, C},
    "estoque": {A, G, T}, "relatorios": {A, G, T, C},
}


@pytest.mark.parametrize("perfil", PERFIS)
def test_menu_lateral_mostra_so_o_que_o_perfil_pode_abrir(cliente_de, perfil):
    h = html_de(cliente_de(perfil).get("/menu"))
    for item, perfis in VISIVEL.items():
        href = ITENS_MENU[item]
        tem = (f'href="{href}"' in h) or (f"href='{href}'" in h)
        if perfil in perfis:
            assert tem, f"{perfil} deveria ver o item de menu {item} ({href}) (SPEC §2)"
        else:
            assert not tem, f"{perfil} NAO deveria ver o item de menu {item} ({href}): itens sem permissao nao aparecem (SPEC §2)"


@pytest.mark.parametrize("perfil", PERFIS)
def test_todo_link_do_menu_leva_a_pagina_permitida(cliente_de, perfil):
    """Coerencia menu x autorizacao: nenhum item visivel do menu pode resultar em 403/404/500."""
    import re
    c = cliente_de(perfil)
    h = html_de(c.get("/menu"))
    hrefs = set(re.findall(r'href="(/[a-z0-9\-_/]*)"', h)) - {"/logout", "/"}
    hrefs = {x for x in hrefs if not x.startswith("/static")}
    assert hrefs, "O menu nao tem nenhum link"
    for href in sorted(hrefs):
        r = c.get(href, follow_redirects=True)
        assert r.status_code == 200, f"{perfil}: link de menu {href} devolveu {r.status_code} (menu mostra item que o perfil nao abre)"


def test_cards_do_menu_principal_por_perfil(cliente_de):
    """Manual §5/SPEC §4: 6 cards no menu principal, filtrados por perfil."""
    cards_admin = texto_visivel(html_de(cliente_de(A).get("/menu")))
    for nome in ("Cadastros", "Ordens de Serviço", "Estoque", "Pedidos de Manutenção", "Relatórios", "Dashboard"):
        assert nome in cards_admin, f"Card {nome!r} ausente do menu principal do Administrador"
    comum = texto_visivel(html_de(cliente_de(C).get("/menu")))
    h = html_de(cliente_de(C).get("/menu"))
    assert 'href="/estoque"' not in h and 'href="/usuarios"' not in h


# ---------------------------------------------------------------------------------------------- POST: matriz (estrita)

# (metodo-url, perfis permitidos, destrutivo?)  destrutivo => perfil permitido e testado com id inexistente
MATRIZ_POST = [
    ("/usuarios", {A}, False),
    ("/usuarios/{usuario}/editar", {A}, False),
    ("/usuarios/{usuario}/excluir", {A}, True),
    ("/equipamentos", {A, T}, False),
    ("/equipamentos/{equipamento}/editar", {A, T}, False),
    ("/equipamentos/{equipamento}/excluir", {A, T}, True),
    ("/pecas", {A, T}, False),
    ("/pecas/{peca}/editar", {A, T}, False),
    ("/pecas/{peca}/excluir", {A, T}, True),
    ("/pecas/{peca}/estoque", {A, T}, False),
    ("/fornecedores/novo", {A}, False),
    ("/fornecedores/{fornecedor}/editar", {A}, False),
    ("/fornecedores/{fornecedor}/excluir", {A}, True),
    ("/prestadores/novo", {A}, False),
    ("/prestadores/{prestador}/editar", {A}, False),
    ("/prestadores/{prestador}/excluir", {A}, True),
    ("/departamentos", {A}, False),
    ("/departamentos/{departamento}/editar", {A}, False),
    ("/departamentos/{departamento}/excluir", {A}, True),
    ("/pedidos/novo", {A, G, T, C}, False),
    ("/pedidos/{pedido_ana}/aprovar", {A, G}, True),
    ("/pedidos/{pedido_ana}/abrir-os", {A, T}, True),
    ("/os/nova", {A, T}, False),
    ("/os/{os_ana}/pecas", {A, T}, False),
    ("/os/{os_ana}/servicos", {A, T}, False),
    ("/os/{os_ana}/apontamentos", {A, T}, False),
    ("/os/{os_ana}/fechar", {A, G, T}, True),
    ("/os/{os_ana}/excluir", {A, T}, True),
    ("/estoque", {A, T}, False),
    ("/estoque/{movimento}/excluir", {A, T}, True),
]

CASOS_POST = [(rota, p, p in permitidos, destr) for rota, permitidos, destr in MATRIZ_POST for p in PERFIS]


def _com_id_inexistente(rota):
    import re
    return re.sub(r"\{(\w+)\}", "999999", rota)


@pytest.mark.parametrize("rota,perfil,permitido,destrutivo", CASOS_POST,
                         ids=[f"{p}:{'ok' if ok else 'nega'}:{r}" for r, p, ok, _ in CASOS_POST])
def test_matriz_post(cliente_de, ids, app, rota, perfil, permitido, destrutivo):
    c = cliente_de(perfil)
    tabs = [t for t in ("usuarios", "equipamentos", "pecas", "fornecedores", "prestadores_servico", "departamentos",
                        "pedidos_manutencao", "ordens_servico", "itens_os", "servicos_os", "apontamentos_os",
                        "movimentacao_estoque_pecas") ]
    antes = snapshot(tabs)
    if permitido:
        url = _com_id_inexistente(rota) if destrutivo else _url(rota, ids)
        r = post(c, url, {})        # dados vazios: nada deve ser gravado
        assert r.status_code != 403, f"{perfil} POST {rota}: perfil permitido recebeu 403 (SPEC §2)"
        assert r.status_code < 500, f"{perfil} POST {rota}: erro {r.status_code} com dados vazios (deveria validar)"
    else:
        r = post(c, _url(rota, ids), {})
        assert r.status_code == 403, f"{perfil} POST {rota}: sem permissao => 403 (SPEC §2). Veio {r.status_code} ({local(r)})"
        depois = snapshot(tabs)
        assert antes == depois, f"{perfil} POST negado mudou o banco: {[(t, antes[t], depois[t]) for t in antes if antes[t] != depois[t]]}"


@pytest.mark.parametrize("rota", [r for r, _, _ in MATRIZ_POST], ids=[r for r, _, _ in MATRIZ_POST])
def test_post_anonimo_redireciona_ao_login(anonimo, ids, rota):
    anonimo.get("/login")  # abre sessao e token csrf
    tok = obter_csrf(anonimo)
    r = post(anonimo, _url(rota, ids), {}, csrf=tok)
    assert e_redirect_login(r) or r.status_code in (401,), \
        f"POST {rota} sem login deveria redirecionar ao login (302), veio {r.status_code} {local(r)}"


# ---------------------------------------------------------------------------------------------- escrita real negada

def test_gestor_nao_consegue_criar_equipamento_via_post_forjado(gestor):
    antes = contar("equipamentos")
    r = post(gestor, "/equipamentos", {"codigo": "99.999.9999", "descricao": "FORJADO", "id_grupo": 1, "id_subgrupo": 1,
                                       "id_departamento": 1, "status": "Ativo"})
    assert r.status_code == 403
    assert contar("equipamentos") == antes


def test_tecnico_nao_consegue_excluir_usuario(tecnico, ids):
    r = post(tecnico, f"/usuarios/{ids['usuario']}/excluir", {})
    assert r.status_code == 403
    assert contar("usuarios", "login='plima'") == 1


def test_comum_nao_consegue_aprovar_pedido_proprio(comum):
    r = post(comum, "/pedidos/1623/aprovar", {})
    assert r.status_code == 403
    assert linha("SELECT aprovado_por FROM pedidos_manutencao WHERE id=1623")["aprovado_por"] in (None, "", 0)


def test_gestor_nao_abre_os_mas_pode_fechar(gestor):
    r = post(gestor, "/pedidos/1624/abrir-os", {})
    assert r.status_code == 403
    assert contar("ordens_servico", "id_pedido=1624") == 0


def test_perfil_do_usuario_nao_e_alteravel_pelo_proprio_usuario(app, tecnico):
    """Escalada de privilegio: Tecnico tenta virar Administrador pelo form de configuracoes."""
    from helpers import id_perfil
    tid = um("SELECT id FROM usuarios WHERE login='tecnico'")
    antes = um("SELECT id_perfil FROM usuarios_perfis WHERE id_usuario=?", tid)
    post(tecnico, "/configuracoes", {"perfil": id_perfil("Administrador"), "id_perfil": id_perfil("Administrador"),
                                     "nome": "Maria Técnica", "email": "tecnico@techmaint.com"})
    assert um("SELECT id_perfil FROM usuarios_perfis WHERE id_usuario=?", tid) == antes, "Escalada de privilegio via /configuracoes!"
    assert tecnico.get("/usuarios").status_code == 403


def test_usuario_comum_ve_so_o_status_das_proprias_os_sem_pecas_servicos_e_valores(cliente_de):
    """SPEC §2: Usuario Comum 'consulta status das proprias' OS. Nada de pecas, servicos ou R$ no detalhe (FE-002)."""
    comum = cliente_de(C)
    alvo = consulta("SELECT o.id FROM ordens_servico o JOIN pedidos_manutencao p ON p.id=o.id_pedido "
                    "WHERE p.solicitante='Ana Solicitante' AND (EXISTS (SELECT 1 FROM itens_os i WHERE i.id_os=o.id) "
                    "OR EXISTS (SELECT 1 FROM servicos_os s WHERE s.id_os=o.id)) LIMIT 5")
    assert alvo, "Seed deveria ter OS da Ana com pecas/servicos para este teste"
    for o in alvo:
        h = html_de(comum.get(f"/os/{o['id']}"))
        t = texto_visivel(h)
        assert "R$" not in t, f"OS {o['id']}: usuario comum viu valores monetarios"
        for p in consulta("SELECT p.nome FROM itens_os i JOIN pecas p ON p.id=i.id_peca WHERE i.id_os=?", o["id"]):
            assert p["nome"] not in h, f"OS {o['id']}: usuario comum viu a peca {p['nome']!r} (so status e permitido)"
        for s in consulta("SELECT descricao_servico FROM servicos_os WHERE id_os=?", o["id"]):
            assert s["descricao_servico"] not in h, f"OS {o['id']}: usuario comum viu servico {s['descricao_servico']!r}"
        assert "Adicionar" not in t and "Fechar OS" not in t, "Usuario comum nao pode ter botoes de acao na OS"


def test_usuario_comum_nao_ve_os_de_outro_solicitante(cliente_de):
    comum = cliente_de(C)
    alheia = um("SELECT o.id FROM ordens_servico o JOIN pedidos_manutencao p ON p.id=o.id_pedido WHERE p.solicitante<>'Ana Solicitante' LIMIT 1")
    assert comum.get(f"/os/{alheia}").status_code in (403, 404), "IDOR: usuario comum abriu OS de outra pessoa"
    avulsa = um("SELECT id FROM ordens_servico WHERE id_pedido IS NULL LIMIT 1")
    if avulsa:
        assert comum.get(f"/os/{avulsa}").status_code in (403, 404)
