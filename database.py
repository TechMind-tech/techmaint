"""
database.py
-----------
Tudo que cuida da CONEXAO com o banco (SQLite) mora aqui.

Cada modulo (modulos/*.py) escreve o proprio SQL, sempre com `?` no lugar dos
valores ("query parametrizada"), mas todos abrem o banco por este arquivo.

SQLite e um banco que vive em um arquivo unico. Nao precisa instalar servidor.
O arquivo e definido pela variavel de ambiente TECHMAINT_DB
(padrao: techmaint.db na pasta do projeto).

Ideias principais:
- `get_db()`   : uma conexao por requisicao (fica em `g` e fecha sozinha no fim).
- `transacao()`: agrupa varias escritas — ou grava tudo, ou nao grava nada.
- `init_db()`  : cria as tabelas (schema.sql) e os dados basicos (perfis, permissoes).
"""

import logging
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from flask import current_app, g, has_app_context

from servicos.formatacao import normalizar

log = logging.getLogger("techmaint")

RAIZ = Path(__file__).resolve().parent
ARQUIVO_SCHEMA = RAIZ / "schema.sql"
BANCO_PADRAO = str(RAIZ / "techmaint.db")

# Valores iniciais da tabela `parametros` (podem ser alterados no banco).
PARAMETROS_PADRAO = {
    "meta_os_mes": "20",         # meta de OS concluidas por mes (KPI do dashboard)
    "orcamento_mes": "40000",    # orcamento mensal de manutencao (R$)
    "dias_os_atrasada": "7",     # OS aberta ha mais de N dias vira alerta
}

# Numeracao exibida: pedidos comecam em #1621 e OS em OS-10232 (como no Figma).
SEQUENCIAS_INICIAIS = {"pedidos_manutencao": 1620, "ordens_servico": 10231}


def caminho_banco():
    """Arquivo do banco: config DATABASE > variavel TECHMAINT_DB > padrao."""
    if has_app_context() and current_app.config.get("DATABASE"):
        return str(current_app.config["DATABASE"])
    return os.environ.get("TECHMAINT_DB") or BANCO_PADRAO


def conectar(caminho=None):
    """Abre uma conexao nova.

    - `row_factory = sqlite3.Row`: cada linha vira algo parecido com um dicionario
      (`linha["nome"]`), muito mais legivel que `linha[0]`.
    - `PRAGMA foreign_keys = ON`: o SQLite ignora chaves estrangeiras por padrao;
      ligando, ele impede apagar um registro que outro registro ainda usa.
    - `isolation_level = None`: nos controlamos as transacoes (veja `transacao()`).
    - `norm(texto)`: funcao SQL que tira acentos e maiusculas (busca "balanca" acha "Balança").
    """
    conexao = sqlite3.connect(caminho or caminho_banco(), timeout=15, isolation_level=None)
    conexao.row_factory = sqlite3.Row
    conexao.execute("PRAGMA foreign_keys = ON")
    conexao.execute("PRAGMA busy_timeout = 15000")
    conexao.create_function("norm", 1, normalizar, deterministic=True)
    return conexao


def get_db():
    """Conexao da requisicao atual (criada na primeira chamada)."""
    if "db" not in g:
        g.db = conectar()
    return g.db


def fechar_db(erro=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


@contextmanager
def transacao(db=None):
    """Agrupa escritas: `with transacao(): ...`

    Tudo dentro do `with` e gravado junto (COMMIT) ou desfeito junto (ROLLBACK) se
    ocorrer qualquer erro. `BEGIN IMMEDIATE` ja reserva o direito de escrever, entao
    duas pessoas gravando ao mesmo tempo esperam a vez em vez de se atropelarem
    (importante no estoque: "ler saldo, conferir, baixar" nao pode ser interrompido).
    """
    db = db or get_db()
    if db.in_transaction:        # ja estamos dentro de uma: so reaproveita
        yield db
        return
    db.execute("BEGIN IMMEDIATE")
    try:
        yield db
    except BaseException:
        db.execute("ROLLBACK")
        raise
    else:
        db.execute("COMMIT")


# ---------------------------------------------------------------------------
# Criacao do banco
# ---------------------------------------------------------------------------
def _migrar_legado(db):
    """O CRUD didatico antigo tinha `equipamentos(nome, setor, status)`.

    Se um techmaint.db antigo for encontrado, a tabela e renomeada (nada se perde)
    para que o esquema novo possa ser criado.
    """
    colunas = [r["name"] for r in db.execute("PRAGMA table_info(equipamentos)")]
    if colunas and "codigo" not in colunas:
        db.execute("ALTER TABLE equipamentos RENAME TO equipamentos_legado")
        log.warning("Tabela 'equipamentos' antiga renomeada para 'equipamentos_legado'.")


def init_db(caminho=None):
    """Cria tabelas (se nao existirem) e dados basicos. Pode rodar quantas vezes quiser."""
    from servicos import permissoes

    db = conectar(caminho)
    try:
        _migrar_legado(db)
        db.executescript(ARQUIVO_SCHEMA.read_text(encoding="utf-8"))
        db.execute("PRAGMA foreign_keys = ON")
        with transacao(db):
            # perfis (a ordem define o id: Administrador=1, Tecnico=2, Gestor=3, Usuario Comum=4)
            for nome, descricao in permissoes.PERFIS.items():
                db.execute("INSERT OR IGNORE INTO perfis (nome, descricao) VALUES (?, ?)", (nome, descricao))
            # permissoes e relacao perfil <-> permissao (espelho da matriz em codigo)
            for chave, perfis in permissoes.MATRIZ.items():
                db.execute("INSERT OR IGNORE INTO permissoes (nome, descricao) VALUES (?, ?)",
                           (chave, f"Permissão {chave}"))
                for perfil in perfis:
                    db.execute(
                        "INSERT OR IGNORE INTO perfis_permissoes (id_perfil, id_permissao) "
                        "SELECT p.id, m.id FROM perfis p, permissoes m WHERE p.nome = ? AND m.nome = ?",
                        (perfil, chave))
            for chave, valor in PARAMETROS_PADRAO.items():
                db.execute("INSERT OR IGNORE INTO parametros (chave, valor) VALUES (?, ?)", (chave, valor))
            # numeracao inicial (#1621 / OS-10232) so se a tabela esta vazia e sem sequencia
            for tabela, inicio in SEQUENCIAS_INICIAIS.items():
                ja = db.execute("SELECT 1 FROM sqlite_sequence WHERE name = ?", (tabela,)).fetchone()
                vazia = db.execute(f"SELECT 1 FROM {tabela} LIMIT 1").fetchone() is None  # nome fixo, nao vem do usuario
                if not ja and vazia:
                    db.execute("INSERT INTO sqlite_sequence (name, seq) VALUES (?, ?)", (tabela, inicio))
        db.execute("PRAGMA user_version = 1")
    finally:
        db.close()


def parametro(chave, padrao=None, db=None):
    """Le um valor da tabela `parametros`."""
    db = db or get_db()
    linha = db.execute("SELECT valor FROM parametros WHERE chave = ?", (chave,)).fetchone()
    if linha is None or linha["valor"] is None:
        return padrao if padrao is not None else PARAMETROS_PADRAO.get(chave)
    return linha["valor"]


def parametro_numero(chave, padrao=0, db=None):
    try:
        return float(parametro(chave, str(padrao), db))
    except (TypeError, ValueError):
        return float(padrao)
