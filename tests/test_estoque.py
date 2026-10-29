"""
Movimentacao de Estoque (Manual §2.3, Figma 19, SPEC §3 regra 3, §4 /estoque).

Rastreabilidade: RF "Controle de Estoque: atualizacao automatica, alertas de baixo estoque, historico de consumo"
(Projeto §15b), Manual 2.3 (Tipo Entrada/Saida, Codigo, Descricao, Quantidade, Valor unitario, Documento origem;
Registrar Movimento/Cancelar/Editar/Excluir; historico), SPEC §3.3 (Saida > saldo = erro e nada muda; Entrada nao altera
valor_unitario da peca; excluir movimento estorna saldo se nao ficar negativo), apoio §4 (Documento Origem).
"""

import datetime
import re

import pytest

from fluxo_util import ALIASES_ESTOQUE, liquido, movs, peca_id, saldo
from helpers import (lista_de, Bruto, assert_rejeitado, assert_sucesso_post, coluna, consulta, contar, enviar, executa, formularios, html_de,
                     linha, numero, post, texto_visivel, unico, um)


def registrar(c, tipo="Entrada", peca="Rolamento 6204", qtd="10", valor="15,00", doc="Nota Fiscal", numero_doc="NF-000123", **kw):
    d = dict(tipo=tipo, peca=peca, quantidade=qtd, valor=valor, documento=doc, numero=numero_doc)
    d.update(kw)
    return enviar(c, "/estoque", d, ALIASES_ESTOQUE, estrito=False)


def brl(v):
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


# --------------------------------------------------------------------------------------------- tela

def test_tela_de_estoque(admin):
    r = admin.get("/estoque")
    assert r.status_code == 200
    t = texto_visivel(html_de(r))
    for trecho in ("Movimentação de Estoque", "Registrar Movimento", "Entrada", "Saída", "Quantidade", "Valor Unit",
                   "Tipo de Documento", "Nota Fiscal", "Ordem de Serviço", "Pedido Interno", "Registrar Movimento", "Limpar",
                   "Rolamento 6204"):
        assert trecho.lower() in t.lower(), f"Figma 19: {trecho!r} ausente"


def test_formulario_de_movimento(admin):
    forms = [f for f in formularios(html_de(admin.get("/estoque"))) if f.method == "post" and "csrf_token" in f.nomes]
    f = max(forms, key=lambda x: len(x.campos))
    tipo = next(c for c in f.campos if c.nome and "tipo" in c.nome and "doc" not in c.nome)
    assert tipo.tipo == "radio" and {"Entrada", "Saída"} <= {o["rotulo"] for o in tipo.opcoes}
    assert next(o for o in tipo.opcoes if o["selecionado"])["rotulo"] == "Entrada", "Figma 19: Entrada pre-selecionada"
    doc = next(c for c in f.campos if c.nome and "doc" in c.nome and "numero" not in c.nome and "n_" not in c.nome)
    assert [o["rotulo"] for o in doc.opcoes] == ["Nota Fiscal", "Ordem de Serviço", "Pedido Interno"]
    peca = next(c for c in f.campos if c.nome and ("peca" in c.nome or "descricao" in c.nome))
    assert peca.tag == "select" and len(peca.opcoes) >= 4


def test_cards_de_resumo_batem_com_o_banco(admin):
    mes = datetime.date.today().strftime("%Y-%m")
    ent = float(um("SELECT COALESCE(SUM(quantidade*valor_unitario),0) FROM movimentacao_estoque_pecas WHERE tipo='Entrada' AND substr(data,1,7)=?", mes))
    sai = float(um("SELECT COALESCE(SUM(quantidade*valor_unitario),0) FROM movimentacao_estoque_pecas WHERE tipo='Saída' AND substr(data,1,7)=?", mes))
    t = texto_visivel(html_de(admin.get("/estoque")))
    assert brl(ent) in t, f"Total de entradas do mes deveria ser {brl(ent)} (card 'Total Entradas (mes)')"
    assert brl(sai) in t, f"Total de saidas do mes deveria ser {brl(sai)} (card 'Total Saidas (mes)')"


def test_seed_do_figma_entradas_1390_saidas_54(admin):
    """SPEC §3: 'Movimentacoes (4): total entradas do mes R$ 1.390,00, saidas R$ 54,00 (como no Figma)'."""
    t = texto_visivel(html_de(admin.get("/estoque")))
    assert "R$ 1.390,00" in t and "R$ 54,00" in t, "O seed deveria reproduzir os cards do Figma 19 no mes corrente"


def test_cards_atualizam_apos_registrar(admin):
    def lido():
        t = texto_visivel(html_de(admin.get("/estoque")))
        m = re.search(r"R\$\s?([\d\.]+,\d\d)\s*Total\s+Entradas", t) or re.search(r"Total\s+Entradas[^R]*R\$\s?([\d\.]+,\d\d)", t)
        return numero(m.group(1)) if m else None
    antes = lido()
    registrar(admin, qtd="10", valor="20,00")
    depois = lido()
    assert antes is not None and depois is not None, "Nao consegui ler o card 'Total Entradas'"
    assert round(depois - antes, 2) == 200.00


# --------------------------------------------------------------------------------------------- entrada

def test_registrar_entrada(admin):
    pid = peca_id("Rolamento 6204")
    s0, n0 = saldo(pid), len(movs(pid))
    r = registrar(admin, "Entrada", qtd="10", valor="16,50", doc="Nota Fiscal", numero_doc="NF-777")
    assert_sucesso_post(r, "registrar entrada")
    assert saldo(pid) == s0 + 10
    m = movs(pid)[n0:]
    assert len(m) == 1
    m = m[0]
    assert m["tipo"] == "Entrada" and float(m["quantidade"]) == 10 and float(m["valor_unitario"]) == 16.5
    assert m["documento_origem"] == "Nota Fiscal" and m["numero_documento"] == "NF-777"
    assert m["id_usuario"] == um("SELECT id FROM usuarios WHERE login='admin'")
    assert str(m["data"]).startswith(datetime.date.today().isoformat())


def test_entrada_nao_altera_valor_unitario_da_peca(admin):
    pid = peca_id("Rolamento 6204")
    registrar(admin, "Entrada", qtd="5", valor="99,99")
    assert float(um("SELECT valor_unitario FROM pecas WHERE id=?", pid)) == 15.0, "SPEC §3.3: so registra, nao atualiza o valor da peca"


def test_movimento_aparece_no_historico(admin):
    registrar(admin, "Entrada", numero_doc="NF-HIST-9")
    assert "NF-HIST-9" in texto_visivel(html_de(admin.get("/estoque")))


def test_entrada_tira_a_peca_do_alerta_de_estoque_baixo(admin):
    pid = peca_id("Filtro de Ar")
    assert "Baixo" in texto_visivel(lista_de(html_de(admin.get("/pecas?busca=Filtro"))))
    registrar(admin, "Entrada", peca="Filtro de Ar", qtd="15", valor="32")
    assert saldo(pid) == 45
    assert "Baixo" not in texto_visivel(lista_de(html_de(admin.get("/pecas?busca=Filtro"))))


def test_estoque_pecas_coerente_apos_movimento(admin):
    pid = peca_id("Correia V")
    registrar(admin, "Entrada", peca="Correia V", qtd="7", valor="8")
    registrar(admin, "Saída", peca="Correia V", qtd="3", valor="8", doc="Pedido Interno", numero_doc="PI-1")
    col = coluna("estoque_pecas", "qtde_atual", "saldo", "quantidade")
    assert float(um(f"SELECT {col} FROM estoque_pecas WHERE id_peca=?", pid)) == saldo(pid) == 204


# --------------------------------------------------------------------------------------------- saida

def test_registrar_saida(admin):
    pid = peca_id("Rolamento 6204")
    s0 = saldo(pid)
    r = registrar(admin, "Saída", qtd="20", valor="15", doc="Pedido Interno", numero_doc="PI-001")
    assert_sucesso_post(r, "registrar saida")
    assert saldo(pid) == s0 - 20
    m = movs(pid)[-1]
    assert m["tipo"] == "Saída" and m["documento_origem"] == "Pedido Interno"


def test_saida_maior_que_o_saldo_e_bloqueada_e_nada_muda(admin):
    pid = peca_id("Filtro de Ar")
    s0, n0 = saldo(pid), len(movs(pid))
    r = registrar(admin, "Saída", peca="Filtro de Ar", qtd="31", doc="Pedido Interno", numero_doc="PI-2")
    assert_rejeitado(r, "saida acima do saldo")
    assert saldo(pid) == s0 and len(movs(pid)) == n0, "Saida maior que o saldo: erro e NADA muda (SPEC §3.3)"
    t = texto_visivel(html_de(r)).lower()
    assert "saldo" in t or "insuficiente" in t or "estoque" in t


def test_saida_igual_ao_saldo_zera(admin):
    pid = peca_id("Filtro de Ar")
    assert_sucesso_post(registrar(admin, "Saída", peca="Filtro de Ar", qtd="30", doc="Pedido Interno", numero_doc="PI-3"), "saida total")
    assert saldo(pid) == 0


def test_saida_sucessivas_nao_deixam_saldo_negativo(admin):
    pid = peca_id("Filtro de Ar")
    for _ in range(5):
        registrar(admin, "Saída", peca="Filtro de Ar", qtd="10", doc="Pedido Interno", numero_doc="PI-4")
    assert saldo(pid) == 0, "3 saidas de 10 consomem 30; 4a e 5a devem falhar"
    assert contar("movimentacao_estoque_pecas", "id_peca=? AND numero_documento='PI-4'", pid) == 3, "So 3 saidas cabem no saldo de 30"


# --------------------------------------------------------------------------------------------- validacoes

INVALIDOS = [
    ("quantidade_zero", dict(qtd="0")),
    ("quantidade_negativa", dict(qtd="-5")),
    ("quantidade_texto", dict(qtd="muitos")),
    ("quantidade_vazia", dict(qtd="")),
    ("valor_negativo", dict(valor="-1")),
    ("valor_texto", dict(valor="x")),
    ("peca_inexistente", dict(peca=Bruto("99999"))),
    ("tipo_invalido", dict(tipo=Bruto("Transferencia"))),
    ("documento_invalido", dict(doc=Bruto("Cheque"))),
]


@pytest.mark.parametrize("nome,mudanca", INVALIDOS, ids=[i[0] for i in INVALIDOS])
def test_validacoes_de_movimento(admin, nome, mudanca):
    n = contar("movimentacao_estoque_pecas")
    s = {p["id"]: p["qtde_estoque"] for p in consulta("SELECT id, qtde_estoque FROM pecas")}
    r = registrar(admin, **mudanca)
    assert_rejeitado(r, f"movimento invalido ({nome})")
    assert contar("movimentacao_estoque_pecas") == n
    assert s == {p["id"]: p["qtde_estoque"] for p in consulta("SELECT id, qtde_estoque FROM pecas")}, "O saldo mudou apesar do erro"


def test_valor_zero_e_aceito(admin):
    assert_sucesso_post(registrar(admin, valor="0"), "valor 0 (>= 0)")


def test_quantidade_extrema_nao_quebra(admin):
    for q in ("99999999999999999999", "1e308", "0,0001", "NaN"):
        assert registrar(admin, qtd=q).status_code < 500, f"qtd {q!r}"


def test_numero_documento_longo_e_hostil(admin):
    from helpers import PAYLOADS_HOSTIS
    for b in PAYLOADS_HOSTIS + ["N" * 3000]:
        r = registrar(admin, numero_doc=b)
        assert r.status_code < 500
    assert "<script>alert" not in html_de(admin.get("/estoque"))


def test_form_com_erro_nao_perde_o_digitado(admin):
    r = registrar(admin, qtd="-5", numero_doc="NF-NAO-PERDER")
    assert "NF-NAO-PERDER" in html_de(r)


# --------------------------------------------------------------------------------------------- excluir movimento

def test_excluir_entrada_estorna_o_saldo(admin):
    pid = peca_id("Rolamento 6204")
    s0 = saldo(pid)
    registrar(admin, "Entrada", qtd="10")
    mid = movs(pid)[-1]["id"]
    assert saldo(pid) == s0 + 10
    r = post(admin, f"/estoque/{mid}/excluir")
    assert_sucesso_post(r, "excluir movimento")
    assert saldo(pid) == s0, "Excluir movimento estorna o saldo (SPEC §3.3)"
    assert linha("SELECT * FROM movimentacao_estoque_pecas WHERE id=?", mid) is None


def test_excluir_saida_devolve_ao_saldo(admin):
    pid = peca_id("Rolamento 6204")
    s0 = saldo(pid)
    registrar(admin, "Saída", qtd="10", doc="Pedido Interno", numero_doc="PI-9")
    mid = movs(pid)[-1]["id"]
    post(admin, f"/estoque/{mid}/excluir")
    assert saldo(pid) == s0


def test_excluir_entrada_que_deixaria_saldo_negativo_e_bloqueado(admin):
    pid = peca_id("Filtro de Ar")   # saldo 30
    registrar(admin, "Entrada", peca="Filtro de Ar", qtd="10", valor="32")      # 40
    mid = movs(pid)[-1]["id"]
    registrar(admin, "Saída", peca="Filtro de Ar", qtd="40", doc="Pedido Interno", numero_doc="PI-10")   # 0
    assert saldo(pid) == 0
    r = post(admin, f"/estoque/{mid}/excluir")
    assert r.status_code < 500
    assert saldo(pid) >= 0, "Estorno deixou saldo NEGATIVO (SPEC §3.3: so estorna se nao ficar negativo)"
    assert linha("SELECT * FROM movimentacao_estoque_pecas WHERE id=?", mid) is not None, "Movimento deveria permanecer"


def test_excluir_movimento_inexistente(admin):
    assert post(admin, "/estoque/999999/excluir").status_code in (404, 302, 303)


def test_excluir_so_por_post(admin):
    mid = um("SELECT id FROM movimentacao_estoque_pecas LIMIT 1")
    assert admin.get(f"/estoque/{mid}/excluir").status_code == 405


def test_excluir_movimento_gerado_pela_os_nao_deixa_item_inconsistente(admin, tecnico):
    from fluxo_util import add_peca, pedido_com_os, item_os
    pid_ped, oid = pedido_com_os(admin, tecnico)
    pid = peca_id("Sensor Indutivo")
    add_peca(tecnico, oid, "Sensor Indutivo", "3")
    mid = movs(pid)[-1]["id"]
    s = saldo(pid)
    r = post(admin, f"/estoque/{mid}/excluir")
    assert r.status_code < 500
    # Ou bloqueia (saldo e itens intactos) ou mantem a coerencia item x saldo x historico.
    if linha("SELECT * FROM movimentacao_estoque_pecas WHERE id=?", mid):
        assert saldo(pid) == s
    else:
        assert saldo(pid) == s + 3 and item_os(oid, pid), \
            "Excluir a Saida gerada pela OS devolveu estoque mas o item continua na OS (inconsistencia). Deveria bloquear."


# --------------------------------------------------------------------------------------------- filtros

def test_filtro_por_tipo(admin):
    registrar(admin, "Entrada", numero_doc="NF-FILTRO-ENT")
    registrar(admin, "Saída", qtd="1", doc="Pedido Interno", numero_doc="PI-FILTRO-SAI")
    ok = False
    for nome in ("tipo", "filtro_tipo", "tipo_movimento"):
        h = html_de(admin.get(f"/estoque?{nome}=Entrada"))
        if "NF-FILTRO-ENT" in h and "PI-FILTRO-SAI" not in h:
            ok = True
            break
    assert ok, "Filtro por tipo (SPEC §4: filtros tipo, busca, periodo) nao funcionou"


def test_busca_no_historico(admin):
    registrar(admin, numero_doc="NF-BUSCA-UNICA")
    h = html_de(admin.get("/estoque?busca=BUSCA-UNICA"))
    assert "NF-BUSCA-UNICA" in h
    h2 = html_de(admin.get("/estoque?busca=Sensor"))
    assert "NF-BUSCA-UNICA" not in h2 or "Rolamento" not in h2


def test_filtro_por_periodo(admin):
    mid = um("SELECT id FROM movimentacao_estoque_pecas ORDER BY id LIMIT 1")
    executa("UPDATE movimentacao_estoque_pecas SET data=?, numero_documento='NF-VELHO' WHERE id=?",
            (datetime.date.today() - datetime.timedelta(days=200)).isoformat() + " 10:00:00", mid)
    registrar(admin, numero_doc="NF-NOVO-HOJE")
    for nome, val in (("periodo", "7d"), ("periodo", "30d")):
        h = html_de(admin.get(f"/estoque?{nome}={val}"))
        assert "NF-NOVO-HOJE" in h and "NF-VELHO" not in h, f"periodo={val} nao filtrou (SPEC §4)"
    h = html_de(admin.get("/estoque?periodo=12m"))
    assert "NF-VELHO" in h


def test_filtros_invalidos_nao_quebram(admin):
    for qs in ("tipo=Foo", "periodo=zzz", "busca=%27", "periodo=-1"):
        assert admin.get("/estoque?" + qs).status_code < 500


# --------------------------------------------------------------------------------------------- permissoes

def test_gestor_so_ve_estoque(gestor):
    r = gestor.get("/estoque")
    assert r.status_code == 200
    h = html_de(gestor.get("/estoque"))
    assert "Registrar Movimento" not in texto_visivel(h), "Gestor so 'ver' (SPEC §2): sem formulario de registro"
    assert "/excluir" not in h


def test_tecnico_registra_movimento(tecnico):
    assert_sucesso_post(registrar(tecnico), "tecnico registra (SPEC §2: tudo)")
