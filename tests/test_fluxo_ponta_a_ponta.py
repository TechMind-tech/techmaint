"""
Fluxo ponta a ponta (sem navegador): Pedido -> aprovar -> abrir OS -> peca (baixa de estoque + movimentacao) -> servico ->
apontamento -> fechar OS -> pedido Concluido, equipamento Ativo, dashboard e relatorios refletem.

Rastreabilidade: Manual §6 (fluxo Login -> Menu -> Cadastros/Processos -> Relatorios), SPEC §3 regras 1-5, §6 (cobertura minima),
Projeto §8 (dashboard: tempo medio, custo por maquina, pecas mais usadas, status das ordens) e §15b (relatorios).
"""

import datetime
import re

import pytest

from fluxo_util import (abrir_os, add_apontamento, add_peca, add_servico, criar_pedido, custo_os, equip_status, equipamento_id,
                        fechar_os, item_os, liquido, movs, os_row, pedido_row, peca_id, saldo)
from helpers import (assert_sucesso_post, consulta, contar, html_de, linha, numero, post, texto_visivel, um)

EQUIP = "BOMBA 2 (RESFRIADOR)"
CUSTO_SERVICO = 90000.00      # alto de proposito: garante que o equipamento apareca no topo de "custo por maquina"


def _achar(lista, trecho):
    """Primeiro item [{rotulo, valor}] cujo rotulo contem `trecho` (ci)."""
    for x in lista or []:
        if trecho.lower() in str(x.get("rotulo", "")).lower():
            return x
    return None


def _kpi(kpis, *chaves):
    for k, v in (kpis or {}).items():
        nk = k.lower()
        if all(c in nk for c in chaves):
            return v
    return None


def _dash(c, qs="periodo=30d"):
    r = c.get("/api/dashboard?" + qs)
    assert r.status_code == 200, f"/api/dashboard -> {r.status_code}"
    return r.get_json()


def _rel(c, aba, qs="periodo=30d"):
    r = c.get(f"/api/relatorios/{aba}?{qs}")
    assert r.status_code == 200, f"/api/relatorios/{aba} -> {r.status_code}"
    return r.get_json()


def _linhas_com(tabela, *trechos):
    achadas = []
    for ln in (tabela or {}).get("linhas", []):
        cel = [str(x) for x in (ln.values() if isinstance(ln, dict) else ln)]
        if all(any(t.lower() in c.lower() for c in cel) for t in trechos):
            achadas.append(ln)
    return achadas


def test_fluxo_completo_do_pedido_ao_fechamento(cliente_de):
    ana, gestor, tecnico, admin = (cliente_de(p) for p in ("comum", "gestor", "tecnico", "admin"))
    eqid = equipamento_id(EQUIP)
    pr = peca_id("Rolamento 6204")
    s0, liq0 = saldo(pr), liquido(pr)
    dash0, rel0 = _dash(admin), _rel(admin, "os")

    # 1) Usuario Comum abre o pedido
    pid = criar_pedido(ana, equipamento=EQUIP, departamento="Utilidades", descricao="Bomba vazando oleo", prioridade="Alta")
    p = pedido_row(pid)
    assert p["status"] == "Aberto" and p["solicitante"] == "Ana Solicitante"
    assert f"#{pid}" in texto_visivel(html_de(ana.get("/pedidos"))), "Ana deve ver o proprio pedido"
    assert f"#{pid}" in texto_visivel(html_de(tecnico.get("/pedidos"))), "Tecnico deve ver o pedido para atender"

    # 2) Gestor aprova
    assert_sucesso_post(post(gestor, f"/pedidos/{pid}/aprovar"), "aprovar")
    assert pedido_row(pid)["aprovado_por"]

    # 3) Tecnico abre a OS a partir do pedido
    r, oid = abrir_os(tecnico, pid)
    assert_sucesso_post(r, "abrir OS")
    assert oid and os_row(oid)["id_pedido"] == pid
    assert pedido_row(pid)["status"] == "Em andamento"
    assert f"OS-{oid}" in texto_visivel(html_de(ana.get("/os"))), "Ana consulta o status da propria OS"

    # 4) Peca: baixa de estoque + movimentacao
    assert_sucesso_post(add_peca(tecnico, oid, "Rolamento 6204", "4"), "peca")
    assert saldo(pr) == s0 - 4
    assert liquido(pr) == liq0 - 4
    ultima = movs(pr)[-1]
    assert ultima["tipo"] == "Saída" and ultima["documento_origem"] == "Ordem de Serviço"
    assert f"{oid}" in str(ultima["numero_documento"])

    # 5) Servico + apontamento
    assert_sucesso_post(add_servico(tecnico, oid, "Recuperacao do selo mecanico", "90.000,00", prestador="TecServiços Ltda"), "servico")
    assert_sucesso_post(add_apontamento(tecnico, oid, tipo="PEÇA + SERVIÇOS", horas="3,5", observacao="troca do selo"), "apontamento")
    assert custo_os(oid) == 4 * 15.0 + CUSTO_SERVICO
    t = texto_visivel(html_de(tecnico.get(f"/os/{oid}")))
    assert "R$ 90.060,00" in t, "Total geral da OS (pecas R$ 60,00 + servicos R$ 90.000,00) no detalhe"
    assert os_row(oid)["status"] == "Em andamento"
    assert equip_status(eqid) == "Em manutenção"

    # 6) Fechar
    assert_sucesso_post(fechar_os(tecnico, oid), "fechar")
    o = os_row(oid)
    assert o["status"] == "Concluída" and o["data_fechamento"]
    assert pedido_row(pid)["status"] == "Concluído"
    assert equip_status(eqid) == "Ativo"
    assert "Concluída" in texto_visivel(html_de(ana.get(f"/os/{oid}")))
    assert "Concluído" in texto_visivel(html_de(ana.get(f"/pedidos/{pid}")))

    # 7) Dashboard reflete
    dash1 = _dash(admin)
    c0 = _achar(dash0.get("status_ordens"), "conclu")
    c1 = _achar(dash1.get("status_ordens"), "conclu")
    assert c1 and c1["valor"] == (c0["valor"] if c0 else 0) + 1, f"status_ordens: Concluida deveria subir 1. antes={c0} depois={c1}"
    # custo_por_maquina e um Top-N: compara a barra do PROPRIO equipamento (somar o Top-N mudaria quando ele empurra outro para fora)
    m0 = _achar(dash0.get("custo_por_maquina"), EQUIP.split(" (")[0])
    m1 = _achar(dash1.get("custo_por_maquina"), EQUIP.split(" (")[0])
    assert m1, f"custo_por_maquina deveria listar {EQUIP} apos a OS de R$ 90.060: {dash1.get('custo_por_maquina')}"
    assert round(m1["valor"] - (m0["valor"] if m0 else 0), 2) == 90060.00, \
        f"custo_por_maquina de {EQUIP} deveria subir R$ 90.060 (antes {m0}, depois {m1})"
    u0, u1 = _achar(dash0.get("pecas_mais_usadas"), "Rolamento 6204"), _achar(dash1.get("pecas_mais_usadas"), "Rolamento 6204")
    assert u1 and u1["valor"] == (u0["valor"] if u0 else 0) + 4, f"pecas_mais_usadas: Rolamento +4. antes={u0} depois={u1}"
    k0, k1 = _kpi(dash0["kpis"], "conclu"), _kpi(dash1["kpis"], "conclu")
    assert k0 is not None and k1 == k0 + 1, f"KPI 'OS concluidas' deveria subir 1: {dash0['kpis']} -> {dash1['kpis']}"
    custo0, custo1 = _kpi(dash0["kpis"], "custo"), _kpi(dash1["kpis"], "custo")
    assert numero(custo1) - numero(custo0) >= 90060 - 0.01, f"KPI custo total deveria subir R$ 90.060: {custo0} -> {custo1}"

    # 8) Relatorios refletem (aba OS e Financeiro) e a tela HTML tambem
    rel1 = _rel(admin, "os")
    assert rel1["tabela"]["linhas"] != rel0["tabela"]["linhas"], "Tabela de OS nao mudou apos fechar uma OS"
    assert _linhas_com(rel1["tabela"], "Conclu", "Maria Técnica"), "Linha (Concluida, Maria Tecnica) deveria existir no relatorio de OS"
    graf = next((g for g in rel1["graficos"] if "técnico" in g["titulo"].lower() and "custo" not in g["titulo"].lower()), None)
    assert graf and "Maria Técnica" in graf["rotulos"], f"Grafico 'OS por Tecnico' sem Maria Tecnica: {graf}"
    fin = _rel(admin, "financeiro")
    assert fin["tabela"]["linhas"], "Relatorio financeiro vazio"
    assert any(f"OS-{oid}" in str(x) or str(oid) in str(x) for x in fin["tabela"]["linhas"]) or \
        any(EQUIP.split(" (")[0] in str(x) for x in fin["tabela"]["linhas"]), "Financeiro deveria listar a OS/equipamento (custos por OS, por equipamento - Manual 3.2)"
    est = _rel(admin, "estoque")
    assert _linhas_com(est["tabela"], "Rolamento 6204"), "Relatorio de estoque sem a peca"
    assert any(str(int(s0 - 4)) in str(c) for ln in _linhas_com(est["tabela"], "Rolamento 6204") for c in (ln.values() if isinstance(ln, dict) else ln)), \
        f"Relatorio de estoque deveria mostrar o novo saldo {s0 - 4} do Rolamento 6204"
    pagina = texto_visivel(html_de(admin.get("/relatorios?aba=os&periodo=30d")))
    assert "Maria Técnica" in pagina

    # 9) Tela inicial do dashboard (HTML)
    h = texto_visivel(html_de(admin.get("/dashboard")))
    assert "R$" in h and "Pedidos Abertos" in h or "pedidos abertos" in h.lower()

    # 10) Historico (auditoria)
    assert contar("historico_alteracoes", "id_entidade=? AND lower(entidade) LIKE 'pedido%'", pid) >= 3, "criar + aprovar + status"
    assert contar("historico_alteracoes", "id_entidade=? AND (lower(entidade) LIKE 'ordem%' OR lower(entidade) LIKE 'os%')", oid) >= 2, "abrir + fechar"


def test_fluxo_cancelamento_e_reabertura_de_pedido(cliente_de):
    admin, tecnico = cliente_de("admin"), cliente_de("tecnico")
    pid = criar_pedido(admin)
    post(admin, f"/pedidos/{pid}/cancelar")
    assert pedido_row(pid)["status"] == "Cancelado"
    r, oid = abrir_os(tecnico, pid)
    assert oid is None


def test_valores_do_dashboard_batem_com_o_banco_apos_o_fluxo(cliente_de):
    """KPIs sao CALCULADOS do banco (SPEC §3 Dashboard), nao constantes do Figma."""
    admin = cliente_de("admin")
    k = _dash(admin, "")["kpis"]
    abertos = contar("pedidos_manutencao", "status='Aberto'")
    v = _kpi(k, "abert")
    assert v == abertos, f"KPI 'pedidos abertos' = {v}, banco = {abertos} (kpis={k})"
    and_ = contar("ordens_servico", "status='Em andamento'")
    va = _kpi(k, "andamento")
    assert va == and_, f"KPI 'OS em andamento' = {va}, banco = {and_}"


def test_kpis_mudam_quando_o_banco_muda(cliente_de):
    admin = cliente_de("admin")
    a0 = _kpi(_dash(admin, "")["kpis"], "abert")
    criar_pedido(admin)
    criar_pedido(admin)
    a1 = _kpi(_dash(admin, "")["kpis"], "abert")
    assert a1 == a0 + 2, "KPI deve ser calculado a cada requisicao (nao cacheado/constante)"


def test_fluxo_com_duas_os_simultaneas_consome_estoque_independente(cliente_de):
    admin, tecnico = cliente_de("admin"), cliente_de("tecnico")
    pr = peca_id("Correia V")
    s0 = saldo(pr)
    _, o1 = abrir_os(tecnico, criar_pedido(admin))
    _, o2 = abrir_os(tecnico, criar_pedido(admin))
    add_peca(tecnico, o1, "Correia V", "50")
    add_peca(tecnico, o2, "Correia V", "70")
    assert saldo(pr) == s0 - 120
    fechar_os(tecnico, o1)
    assert saldo(pr) == s0 - 120, "Fechar OS nao mexe no estoque"
    assert custo_os(o1) == 400.0 and custo_os(o2) == 560.0


def test_menu_principal_leva_ao_fluxo(cliente_de):
    """Manual §6: Menu Principal -> Pedidos/OS/Estoque/Relatorios."""
    admin = cliente_de("admin")
    h = html_de(admin.get("/menu"))
    for href in ("/pedidos", "/os", "/estoque", "/relatorios", "/dashboard"):
        assert f'href="{href}"' in h, f"Menu principal sem atalho para {href}"
