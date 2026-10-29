"""
database.py
-----------
Tudo que e GERAL do banco de dados mora aqui: abrir conexao, criar as
tabelas e tres funcoes "atalho" para rodar SQL.

O SQL especifico de cada assunto (maquinas, pecas, usuarios...) fica no
arquivo `dados.py` de cada modulo, dentro de `modulos/`.

SQLite e um banco de dados que vive em um arquivo unico (techmaint.db).
Nao precisa instalar servidor nenhum: ja vem junto com o Python.
"""

import os
import sqlite3

# Nome do arquivo do banco. Ele e criado sozinho na primeira execucao.
# Da para trocar com a variavel de ambiente TECHMAINT_BANCO (os testes
# usam isso para trabalhar num banco descartavel).
NOME_DO_BANCO = os.environ.get("TECHMAINT_BANCO", "techmaint.db")

# Caminho do arquivo com o CREATE TABLE de todas as tabelas.
ARQUIVO_SCHEMA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema.sql")


def conectar():
    """Abre uma conexao com o banco e devolve ela.

    - `row_factory = sqlite3.Row` faz cada linha virar algo parecido com um
      dicionario: voce acessa por nome (`linha["nome"]`), nao por posicao.
    - `PRAGMA foreign_keys = ON` liga a checagem de chave estrangeira.
      No SQLite ela vem DESLIGADA e precisa ser ligada em toda conexao.
      Sem isso, o banco deixaria cadastrar maquina num departamento que
      nao existe.
    """
    conexao = sqlite3.connect(NOME_DO_BANCO)
    conexao.row_factory = sqlite3.Row
    conexao.execute("PRAGMA foreign_keys = ON")
    return conexao


def criar_tabelas():
    """Le o schema.sql e cria as tabelas que ainda nao existirem.

    Roda toda vez que o app sobe. O `IF NOT EXISTS` dentro do schema.sql
    garante que nada seja apagado se a tabela ja estiver la.
    """
    with open(ARQUIVO_SCHEMA, encoding="utf-8") as arquivo:
        script = arquivo.read()
    conexao = conectar()
    # executescript roda varios comandos SQL de uma vez (separados por ;)
    conexao.executescript(script)
    conexao.commit()
    conexao.close()


# ---------------------------------------------------------------------------
# Tres atalhos usados por todos os modulos
#
# Eles fazem sempre o mesmo ritual: conectar -> executar -> (commit) -> fechar.
# Assim o dados.py de cada modulo fica so com o SQL, que e o que importa.
#
# Repare que TODA consulta recebe os valores separados em `parametros` e o
# SQL usa `?` no lugar deles. Isso se chama "query parametrizada" e protege
# contra SQL Injection. Nunca monte SQL com f-string ou com `+`.
# ---------------------------------------------------------------------------


def consultar(sql, parametros=()):
    """SELECT que devolve VARIAS linhas (uma lista, que pode vir vazia)."""
    conexao = conectar()
    linhas = conexao.execute(sql, parametros).fetchall()
    conexao.close()
    return linhas


def consultar_um(sql, parametros=()):
    """SELECT que devolve UMA linha (ou None se nao achar nada)."""
    conexao = conectar()
    linha = conexao.execute(sql, parametros).fetchone()
    conexao.close()
    return linha


def executar(sql, parametros=()):
    """INSERT, UPDATE ou DELETE. Devolve o id da linha inserida.

    `commit` = confirma a gravacao. Sem ele, nada e salvo de verdade.
    Se o banco recusar (ex.: CNPJ repetido, chave estrangeira), o erro
    sqlite3.IntegrityError sobe para quem chamou tratar.
    """
    conexao = conectar()
    try:
        cursor = conexao.execute(sql, parametros)
        conexao.commit()
        return cursor.lastrowid
    finally:
        # `finally` roda SEMPRE, dando erro ou nao: a conexao nunca fica aberta.
        conexao.close()


def para_dicionario(linha):
    """Converte uma linha do banco em dicionario (usado pela API JSON)."""
    return dict(linha) if linha is not None else None
