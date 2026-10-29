"""
modulos/fornecedores/dados.py
-----------------------------
SQL de fornecedores (SB-107).

Fornecedor NUNCA e apagado de verdade: e desativado (ativo = 0). Isso se
chama EXCLUSAO LOGICA. As notas fiscais de compra vao apontar para o
fornecedor; se ele sumisse do banco, o historico de compras quebraria.
"""

import database

CAMPOS = ["razao_social", "nome_fantasia", "cnpj", "email", "telefone", "contato", "endereco"]


def listar(busca="", mostrar_inativos=False):
    sql = """
        SELECT * FROM fornecedores
         WHERE (razao_social LIKE ? OR IFNULL(nome_fantasia, '') LIKE ? OR cnpj LIKE ?)
    """
    # O CNPJ esta salvo so com numeros; tiramos a pontuacao da busca tambem.
    numeros = "".join(c for c in busca if c.isdigit())
    parametros = [f"%{busca}%", f"%{busca}%", f"%{numeros or busca}%"]
    if not mostrar_inativos:
        sql += " AND ativo = 1"
    sql += " ORDER BY ativo DESC, razao_social"
    return database.consultar(sql, parametros)


def buscar(id_fornecedor):
    return database.consultar_um("SELECT * FROM fornecedores WHERE id = ?", (id_fornecedor,))


def cnpj_em_uso(cnpj, ignorar_id=None):
    linha = database.consultar_um(
        "SELECT id FROM fornecedores WHERE cnpj = ? AND id IS NOT ?", (cnpj, ignorar_id)
    )
    return linha is not None


def criar(d):
    return database.executar(
        """
        INSERT INTO fornecedores
               (razao_social, nome_fantasia, cnpj, email, telefone, contato, endereco)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [d[campo] for campo in CAMPOS],
    )


def atualizar(id_fornecedor, d):
    database.executar(
        """
        UPDATE fornecedores
           SET razao_social = ?, nome_fantasia = ?, cnpj = ?, email = ?,
               telefone = ?, contato = ?, endereco = ?
         WHERE id = ?
        """,
        [d[campo] for campo in CAMPOS] + [id_fornecedor],
    )


def definir_ativo(id_fornecedor, ativo):
    database.executar(
        "UPDATE fornecedores SET ativo = ? WHERE id = ?", (1 if ativo else 0, id_fornecedor)
    )
