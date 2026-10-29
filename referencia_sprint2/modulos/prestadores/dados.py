"""
modulos/prestadores/dados.py
----------------------------
SQL de prestadores de servico (SB-109): as empresas que EXECUTAM a
manutencao (eletrica, refrigeracao, hidraulica...). Vao aparecer nos
servicos das ordens de servico.

Mesma regra de fornecedores: exclusao LOGICA (ativo = 0), nunca DELETE.
"""

import database

CAMPOS = ["razao_social", "cnpj", "especialidade", "email", "telefone", "contato"]


def listar(busca="", mostrar_inativos=False):
    sql = """
        SELECT * FROM prestadores
         WHERE (razao_social LIKE ? OR IFNULL(especialidade, '') LIKE ? OR cnpj LIKE ?)
    """
    numeros = "".join(c for c in busca if c.isdigit())
    parametros = [f"%{busca}%", f"%{busca}%", f"%{numeros or busca}%"]
    if not mostrar_inativos:
        sql += " AND ativo = 1"
    sql += " ORDER BY ativo DESC, razao_social"
    return database.consultar(sql, parametros)


def buscar(id_prestador):
    return database.consultar_um("SELECT * FROM prestadores WHERE id = ?", (id_prestador,))


def cnpj_em_uso(cnpj, ignorar_id=None):
    linha = database.consultar_um(
        "SELECT id FROM prestadores WHERE cnpj = ? AND id IS NOT ?", (cnpj, ignorar_id)
    )
    return linha is not None


def criar(d):
    return database.executar(
        """
        INSERT INTO prestadores (razao_social, cnpj, especialidade, email, telefone, contato)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        [d[campo] for campo in CAMPOS],
    )


def atualizar(id_prestador, d):
    database.executar(
        """
        UPDATE prestadores
           SET razao_social = ?, cnpj = ?, especialidade = ?, email = ?,
               telefone = ?, contato = ?
         WHERE id = ?
        """,
        [d[campo] for campo in CAMPOS] + [id_prestador],
    )


def definir_ativo(id_prestador, ativo):
    database.executar(
        "UPDATE prestadores SET ativo = ? WHERE id = ?", (1 if ativo else 0, id_prestador)
    )
