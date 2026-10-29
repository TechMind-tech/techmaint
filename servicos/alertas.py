"""
alertas.py (servicos)
---------------------
Alertas do sino do cabecalho (regra 5):
  - pecas com estoque baixo      (qtde_estoque < estoque_minimo)
  - OS atrasadas                 (aberta ha mais de N dias sem fechar; N = parametro `dias_os_atrasada`)
  - pedidos "Aberto" de prioridade Alta ainda sem OS

Devolve {"total": int, "itens": [{"tipo", "texto", "url"}]}. A lista mostra no maximo 20 itens,
mas `total` conta todos.
"""

from datetime import date, timedelta

from flask import url_for

import database
from servicos.formatacao import hoje, qtd_br
from servicos.permissoes import pode, e_perfil, COM

LIMITE_LISTA = 20


def dias_limite_os(db=None):
    try:
        return int(database.parametro_numero("dias_os_atrasada", 7, db))
    except (TypeError, ValueError):
        return 7


def os_atrasadas(db, usuario=None, dias=None):
    """OS ainda abertas ha mais de `dias`. `usuario` (Usuario Comum) restringe as proprias."""
    dias = dias_limite_os(db) if dias is None else dias
    limite = (hoje() - timedelta(days=dias)).isoformat()
    sql = ("SELECT os.id, os.data_abertura FROM ordens_servico os "
           "LEFT JOIN pedidos_manutencao p ON p.id = os.id_pedido "
           "WHERE os.status IN ('Aberta', 'Em andamento') AND substr(os.data_abertura, 1, 10) < ?")
    params = [limite]
    if usuario is not None:
        sql += " AND p.id_usuario_solicitante = ?"
        params.append(usuario["id"])
    return db.execute(sql + " ORDER BY os.data_abertura", params).fetchall()


def pecas_estoque_baixo(db):
    return db.execute("SELECT id, nome, qtde_estoque, estoque_minimo FROM pecas "
                      "WHERE qtde_estoque < estoque_minimo ORDER BY (qtde_estoque - estoque_minimo), nome").fetchall()


def pedidos_alta_sem_os(db):
    return db.execute(
        "SELECT p.id FROM pedidos_manutencao p WHERE p.status = 'Aberto' AND p.prioridade = 'Alta' "
        "AND NOT EXISTS (SELECT 1 FROM ordens_servico os WHERE os.id_pedido = p.id AND os.status <> 'Cancelada') "
        "ORDER BY p.id").fetchall()


def calcular(db, usuario):
    """Alertas visiveis para `usuario` (dict de g.usuario)."""
    itens, total = [], 0
    if usuario is None:
        return {"total": 0, "itens": []}

    if pode("pecas.ver", usuario):
        for p in pecas_estoque_baixo(db):
            total += 1
            itens.append({"tipo": "estoque",
                          "texto": f"Estoque baixo: {p['nome']} ({qtd_br(p['qtde_estoque'])} un.; mínimo {qtd_br(p['estoque_minimo'])})",
                          "url": url_for("pecas.listar", busca=p["nome"])})

    restrito = usuario if e_perfil(COM, usuario=usuario) and not pode("os.gerir", usuario) else None
    if pode("os.ver", usuario):
        for o in os_atrasadas(db, restrito):
            total += 1
            dias = (hoje() - date.fromisoformat(o["data_abertura"][:10])).days
            itens.append({"tipo": "os", "texto": f"OS-{o['id']} aberta há {dias} dias sem fechamento",
                          "url": url_for("ordens.detalhe", id=o["id"])})

    if pode("pedidos.editar", usuario):
        for p in pedidos_alta_sem_os(db):
            total += 1
            itens.append({"tipo": "pedido", "texto": f"Pedido #{p['id']} de prioridade Alta aguardando abertura de OS",
                          "url": url_for("pedidos.detalhe", id=p["id"])})
    return {"total": total, "itens": itens[:LIMITE_LISTA]}
