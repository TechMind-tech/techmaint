"""
fluxo_util.py - atalhos para montar o fluxo Pedido -> OS -> pecas/servicos/apontamentos -> fechamento
(usados por test_pedidos, test_os, test_estoque, test_fluxo_ponta_a_ponta e testes exploratorios).
"""

from helpers import (Bruto, ContratoAusente, consulta, enviar, html_de, linha, post, unico, um)

ALIASES_PEDIDO = {
    "equipamento": ["id_equipamento", "equipamento", "equipamento_id"],
    "departamento": ["id_departamento", "departamento", "departamento_id", "depto"],
    "descricao": ["descricao_problema", "descricao", "problema"],
    "prioridade": ["prioridade"],
}
ALIASES_OS = {
    "pedido": ["id_pedido", "pedido_id", "pedido"],
    "tecnico": ["id_tecnico", "tecnico_id", "tecnico", "responsavel"],
    "observacao": ["observacao", "observacoes", "obs"],
}
ALIASES_OS_PECA = {"peca": ["id_peca", "peca", "peca_id"], "quantidade": ["quantidade", "qtde", "qtd"]}
ALIASES_OS_SERVICO = {
    "descricao": ["descricao_servico", "descricao", "servico"], "valor": ["valor_servico", "valor"],
    "prestador": ["id_prestador", "prestador", "prestador_id"],
}
ALIASES_APONTAMENTO = {
    "data": ["data", "data_apontamento"], "tecnico": ["tecnico", "id_tecnico"],
    "horas": ["horas_trabalhadas", "horas"], "tipo": ["tipo", "tipo_apontamento"], "observacao": ["observacao", "obs"],
}
ALIASES_ESTOQUE = {
    "tipo": ["tipo_movimento", "tipo"], "codigo": ["codigo", "codigo_item"],
    "peca": ["id_peca", "peca", "descricao", "item"], "quantidade": ["quantidade", "qtde", "qtd"],
    "valor": ["valor_unitario", "valor_unit", "valor"], "documento": ["documento_origem", "tipo_documento", "documento"],
    "numero": ["numero_documento", "n_documento", "numero_doc", "numero"], "observacao": ["observacao", "obs"],
}


# ----------------------------------------------------------------------------- consultas

def saldo(peca_id) -> float:
    return float(um("SELECT qtde_estoque FROM pecas WHERE id=?", peca_id))


def peca_id(nome) -> int:
    v = um("SELECT id FROM pecas WHERE nome=?", nome)
    if v is None:
        raise ContratoAusente(f"Peca {nome!r} nao existe no seed")
    return v


def movs(peca_id_):
    return consulta("SELECT * FROM movimentacao_estoque_pecas WHERE id_peca=? ORDER BY id", peca_id_)


def liquido(peca_id_) -> float:
    """Entradas - Saidas registradas para a peca."""
    return sum((float(m["quantidade"]) if m["tipo"] == "Entrada" else -float(m["quantidade"])) for m in movs(peca_id_))


def os_row(os_id):
    return linha("SELECT * FROM ordens_servico WHERE id=?", os_id)


def pedido_row(pid):
    return linha("SELECT * FROM pedidos_manutencao WHERE id=?", pid)


def equip_status(eq_id):
    return um("SELECT status FROM equipamentos WHERE id=?", eq_id)


def equipamento_id(desc):
    return um("SELECT id FROM equipamentos WHERE descricao=?", desc)


# ----------------------------------------------------------------------------- acoes

def criar_pedido(c, *, equipamento="BOMBA 2 (RESFRIADOR)", departamento="Utilidades", descricao=None, prioridade="Média",
                 **extras):
    """Cria pedido pela UI (formulario real) e devolve o id."""
    desc = descricao or f"Problema de teste {unico('ped')}"
    r = enviar(c, "/pedidos/novo", dict(equipamento=equipamento, departamento=departamento, descricao=desc,
                                        prioridade=prioridade, **extras), ALIASES_PEDIDO, estrito=False)
    if r.status_code not in (302, 303):
        raise ContratoAusente(f"Nao consegui abrir pedido pela UI: HTTP {r.status_code}. "
                              f"Trecho: {html_de(r)[:300]!r}")
    pid = um("SELECT id FROM pedidos_manutencao WHERE descricao_problema=? ORDER BY id DESC LIMIT 1", desc)
    if pid is None:
        raise ContratoAusente("Pedido criado (redirect) mas nao encontrado no banco por descricao_problema")
    return pid


def abrir_os(c, pedido_id, tecnico="Maria Técnica", observacao="OS aberta pelo teste"):
    """Botao 'Abrir OS' do pedido (link GET /pedidos/<id>/abrir-os -> formulario /os/nova com o pedido escolhido ->
    POST). Segue o fluxo real da UI. Devolve (resposta, os_id|None)."""
    pagina = f"/pedidos/{pedido_id}/abrir-os"
    r0 = c.get(pagina)
    if r0.status_code in (301, 302, 303, 307, 308):
        pagina = r0.headers["Location"]
    r = enviar(c, pagina, dict(pedido=Bruto(str(pedido_id)), tecnico=tecnico, observacao=observacao), ALIASES_OS, estrito=False)
    return r, um("SELECT id FROM ordens_servico WHERE id_pedido=? ORDER BY id DESC LIMIT 1", pedido_id)


def abrir_os_avulsa(c, tecnico="Maria Técnica", observacao="OS avulsa de teste"):
    antes = um("SELECT COALESCE(MAX(id),0) FROM ordens_servico")
    r = enviar(c, "/os/nova", dict(tecnico=tecnico, observacao=observacao), ALIASES_OS, estrito=False)
    novo = um("SELECT MAX(id) FROM ordens_servico")
    return r, (novo if novo and novo > antes else None)


def pedido_com_os(c_pedido, c_tecnico, **kw):
    """Cria pedido (como c_pedido) e abre a OS (como c_tecnico). Devolve (pedido_id, os_id)."""
    pid = criar_pedido(c_pedido, **kw)
    r, oid = abrir_os(c_tecnico, pid)
    if oid is None:
        raise ContratoAusente(f"Abrir OS do pedido #{pid} nao criou ordem de servico (HTTP {r.status_code}).")
    return pid, oid


def add_peca(c, os_id, peca, qtd, *, seguir=False):
    return enviar(c, f"/os/{os_id}", dict(peca=peca, quantidade=qtd), ALIASES_OS_PECA, estrito=False,
                  action_contem="/pecas", seguir=seguir)


def add_servico(c, os_id, descricao, valor, prestador=None, *, seguir=False):
    d = dict(descricao=descricao, valor=valor)
    if prestador is not None:
        d["prestador"] = prestador
    return enviar(c, f"/os/{os_id}", d, ALIASES_OS_SERVICO, estrito=False, action_contem="/servicos", seguir=seguir)


def add_apontamento(c, os_id, *, data=None, tecnico=None, horas="1,5", tipo="INSPECAO", observacao="apontamento qa"):
    import datetime
    d = dict(data=data or datetime.date.today().isoformat(), horas=horas, tipo=tipo, observacao=observacao)
    if tecnico is not None:
        d["tecnico"] = tecnico
    return enviar(c, f"/os/{os_id}", d, ALIASES_APONTAMENTO, estrito=False, action_contem="/apontamentos")


def fechar_os(c, os_id):
    return post(c, f"/os/{os_id}/fechar")


def item_os(os_id, peca_id_=None):
    if peca_id_ is None:
        return consulta("SELECT * FROM itens_os WHERE id_os=? ORDER BY id", os_id)
    return consulta("SELECT * FROM itens_os WHERE id_os=? AND id_peca=? ORDER BY id", os_id, peca_id_)


def editar_item_os(c, os_id, item_id, qtd):
    return enviar(c, f"/os/{os_id}", dict(quantidade=qtd), ALIASES_OS_PECA, estrito=False,
                  action_contem=f"/pecas/{item_id}/editar")


def excluir_item_os(c, os_id, item_id):
    return post(c, f"/os/{os_id}/pecas/{item_id}/excluir")


def custo_os(os_id) -> float:
    p = um("SELECT COALESCE(SUM(valor_total),0) FROM itens_os WHERE id_os=?", os_id)
    s = um("SELECT COALESCE(SUM(valor_servico),0) FROM servicos_os WHERE id_os=?", os_id)
    return float(p) + float(s)
