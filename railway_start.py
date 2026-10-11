"""
railway_start.py
----------------
Ponto de entrada para publicar o TechMaint no Railway (ou em qualquer PaaS).

O que faz, nesta ordem:
  1. Cria as tabelas e, se o banco estiver VAZIO, roda o seed de demonstracao.
  2. Na primeira vez, troca as senhas de demonstracao:
       - admin  -> senha vinda da variavel TECHMAINT_SENHA_ADMIN (obrigatoria)
       - demais -> senhas aleatorias que ninguem conhece (use a tela de Usuarios
                   para redefinir quando precisar)
  3. Sobe o gunicorn escutando em 0.0.0.0:$PORT.

Variaveis de ambiente:
  TECHMAINT_DB             caminho do SQLite (ex.: /data/techmaint.db, num Volume)
  TECHMAINT_SECRET_KEY     chave da sessao (obrigatoria)
  TECHMAINT_SENHA_ADMIN    senha inicial do usuario "admin" (obrigatoria na 1a vez)
  TECHMAINT_COOKIE_SEGURO  use 1 (o Railway serve em HTTPS)
  PORT                     o Railway define sozinho
"""

import os
import secrets
import sqlite3
import sys

from werkzeug.security import generate_password_hash

import database


def banco_vazio(caminho):
    if not os.path.exists(caminho):
        return True
    con = sqlite3.connect(caminho)
    try:
        return con.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0] == 0
    except sqlite3.OperationalError:
        return True
    finally:
        con.close()


def preparar_banco():
    caminho = os.environ.get("TECHMAINT_DB", "techmaint.db")
    pasta = os.path.dirname(os.path.abspath(caminho))
    os.makedirs(pasta, exist_ok=True)

    if not banco_vazio(caminho):
        print("[railway_start] Banco ja populado: nada a fazer.", flush=True)
        return

    senha_admin = os.environ.get("TECHMAINT_SENHA_ADMIN", "")
    if len(senha_admin) < 10:
        sys.exit("[railway_start] Defina TECHMAINT_SENHA_ADMIN (minimo 10 caracteres) antes do primeiro deploy.")

    print("[railway_start] Banco vazio: criando tabelas e dados de demonstracao...", flush=True)
    import seed
    seed.main([])

    con = sqlite3.connect(caminho)
    for id_, login in con.execute("SELECT id, login FROM usuarios").fetchall():
        senha = senha_admin if login == "admin" else secrets.token_urlsafe(24)
        con.execute("UPDATE usuarios SET senha_hash = ? WHERE id = ?", (generate_password_hash(senha), id_))
    con.commit()
    con.close()
    print("[railway_start] Senhas de demonstracao substituidas (admin usa TECHMAINT_SENHA_ADMIN).", flush=True)


if __name__ == "__main__":
    if not os.environ.get("TECHMAINT_SECRET_KEY"):
        sys.exit("[railway_start] Defina TECHMAINT_SECRET_KEY.")
    preparar_banco()
    porta = os.environ.get("PORT", "8000")
    os.execvp("gunicorn", ["gunicorn", "app:app", "--bind", f"0.0.0.0:{porta}",
                           "--workers", "2", "--timeout", "60", "--access-logfile", "-"])
