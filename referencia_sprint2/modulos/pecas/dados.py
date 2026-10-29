"""
modulos/pecas/dados.py
----------------------
SQL de pecas e do estoque de cada peca (SB-105).

    maquinas 1:N pecas          uma maquina tem varias pecas
    pecas    1:1 estoque_pecas  cada peca tem UMA linha de estoque

Peca e estoque sao gravados JUNTOS, numa transacao so (ver criar()).
"""

import database

# Situacao do estoque, calculada pelo proprio SQL (coluna `situacao`):
SITUACOES = {
    "REPOR": "Repor",        # abaixo do minimo
    "EXCESSO": "Excesso",    # acima do maximo
    "OK": "Normal",
}

# Um pedaco de SQL reaproveitado em varias consultas.
# CASE e o "if" do SQL.
_SITUACAO = """
    CASE
        WHEN e.qtde_atual < e.qtde_minima THEN 'REPOR'
        WHEN e.qtde_atual > e.qtde_maxima THEN 'EXCESSO'
        ELSE 'OK'
    END
"""

_SELECT = f"""
    SELECT p.id, p.nome, p.codigo, p.ncm, p.valor_centavos, p.id_maquina,
           m.nome AS maquina, m.patrimonio,
           e.qtde_atual, e.qtde_minima, e.qtde_maxima, e.local,
           {_SITUACAO} AS situacao,
           -- quanto comprar para voltar ao maximo (so faz sentido se REPOR)
           MAX(e.qtde_maxima - e.qtde_atual, 0) AS sugestao_compra
      FROM pecas p
      JOIN maquinas m      ON m.id = p.id_maquina
      JOIN estoque_pecas e ON e.id_peca = p.id
"""


def listar(busca="", id_maquina=None, so_alerta=False):
    """Lista pecas com o estoque. Os mais criticos aparecem primeiro:
    primeiro quem precisa REPOR, e entre eles quem esta mais longe do minimo.
    """
    sql = _SELECT + " WHERE (p.nome LIKE ? OR IFNULL(p.codigo, '') LIKE ?)"
    parametros = [f"%{busca}%", f"%{busca}%"]
    if id_maquina:
        sql += " AND p.id_maquina = ?"
        parametros.append(id_maquina)
    if so_alerta:
        sql += " AND e.qtde_atual < e.qtde_minima"
    sql += """
        ORDER BY CASE situacao WHEN 'REPOR' THEN 0 WHEN 'EXCESSO' THEN 1 ELSE 2 END,
                 e.qtde_atual * 1.0 / MAX(e.qtde_minima, 1),
                 p.nome
    """
    return database.consultar(sql, parametros)


def buscar(id_peca):
    return database.consultar_um(_SELECT + " WHERE p.id = ?", (id_peca,))


def contar_alertas():
    """Quantas pecas estao abaixo do minimo (usado no painel inicial)."""
    linha = database.consultar_um(
        "SELECT COUNT(*) AS total FROM estoque_pecas WHERE qtde_atual < qtde_minima"
    )
    return linha["total"]


def codigo_em_uso(codigo, ignorar_id=None):
    if not codigo:
        return False
    linha = database.consultar_um(
        "SELECT id FROM pecas WHERE codigo = ? AND id IS NOT ?", (codigo, ignorar_id)
    )
    return linha is not None


def criar(d):
    """Cria a peca E a linha de estoque dela, numa transacao so.

    `with conexao:` = tudo ou nada. Se o INSERT do estoque falhar, o
    INSERT da peca e desfeito (rollback). Nunca sobra peca sem estoque.
    """
    conexao = database.conectar()
    try:
        with conexao:
            cursor = conexao.execute(
                """
                INSERT INTO pecas (nome, codigo, ncm, valor_centavos, id_maquina)
                VALUES (?, ?, ?, ?, ?)
                """,
                (d["nome"], d["codigo"], d["ncm"], d["valor"], d["id_maquina"]),
            )
            id_peca = cursor.lastrowid
            conexao.execute(
                """
                INSERT INTO estoque_pecas (id_peca, qtde_atual, qtde_minima, qtde_maxima, local)
                VALUES (?, ?, ?, ?, ?)
                """,
                (id_peca, d["qtde_atual"], d["qtde_minima"], d["qtde_maxima"], d["local"]),
            )
        return id_peca
    finally:
        conexao.close()


def atualizar(id_peca, d):
    """Atualiza cadastro e limites do estoque.

    A QUANTIDADE ATUAL nao e alterada aqui de proposito: saldo so muda por
    movimentacao (entrada de nota fiscal, baixa na OS, ajuste de inventario),
    que e a proxima etapa do projeto. Assim o saldo sempre tem explicacao.
    """
    conexao = database.conectar()
    try:
        with conexao:
            conexao.execute(
                """
                UPDATE pecas
                   SET nome = ?, codigo = ?, ncm = ?, valor_centavos = ?, id_maquina = ?
                 WHERE id = ?
                """,
                (d["nome"], d["codigo"], d["ncm"], d["valor"], d["id_maquina"], id_peca),
            )
            conexao.execute(
                """
                UPDATE estoque_pecas
                   SET qtde_minima = ?, qtde_maxima = ?, local = ?
                 WHERE id_peca = ?
                """,
                (d["qtde_minima"], d["qtde_maxima"], d["local"], id_peca),
            )
    finally:
        conexao.close()


def apagar(id_peca):
    # O estoque vai junto sozinho: ON DELETE CASCADE no schema.sql.
    database.executar("DELETE FROM pecas WHERE id = ?", (id_peca,))
