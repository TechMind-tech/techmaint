"""
Ordens de Servico (Manual §2.2, Figma 17-18, SPEC §3 regras 1-4, §4 /os).

Rastreabilidade: RF "Emissao e acompanhamento de ordens de servico" (Projeto §8), Manual 2.2 (Pedido vinculado, Data,
Tecnico, Status, Observacoes; subformularios Itens da OS e Servicos executados; Abrir/Fechar OS, Adicionar Peca/Servico,
Voltar, Editar, Excluir, Editar/Excluir Peca), apoio §4 (Apontamentos: tipos; Tecnico = usuarios com perfil Tecnico),
SPEC §3 regra 2 (valida saldo, baixa, movimentacao Saida, estorno ao editar/excluir; OS Concluida somente leitura),
regra 4 (status do equipamento).
"""

import datetime
import re

import pytest

from dados_apoio import TIPOS_APONTAMENTO
from fluxo_util import (ALIASES_OS, abrir_os, abrir_os_avulsa, add_apontamento, add_peca, add_servico, criar_pedido, custo_os,
                        editar_item_os, equip_status, equipamento_id, excluir_item_os, fechar_os, item_os, liquido, movs, os_row,
                        pedido_com_os, pedido_row, peca_id, saldo)
from helpers import (obter_csrf, lista_de, Bruto, assert_rejeitado, assert_sucesso_post, consulta, contar, enviar, executa, formularios, html_de, linha,
                     numero, post, texto_visivel, unico, um)

BOMBA2 = "BOMBA 2 (RESFRIADOR)"


@pytest.fixture()
def os_aberta(admin, tecnico):
    """Pedido novo + OS aberta pelo tecnico. Devolve (pedido_id, os_id)."""
    return pedido_com_os(admin, tecnico, equipamento=BOMBA2)


# --------------------------------------------------------------------------------------------- lista

def test_tela_lista_de_os(admin):
    r = admin.get("/os")
    assert r.status_code == 200
    t = texto_visivel(html_de(r))
    for trecho in ("Ordens de Serviço", "Nova OS", "OS-10234", "OS-10233", "OS-10232", "#1623", "BOMBA 1 (RESFRIADOR)",
                   "Maria Técnica", "Em Andamento", "Concluída", "Aberta"):
        assert trecho.lower() in t.lower(), f"Figma 17: {trecho!r} ausente"


def test_faixa_de_pedidos_aguardando_abertura_de_os(admin):
    esperado = um("SELECT COUNT(*) FROM pedidos_manutencao p WHERE p.status='Aberto' AND NOT EXISTS "
                  "(SELECT 1 FROM ordens_servico o WHERE o.id_pedido=p.id AND o.status<>'Cancelada')")
    t = texto_visivel(html_de(admin.get("/os")))
    m = re.search(r"(\d+)\s+pedido\(s\)\s+aguardando", t)
    assert m, f"Faixa amarela '⚠ N pedido(s) aguardando abertura de OS' ausente (Figma 17). Texto: {t[:400]!r}"
    assert int(m.group(1)) == esperado, f"N da faixa: {m.group(1)} x banco {esperado}"


def test_faixa_some_quando_nao_ha_pedido_aguardando(admin):
    executa("UPDATE pedidos_manutencao SET status='Cancelado' WHERE status='Aberto'")
    t = texto_visivel(html_de(admin.get("/os")))
    assert not re.search(r"[1-9]\d*\s+pedido\(s\)\s+aguardando", t)


def test_resumo_de_status_na_lista(admin):
    t = texto_visivel(html_de(admin.get("/os")))
    for rotulo, status in (("Aberta", "Aberta"), ("Concluída", "Concluída"), ("Cancelada", "Cancelada")):
        n = contar("ordens_servico", "status=?", status)
        m = re.search(rf"{rotulo}:\s*(\d+)", t, re.I)
        if m:
            assert int(m.group(1)) == n, f"Resumo {rotulo}: tela {m.group(1)} x banco {n}"
    n = contar("ordens_servico", "status='Em andamento'")
    m = re.search(r"Em\s+Andamento:\s*(\d+)", t, re.I)
    assert m and int(m.group(1)) == n


def test_filtro_por_status_tecnico_e_busca(admin):
    h = lista_de(html_de(admin.get("/os?status=Concluída")))
    assert "OS-10233" in h and "OS-10234" not in h
    h = lista_de(html_de(admin.get("/os?busca=EMPILHADEIRA")))
    assert "OS-10233" in h and "OS-10234" not in h
    h = lista_de(html_de(admin.get("/os?busca=10232")))
    assert "OS-10232" in h and "OS-10233" not in h
    tid = um("SELECT id_tecnico FROM ordens_servico WHERE id=10234")
    h = html_de(admin.get(f"/os?tecnico_id={tid}"))
    assert "OS-10234" in h


def test_filtros_invalidos_nao_quebram(admin):
    for qs in ("status=Foo", "tecnico_id=abc", "busca=%27%3B--", "status=%3Cscript%3E"):
        assert admin.get("/os?" + qs).status_code < 500


# --------------------------------------------------------------------------------------------- nova OS

def test_formulario_nova_os(admin):
    r = admin.get("/os/nova")
    assert r.status_code == 200
    forms = [f for f in formularios(html_de(r)) if f.method == "post" and "csrf_token" in f.nomes]
    f = max(forms, key=lambda x: len(x.campos))
    nomes = " ".join(f.nomes).lower()
    assert "pedido" in nomes and "tecnico" in nomes and "observ" in nomes, f"Campos da Nova OS (Figma 18): {f.nomes}"
    tec = next(c for c in f.campos if c.nome and "tecnico" in c.nome)
    rotulos = " | ".join(o["rotulo"] for o in tec.opcoes)
    assert "Maria Técnica" in rotulos and "Pedro Lima" in rotulos, f"Tecnicos = usuarios com perfil Tecnico: {rotulos}"
    assert "Ana Solicitante" not in rotulos and "Carlos Gestor" not in rotulos, "Select de tecnico so deve ter usuarios do perfil Tecnico (apoio §4)"
    ped = next(c for c in f.campos if c.nome and "pedido" in c.nome)
    assert ped.opcoes[0]["valor"] in ("", "0"), "Primeira opcao: '— Sem pedido vinculado —' (Figma 18)"
    t = texto_visivel(html_de(r))
    assert "Abrir OS" in t and "Cancelar" in t and "Voltar" in t


def test_pedidos_disponiveis_so_abertos_e_sem_os(admin):
    h = lista_de(html_de(admin.get("/os/nova")))
    assert "#1624" in h and "#1626" in h, "Pedidos Abertos sem OS devem estar disponiveis"
    assert "#1623" not in h, "#1623 ja tem OS"
    assert "#1625" not in h, "#1625 esta Concluido"


def test_pre_selecao_por_query_pedido_id(admin):
    h = lista_de(html_de(admin.get("/os/nova?pedido_id=1624")))
    forms = [f for f in formularios(h) if f.method == "post" and "csrf_token" in f.nomes]
    f = max(forms, key=lambda x: len(x.campos))
    ped = next(c for c in f.campos if c.nome and "pedido" in c.nome)
    sel = next((o for o in ped.opcoes if o["selecionado"]), None)
    assert sel and sel["valor"] == "1624", "pedido_id da URL deve vir pre-selecionado (SPEC §4)"


def test_abrir_os_avulsa_sem_pedido(admin):
    r, oid = abrir_os_avulsa(admin, tecnico="Pedro Lima", observacao="manutencao preventiva predial")
    assert_sucesso_post(r, "abrir OS sem pedido")
    assert oid, "OS nao criada"
    o = os_row(oid)
    assert o["id_pedido"] in (None, 0) and o["observacao"] == "manutencao preventiva predial"
    assert o["id_tecnico"] == um("SELECT id FROM usuarios WHERE login='plima'")
    assert o["status"] in ("Aberta", "Em andamento")


def test_abrir_os_vinculando_pedido_pelo_formulario(admin):
    r = enviar(admin, "/os/nova", {"pedido": "#1624", "tecnico": "Maria Técnica", "observacao": "via form"}, ALIASES_OS, estrito=False)
    assert_sucesso_post(r, "abrir OS vinculada")
    assert contar("ordens_servico", "id_pedido=1624") == 1
    assert pedido_row(1624)["status"] == "Em andamento"


def test_nova_os_com_pedido_que_ja_tem_os_e_rejeitada(admin):
    n = contar("ordens_servico")
    r = enviar(admin, "/os/nova", {"pedido": Bruto("1623"), "tecnico": "Maria Técnica"}, ALIASES_OS, estrito=False)
    assert_rejeitado(r, "2a OS para o pedido #1623 (1:1)")
    assert contar("ordens_servico") == n


@pytest.mark.parametrize("nome,dados", [
    ("pedido_inexistente", {"pedido": Bruto("99999"), "tecnico": "Maria Técnica"}),
    ("pedido_concluido", {"pedido": Bruto("1625"), "tecnico": "Maria Técnica"}),
    ("tecnico_inexistente", {"tecnico": Bruto("99999")}),
    ("tecnico_nao_tecnico", {"tecnico": "__COMUM__"}),
    ("tecnico_vazio", {"tecnico": Bruto("")}),
])
def test_validacoes_nova_os(admin, nome, dados):
    if dados.get("tecnico") == "__COMUM__":
        dados = {"tecnico": Bruto(str(um("SELECT id FROM usuarios WHERE login='solicitante'")))}
    n = contar("ordens_servico")
    r = enviar(admin, "/os/nova", dados, ALIASES_OS, estrito=False)
    assert_rejeitado(r, f"nova OS invalida ({nome})")
    assert contar("ordens_servico") == n


def test_observacao_hostil(admin):
    from helpers import PAYLOADS_HOSTIS, assert_exibido_com_seguranca
    for bruto in PAYLOADS_HOSTIS:
        r, oid = abrir_os_avulsa(admin, observacao=bruto)
        assert oid, f"OS nao criada com observacao {bruto!r}"
        assert_exibido_com_seguranca(html_de(admin.get(f"/os/{oid}")), bruto, "detalhe da OS")


def test_gestor_e_comum_nao_abrem_os(gestor, comum):
    assert gestor.get("/os/nova").status_code == 403
    assert comum.get("/os/nova").status_code == 403


# --------------------------------------------------------------------------------------------- detalhe

def test_detalhe_da_os_do_seed(admin):
    r = admin.get("/os/10234")
    assert r.status_code == 200
    t = texto_visivel(html_de(r))
    for trecho in ("OS-10234", "#1623", "BOMBA 1 (RESFRIADOR)", "Maria Técnica", "Em Andamento", "Peças", "Serviços", "Apontamentos"):
        assert trecho.lower() in t.lower(), f"Detalhe da OS sem {trecho!r} (SPEC §5)"
    for botao in ("Adicionar Peça", "Adicionar Serviço", "Fechar OS", "Voltar"):
        assert botao.lower() in t.lower(), f"Botao {botao!r} ausente (Manual 2.2)"


def test_detalhe_inexistente_404(admin):
    assert admin.get("/os/999999").status_code == 404
    assert admin.get("/os/abc").status_code == 404


def test_detalhe_mostra_totais_em_reais(admin):
    oid = um("SELECT id_os FROM itens_os GROUP BY id_os ORDER BY SUM(valor_total) DESC LIMIT 1")
    t = texto_visivel(html_de(admin.get(f"/os/{oid}")))
    pecas = float(um("SELECT COALESCE(SUM(valor_total),0) FROM itens_os WHERE id_os=?", oid))
    fmt = f"R$ {pecas:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    assert fmt in t, f"Total de pecas {fmt} deveria aparecer no formato brasileiro"


# --------------------------------------------------------------------------------------------- pecas na OS (regra 2)

def test_adicionar_peca_baixa_estoque_e_cria_movimentacao_de_saida(os_aberta, tecnico):
    _, oid = os_aberta
    pid = peca_id("Rolamento 6204")
    s0, n0 = saldo(pid), len(movs(pid))
    r = add_peca(tecnico, oid, "Rolamento 6204", "3")
    assert_sucesso_post(r, "adicionar peca")
    assert saldo(pid) == s0 - 3, "Estoque deve baixar (SPEC §3.2)"
    it = item_os(oid, pid)
    assert len(it) == 1 and float(it[0]["quantidade"]) == 3
    assert float(it[0]["valor_unitario"]) == 15.0 and float(it[0]["valor_total"]) == 45.0
    novos = movs(pid)[n0:]
    assert len(novos) == 1, f"Deveria criar 1 movimentacao, criou {len(novos)}"
    m = novos[0]
    assert m["tipo"] == "Saída" and float(m["quantidade"]) == 3
    assert m["documento_origem"] == "Ordem de Serviço", "documento_origem = 'Ordem de Serviço' (SPEC §3.2)"
    assert str(m["numero_documento"]) in (f"OS-{oid}", str(oid)), f"numero_documento = numero da OS: {m['numero_documento']}"
    assert m["id_usuario"] == um("SELECT id FROM usuarios WHERE login='tecnico'")
    assert float(m["valor_unitario"]) == 15.0


def test_item_aparece_no_detalhe_e_no_total(os_aberta, tecnico):
    _, oid = os_aberta
    add_peca(tecnico, oid, "Sensor Indutivo", "2")
    t = texto_visivel(html_de(tecnico.get(f"/os/{oid}")))
    assert "Sensor Indutivo" in t and "R$ 51,00" in t, "2 x R$ 25,50 = R$ 51,00 (subtotal/total da OS)"


def test_estoque_pecas_continua_coerente_apos_baixa(os_aberta, tecnico):
    from helpers import coluna
    _, oid = os_aberta
    pid = peca_id("Correia V")
    add_peca(tecnico, oid, "Correia V", "10")
    col = coluna("estoque_pecas", "qtde_atual", "saldo", "quantidade")
    assert float(um(f"SELECT {col} FROM estoque_pecas WHERE id_peca=?", pid)) == saldo(pid)


def test_saldo_insuficiente_e_bloqueado_e_nada_muda(os_aberta, tecnico):
    _, oid = os_aberta
    pid = peca_id("Filtro de Ar")  # saldo 30
    s0, n0, i0 = saldo(pid), len(movs(pid)), len(item_os(oid))
    r = add_peca(tecnico, oid, "Filtro de Ar", "31")
    assert_rejeitado(r, "peca acima do saldo")
    assert saldo(pid) == s0 and len(movs(pid)) == n0 and len(item_os(oid)) == i0, "Saldo insuficiente nao pode alterar NADA"
    t = texto_visivel(html_de(r)).lower()
    assert "saldo" in t or "estoque" in t or "insuficiente" in t, "Mensagem clara de saldo insuficiente"


def test_pode_usar_exatamente_o_saldo_e_zera(os_aberta, tecnico):
    _, oid = os_aberta
    pid = peca_id("Filtro de Ar")
    assert_sucesso_post(add_peca(tecnico, oid, "Filtro de Ar", "30"), "usar todo o saldo")
    assert saldo(pid) == 0
    r = add_peca(tecnico, oid, "Filtro de Ar", "1")
    assert_rejeitado(r, "peca sem saldo")
    assert saldo(pid) == 0


@pytest.mark.parametrize("qtd", ["0", "-1", "-0,5", "abc", "", "1e9", "99999999999999999999", "0,0001"])
def test_quantidade_invalida_na_os(os_aberta, tecnico, qtd):
    _, oid = os_aberta
    pid = peca_id("Rolamento 6204")
    s0 = saldo(pid)
    r = add_peca(tecnico, oid, "Rolamento 6204", qtd)
    assert r.status_code < 500
    if qtd in ("0", "-1", "-0,5", "abc", "", "1e9", "99999999999999999999"):
        assert_rejeitado(r, f"quantidade {qtd!r}")
        assert saldo(pid) == s0, f"quantidade {qtd!r} alterou o estoque"
    assert saldo(pid) >= 0


def test_peca_inexistente_na_os(os_aberta, tecnico):
    _, oid = os_aberta
    r = add_peca(tecnico, oid, Bruto("99999"), "1")
    assert_rejeitado(r, "peca inexistente")
    assert contar("itens_os", "id_os=?", oid) == 0


def test_mesma_peca_duas_vezes_baixa_a_soma(os_aberta, tecnico):
    _, oid = os_aberta
    pid = peca_id("Rolamento 6204")
    s0 = saldo(pid)
    add_peca(tecnico, oid, "Rolamento 6204", "2")
    add_peca(tecnico, oid, "Rolamento 6204", "5")
    assert saldo(pid) == s0 - 7
    assert sum(float(i["quantidade"]) for i in item_os(oid, pid)) == 7
    assert liquido(pid) == liquido(pid)  # consistente
    assert float(um("SELECT COALESCE(SUM(valor_total),0) FROM itens_os WHERE id_os=?", oid)) == 105.0


def test_editar_quantidade_para_menos_estorna(os_aberta, tecnico):
    _, oid = os_aberta
    pid = peca_id("Rolamento 6204")
    s0 = saldo(pid)
    add_peca(tecnico, oid, "Rolamento 6204", "10")
    it = item_os(oid, pid)[0]
    r = editar_item_os(tecnico, oid, it["id"], "4")
    assert_sucesso_post(r, "editar quantidade da peca")
    assert saldo(pid) == s0 - 4, "Reduzir de 10 para 4 deve devolver 6 ao estoque"
    it2 = item_os(oid, pid)[0]
    assert float(it2["quantidade"]) == 4 and float(it2["valor_total"]) == 60.0


def test_editar_quantidade_para_mais_baixa_a_diferenca(os_aberta, tecnico):
    _, oid = os_aberta
    pid = peca_id("Rolamento 6204")
    s0 = saldo(pid)
    add_peca(tecnico, oid, "Rolamento 6204", "2")
    it = item_os(oid, pid)[0]
    editar_item_os(tecnico, oid, it["id"], "9")
    assert saldo(pid) == s0 - 9
    assert float(item_os(oid, pid)[0]["valor_total"]) == 135.0


def test_editar_quantidade_alem_do_saldo_disponivel_e_rejeitado(os_aberta, tecnico):
    _, oid = os_aberta
    pid = peca_id("Filtro de Ar")  # 30
    add_peca(tecnico, oid, "Filtro de Ar", "10")
    it = item_os(oid, pid)[0]
    r = editar_item_os(tecnico, oid, it["id"], "41")   # precisaria de 31 a mais, so ha 20
    assert_rejeitado(r, "editar acima do saldo")
    assert saldo(pid) == 20 and float(item_os(oid, pid)[0]["quantidade"]) == 10


def test_editar_para_exatamente_o_maximo_possivel(os_aberta, tecnico):
    _, oid = os_aberta
    pid = peca_id("Filtro de Ar")
    add_peca(tecnico, oid, "Filtro de Ar", "10")
    it = item_os(oid, pid)[0]
    assert_sucesso_post(editar_item_os(tecnico, oid, it["id"], "30"), "editar ate zerar o estoque")
    assert saldo(pid) == 0


@pytest.mark.parametrize("qtd", ["0", "-2", "abc", ""])
def test_editar_quantidade_invalida(os_aberta, tecnico, qtd):
    _, oid = os_aberta
    pid = peca_id("Rolamento 6204")
    add_peca(tecnico, oid, "Rolamento 6204", "5")
    it = item_os(oid, pid)[0]
    s = saldo(pid)
    r = editar_item_os(tecnico, oid, it["id"], qtd)
    assert_rejeitado(r, f"editar quantidade para {qtd!r}")
    assert saldo(pid) == s and float(item_os(oid, pid)[0]["quantidade"]) == 5


def test_excluir_peca_da_os_estorna_estoque_e_registra_movimento(os_aberta, tecnico):
    _, oid = os_aberta
    pid = peca_id("Sensor Indutivo")
    s0, liq0 = saldo(pid), liquido(pid)
    add_peca(tecnico, oid, "Sensor Indutivo", "6")
    it = item_os(oid, pid)[0]
    r = excluir_item_os(tecnico, oid, it["id"])
    assert_sucesso_post(r, "excluir peca da OS")
    assert saldo(pid) == s0, "Excluir a peca da OS deve ESTORNAR o estoque (SPEC §3.2)"
    assert item_os(oid, pid) == []
    assert liquido(pid) == liq0, "O historico de movimentacao deve fechar (estorno = Entrada ou remocao da Saida)"


def test_estorno_em_ciclo_nao_perde_nem_cria_estoque(os_aberta, tecnico):
    _, oid = os_aberta
    pid = peca_id("Correia V")
    s0 = saldo(pid)
    for _ in range(3):
        add_peca(tecnico, oid, "Correia V", "7")
        excluir_item_os(tecnico, oid, item_os(oid, pid)[-1]["id"])
    assert saldo(pid) == s0


def test_excluir_item_inexistente_ou_de_outra_os(os_aberta, tecnico):
    _, oid = os_aberta
    r = excluir_item_os(tecnico, oid, 999999)
    assert r.status_code in (404, 302, 303)
    it = linha("SELECT * FROM itens_os ORDER BY id LIMIT 1")   # item do seed, de OUTRA os
    outra = [x for x in consulta("SELECT id FROM ordens_servico") if x["id"] != it["id_os"]][0]["id"]
    n = contar("itens_os")
    r = excluir_item_os(tecnico, outra, it["id"])
    assert contar("itens_os") == n, "Excluiu item de outra OS usando um id de OS diferente na URL (IDOR)"


def test_valor_da_peca_na_os_e_o_do_momento_da_inclusao(os_aberta, tecnico, admin):
    _, oid = os_aberta
    pid = peca_id("Rolamento 6204")
    add_peca(tecnico, oid, "Rolamento 6204", "2")
    executa("UPDATE pecas SET valor_unitario=99 WHERE id=?", pid)
    assert float(item_os(oid, pid)[0]["valor_unitario"]) == 15.0
    assert custo_os(oid) == 30.0


# --------------------------------------------------------------------------------------------- servicos

def test_adicionar_servico_com_e_sem_prestador(os_aberta, tecnico):
    _, oid = os_aberta
    r = add_servico(tecnico, oid, "Troca de rolamento", "250,00")
    assert_sucesso_post(r, "adicionar servico")
    prest = um("SELECT id FROM prestadores_servico WHERE razao_social='TecServiços Ltda'")
    r = add_servico(tecnico, oid, "Soldagem externa", "1.000,50", prestador="TecServiços Ltda")
    assert_sucesso_post(r, "adicionar servico com prestador")
    s = consulta("SELECT * FROM servicos_os WHERE id_os=? ORDER BY id", oid)
    assert len(s) == 2
    assert s[0]["id_prestador"] in (None, 0) and float(s[0]["valor_servico"]) == 250.0
    assert s[1]["id_prestador"] == prest and float(s[1]["valor_servico"]) == 1000.5
    t = texto_visivel(html_de(tecnico.get(f"/os/{oid}")))
    assert "Troca de rolamento" in t and "R$ 1.250,50" in t, "Total de servicos 250,00 + 1.000,50"


@pytest.mark.parametrize("nome,dados", [
    ("descricao_vazia", dict(descricao="", valor="10")),
    ("valor_negativo", dict(descricao="x", valor="-5")),
    ("valor_texto", dict(descricao="x", valor="caro")),
    ("valor_vazio", dict(descricao="x", valor="")),
    ("prestador_inexistente", dict(descricao="x", valor="10", prestador=Bruto("99999"))),
])
def test_validacoes_de_servico(os_aberta, tecnico, nome, dados):
    _, oid = os_aberta
    r = enviar(tecnico, f"/os/{oid}", dados, {"descricao": ["descricao_servico", "descricao"], "valor": ["valor_servico", "valor"],
                                              "prestador": ["id_prestador", "prestador"]}, estrito=False, action_contem="/servicos")
    assert_rejeitado(r, f"servico invalido ({nome})")
    assert contar("servicos_os", "id_os=?", oid) == 0


def test_servico_valor_zero_e_aceito(os_aberta, tecnico):
    _, oid = os_aberta
    assert_sucesso_post(add_servico(tecnico, oid, "Servico em garantia", "0"), "servico de valor 0 (valores >= 0)")


def test_excluir_servico(os_aberta, tecnico):
    _, oid = os_aberta
    add_servico(tecnico, oid, "Servico a remover", "100")
    sid = um("SELECT id FROM servicos_os WHERE id_os=?", oid)
    r = post(tecnico, f"/os/{oid}/servicos/{sid}/excluir")
    assert_sucesso_post(r, "excluir servico")
    assert contar("servicos_os", "id_os=?", oid) == 0


def test_servico_prestador_inativo_nao_deveria_ser_oferecido(os_aberta, tecnico):
    _, oid = os_aberta
    inativo = um("SELECT razao_social FROM prestadores_servico WHERE ativo=0 LIMIT 1")
    if not inativo:
        pytest.skip("seed sem prestador inativo")
    h = html_de(tecnico.get(f"/os/{oid}"))
    forms = [f for f in formularios(h) if "/servicos" in f.action]
    ops = " ".join(o["rotulo"] for f in forms for c in f.campos if c.nome and "prestador" in c.nome for o in c.opcoes)
    assert inativo not in ops, f"Prestador inativo ({inativo}) aparece na lista de selecao de servicos"


# --------------------------------------------------------------------------------------------- apontamentos

def test_form_de_apontamento_tem_os_11_tipos(os_aberta, tecnico):
    _, oid = os_aberta
    forms = [f for f in formularios(html_de(tecnico.get(f"/os/{oid}"))) if "/apontamentos" in f.action]
    assert forms, "Detalhe da OS sem formulario de Apontamento (SPEC §5)"
    tipo = next(c for c in forms[0].campos if c.nome and "tipo" in c.nome)
    reais = [o for o in tipo.opcoes if o["valor"] != ""]   # a 1a opcao e o placeholder "Selecione"
    assert [o["valor"] for o in reais] == TIPOS_APONTAMENTO or {o["rotulo"] for o in reais} == set(TIPOS_APONTAMENTO), \
        f"Tipos de apontamento (apoio §4): {[o['rotulo'] for o in reais]}"


@pytest.mark.parametrize("tipo", TIPOS_APONTAMENTO)
def test_apontamento_de_cada_tipo(os_aberta, tecnico, tipo):
    _, oid = os_aberta
    r = add_apontamento(tecnico, oid, tipo=tipo, horas="2")
    assert_sucesso_post(r, f"apontamento {tipo}")
    ap = linha("SELECT * FROM apontamentos_os WHERE id_os=? ORDER BY id DESC LIMIT 1", oid)
    assert ap["tipo"] == tipo and float(ap["horas_trabalhadas"]) == 2.0
    assert ap["tecnico"], "tecnico do apontamento obrigatorio"


def test_apontamento_sem_data_assume_hoje(os_aberta, tecnico):
    """Decisao D-11: data vazia nao e erro; o app assume a data de hoje (o campo ja vem preenchido no Figma)."""
    import datetime
    _, oid = os_aberta
    add_apontamento(tecnico, oid, data=Bruto(""))
    d = um("SELECT data FROM apontamentos_os WHERE id_os=? ORDER BY id DESC LIMIT 1", oid)
    assert d == datetime.date.today().isoformat()


@pytest.mark.parametrize("nome,mudanca", [
    ("tipo_invalido", dict(tipo=Bruto("INVENTADO"))),
    ("horas_negativas", dict(horas="-1")),
    ("horas_texto", dict(horas="muitas")),
    ("horas_vazias", dict(horas="")),
    ("data_invalida", dict(data="31/02/2026")),
])
def test_validacoes_de_apontamento(os_aberta, tecnico, nome, mudanca):
    _, oid = os_aberta
    r = add_apontamento(tecnico, oid, **mudanca)
    assert_rejeitado(r, f"apontamento invalido ({nome})")
    assert contar("apontamentos_os", "id_os=?", oid) == 0


def test_horas_com_virgula_decimal(os_aberta, tecnico):
    _, oid = os_aberta
    assert_sucesso_post(add_apontamento(tecnico, oid, horas="1,75"), "horas 1,75")
    assert float(um("SELECT horas_trabalhadas FROM apontamentos_os WHERE id_os=?", oid)) == 1.75


def test_horas_absurdas_nao_quebram(os_aberta, tecnico):
    _, oid = os_aberta
    for h in ("24", "25", "1000", "99999999"):
        assert add_apontamento(tecnico, oid, horas=h).status_code < 500
    assert contar("apontamentos_os", "id_os=? AND horas_trabalhadas > 999.99", oid) == 0, "DECIMAL(5,2): nao pode estourar"


def test_apontamento_aparece_no_detalhe(os_aberta, tecnico):
    _, oid = os_aberta
    add_apontamento(tecnico, oid, tipo="LUBRIFICACAO", horas="3", observacao="lubrificado mancal X")
    t = texto_visivel(html_de(tecnico.get(f"/os/{oid}")))
    assert "LUBRIFICACAO" in t and "lubrificado mancal X" in t


# --------------------------------------------------------------------------------------------- fechar OS

def test_fechar_os(os_aberta, tecnico):
    pid, oid = os_aberta
    add_peca(tecnico, oid, "Rolamento 6204", "1")
    r = fechar_os(tecnico, oid)
    assert_sucesso_post(r, "fechar OS")
    o = os_row(oid)
    assert o["status"] == "Concluída"
    assert o["data_fechamento"] and str(o["data_fechamento"]).startswith(datetime.date.today().isoformat())
    assert pedido_row(pid)["status"] == "Concluído", "Fechar OS conclui o pedido (SPEC §3.1)"
    assert equip_status(equipamento_id(BOMBA2)) == "Ativo", "Equipamento volta a Ativo (SPEC §3.4)"
    assert contar("historico_alteracoes", "lower(entidade) LIKE 'ordem%' OR lower(entidade) LIKE 'os%'") >= 1


def test_fechar_os_avulsa_sem_pedido(admin):
    r, oid = abrir_os_avulsa(admin)
    assert_sucesso_post(fechar_os(admin, oid), "fechar OS sem pedido")
    assert os_row(oid)["status"] == "Concluída"


def test_gestor_pode_fechar_os(os_aberta, gestor):
    pid, oid = os_aberta
    r = fechar_os(gestor, oid)
    assert_sucesso_post(r, "gestor fecha OS (SPEC §2: ver + fechar)")
    assert os_row(oid)["status"] == "Concluída"


def test_fechar_duas_vezes_mantem_a_data_original(os_aberta, tecnico):
    pid, oid = os_aberta
    fechar_os(tecnico, oid)
    d1 = os_row(oid)["data_fechamento"]
    executa("UPDATE ordens_servico SET data_fechamento='2020-01-02 10:00:00' WHERE id=?", oid)
    r = fechar_os(tecnico, oid)
    assert r.status_code < 500
    assert os_row(oid)["data_fechamento"] == "2020-01-02 10:00:00", "Fechar de novo nao pode reescrever a data de fechamento"


def test_fechar_os_inexistente(tecnico):
    assert fechar_os(tecnico, 999999).status_code in (404, 302, 303)


def test_fechar_so_por_post(tecnico, os_aberta):
    assert tecnico.get(f"/os/{os_aberta[1]}/fechar").status_code == 405


# --------------------------------------------------------------------------------------------- OS concluida = somente leitura

@pytest.fixture()
def os_fechada(admin, tecnico):
    pid, oid = pedido_com_os(admin, tecnico, equipamento=BOMBA2)
    add_peca(tecnico, oid, "Rolamento 6204", "2")
    add_servico(tecnico, oid, "Servico fechado", "100")
    fechar_os(tecnico, oid)
    return pid, oid


def test_os_concluida_nao_aceita_nova_peca(os_fechada, tecnico):
    _, oid = os_fechada
    pid = peca_id("Rolamento 6204")
    s0 = saldo(pid)
    r = add_peca(tecnico, oid, "Rolamento 6204", "1")
    assert r.status_code in (400, 403, 409, 422, 302, 303, 200, 404) and r.status_code < 500
    assert saldo(pid) == s0 and len(item_os(oid)) == 1, "OS Concluida e somente leitura (SPEC §3.2): adicionou peca"


def test_os_concluida_nao_aceita_servico_apontamento_nem_edicao(os_fechada, tecnico):
    _, oid = os_fechada
    add_servico(tecnico, oid, "Novo servico", "5")
    add_apontamento(tecnico, oid)
    assert contar("servicos_os", "id_os=?", oid) == 1, "Aceitou servico em OS concluida"
    assert contar("apontamentos_os", "id_os=?", oid) == 0, "Aceitou apontamento em OS concluida"
    r = enviar(tecnico, f"/os/{oid}/editar", {"observacao": "alterada depois de fechada"}, ALIASES_OS, estrito=False)
    assert os_row(oid)["observacao"] != "alterada depois de fechada", "Editou OS concluida"


def test_os_concluida_nao_edita_nem_exclui_peca(os_fechada, tecnico):
    _, oid = os_fechada
    pid = peca_id("Rolamento 6204")
    it = item_os(oid, pid)[0]
    s0 = saldo(pid)
    post(tecnico, f"/os/{oid}/pecas/{it['id']}/editar", {"quantidade": "9"})
    excluir_item_os(tecnico, oid, it["id"])
    assert saldo(pid) == s0 and float(item_os(oid, pid)[0]["quantidade"]) == 2, "Alterou peca de OS concluida"


def test_os_concluida_nao_pode_ser_excluida(os_fechada, tecnico):
    _, oid = os_fechada
    post(tecnico, f"/os/{oid}/excluir")
    assert os_row(oid) is not None, "OS Concluida somente leitura: nao deveria ser excluida"


def test_tela_da_os_concluida_nao_mostra_acoes_de_edicao(os_fechada, tecnico):
    _, oid = os_fechada
    h = html_de(tecnico.get(f"/os/{oid}"))
    t = texto_visivel(h)
    assert "Concluída" in t
    assert "Fechar OS" not in t, "OS fechada nao deveria oferecer 'Fechar OS'"
    for acao in ("/pecas", "/servicos", "/apontamentos", "/fechar", "/excluir"):
        forms = [f for f in formularios(h) if f.method == "post" and f.action.rstrip("/").endswith(acao) and "/os/" in f.action]
        assert not forms, f"OS concluida ainda renderiza formulario de {acao} (somente leitura, SPEC §3.2/§4 somente_leitura)"


def test_os_concluida_mostra_os_dados_gravados(os_fechada, tecnico):
    _, oid = os_fechada
    t = texto_visivel(html_de(tecnico.get(f"/os/{oid}")))
    assert "Rolamento 6204" in t and "Servico fechado" in t and "R$ 130,00" in t


# --------------------------------------------------------------------------------------------- editar OS

def test_editar_os(os_aberta, admin):
    _, oid = os_aberta
    r = enviar(admin, f"/os/{oid}/editar", {"tecnico": "Pedro Lima", "observacao": "nova observacao"}, ALIASES_OS, estrito=False)
    assert_sucesso_post(r, "editar OS")
    o = os_row(oid)
    assert o["observacao"] == "nova observacao" and o["id_tecnico"] == um("SELECT id FROM usuarios WHERE login='plima'")


def test_editar_os_preenche_formulario(admin):
    h = lista_de(html_de(admin.get("/os/10234/editar")))
    assert "Maria Técnica" in h


def test_editar_os_nao_permite_trocar_para_pedido_que_ja_tem_outra_os(os_aberta, admin):
    _, oid = os_aberta
    r = enviar(admin, f"/os/{oid}/editar", {"pedido": Bruto("1623")}, ALIASES_OS, estrito=False)
    assert contar("ordens_servico", "id_pedido=1623") == 1, "Dois OS para o pedido #1623 (1:1 quebrado pela edicao)"


def test_editar_os_inexistente(admin):
    assert admin.get("/os/999999/editar").status_code == 404


# --------------------------------------------------------------------------------------------- excluir OS

def test_excluir_os_sem_itens(admin):
    r, oid = abrir_os_avulsa(admin)
    assert_sucesso_post(post(admin, f"/os/{oid}/excluir"), "excluir OS")
    assert os_row(oid) is None


def test_excluir_os_com_pecas_estorna_estoque(os_aberta, tecnico):
    pid_ped, oid = os_aberta
    pid = peca_id("Rolamento 6204")
    s0 = saldo(pid)
    add_peca(tecnico, oid, "Rolamento 6204", "5")
    post(tecnico, f"/os/{oid}/excluir")
    if os_row(oid) is None:
        assert saldo(pid) == s0, "Excluiu a OS mas NAO estornou as pecas (estoque perdido)"
        assert contar("itens_os", "id_os=?", oid) == 0
        assert contar("servicos_os", "id_os=?", oid) == 0
        assert contar("apontamentos_os", "id_os=?", oid) == 0
        assert pedido_row(pid_ped)["status"] == "Aberto", "Pedido sem OS nao pode ficar 'Em andamento'"
        assert equip_status(equipamento_id(BOMBA2)) != "Em manutenção" or contar("ordens_servico", "status='Em andamento'") > 0
    else:
        assert saldo(pid) == s0 - 5, "OS mantida: estoque deve continuar baixado"
    assert consulta("PRAGMA foreign_key_check") == []


def test_excluir_os_so_por_post(os_aberta, admin):
    assert admin.get(f"/os/{os_aberta[1]}/excluir").status_code == 405


# --------------------------------------------------------------------------------------------- equipamento x status da OS (regra 4)

def test_equipamento_em_manutencao_enquanto_ha_os_em_andamento(admin, tecnico):
    eqid = equipamento_id(BOMBA2)
    pid, oid = pedido_com_os(admin, tecnico, equipamento=BOMBA2)
    if os_row(oid)["status"] != "Em andamento":
        # a OS pode comecar 'Aberta' e passar a 'Em andamento' ao primeiro lancamento
        add_apontamento(tecnico, oid)
        add_peca(tecnico, oid, "Rolamento 6204", "1")
    assert os_row(oid)["status"] == "Em andamento", "Depois de lancar peca/apontamento a OS deveria estar Em andamento (Figma 17: status Em Andamento)"
    assert equip_status(eqid) == "Em manutenção", "SPEC §3.4"
    fechar_os(tecnico, oid)
    assert equip_status(eqid) == "Ativo"


def test_equipamento_baixado_nao_volta_a_ativo_ao_fechar_os(admin, tecnico):
    eqid = equipamento_id(BOMBA2)
    pid, oid = pedido_com_os(admin, tecnico, equipamento=BOMBA2)
    executa("UPDATE equipamentos SET status='Baixado' WHERE id=?", eqid)
    fechar_os(tecnico, oid)
    assert equip_status(eqid) == "Baixado", "'(a menos que Baixado)' - SPEC §3.4"


def test_duas_os_ativas_no_mesmo_equipamento_mantem_em_manutencao(admin, tecnico):
    eqid = equipamento_id(BOMBA2)
    p1, o1 = pedido_com_os(admin, tecnico, equipamento=BOMBA2)
    p2, o2 = pedido_com_os(admin, tecnico, equipamento=BOMBA2)
    for o in (o1, o2):
        add_apontamento(tecnico, o)
    fechar_os(tecnico, o1)
    if os_row(o2)["status"] == "Em andamento":
        assert equip_status(eqid) == "Em manutenção", "Ainda ha outra OS Em andamento para o equipamento (SPEC §3.4)"
    fechar_os(tecnico, o2)
    assert equip_status(eqid) == "Ativo"


def test_tela_de_equipamentos_reflete_em_manutencao(admin, tecnico):
    pid, oid = pedido_com_os(admin, tecnico, equipamento=BOMBA2)
    add_apontamento(tecnico, oid)
    if os_row(oid)["status"] == "Em andamento":
        t = texto_visivel(html_de(admin.get("/equipamentos?busca=BOMBA 2")))
        assert "Em manutenção" in t


# --------------------------------------------------------------------------------------------- reabrir (SPEC §3.2: opcional, so Administrador)

def _os_concluida_do_fluxo(admin, tecnico):
    pid, oid = pedido_com_os(admin, tecnico, equipamento=BOMBA2)
    add_peca(tecnico, oid, "Rolamento 6204", "2")
    fechar_os(tecnico, oid)
    assert os_row(oid)["status"] == "Concluída"
    return pid, oid


def test_administrador_reabre_os_concluida(admin, tecnico):
    pid, oid = _os_concluida_do_fluxo(admin, tecnico)
    r = post(admin, f"/os/{oid}/reabrir")
    assert r.status_code in (302, 303), f"reabrir -> HTTP {r.status_code}"
    o = os_row(oid)
    assert o["status"] in ("Em andamento", "Aberta") and not o["data_fechamento"]
    assert um("SELECT status FROM pedidos_manutencao WHERE id=?", pid) == "Em andamento", "Pedido volta a Em andamento"
    if o["status"] == "Em andamento":   # regra 4: OS em andamento => equipamento Em manutencao
        assert um("SELECT status FROM equipamentos WHERE descricao='BOMBA 2 (RESFRIADOR)'") == "Em manutenção"
    # e volta a aceitar edicao
    assert_sucesso_post(add_peca(tecnico, oid, "Rolamento 6204", "1"), "peca apos reabrir")


@pytest.mark.parametrize("perfil", ["tecnico", "gestor", "comum"])
def test_so_administrador_reabre_os(admin, tecnico, cliente_de, perfil):
    _, oid = _os_concluida_do_fluxo(admin, tecnico)
    r = post(cliente_de(perfil), f"/os/{oid}/reabrir")
    assert r.status_code == 403, f"{perfil} reabriu OS concluida (HTTP {r.status_code})"
    assert os_row(oid)["status"] == "Concluída"


def test_reabrir_os_que_nao_esta_concluida_nao_muda_nada(admin, tecnico):
    _, oid = pedido_com_os(admin, tecnico, equipamento=BOMBA2)
    antes = os_row(oid)["status"]
    post(admin, f"/os/{oid}/reabrir")
    assert os_row(oid)["status"] == antes
    assert post(admin, "/os/99999999/reabrir").status_code == 404


# --------------------------------------------------------------------------------------------- BUG-008: fechar OS vazia

def test_fechar_os_sem_lancamentos_fecha_e_avisa(admin, tecnico):
    """Decisao do PO: permitido, mas o app avisa (flash 'aviso') que a OS foi fechada sem peca, servico nem apontamento."""
    pid, oid = pedido_com_os(admin, tecnico, equipamento=BOMBA2)
    r = tecnico.post(f"/os/{oid}/fechar", data={"csrf_token": obter_csrf(tecnico, f"/os/{oid}")}, follow_redirects=True)
    assert r.status_code == 200
    assert os_row(oid)["status"] == "Concluída"
    assert um("SELECT status FROM pedidos_manutencao WHERE id=?", pid) == "Concluído"
    h = html_de(r)
    avisos = re.findall(r'class="aviso aviso--(\w+)"[^>]*>.*?aviso__texto">([^<]+)', h, re.S)
    assert any(cat == "aviso" and "sem" in txt.lower() for cat, txt in avisos), f"Esperado flash de aviso de OS vazia: {avisos}"


def test_fechar_os_com_lancamento_nao_mostra_aviso_de_os_vazia(admin, tecnico):
    pid, oid = pedido_com_os(admin, tecnico, equipamento=BOMBA2)
    add_peca(tecnico, oid, "Rolamento 6204", "1")
    r = tecnico.post(f"/os/{oid}/fechar", data={"csrf_token": obter_csrf(tecnico, f"/os/{oid}")}, follow_redirects=True)
    assert "fechada sem peças, serviços ou apontamentos" not in html_de(r)
    assert os_row(oid)["status"] == "Concluída"
