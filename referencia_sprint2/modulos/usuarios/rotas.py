"""
modulos/usuarios/rotas.py
-------------------------
SB-102 - Usuarios com RBAC: login/logout e o CRUD de usuarios.

Blueprint = um "pedaco" do app com as suas proprias rotas. O app.py junta
todos os pedacos com app.register_blueprint(...). Os nomes das rotas ficam
com o nome do blueprint na frente: url_for("usuarios.listar").

Rotas de TELA                          Rotas da API (JSON)
-------------                          -------------------
GET/POST /login                        POST   /api/login
POST     /logout                       POST   /api/logout
GET      /usuarios/                    GET    /api/eu
GET/POST /usuarios/novo                GET    /api/usuarios
GET/POST /usuarios/editar/<id>         POST   /api/usuarios
POST     /usuarios/desativar/<id>      GET    /api/usuarios/<id>
POST     /usuarios/reativar/<id>       PUT    /api/usuarios/<id>
                                       DELETE /api/usuarios/<id>  (desativa)
"""

import re

from flask import (Blueprint, flash, g, jsonify, redirect, render_template,
                   request, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

import api
from seguranca import PERFIS, destino_seguro, requer_login, requer_permissao
from validadores import Validacao

from . import dados

bp = Blueprint("usuarios", __name__)

TAMANHO_MINIMO_SENHA = 8
PADRAO_LOGIN = re.compile(r"^[a-zA-Z0-9._-]{3,50}$")


# ---------------------------------------------------------------------------
# Validacao (usada pela tela E pela API)
# ---------------------------------------------------------------------------


def validar(entrada, perfis_escolhidos, id_usuario=None):
    """Confere os dados de um usuario. `id_usuario` None = criando."""
    criando = id_usuario is None
    v = Validacao(entrada)
    v.texto("nome", obrigatorio=True, maximo=100, rotulo="o nome")
    login = v.texto("login", obrigatorio=True, maximo=50, rotulo="o login")
    email = v.email("email")
    senha = str(entrada.get("senha") or "")

    if login and not PADRAO_LOGIN.match(login):
        v.erro("login", "Login: de 3 a 50 caracteres, so letras, numeros, ponto, - e _.")
    elif login and dados.login_em_uso(login, id_usuario):
        v.erro("login", "Este login ja esta em uso.")

    if email and "email" not in v.erros and dados.email_em_uso(email, id_usuario):
        v.erro("email", "Este e-mail ja esta em uso.")

    # Senha: obrigatoria ao criar; ao editar, vazia = manter a atual.
    if criando and not senha:
        v.erro("senha", "Defina uma senha.")
    elif senha and len(senha) < TAMANHO_MINIMO_SENHA:
        v.erro("senha", f"A senha precisa de pelo menos {TAMANHO_MINIMO_SENHA} caracteres.")

    perfis_escolhidos = [p for p in perfis_escolhidos if p]
    if not perfis_escolhidos:
        v.erro("perfis", "Escolha pelo menos um perfil.")
    elif any(p not in PERFIS for p in perfis_escolhidos):
        v.erro("perfis", "Perfil invalido.")

    # Regra de negocio: o sistema nunca pode ficar sem administrador.
    if (not criando and "ADMINISTRADOR" not in perfis_escolhidos
            and "ADMINISTRADOR" in dados.perfis_do_usuario(id_usuario)
            and dados.contar_administradores_ativos(ignorar_id=id_usuario) == 0):
        v.erro("perfis", "Este e o unico administrador ativo: o perfil ADMINISTRADOR nao pode ser retirado.")

    v.dados["senha"] = senha
    v.dados["perfis"] = perfis_escolhidos
    return v


def perfis_do_json(corpo):
    """Na API, "perfis" deve ser uma lista: ["GESTOR", "TECNICO"].
    Se vier um texto solto ("GESTOR"), aceitamos como lista de um."""
    perfis = corpo.get("perfis")
    if isinstance(perfis, str):
        return [perfis]
    if isinstance(perfis, list):
        return [str(p) for p in perfis]
    return []


def gravar(v, id_usuario=None):
    """Grava no banco o que ja foi validado. Devolve o id."""
    d = v.dados
    # A senha vira HASH aqui. O hash e de mao unica: da para conferir uma
    # senha contra ele, mas nao da para "desfazer" e descobrir a senha.
    senha_hash = generate_password_hash(d["senha"]) if d["senha"] else None
    if id_usuario is None:
        return dados.criar(d["nome"], d["login"], d["email"], senha_hash, d["perfis"])
    dados.atualizar(id_usuario, d["nome"], d["login"], d["email"], d["perfis"], senha_hash)
    return id_usuario


def motivo_para_nao_desativar(id_usuario):
    """Devolve um texto explicando por que nao pode desativar (ou None)."""
    if g.usuario and g.usuario["id"] == id_usuario:
        return "Voce nao pode desativar o proprio usuario."
    if ("ADMINISTRADOR" in dados.perfis_do_usuario(id_usuario)
            and dados.contar_administradores_ativos(ignorar_id=id_usuario) == 0):
        return "Este e o unico administrador ativo e nao pode ser desativado."
    return None


def para_json(usuario):
    """Usuario em formato JSON. NUNCA inclui o senha_hash."""
    return {
        "id": usuario["id"],
        "nome": usuario["nome"],
        "login": usuario["login"],
        "email": usuario["email"],
        "ativo": bool(usuario["ativo"]),
        "data_cadastro": usuario["data_cadastro"],
        "perfis": dados.perfis_do_usuario(usuario["id"]),
    }


def autenticar(login, senha):
    """Devolve o usuario se login e senha baterem (e ele estiver ativo)."""
    usuario = dados.buscar_por_login((login or "").strip())
    if usuario and usuario["ativo"] and check_password_hash(usuario["senha_hash"], senha or ""):
        return usuario
    return None


def iniciar_sessao(usuario):
    # session.clear() antes de logar: joga fora qualquer sessao anterior.
    # Isso evita o ataque de "fixacao de sessao".
    session.clear()
    session["id_usuario"] = usuario["id"]


# ---------------------------------------------------------------------------
# TELAS - login e logout
# ---------------------------------------------------------------------------


@bp.route("/login", methods=["GET", "POST"])
def login():
    destino = destino_seguro(request.args.get("next"))

    if request.method == "POST":
        usuario = autenticar(request.form.get("login"), request.form.get("senha"))
        if usuario is None:
            # Mensagem generica de proposito: nao contamos se o erro foi
            # no login ou na senha (isso ajudaria quem tenta adivinhar).
            flash("Login ou senha incorretos.", "erro")
            return render_template("usuarios/login.html", login=request.form.get("login", "")), 401

        iniciar_sessao(usuario)
        flash(f"Bem-vindo(a), {usuario['nome']}.", "sucesso")
        return redirect(destino or url_for("inicio"))

    if g.usuario:
        return redirect(destino or url_for("inicio"))
    return render_template("usuarios/login.html", login="")


@bp.route("/logout", methods=["POST"])
def logout():
    # POST (e nao link GET) pelo mesmo motivo do apagar: link pode ser
    # aberto sem querer, ou por outro site.
    session.clear()
    flash("Voce saiu do sistema.", "sucesso")
    return redirect(url_for("usuarios.login"))


# ---------------------------------------------------------------------------
# TELAS - CRUD de usuarios
# ---------------------------------------------------------------------------


@bp.route("/usuarios/")
@requer_permissao("usuarios:ver")
def listar():
    busca = request.args.get("busca", "").strip()
    inativos = request.args.get("inativos") == "1"
    usuarios = dados.listar(busca, mostrar_inativos=inativos)
    return render_template("usuarios/listar.html", usuarios=usuarios, busca=busca, inativos=inativos)


@bp.route("/usuarios/novo", methods=["GET", "POST"])
@requer_permissao("usuarios:editar")
def novo():
    if request.method == "POST":
        v = validar(request.form, request.form.getlist("perfis"))
        if v.erros:
            flash("Corrija os campos destacados.", "erro")
            return render_template("usuarios/form.html", titulo="Novo usuario",
                                   item=request.form, perfis_marcados=v.dados["perfis"],
                                   erros=v.erros, perfis=PERFIS), 422
        gravar(v)
        flash("Usuario criado.", "sucesso")
        return redirect(url_for("usuarios.listar"))

    return render_template("usuarios/form.html", titulo="Novo usuario", item=None,
                           perfis_marcados=[], erros={}, perfis=PERFIS)


@bp.route("/usuarios/editar/<int:id_usuario>", methods=["GET", "POST"])
@requer_permissao("usuarios:editar")
def editar(id_usuario):
    usuario = dados.buscar(id_usuario)
    if usuario is None:
        flash("Usuario nao encontrado.", "erro")
        return redirect(url_for("usuarios.listar"))

    if request.method == "POST":
        v = validar(request.form, request.form.getlist("perfis"), id_usuario)
        if v.erros:
            flash("Corrija os campos destacados.", "erro")
            return render_template("usuarios/form.html", titulo="Editar usuario",
                                   item=request.form, perfis_marcados=v.dados["perfis"],
                                   erros=v.erros, perfis=PERFIS, editando=True), 422
        gravar(v, id_usuario)
        flash("Usuario atualizado.", "sucesso")
        return redirect(url_for("usuarios.listar"))

    return render_template("usuarios/form.html", titulo="Editar usuario", item=usuario,
                           perfis_marcados=dados.perfis_do_usuario(id_usuario),
                           erros={}, perfis=PERFIS, editando=True)


@bp.route("/usuarios/desativar/<int:id_usuario>", methods=["POST"])
@requer_permissao("usuarios:editar")
def desativar(id_usuario):
    motivo = motivo_para_nao_desativar(id_usuario)
    if motivo:
        flash(motivo, "erro")
    elif dados.buscar(id_usuario) is None:
        flash("Usuario nao encontrado.", "erro")
    else:
        dados.definir_ativo(id_usuario, False)
        flash("Usuario desativado.", "sucesso")
    return redirect(url_for("usuarios.listar"))


@bp.route("/usuarios/reativar/<int:id_usuario>", methods=["POST"])
@requer_permissao("usuarios:editar")
def reativar(id_usuario):
    if dados.buscar(id_usuario) is None:
        flash("Usuario nao encontrado.", "erro")
    else:
        dados.definir_ativo(id_usuario, True)
        flash("Usuario reativado.", "sucesso")
    return redirect(url_for("usuarios.listar", inativos=1))


# ---------------------------------------------------------------------------
# API JSON
# ---------------------------------------------------------------------------


@bp.route("/api/login", methods=["POST"])
def api_login():
    corpo = api.ler_json()
    usuario = autenticar(corpo.get("login"), corpo.get("senha"))
    if usuario is None:
        return jsonify(erro="Login ou senha incorretos."), 401
    iniciar_sessao(usuario)
    return jsonify(para_json(usuario))


@bp.route("/api/logout", methods=["POST"])
def api_logout():
    session.clear()
    return jsonify(mensagem="Sessao encerrada.")


@bp.route("/api/eu")
@requer_login
def api_eu():
    """Quem sou eu? Devolve o usuario logado e as permissoes dele."""
    resposta = para_json(g.usuario)
    resposta["permissoes"] = sorted(g.permissoes)
    return jsonify(resposta)


@bp.route("/api/usuarios")
@requer_permissao("usuarios:ver")
def api_listar():
    busca = request.args.get("busca", "").strip()
    inativos = request.args.get("inativos") == "1"
    return jsonify([para_json(u) for u in dados.listar(busca, mostrar_inativos=inativos)])


@bp.route("/api/usuarios/<int:id_usuario>")
@requer_permissao("usuarios:ver")
def api_buscar(id_usuario):
    usuario = dados.buscar(id_usuario)
    if usuario is None:
        return api.nao_encontrado("Usuario nao encontrado.")
    return jsonify(para_json(usuario))


@bp.route("/api/usuarios", methods=["POST"])
@requer_permissao("usuarios:editar")
def api_criar():
    corpo = api.ler_json()
    v = validar(corpo, perfis_do_json(corpo))
    if v.erros:
        return api.erro_validacao(v.erros)
    id_usuario = gravar(v)
    return jsonify(para_json(dados.buscar(id_usuario))), 201


@bp.route("/api/usuarios/<int:id_usuario>", methods=["PUT"])
@requer_permissao("usuarios:editar")
def api_atualizar(id_usuario):
    if dados.buscar(id_usuario) is None:
        return api.nao_encontrado("Usuario nao encontrado.")
    corpo = api.ler_json()
    v = validar(corpo, perfis_do_json(corpo), id_usuario)
    if v.erros:
        return api.erro_validacao(v.erros)
    gravar(v, id_usuario)
    return jsonify(para_json(dados.buscar(id_usuario)))


@bp.route("/api/usuarios/<int:id_usuario>", methods=["DELETE"])
@requer_permissao("usuarios:editar")
def api_desativar(id_usuario):
    if dados.buscar(id_usuario) is None:
        return api.nao_encontrado("Usuario nao encontrado.")
    motivo = motivo_para_nao_desativar(id_usuario)
    if motivo:
        return api.conflito(motivo)
    dados.definir_ativo(id_usuario, False)
    return jsonify(para_json(dados.buscar(id_usuario)))
