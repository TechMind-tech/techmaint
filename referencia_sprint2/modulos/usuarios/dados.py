"""
modulos/usuarios/dados.py
-------------------------
SQL de usuarios, perfis e permissoes (SB-102).

Repare que a senha NUNCA passa por aqui em texto puro: quem chama ja
entrega o `senha_hash` pronto (ver rotas.py).
"""

import database


# ---------------------------------------------------------------------------
# READ
# ---------------------------------------------------------------------------


def listar(busca="", mostrar_inativos=False):
    """Lista usuarios com os nomes dos perfis juntos numa coluna so.

    GROUP_CONCAT junta varias linhas em um texto: 'GESTOR, TECNICO'.
    LEFT JOIN (e nao JOIN) para nao sumir quem ainda nao tem perfil.
    """
    sql = """
        SELECT u.id, u.nome, u.login, u.email, u.ativo, u.data_cadastro,
               GROUP_CONCAT(p.nome, ', ') AS perfis
          FROM usuarios u
          LEFT JOIN usuarios_perfis up ON up.id_usuario = u.id
          LEFT JOIN perfis p           ON p.id = up.id_perfil
         WHERE (u.nome LIKE ? OR u.login LIKE ?)
    """
    parametros = [f"%{busca}%", f"%{busca}%"]
    if not mostrar_inativos:
        sql += " AND u.ativo = 1"
    sql += " GROUP BY u.id ORDER BY u.nome"
    return database.consultar(sql, parametros)


def buscar(id_usuario):
    return database.consultar_um("SELECT * FROM usuarios WHERE id = ?", (id_usuario,))


def buscar_por_login(login):
    # COLLATE NOCASE na tabela: 'Admin' e 'admin' sao o mesmo login.
    return database.consultar_um("SELECT * FROM usuarios WHERE login = ?", (login,))


def perfis_do_usuario(id_usuario):
    """Lista com os NOMES dos perfis: ['GESTOR', 'TECNICO']."""
    linhas = database.consultar(
        """
        SELECT p.nome
          FROM perfis p
          JOIN usuarios_perfis up ON up.id_perfil = p.id
         WHERE up.id_usuario = ?
         ORDER BY p.nome
        """,
        (id_usuario,),
    )
    return [linha["nome"] for linha in linhas]


def permissoes_do_usuario(id_usuario):
    """Conjunto (set) com os codigos de TODAS as permissoes da pessoa,
    somando as de todos os perfis dela. DISTINCT tira as repetidas.

    E aqui que o RBAC acontece: usuario -> perfis -> permissoes.
    """
    linhas = database.consultar(
        """
        SELECT DISTINCT pm.codigo
          FROM usuarios_perfis up
          JOIN perfis_permissoes pp ON pp.id_perfil = up.id_perfil
          JOIN permissoes pm        ON pm.id = pp.id_permissao
         WHERE up.id_usuario = ?
        """,
        (id_usuario,),
    )
    return {linha["codigo"] for linha in linhas}


def listar_perfis():
    return database.consultar("SELECT * FROM perfis ORDER BY id")


def login_em_uso(login, ignorar_id=None):
    linha = database.consultar_um(
        "SELECT id FROM usuarios WHERE login = ? AND id IS NOT ?", (login, ignorar_id)
    )
    return linha is not None


def email_em_uso(email, ignorar_id=None):
    if not email:
        return False
    linha = database.consultar_um(
        "SELECT id FROM usuarios WHERE email = ? AND id IS NOT ?", (email, ignorar_id)
    )
    return linha is not None


def contar_administradores_ativos(ignorar_id=None):
    """Quantos ADMINISTRADORES ativos existem (sem contar `ignorar_id`).
    Serve para nunca deixar o sistema sem nenhum administrador."""
    linha = database.consultar_um(
        """
        SELECT COUNT(*) AS total
          FROM usuarios u
          JOIN usuarios_perfis up ON up.id_usuario = u.id
          JOIN perfis p           ON p.id = up.id_perfil
         WHERE p.nome = 'ADMINISTRADOR' AND u.ativo = 1 AND u.id IS NOT ?
        """,
        (ignorar_id,),
    )
    return linha["total"]


# ---------------------------------------------------------------------------
# CREATE / UPDATE
#
# Usuario e perfis sao gravados JUNTOS, numa transacao so: ou grava tudo,
# ou nao grava nada. O `with conexao:` faz isso sozinho:
#   - terminou sem erro -> commit
#   - deu erro no meio  -> rollback (desfaz o que ja tinha feito)
# Sem isso, poderia sobrar um usuario sem perfil no banco.
# ---------------------------------------------------------------------------


def _gravar_perfis(conexao, id_usuario, nomes_perfis):
    conexao.execute("DELETE FROM usuarios_perfis WHERE id_usuario = ?", (id_usuario,))
    for nome in nomes_perfis:
        conexao.execute(
            """
            INSERT INTO usuarios_perfis (id_usuario, id_perfil)
            SELECT ?, id FROM perfis WHERE nome = ?
            """,
            (id_usuario, nome),
        )


def criar(nome, login, email, senha_hash, nomes_perfis):
    conexao = database.conectar()
    try:
        with conexao:
            cursor = conexao.execute(
                "INSERT INTO usuarios (nome, login, email, senha_hash) VALUES (?, ?, ?, ?)",
                (nome, login, email, senha_hash),
            )
            id_usuario = cursor.lastrowid
            _gravar_perfis(conexao, id_usuario, nomes_perfis)
        return id_usuario
    finally:
        conexao.close()


def atualizar(id_usuario, nome, login, email, nomes_perfis, senha_hash=None):
    """Se `senha_hash` vier None, a senha atual e mantida."""
    conexao = database.conectar()
    try:
        with conexao:
            conexao.execute(
                "UPDATE usuarios SET nome = ?, login = ?, email = ? WHERE id = ?",
                (nome, login, email, id_usuario),
            )
            if senha_hash:
                conexao.execute(
                    "UPDATE usuarios SET senha_hash = ? WHERE id = ?", (senha_hash, id_usuario)
                )
            _gravar_perfis(conexao, id_usuario, nomes_perfis)
    finally:
        conexao.close()


def definir_ativo(id_usuario, ativo):
    """Exclusao LOGICA: usuario nao e apagado, e desativado.
    Assim o historico (quem abriu o pedido, quem fechou a OS) continua."""
    database.executar("UPDATE usuarios SET ativo = ? WHERE id = ?", (1 if ativo else 0, id_usuario))
