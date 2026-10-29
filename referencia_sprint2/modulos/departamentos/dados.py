"""
modulos/departamentos/dados.py
------------------------------
SQL de departamentos (SB-103). O modulo mais simples do sistema: e o
melhor lugar para entender o padrao que todos os outros seguem.

    C = Create  -> criar()
    R = Read    -> listar() e buscar()
    U = Update  -> atualizar()
    D = Delete  -> apagar()
"""

import database


def listar(busca=""):
    """Lista os departamentos com a QUANTIDADE de maquinas de cada um.

    LEFT JOIN + COUNT: conta as maquinas; o LEFT garante que departamento
    sem nenhuma maquina tambem aparece (com 0).
    """
    return database.consultar(
        """
        SELECT d.id, d.nome, d.responsavel, COUNT(m.id) AS total_maquinas
          FROM departamentos d
          LEFT JOIN maquinas m ON m.id_departamento = d.id
         WHERE d.nome LIKE ?
         GROUP BY d.id
         ORDER BY d.nome
        """,
        (f"%{busca}%",),
    )


def listar_para_escolha():
    """So id e nome, para montar o <select> no formulario de maquinas."""
    return database.consultar("SELECT id, nome FROM departamentos ORDER BY nome")


def buscar(id_departamento):
    return database.consultar_um("SELECT * FROM departamentos WHERE id = ?", (id_departamento,))


def nome_em_uso(nome, ignorar_id=None):
    # `id IS NOT ?` com None compara com NULL: na criacao nao ignora ninguem.
    linha = database.consultar_um(
        "SELECT id FROM departamentos WHERE nome = ? AND id IS NOT ?", (nome, ignorar_id)
    )
    return linha is not None


def total_maquinas(id_departamento):
    linha = database.consultar_um(
        "SELECT COUNT(*) AS total FROM maquinas WHERE id_departamento = ?", (id_departamento,)
    )
    return linha["total"]


def criar(nome, responsavel):
    return database.executar(
        "INSERT INTO departamentos (nome, responsavel) VALUES (?, ?)", (nome, responsavel)
    )


def atualizar(id_departamento, nome, responsavel):
    # UPDATE sem WHERE altera a tabela inteira. O WHERE e obrigatorio.
    database.executar(
        "UPDATE departamentos SET nome = ?, responsavel = ? WHERE id = ?",
        (nome, responsavel, id_departamento),
    )


def apagar(id_departamento):
    database.executar("DELETE FROM departamentos WHERE id = ?", (id_departamento,))
