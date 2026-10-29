"""
seguranca.py
------------
Pecas de seguranca: CSRF, redirecionamento seguro, bloqueio de login e
tokens de recuperacao de senha.
"""

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta
from urllib.parse import urlparse

from flask import request, session
from werkzeug.security import check_password_hash, generate_password_hash

LIMITE_FALHAS = 5          # falhas seguidas para bloquear o login
MINUTOS_BLOQUEIO = 5       # duracao do bloqueio
MINUTOS_TOKEN = 30         # validade do link de redefinicao de senha
FORMATO = "%Y-%m-%d %H:%M:%S"

# Hash "de mentira": conferido quando o login nao existe, para a resposta demorar
# o mesmo tempo (nao revelar se o usuario existe).
_HASH_FALSO = generate_password_hash("senha-que-ninguem-usa")


# ---------------------------------------------------------------------------
# CSRF: um token secreto por sessao, que todo formulario POST precisa devolver.
# Sem isso, outro site poderia enviar um formulario em nome do usuario logado.
# ---------------------------------------------------------------------------
def csrf_token():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)
    return session["csrf_token"]


def csrf_valido():
    enviado = (request.form.get("csrf_token")
               or request.headers.get("X-CSRFToken")
               or request.headers.get("X-CSRF-Token") or "")
    esperado = session.get("csrf_token", "")
    return bool(esperado) and hmac.compare_digest(str(enviado), str(esperado))


# ---------------------------------------------------------------------------
# Redirecionamento seguro (parametro `proximo` do login)
# ---------------------------------------------------------------------------
def proximo_seguro(destino, padrao="/menu"):
    """So aceita caminhos locais ("/os/3"). Bloqueia "http://outro.site", "//outro.site", "/\\x"."""
    d = (destino or "").strip()
    if not d or not d.startswith("/") or d.startswith("//") or "\\" in d:
        return padrao
    if any(ord(c) < 32 for c in d):
        return padrao
    partes = urlparse(d)
    if partes.scheme or partes.netloc:
        return padrao
    if partes.path.startswith("/login") or partes.path.startswith("/logout"):
        return padrao
    return d


# ---------------------------------------------------------------------------
# Senhas
# ---------------------------------------------------------------------------
def gerar_hash(senha):
    return generate_password_hash(senha)


def conferir_senha(hash_guardado, senha):
    """Confere a senha; se nao ha hash (usuario inexistente) gasta o mesmo tempo e falha."""
    if not hash_guardado:
        check_password_hash(_HASH_FALSO, senha or "")
        return False
    try:
        return check_password_hash(hash_guardado, senha or "")
    except (ValueError, TypeError):
        return False


# ---------------------------------------------------------------------------
# Bloqueio por forca bruta (tabela tentativas_login)
# ---------------------------------------------------------------------------
def _chave(login):
    return (login or "").strip().lower()[:50]


def segundos_de_bloqueio(db, login):
    """Quantos segundos faltam para o login ser liberado (0 = livre)."""
    linha = db.execute("SELECT bloqueado_ate FROM tentativas_login WHERE login = ?", (_chave(login),)).fetchone()
    if not linha or not linha["bloqueado_ate"]:
        return 0
    falta = (datetime.strptime(linha["bloqueado_ate"], FORMATO) - datetime.now()).total_seconds()
    if falta <= 0:
        # o bloqueio acabou: zera o contador
        db.execute("DELETE FROM tentativas_login WHERE login = ?", (_chave(login),))
        return 0
    return int(falta) + 1


def registrar_falha(db, login):
    chave = _chave(login)
    db.execute("INSERT OR IGNORE INTO tentativas_login (login, falhas) VALUES (?, 0)", (chave,))
    db.execute("UPDATE tentativas_login SET falhas = falhas + 1 WHERE login = ?", (chave,))
    falhas = db.execute("SELECT falhas FROM tentativas_login WHERE login = ?", (chave,)).fetchone()["falhas"]
    if falhas >= LIMITE_FALHAS:
        ate = (datetime.now() + timedelta(minutes=MINUTOS_BLOQUEIO)).strftime(FORMATO)
        db.execute("UPDATE tentativas_login SET bloqueado_ate = ? WHERE login = ?", (ate, chave))
    return falhas


def limpar_falhas(db, login):
    db.execute("DELETE FROM tentativas_login WHERE login = ?", (_chave(login),))


# ---------------------------------------------------------------------------
# Recuperacao de senha (simulada): so guardamos o HASH do token
# ---------------------------------------------------------------------------
def _hash_token(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def criar_token_recuperacao(db, id_usuario):
    token = secrets.token_urlsafe(32)
    expira = (datetime.now() + timedelta(minutes=MINUTOS_TOKEN)).strftime(FORMATO)
    db.execute("UPDATE tokens_recuperacao SET usado = 1 WHERE id_usuario = ?", (id_usuario,))
    db.execute("INSERT INTO tokens_recuperacao (token_hash, id_usuario, expira_em) VALUES (?, ?, ?)",
               (_hash_token(token), id_usuario, expira))
    return token


def usuario_do_token(db, token):
    """Id do usuario dono de um token valido (nao usado e nao expirado) ou None."""
    linha = db.execute("SELECT id_usuario, expira_em, usado FROM tokens_recuperacao WHERE token_hash = ?",
                       (_hash_token(token or ""),)).fetchone()
    if not linha or linha["usado"]:
        return None
    if datetime.strptime(linha["expira_em"], FORMATO) < datetime.now():
        return None
    return linha["id_usuario"]


def consumir_token(db, token):
    db.execute("UPDATE tokens_recuperacao SET usado = 1 WHERE token_hash = ?", (_hash_token(token or ""),))
