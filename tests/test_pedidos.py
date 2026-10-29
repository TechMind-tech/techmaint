"""
Pedidos de Manutencao (Manual §2.1, Figma 16, SPEC §3 regra 1 e 5, §4 /pedidos).

Rastreabilidade: RF "Processamento de Pedidos: criacao, aprovacao, execucao e encerramento" (Projeto §15b),
Manual 2.1 (Equipamento, Departamento solicitante, Data, Solicitante, Descricao, Prioridade; Abrir/Cancelar/Editar/Consultar
Pedido, Visualizar OS), apoio §4 (Prioridade Baixa/Media/Alta; Status Aberto/Em andamento/Concluido/Cancelado),
casos de uso (Gestor aprova; Usuario Cliente solicita/consulta).
"""

import datetime
import re

import pytest

from fluxo_util import (ALIASES_PEDIDO, abrir_os, criar_pedido, equip_status, equipamento_id, os_row, pedido_row)
from helpers import (lista_de, Bruto, PAYLOADS_HOSTIS, assert_exibido_com_seguranca, assert_rejeitado, assert_sucesso_post, consulta,
                     contar, enviar, executa, formularios, html_de, linha, post, texto_visivel, unico, um)


def payload(**kw):
    base = dict(equipamento="BOMBA 2 (RESFRIADOR)", departamento="Utilidades", descricao=f"Vazamento {unico('v')}", prioridade="Alta")
    base.update(kw)
    return base


# --------------------------------------------------------------------------------------------- lista

def test_tela_de_pedidos(admin):
    r = admin.get("/pedidos")
    assert r.status_code == 200
    t = texto_visivel(html_de(r))
    for trecho in ("Pedidos de Manutenção", "Novo Pedido", "Abertos", "Concluídos", "Cancelados", "#1623", "#1624", "#1625", "#1626"):
        assert trecho.lower() in t.lower(), f"Figma 16: {trecho!r} ausente"
    for col in ("Equipamento", "Departamento", "Solicitante", "Prioridade", "Status", "Data"):
        assert col.lower() in t.lower(), f"Coluna {col!r} ausente da tabela (SPEC §5)"


def test_contadores_de_status_batem_com_o_banco(admin):
    t = texto_visivel(html_de(admin.get("/pedidos")))
    esperado = {"Abertos": "Aberto", "Concluídos": "Concluído", "Cancelados": "Cancelado"}
    for rotulo, status in esperado.items():
        n = contar("pedidos_manutencao", "status=?", status)
        m = re.search(rf"(\d+)\s+{rotulo}", t, re.I) or re.search(rf"{rotulo}\s+(\d+)", t, re.I)
        assert m, f"Contador {rotulo!r} nao encontrado: {t[:300]!r}"
        assert int(m.group(1)) == n, f"Contador {rotulo}: tela {m.group(1)} x banco {n}"
    n = contar("pedidos_manutencao", "status='Em andamento'")
    m = re.search(r"(\d+)\s+Em\s+Andamento", t, re.I) or re.search(r"Em\s+Andamento\s+(\d+)", t, re.I)
    assert m and int(m.group(1)) == n, f"Contador Em andamento: {m and m.group(1)} x banco {n}"


def test_contadores_atualizam_apos_criar_e_cancelar(admin):
    def ab():
        t = texto_visivel(html_de(admin.get("/pedidos")))
        m = re.search(r"(\d+)\s+Abertos", t, re.I) or re.search(r"Abertos\s+(\d+)", t, re.I)
        return int(m.group(1))
    a0 = ab()
    pid = criar_pedido(admin)
    assert ab() == a0 + 1
    post(admin, f"/pedidos/{pid}/cancelar")
    assert ab() == a0


def test_busca_por_equipamento_solicitante_e_numero(admin):
    h = lista_de(html_de(admin.get("/pedidos?busca=EMPILHADEIRA")))
    assert "#1625" in h and "#1623" not in h
    h = lista_de(html_de(admin.get("/pedidos?busca=Carlos")))
    assert "#1625" in h and "#1623" not in h
    h = lista_de(html_de(admin.get("/pedidos?busca=1626")))
    assert "#1626" in h and "#1623" not in h


def test_filtros_status_prioridade_departamento(admin):
    # status
    h = lista_de(html_de(admin.get("/pedidos?status=Concluído")))
    assert "#1625" in h and "#1623" not in h and "#1624" not in h
    # prioridade
    h = lista_de(html_de(admin.get("/pedidos?prioridade=Baixa")))
    assert "#1625" in h and "#1623" not in h
    # departamento
    did = um("SELECT id FROM departamentos WHERE nome='Logística'")
    h = html_de(admin.get(f"/pedidos?departamento_id={did}"))
    assert "#1625" in h and "#1623" not in h


def test_filtros_combinados(admin):
    h = lista_de(html_de(admin.get("/pedidos?status=Aberto&busca=INJETORA")))
    assert "#1624" in h and "#1626" not in h and "#1625" not in h


def test_lista_vazia_tem_estado_amigavel(admin):
    assert "nenhum" in texto_visivel(html_de(admin.get("/pedidos?busca=zzzz_inexistente"))).lower()


def test_filtro_status_invalido_nao_quebra(admin):
    assert admin.get("/pedidos?status=Inexistente").status_code < 500
    assert admin.get("/pedidos?departamento_id=abc").status_code < 500
    assert admin.get("/pedidos?prioridade='; DROP TABLE pedidos_manutencao;--").status_code < 500
    assert contar("pedidos_manutencao") >= 4


# --------------------------------------------------------------------------------------------- novo pedido

def test_formulario_novo_pedido(admin):
    r = admin.get("/pedidos/novo")
    assert r.status_code == 200
    forms = [f for f in formularios(html_de(r)) if f.method == "post" and "csrf_token" in f.nomes]
    f = max(forms, key=lambda x: len(x.campos))
    nomes = " ".join(f.nomes).lower()
    for campo in ("equipamento", "departamento", "descricao", "prioridade"):
        assert campo in nomes, f"Campo {campo!r} ausente (Manual 2.1). Campos: {f.nomes}"
    t = texto_visivel(html_de(r))
    assert datetime.date.today().strftime("%d/%m/%Y") in html_de(r), "Data da solicitacao (hoje, dd/mm/aaaa) deveria aparecer (SPEC §4)"
    assert "João Administrador" in t, "Solicitante = usuario logado (SPEC §4)"
    prioridade = next(c for c in f.campos if c.nome == "prioridade")
    assert {"Baixa", "Média", "Alta"} <= {o["rotulo"] for o in prioridade.opcoes}


def test_abrir_pedido_valido(admin):
    d = payload()
    r = enviar(admin, "/pedidos/novo", d, ALIASES_PEDIDO, estrito=False)
    assert_sucesso_post(r, "abrir pedido")
    p = linha("SELECT * FROM pedidos_manutencao WHERE descricao_problema=?", d["descricao"])
    assert p, "pedido nao gravado"
    assert p["status"] == "Aberto" and p["prioridade"] == "Alta"
    assert p["id"] > 1626, "ids novos devem continuar a sequencia (seed comeca em 1621)"
    assert p["id_equipamento"] == equipamento_id("BOMBA 2 (RESFRIADOR)")
    assert p["solicitante"] == "João Administrador"
    assert str(p["data_solicitacao"]).startswith(datetime.date.today().isoformat())
    assert not p["aprovado_por"]


def test_pedido_novo_aparece_na_lista_com_numero_formatado(admin):
    pid = criar_pedido(admin)
    assert f"#{pid}" in texto_visivel(html_de(admin.get("/pedidos")))


def test_solicitante_e_o_usuario_logado_e_nao_o_enviado(comum):
    d = payload(descricao="Tentativa de forjar solicitante")
    d2 = dict(d)
    r = enviar(comum, "/pedidos/novo", d2, ALIASES_PEDIDO, estrito=False,
               extras={"solicitante": "Hacker Malvado", "id_usuario_solicitante": "1", "data_solicitacao": "2000-01-01",
                       "status": "Concluído", "aprovado_por": "Gestor Forjado", "id": "5"})
    assert_sucesso_post(r, "pedido do usuario comum")
    p = linha("SELECT * FROM pedidos_manutencao WHERE descricao_problema=?", d["descricao"])
    assert p["solicitante"] == "Ana Solicitante", "solicitante deve vir da sessao (SPEC §4)"
    assert p["id_usuario_solicitante"] == um("SELECT id FROM usuarios WHERE login='solicitante'")
    assert p["status"] == "Aberto", "status inicial e sempre Aberto"
    assert not p["aprovado_por"], "usuario nao pode se auto-aprovar via campo forjado"
    assert str(p["data_solicitacao"]).startswith(datetime.date.today().isoformat()), "data e o dia da solicitacao (SPEC §4)"
    assert p["id"] != 5


def test_usuario_comum_abre_pedido_e_ve_na_sua_lista(comum):
    pid = criar_pedido(comum, descricao="Pedido da Ana QA")
    assert f"#{pid}" in texto_visivel(html_de(comum.get("/pedidos")))


INVALIDOS = [
    ("equipamento_inexistente", dict(equipamento=Bruto("99999"))),
    ("equipamento_nao_numerico", dict(equipamento=Bruto("abc"))),
    ("departamento_inexistente", dict(departamento=Bruto("99999"))),
    ("descricao_vazia", dict(descricao="")),
    ("descricao_so_espacos", dict(descricao="    ")),
    ("prioridade_invalida", dict(prioridade=Bruto("Urgentissima"))),
]


@pytest.mark.parametrize("nome,mudanca", INVALIDOS, ids=[i[0] for i in INVALIDOS])
def test_validacoes_na_abertura(admin, nome, mudanca):
    antes = contar("pedidos_manutencao")
    r = enviar(admin, "/pedidos/novo", {**payload(), **mudanca}, ALIASES_PEDIDO, estrito=False)
    assert_rejeitado(r, f"pedido invalido ({nome})")
    assert contar("pedidos_manutencao") == antes


def test_equipamento_vazio_e_rejeitado(admin):
    antes = contar("pedidos_manutencao")
    r = enviar(admin, "/pedidos/novo", payload(), ALIASES_PEDIDO, estrito=False, extras={"id_equipamento": "", "equipamento": ""})
    assert_rejeitado(r, "pedido sem equipamento")
    assert contar("pedidos_manutencao") == antes


def test_descricao_gigante_nao_quebra(admin):
    r = enviar(admin, "/pedidos/novo", payload(descricao="x" * 20000), ALIASES_PEDIDO, estrito=False)
    assert r.status_code < 500
    p = linha("SELECT length(descricao_problema) AS n FROM pedidos_manutencao ORDER BY id DESC LIMIT 1")
    assert p["n"] <= 20000


def test_equipamento_baixado_nao_e_oferecido_nem_aceito_em_pedido(admin):
    """BUG-009 (verificado): Baixado nao aparece no select e o POST forcando o id e recusado, sem criar pedido."""
    eid = um("SELECT id FROM equipamentos WHERE descricao='BOMBA 2 (RESFRIADOR)'")
    executa("UPDATE equipamentos SET status='Baixado' WHERE id=?", eid)
    h = html_de(admin.get("/pedidos/novo"))
    assert f'value="{eid}"' not in h, "Equipamento Baixado nao deve ser oferecido no formulario de pedido"
    antes = contar("pedidos_manutencao")
    r = enviar(admin, "/pedidos/novo", payload(equipamento=Bruto(str(eid))), ALIASES_PEDIDO, estrito=False)
    assert_rejeitado(r, "pedido para equipamento Baixado")
    assert contar("pedidos_manutencao") == antes


def test_equipamento_em_manutencao_ainda_pode_receber_pedido(admin):
    eid = um("SELECT id FROM equipamentos WHERE descricao='BOMBA 2 (RESFRIADOR)'")
    executa("UPDATE equipamentos SET status='Em manutenção' WHERE id=?", eid)
    assert f'value="{eid}"' in html_de(admin.get("/pedidos/novo"))


@pytest.mark.parametrize("bruto", PAYLOADS_HOSTIS)
def test_descricao_hostil_escapada_na_lista_e_no_detalhe(admin, bruto):
    pid = criar_pedido(admin, descricao=bruto)
    assert linha("SELECT descricao_problema d FROM pedidos_manutencao WHERE id=?", pid)["d"] == bruto
    assert_exibido_com_seguranca(html_de(admin.get(f"/pedidos/{pid}")), bruto, "detalhe do pedido")
    assert "<script>alert" not in html_de(admin.get("/pedidos"))


# --------------------------------------------------------------------------------------------- detalhe

def test_detalhe_do_pedido(admin):
    r = admin.get("/pedidos/1623")
    assert r.status_code == 200
    t = texto_visivel(html_de(r))
    for trecho in ("#1623", "BOMBA 1 (RESFRIADOR)", "Utilidades", "Ana Solicitante", "Alta", "Em andamento"):
        assert trecho in t, f"Detalhe do pedido sem {trecho!r}"
    assert "OS-10234" in t, "Pedido com OS deve mostrar a OS vinculada ('Visualizar Ordem de Servico')"


def test_botoes_do_detalhe_conforme_o_estado(admin, gestor):
    pid = criar_pedido(admin)
    t = texto_visivel(html_de(admin.get(f"/pedidos/{pid}")))
    assert "Editar" in t and "Cancelar Pedido" in t and "Abrir OS" in t
    assert "Visualizar Ordem de Serviço" not in t
    tg = texto_visivel(html_de(gestor.get(f"/pedidos/{pid}")))
    assert "Aprovar" in tg, "Gestor aprova pedidos (casos de uso/SPEC §4)"
    t2 = texto_visivel(html_de(admin.get("/pedidos/1623")))
    assert "Visualizar Ordem de Serviço" in t2 or "OS-10234" in t2


def test_detalhe_inexistente_404(admin):
    assert admin.get("/pedidos/999999").status_code == 404
    assert admin.get("/pedidos/abc").status_code == 404


# --------------------------------------------------------------------------------------------- editar

def test_editar_pedido_aberto(admin):
    pid = criar_pedido(admin, prioridade="Baixa")
    r = enviar(admin, f"/pedidos/{pid}/editar", {"descricao": "Descricao revisada", "prioridade": "Alta"}, ALIASES_PEDIDO, estrito=False)
    assert_sucesso_post(r, "editar pedido")
    p = pedido_row(pid)
    assert p["descricao_problema"] == "Descricao revisada" and p["prioridade"] == "Alta"
    assert p["status"] == "Aberto"


def test_editar_preenche_o_formulario(admin):
    h = lista_de(html_de(admin.get("/pedidos/1624/editar")))
    assert "INJETORA 02" in h or "selected" in h


def test_editar_valida_igual_a_criacao(admin):
    pid = criar_pedido(admin)
    r = enviar(admin, f"/pedidos/{pid}/editar", {"descricao": ""}, ALIASES_PEDIDO, estrito=False)
    assert_rejeitado(r, "editar com descricao vazia")
    assert pedido_row(pid)["descricao_problema"]


def test_editar_nao_muda_status_nem_solicitante_por_campo_forjado(admin):
    pid = criar_pedido(admin)
    enviar(admin, f"/pedidos/{pid}/editar", {"descricao": "novo texto"}, ALIASES_PEDIDO, estrito=False,
           extras={"status": "Concluído", "solicitante": "Fulano Forjado"})
    p = pedido_row(pid)
    assert p["status"] == "Aberto" and p["solicitante"] == "João Administrador"


def test_usuario_comum_nao_edita_pedido_de_outro(comum):
    r = post(comum, "/pedidos/1625/editar", {"descricao": "invadido"})
    assert r.status_code in (403, 404)
    assert pedido_row(1625)["descricao_problema"] != "invadido"


# --------------------------------------------------------------------------------------------- cancelar

def test_cancelar_pedido_aberto(admin):
    pid = criar_pedido(admin)
    r = post(admin, f"/pedidos/{pid}/cancelar")
    assert_sucesso_post(r, "cancelar pedido aberto")
    assert pedido_row(pid)["status"] == "Cancelado"
    assert contar("historico_alteracoes", "lower(entidade) LIKE 'pedido%' AND id_entidade=?", pid) >= 2, "auditoria de criar + cancelar"


@pytest.mark.parametrize("pid,status", [(1623, "Em andamento"), (1625, "Concluído")])
def test_cancelar_so_vale_para_pedido_aberto(admin, pid, status):
    r = post(admin, f"/pedidos/{pid}/cancelar", seguir=True)
    assert r.status_code == 200 or r.status_code in (400, 409)
    assert pedido_row(pid)["status"] == status, f"Pedido {status} nao pode ser cancelado (SPEC §3.1)"


def test_cancelar_pedido_com_os_ativa_e_bloqueado(admin, tecnico):
    pid = criar_pedido(admin)
    r, oid = abrir_os(tecnico, pid)
    assert oid
    post(admin, f"/pedidos/{pid}/cancelar")
    assert pedido_row(pid)["status"] != "Cancelado", "Cancelar pedido com OS ativa (SPEC §3.1: 'sem OS ativa')"
    assert os_row(oid)["status"] not in ("Cancelada",)


def test_cancelar_duas_vezes_nao_quebra(admin):
    pid = criar_pedido(admin)
    post(admin, f"/pedidos/{pid}/cancelar")
    r = post(admin, f"/pedidos/{pid}/cancelar")
    assert r.status_code < 500
    assert pedido_row(pid)["status"] == "Cancelado"


def test_cancelar_so_por_post(admin):
    assert admin.get("/pedidos/1624/cancelar").status_code == 405


def test_pedido_cancelado_nao_aparece_para_abrir_os(admin):
    pid = criar_pedido(admin)
    post(admin, f"/pedidos/{pid}/cancelar")
    h = lista_de(html_de(admin.get("/os/nova")))
    assert f"#{pid}" not in h, "Pedido cancelado nao pode ser vinculado a nova OS"


def test_abrir_os_de_pedido_cancelado_e_bloqueado(admin, tecnico):
    pid = criar_pedido(admin)
    post(admin, f"/pedidos/{pid}/cancelar")
    r, oid = abrir_os(tecnico, pid)
    assert oid is None, "Abriu OS para pedido Cancelado"
    assert r.status_code < 500


# --------------------------------------------------------------------------------------------- aprovar

def test_gestor_aprova_pedido(gestor):
    pid = 1624
    r = post(gestor, f"/pedidos/{pid}/aprovar")
    assert_sucesso_post(r, "aprovar")
    p = pedido_row(pid)
    assert p["aprovado_por"], "aprovado_por deveria registrar quem aprovou (SPEC §3)"
    assert "Carlos Gestor" in str(p["aprovado_por"]) or str(p["aprovado_por"]) == str(um("SELECT id FROM usuarios WHERE login='gestor'"))
    assert p["status"] in ("Aberto", "Em andamento"), "Aprovar nao conclui nem cancela o pedido"


def test_aprovar_registra_auditoria(gestor):
    post(gestor, "/pedidos/1624/aprovar")
    assert contar("historico_alteracoes", "lower(entidade) LIKE 'pedido%' AND id_entidade=1624") >= 1


def test_aprovar_pedido_cancelado_e_bloqueado(admin, gestor):
    pid = criar_pedido(admin)
    post(admin, f"/pedidos/{pid}/cancelar")
    post(gestor, f"/pedidos/{pid}/aprovar")
    assert not pedido_row(pid)["aprovado_por"], "Pedido Cancelado nao deveria poder ser aprovado"


# --------------------------------------------------------------------------------------------- abrir OS a partir do pedido

def test_abrir_os_a_partir_do_pedido(admin, tecnico):
    pid = criar_pedido(admin, equipamento="BOMBA 2 (RESFRIADOR)")
    r, oid = abrir_os(tecnico, pid)
    assert_sucesso_post(r, "abrir OS")
    assert oid, "Nenhuma OS criada para o pedido"
    o = os_row(oid)
    assert o["id_pedido"] == pid and o["status"] in ("Aberta", "Em andamento")
    assert oid >= 10235, "ids de OS novos continuam a sequencia do seed (10232..10234)"
    assert str(o["data_abertura"]).startswith(datetime.date.today().isoformat())
    assert pedido_row(pid)["status"] == "Em andamento", "Abrir OS deixa o pedido Em andamento (SPEC §3.1)"
    assert f"/os/{oid}" in (r.headers.get("Location") or ""), f"Apos abrir a OS, redirecionar ao detalhe /os/{oid}"


def test_abrir_os_redireciona_para_a_os(admin, tecnico):
    pid = criar_pedido(admin)
    r, oid = abrir_os(tecnico, pid)
    assert f"/os/{oid}" in r.headers.get("Location", ""), "Depois de abrir a OS, mostrar a OS (fluxo Pedido -> OS)"


def test_um_pedido_so_pode_ter_uma_os(admin, tecnico):
    pid = criar_pedido(admin)
    abrir_os(tecnico, pid)
    r, _ = abrir_os(tecnico, pid)
    assert r.status_code < 500
    assert contar("ordens_servico", "id_pedido=?", pid) == 1, "Pedido 1:1 OS (Projeto §7): abriu 2a OS para o mesmo pedido"


def test_abrir_os_de_pedido_ja_concluido_ou_em_andamento_com_os(tecnico):
    n = contar("ordens_servico")
    for pid in (1623, 1625):   # ja possuem OS
        r, _ = abrir_os(tecnico, pid)
        assert r.status_code < 500
    assert contar("ordens_servico") == n


def test_botao_abrir_os_some_depois_de_abrir(admin, tecnico):
    pid = criar_pedido(admin)
    abrir_os(tecnico, pid)
    t = texto_visivel(html_de(tecnico.get(f"/pedidos/{pid}")))
    assert "Abrir OS" not in t
    assert "OS-" in t


def test_equipamento_do_pedido_fica_em_manutencao_quando_os_em_andamento(admin, tecnico):
    pid = criar_pedido(admin, equipamento="BOMBA 2 (RESFRIADOR)")
    _, oid = abrir_os(tecnico, pid)
    if os_row(oid)["status"] == "Em andamento":
        assert equip_status(equipamento_id("BOMBA 2 (RESFRIADOR)")) == "Em manutenção", "SPEC §3 regra 4"
