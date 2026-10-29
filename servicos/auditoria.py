"""
auditoria.py
------------
Log de alteracoes (tabela `historico_alteracoes`): quem fez o que e quando.
Chame `registrar(...)` dentro da mesma transacao da alteracao.
"""

import logging

from flask import g, has_request_context

from servicos.formatacao import agora_iso

log = logging.getLogger("techmaint.auditoria")


def registrar(db, entidade, id_entidade, acao, detalhe=None, usuario=None):
    """Grava uma linha de auditoria. `usuario` padrao = quem esta logado."""
    if usuario is None:
        atual = getattr(g, "usuario", None) if has_request_context() else None
        usuario = atual["nome"] if atual else "sistema"
    detalhe = (detalhe or "")[:500]
    db.execute(
        "INSERT INTO historico_alteracoes (entidade, id_entidade, acao, usuario, data, detalhe) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (entidade, id_entidade, acao, usuario, agora_iso(), detalhe),
    )
    log.info("%s #%s %s por %s %s", entidade, id_entidade, acao, usuario, detalhe)


def historico_de(db, entidade, id_entidade, limite=50):
    """Linhas de auditoria de um registro (mais recentes primeiro), prontas para a tela."""
    from servicos.formatacao import data_hora_br
    linhas = db.execute(
        "SELECT * FROM historico_alteracoes WHERE entidade = ? AND id_entidade = ? "
        "ORDER BY data DESC, id DESC LIMIT ?", (entidade, id_entidade, limite)).fetchall()
    resultado = []
    for r in linhas:
        d = dict(r)
        d["data_fmt"] = data_hora_br(d["data"])
        resultado.append(d)
    return resultado
