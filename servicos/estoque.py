"""
estoque.py (servicos)
---------------------
Regras do estoque de pecas. TODA alteracao de saldo passa por aqui:

    ajustar_saldo()       muda o saldo (pecas.qtde_estoque e estoque_pecas) sem deixar ficar negativo
    registrar_movimento() ajusta o saldo E grava a linha em movimentacao_estoque_pecas
    excluir_movimento()   estorna o efeito de um movimento e o apaga

Quem chama deve estar dentro de `with transacao():` — assim, se algo falhar no meio,
nada fica pela metade.
"""

from servicos.erros import ErroNegocio, EstoqueInsuficiente
from servicos.formatacao import agora_iso, qtd_br

TIPOS = ("Entrada", "Saída")
DOCUMENTOS = ("Nota Fiscal", "Ordem de Serviço", "Pedido Interno")


def arredondar(valor, casas=3):
    return round(float(valor) + 0.0, casas)


def buscar_peca(db, id_peca):
    return db.execute("SELECT * FROM pecas WHERE id = ?", (id_peca,)).fetchone()


def garantir_linha_estoque(db, id_peca):
    """Cria (se faltar) a linha de estoque_pecas e a deixa igual ao cadastro da peca."""
    p = buscar_peca(db, id_peca)
    if p is None:
        return
    db.execute("INSERT OR IGNORE INTO estoque_pecas (id_peca, qtde_atual, estoque_minimo, localizacao) "
               "VALUES (?, ?, ?, 'Almoxarifado')", (id_peca, p["qtde_estoque"], p["estoque_minimo"]))
    db.execute("UPDATE estoque_pecas SET qtde_atual = ?, estoque_minimo = ?, ultima_atualizacao = ? "
               "WHERE id_peca = ?", (p["qtde_estoque"], p["estoque_minimo"], agora_iso(), id_peca))


def ajustar_saldo(db, id_peca, delta):
    """Soma `delta` (negativo = baixa) ao saldo. Levanta EstoqueInsuficiente se ficaria < 0."""
    p = buscar_peca(db, id_peca)
    if p is None:
        raise ErroNegocio("Peça não encontrada.")
    atual = arredondar(p["qtde_estoque"])
    novo = arredondar(atual + delta)
    if novo < 0:
        raise EstoqueInsuficiente(
            f"Estoque insuficiente de “{p['nome']}”: saldo {qtd_br(atual)}, pedido {qtd_br(abs(delta))}.",
            campo="quantidade")
    db.execute("UPDATE pecas SET qtde_estoque = ? WHERE id = ?", (novo, id_peca))
    garantir_linha_estoque(db, id_peca)
    return novo


def registrar_movimento(db, id_peca, tipo, quantidade, valor_unitario=None, documento_origem=None,
                        numero_documento=None, observacao=None, id_usuario=None, id_os=None,
                        id_nota_fiscal=None, data=None):
    """Registra Entrada/Saida: ajusta o saldo e grava o historico. Devolve o id do movimento."""
    if tipo not in TIPOS:
        raise ErroNegocio("Tipo de movimento inválido.", campo="tipo")
    quantidade = arredondar(quantidade)
    if quantidade <= 0:
        raise ErroNegocio("A quantidade deve ser maior que zero.", campo="quantidade")
    peca = buscar_peca(db, id_peca)
    if peca is None:
        raise ErroNegocio("Peça não encontrada.", campo="id_peca")
    if valor_unitario is None:
        valor_unitario = peca["valor_unitario"]
    ajustar_saldo(db, id_peca, quantidade if tipo == "Entrada" else -quantidade)
    cur = db.execute(
        "INSERT INTO movimentacao_estoque_pecas (id_peca, tipo, quantidade, valor_unitario, data, "
        "documento_origem, numero_documento, observacao, id_usuario, id_nota_fiscal, id_os) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (id_peca, tipo, quantidade, round(float(valor_unitario), 2), data or agora_iso(), documento_origem,
         numero_documento, observacao, id_usuario, id_nota_fiscal, id_os))
    return cur.lastrowid


def excluir_movimento(db, id_movimento):
    """Estorna o efeito do movimento no saldo e apaga a linha. Devolve o movimento apagado."""
    m = db.execute("SELECT * FROM movimentacao_estoque_pecas WHERE id = ?", (id_movimento,)).fetchone()
    if m is None:
        raise ErroNegocio("Movimento não encontrado.")
    if m["id_os"] is not None:
        raise ErroNegocio("Este movimento foi gerado por uma Ordem de Serviço. "
                          "Para estornar, altere ou remova a peça na própria OS.")
    delta = -m["quantidade"] if m["tipo"] == "Entrada" else m["quantidade"]
    try:
        ajustar_saldo(db, m["id_peca"], delta)
    except EstoqueInsuficiente:
        raise ErroNegocio("Não é possível excluir: o estorno deixaria o saldo da peça negativo.")
    db.execute("DELETE FROM movimentacao_estoque_pecas WHERE id = ?", (id_movimento,))
    return m


def normalizar_tipo(texto):
    """'entrada', 'ENTRADA', 'saida', 'Saída' -> 'Entrada' / 'Saída' (ou None)."""
    from servicos.formatacao import normalizar
    t = normalizar(texto or "").strip()
    return {"entrada": "Entrada", "saida": "Saída"}.get(t)


def normalizar_documento(texto):
    from servicos.formatacao import normalizar
    t = normalizar(texto or "").strip()
    for doc in DOCUMENTOS:
        if normalizar(doc) == t:
            return doc
    return None
