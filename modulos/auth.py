"""
auth.py
-------
Login, logout e recuperacao de senha (simulada).

Rotas:
    /login                     GET, POST   login.html
    /logout                    POST        (redireciona para /login)
    /recuperar-senha           GET, POST   recuperar_senha.html
    /redefinir-senha/<token>   GET, POST   redefinir_senha.html

Regras:
- mensagem de erro generica ("Usuário ou senha inválidos."): nao revela se o login existe
- usuario inativo nao entra
- 5 falhas seguidas do mesmo login bloqueiam por 5 minutos
"""

import logging

from flask import Blueprint, current_app, flash, g, redirect, render_template, request, session, url_for

import database
from database import transacao
from servicos import auditoria, seguranca
from servicos.formularios import Form
from servicos.validacoes import erro_senha_nova

bp = Blueprint("auth", __name__)
log = logging.getLogger("techmaint")

MSG_INVALIDO = "Usuário ou senha inválidos."
MSG_VAZIO = "Preencha todos os campos."


HOOK_ULTIMO_LINK = "techmaint_ultimo_link_reset"     # app.extensions[...]: so existe com app.testing = True
HOOK_LINKS = "techmaint_links_reset"                    # idem: {login: link} (todos os links gerados)


@bp.route("/login", methods=["GET", "POST"])
def login():
    proximo = request.values.get("proximo", "")
    if g.usuario is not None and request.method == "GET":
        return redirect(seguranca.proximo_seguro(proximo))

    contexto = {"erro": None, "proximo": proximo if seguranca.proximo_seguro(proximo, "") else "",
                "valores": {"usuario": ""}, "bloqueado": False}
    if request.method == "GET":
        return render_template("login.html", **contexto)

    f = Form(request.form)
    login_digitado = f.get("usuario")
    senha = request.form.get("senha", "")
    contexto["valores"] = {"usuario": login_digitado}
    lembrar = f.booleano("lembrar", False)

    if not login_digitado or not senha:
        contexto["erro"] = MSG_VAZIO
        return render_template("login.html", **contexto)

    db = database.get_db()
    with transacao(db):
        espera = seguranca.segundos_de_bloqueio(db, login_digitado)
        if espera:
            minutos = max(1, -(-espera // 60))
            contexto["erro"] = (f"Muitas tentativas inválidas. Acesso bloqueado temporariamente; "
                                f"tente novamente em {minutos} minuto(s).")
            contexto["bloqueado"] = True
            return render_template("login.html", **contexto)

        u = db.execute("SELECT id, nome, senha_hash, ativo FROM usuarios WHERE login = ?",
                       (login_digitado,)).fetchone()
        senha_ok = seguranca.conferir_senha(u["senha_hash"] if u else None, senha)
        if not (u and senha_ok and u["ativo"]):
            seguranca.registrar_falha(db, login_digitado)
            log.warning("Login recusado para '%s'", login_digitado[:50])
            contexto["erro"] = MSG_INVALIDO
            return render_template("login.html", **contexto)

        seguranca.limpar_falhas(db, login_digitado)
        auditoria.registrar(db, "usuario", u["id"], "login", "Login realizado", usuario=u["nome"])

    # sessao nova (evita "session fixation"): descarta a anterior e cria outra.
    # O token CSRF e mantido: formularios que ja estavam abertos (outra aba) continuam validos.
    token_csrf = session.get("csrf_token")
    session.clear()
    if token_csrf:
        session["csrf_token"] = token_csrf
    session["usuario_id"] = u["id"]
    session.permanent = bool(lembrar)
    return redirect(seguranca.proximo_seguro(proximo))


@bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash("Você saiu do sistema.", "info")
    return redirect(url_for("auth.login"))


@bp.route("/recuperar-senha", methods=["GET", "POST"])
def recuperar_senha():
    contexto = {"enviado": False, "erro": None, "valores": {"usuario": ""}}
    if request.method == "GET":
        return render_template("recuperar_senha.html", **contexto)

    termo = Form(request.form).get("usuario") or Form(request.form).get("email")
    contexto["valores"] = {"usuario": termo}
    if not termo:
        contexto["erro"] = "Informe seu usuário ou e-mail."
        return render_template("recuperar_senha.html", **contexto)

    db = database.get_db()
    with transacao(db):
        u = db.execute("SELECT id, login FROM usuarios WHERE ativo = 1 AND "
                       "(login = ? OR lower(email) = lower(?)) ORDER BY id LIMIT 1", (termo, termo)).fetchone()
        if u:
            token = seguranca.criar_token_recuperacao(db, u["id"])
            link = url_for("auth.redefinir_senha", token=token)
            # Sem e-mail de verdade: o link vai SO para o log do servidor (nunca para a tela).
            log.info("[SIMULADO] Link de redefinição de senha para '%s': %s", u["login"], link)
            if current_app.testing:      # gancho para os testes automatizados; inexistente em producao/dev
                current_app.extensions[HOOK_ULTIMO_LINK] = link
                current_app.extensions.setdefault(HOOK_LINKS, {})[u["login"]] = link
    # Mesma resposta exista o usuario ou nao (nao revelar quem tem conta).
    contexto["enviado"] = True
    return render_template("recuperar_senha.html", **contexto)


@bp.route("/redefinir-senha/<token>", methods=["GET", "POST"])
def redefinir_senha(token):
    db = database.get_db()
    id_usuario = seguranca.usuario_do_token(db, token)
    if id_usuario is None:
        return render_template("redefinir_senha.html", token_invalido=True, erros={}, erro=None), 400
    if request.method == "GET":
        return render_template("redefinir_senha.html", token_invalido=False, erros={}, erro=None)

    f = Form(request.form)
    nova = request.form.get("senha") or f.get("nova_senha", "", strip=False)
    confirma = f.get("confirmar_senha", "", strip=False)
    erros = {}
    msg = erro_senha_nova(nova)
    if msg:
        erros["senha"] = msg
    elif nova != confirma:
        erros["confirmar_senha"] = "A confirmação não confere com a nova senha."
    if erros:
        return render_template("redefinir_senha.html", token_invalido=False, erros=erros,
                               erro=next(iter(erros.values())))

    with transacao(db):
        u = db.execute("SELECT id, login, nome FROM usuarios WHERE id = ?", (id_usuario,)).fetchone()
        db.execute("UPDATE usuarios SET senha_hash = ? WHERE id = ?", (seguranca.gerar_hash(nova), id_usuario))
        seguranca.consumir_token(db, token)
        seguranca.limpar_falhas(db, u["login"])
        auditoria.registrar(db, "usuario", id_usuario, "senha", "Senha redefinida por link de recuperação",
                            usuario=u["nome"])
    session.clear()
    flash("Senha redefinida com sucesso. Entre com a nova senha.", "sucesso")
    return redirect(url_for("auth.login"))
