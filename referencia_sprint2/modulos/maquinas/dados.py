"""
modulos/maquinas/dados.py
-------------------------
SQL de maquinas (SB-103). Toda maquina pertence a UM departamento:
departamentos 1:N maquinas.
"""

import database

# Os status possiveis. A CHAVE vai para o banco; o VALOR aparece na tela.
# Ficam aqui (e no CHECK do schema.sql) para nunca escrever a string solta.
STATUS = {
    "OPERANDO": "Operando",
    "EM_MANUTENCAO": "Em manutencao",
    "PARADO": "Parado",
}


def listar(busca="", id_departamento=None, status=None):
    """Lista maquinas com o NOME do departamento (JOIN) e o total de pecas.

    Os filtros sao opcionais. Repare como o SQL vai sendo montado aos
    pedacos, mas os VALORES continuam indo separados em `parametros`.
    """
    sql = """
        SELECT m.*, d.nome AS departamento,
               (SELECT COUNT(*) FROM pecas p WHERE p.id_maquina = m.id) AS total_pecas
          FROM maquinas m
          JOIN departamentos d ON d.id = m.id_departamento
         WHERE (m.nome LIKE ? OR IFNULL(m.patrimonio, '') LIKE ?)
    """
    parametros = [f"%{busca}%", f"%{busca}%"]
    if id_departamento:
        sql += " AND m.id_departamento = ?"
        parametros.append(id_departamento)
    if status:
        sql += " AND m.status = ?"
        parametros.append(status)
    sql += " ORDER BY m.nome"
    return database.consultar(sql, parametros)


def listar_para_escolha():
    """id, nome e patrimonio, para o <select> do formulario de pecas."""
    return database.consultar("SELECT id, nome, patrimonio FROM maquinas ORDER BY nome")


def buscar(id_maquina):
    return database.consultar_um(
        """
        SELECT m.*, d.nome AS departamento
          FROM maquinas m
          JOIN departamentos d ON d.id = m.id_departamento
         WHERE m.id = ?
        """,
        (id_maquina,),
    )


def patrimonio_em_uso(patrimonio, ignorar_id=None):
    if not patrimonio:
        return False
    linha = database.consultar_um(
        "SELECT id FROM maquinas WHERE patrimonio = ? AND id IS NOT ?", (patrimonio, ignorar_id)
    )
    return linha is not None


def total_pecas(id_maquina):
    linha = database.consultar_um(
        "SELECT COUNT(*) AS total FROM pecas WHERE id_maquina = ?", (id_maquina,)
    )
    return linha["total"]


def criar(d):
    """`d` e o dicionario ja validado (v.dados no rotas.py)."""
    return database.executar(
        """
        INSERT INTO maquinas (nome, patrimonio, fabricante, modelo, id_departamento, status)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (d["nome"], d["patrimonio"], d["fabricante"], d["modelo"], d["id_departamento"], d["status"]),
    )


def atualizar(id_maquina, d):
    database.executar(
        """
        UPDATE maquinas
           SET nome = ?, patrimonio = ?, fabricante = ?, modelo = ?,
               id_departamento = ?, status = ?
         WHERE id = ?
        """,
        (d["nome"], d["patrimonio"], d["fabricante"], d["modelo"], d["id_departamento"],
         d["status"], id_maquina),
    )


def apagar(id_maquina):
    database.executar("DELETE FROM maquinas WHERE id = ?", (id_maquina,))
