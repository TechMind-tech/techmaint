"""
configuracoes.py
----------------
Configuracoes do proprio usuario (todos os perfis): dados do perfil, troca de senha,
idioma e tema.

    /configuracoes   GET, POST   configuracoes.pagina   configuracoes.html

O formulario pode enviar `acao` = perfil | senha | preferencias. Sem `acao`, o servidor
trata o que vier preenchido.
"""

import sqlite3

from flask import Blueprint, flash, g, redirect, render_template, request, url_for

import database
from database import transacao
from servicos import auditoria, seguranca
from servicos.formularios import Form, expandir_erros, montar_valores
from servicos.permissoes import permissao
from servicos.validacoes import erro_email, erro_senha_nova, erro_tamanho

bp = Blueprint("configuracoes", __name__)

IDIOMAS = [
    {"valor": "pt-BR", "rotulo": "Português (Brasil)", "habilitado": True},
    {"valor": "en", "rotulo": "English (em breve)", "habilitado": False},
    {"valor": "es", "rotulo": "Español (en breve)", "habilitado": False},
]
TEMAS = [{"valor": "claro", "rotulo": "Claro"}, {"valor": "escuro", "rotulo": "Escuro"}]


def _contexto(erros=None, valores=None):
    db = database.get_db()
    u = db.execute("SELECT u.nome, u.email, u.login, u.tema, u.idioma, d.nome AS depto FROM usuarios u "
                   "LEFT JOIN departamentos d ON d.id = u.id_departamento WHERE u.id = ?",
                   (g.usuario["id"],)).fetchone()
    perfil = {"nome": u["nome"], "email": u["email"] or "", "login": u["login"], "perfil": g.usuario["perfil"],
              "depto": u["depto"], "tema": u["tema"], "idioma": u["idioma"]}
    if valores is None:
        valores = {"nome": u["nome"], "email": u["email"] or "", "tema": u["tema"], "idioma": u["idioma"]}
    return {"perfil": perfil, "item": perfil, "idiomas": IDIOMAS, "temas": TEMAS, "tema_atual": u["tema"],
            "idioma_atual": u["idioma"], "valores": valores, "erros": expandir_erros(erros or {})}


@bp.route("/configuracoes", methods=["GET", "POST"])
@permissao("configuracoes.ver")
def pagina():
    if request.method == "GET":
        return render_template("configuracoes.html", **_contexto())

    db = database.get_db()
    f = Form(request.form)
    acao = f.get("acao").lower()
    erros, avisos = {}, []
    atual = db.execute("SELECT nome, email, senha_hash FROM usuarios WHERE id = ?", (g.usuario["id"],)).fetchone()

    # --- que secoes foram enviadas? ---
    quer_perfil = acao == "perfil" or (not acao and (f.tem("nome") or f.tem("email")))
    senha_atual = f.get("senha_atual", "", strip=False)
    nova = f.get("nova_senha", "", strip=False)
    confirma = f.get("confirmar_senha", "", strip=False)
    quer_senha = acao == "senha" or (not acao and (senha_atual or nova or confirma))
    quer_prefs = acao in ("preferencias", "preferências", "tema", "idioma") or (not acao and (f.tem("tema") or f.tem("idioma")))

    novo_nome, novo_email = atual["nome"], atual["email"]
    if quer_perfil:
        novo_nome = f.get("nome")
        msg = erro_tamanho(novo_nome, "o nome", 100, obrigatorio=True)
        if msg:
            erros["nome"] = msg
        novo_email = f.get("email") or None
        msg = erro_email(novo_email)
        if msg:
            erros["email"] = msg

    novo_hash = None
    if quer_senha:
        if not senha_atual:
            erros["senha_atual"] = "Informe a senha atual."
        elif not seguranca.conferir_senha(atual["senha_hash"], senha_atual):
            erros["senha_atual"] = "Senha atual incorreta."
        msg = erro_senha_nova(nova)
        if msg:
            erros["nova_senha"] = msg
        elif nova == senha_atual:
            erros["nova_senha"] = "A nova senha deve ser diferente da atual."
        elif nova != confirma:
            erros["confirmar_senha"] = "A confirmação não confere com a nova senha."
        if "senha_atual" not in erros and "nova_senha" not in erros and "confirmar_senha" not in erros:
            novo_hash = seguranca.gerar_hash(nova)

    novo_tema = novo_idioma = None
    if quer_prefs:
        if f.tem("tema"):
            novo_tema = f.get("tema")
            if novo_tema not in [t["valor"] for t in TEMAS]:
                erros["tema"] = "Tema inválido."
        if f.tem("idioma"):
            novo_idioma = f.get("idioma")
            if novo_idioma not in [i["valor"] for i in IDIOMAS if i["habilitado"]]:
                erros["idioma"] = "Idioma indisponível no momento."

    if not (quer_perfil or quer_senha or quer_prefs):
        flash("Nada para salvar.", "info")
        return redirect(url_for("configuracoes.pagina"))
    if erros:
        return render_template("configuracoes.html", **_contexto(erros=erros,
                                                                 valores=montar_valores(request.form, ["nome", "email", "tema", "idioma"])))
    try:
        with transacao(db):
            if quer_perfil:
                db.execute("UPDATE usuarios SET nome = ?, email = ? WHERE id = ?", (novo_nome, novo_email, g.usuario["id"]))
                auditoria.registrar(db, "usuario", g.usuario["id"], "perfil", "Dados do perfil atualizados")
            if novo_hash:
                db.execute("UPDATE usuarios SET senha_hash = ? WHERE id = ?", (novo_hash, g.usuario["id"]))
                auditoria.registrar(db, "usuario", g.usuario["id"], "senha", "Senha alterada pelo próprio usuário")
            if novo_tema:
                db.execute("UPDATE usuarios SET tema = ? WHERE id = ?", (novo_tema, g.usuario["id"]))
            if novo_idioma:
                db.execute("UPDATE usuarios SET idioma = ? WHERE id = ?", (novo_idioma, g.usuario["id"]))
    except sqlite3.IntegrityError:
        flash("Não foi possível salvar as alterações.", "erro")
        return redirect(url_for("configuracoes.pagina"))
    flash("Configurações salvas com sucesso.", "sucesso")
    return redirect(url_for("configuracoes.pagina"))
