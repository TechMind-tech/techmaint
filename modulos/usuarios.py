"""
usuarios.py
-----------
Cadastro de Usuarios e Perfis (so Administrador).

    /usuarios                GET (lista + formulario), POST (criar)      usuarios.listar / usuarios.criar
    /usuarios/<id>/editar    GET, POST                                   usuarios.editar
    /usuarios/<id>/excluir   POST                                        usuarios.excluir

Regras: login unico (sem diferenciar maiusculas), senha >= 8 caracteres ao cadastrar,
e-mail valido, nao se pode apagar/inativar a si mesmo nem o ultimo administrador.
Usuario com vinculos (pedidos, OS, movimentacoes) e INATIVADO em vez de excluido.
"""

import sqlite3

from flask import Blueprint, flash, g, redirect, render_template, request, url_for

import database
from database import transacao
from modulos._comum import flash_erro, ou_404
from servicos import auditoria, seguranca
from servicos.consultas import (ListaDict, contar_vinculos, filtro_busca, inteiro_ou_none, ordenacao,
                                paginacao)
from servicos.erros import ErroNegocio
from servicos.formatacao import data_br, data_iso, hoje_iso, iniciais, parse_data
from servicos.formularios import Form, expandir_erros, montar_valores
from servicos.permissoes import ADM, PERFIS, permissao
from servicos.validacoes import erro_email, erro_login, erro_senha_nova, erro_tamanho

bp = Blueprint("usuarios", __name__)

CAMPOS = ["nome", "login", "senha", "email", "id_perfil", "id_departamento", "ativo", "data_cadastro"]

SELECT_USUARIO = """
    SELECT u.id, u.nome, u.login, u.email, u.ativo, u.data_cadastro, u.id_departamento,
           d.nome AS departamento,
           (SELECT p.id   FROM usuarios_perfis up JOIN perfis p ON p.id = up.id_perfil
             WHERE up.id_usuario = u.id ORDER BY p.id LIMIT 1) AS id_perfil,
           (SELECT p.nome FROM usuarios_perfis up JOIN perfis p ON p.id = up.id_perfil
             WHERE up.id_usuario = u.id ORDER BY p.id LIMIT 1) AS perfil
    FROM usuarios u LEFT JOIN departamentos d ON d.id = u.id_departamento
"""


def _preparar(linha):
    """Linha do banco -> dict com campos prontos para a tela."""
    u = dict(linha)
    u["ativo"] = bool(u["ativo"])
    u["status"] = "Ativo" if u["ativo"] else "Inativo"
    u["data_cadastro_fmt"] = data_br(u["data_cadastro"])
    u["data_cadastro_iso"] = data_iso(u["data_cadastro"])
    u["data_cadastro"] = u["data_cadastro_iso"]          # o <input type="date"> exige AAAA-MM-DD
    u["iniciais"] = iniciais(u["nome"])
    # apelidos usados por alguns formularios
    u["perfil_id"] = u["id_perfil"]
    u["departamento_id"] = u["id_departamento"]
    return u


def _perfis(db):
    return [dict(p) for p in db.execute("SELECT id, nome, descricao FROM perfis ORDER BY id")]


def _departamentos(db):
    return [dict(d) for d in db.execute("SELECT id, nome FROM departamentos ORDER BY nome")]


def _contagem_perfis(db):
    linhas = db.execute(
        "SELECT p.id, p.nome, (SELECT COUNT(*) FROM usuarios_perfis up JOIN usuarios u ON u.id = up.id_usuario "
        "WHERE up.id_perfil = p.id AND u.ativo = 1) AS total FROM perfis p ORDER BY p.id").fetchall()
    return ListaDict([{"nome": l["nome"], "perfil": l["nome"], "total": l["total"], "id": l["id"]} for l in linhas])


def _contexto(item=None, erros=None, valores=None):
    """Monta tudo que usuarios.html precisa (lista + formulario)."""
    db = database.get_db()
    busca = request.args.get("busca", "").strip()
    filtro_perfil = (request.args.get("perfil") or request.args.get("filtro_perfil")
                     or request.args.get("id_perfil") or "").strip()
    if filtro_perfil.lower() in ("todos", "todas"):
        filtro_perfil = ""

    onde, params = [], []
    trecho, ps = filtro_busca(busca, ["u.nome", "u.login", "u.email"])
    if trecho:
        onde.append(trecho)
        params += ps
    if filtro_perfil:
        onde.append("EXISTS (SELECT 1 FROM usuarios_perfis up JOIN perfis p ON p.id = up.id_perfil "
                    "WHERE up.id_usuario = u.id AND (p.id = ? OR p.nome = ?))")
        params += [inteiro_ou_none(filtro_perfil) or -1, filtro_perfil]
    where = (" WHERE " + " AND ".join(onde)) if onde else ""

    total = db.execute("SELECT COUNT(*) FROM usuarios u" + where, params).fetchone()[0]
    pag = paginacao(request.args, total)
    ordem = ordenacao(request.args, {"id": "u.id", "nome": "u.nome", "login": "u.login", "perfil": "perfil",
                                     "cadastro": "u.data_cadastro"}, "u.id")
    linhas = db.execute(SELECT_USUARIO + where + f" ORDER BY {ordem} LIMIT ? OFFSET ?",   # `ordem` vem de whitelist
                        params + [pag["limite"], pag["deslocamento"]]).fetchall()
    ctx = {
        "itens": [_preparar(l) for l in linhas], "item": item, "perfis": _perfis(db),
        "departamentos": _departamentos(db), "contagem_perfis": _contagem_perfis(db),
        "filtro_perfil": filtro_perfil, "busca": busca, "erros": expandir_erros(erros or {}),
        "valores": valores, "total": total, "paginacao": pag,
    }
    ctx.update({k: pag[k] for k in ("pagina", "por_pagina", "total_paginas")})
    return ctx


def _admins_ativos_restantes(db, ignorar_id):
    """Quantos administradores ativos existem alem de `ignorar_id`."""
    return db.execute(
        "SELECT COUNT(*) FROM usuarios u JOIN usuarios_perfis up ON up.id_usuario = u.id "
        "JOIN perfis p ON p.id = up.id_perfil WHERE p.nome = ? AND u.ativo = 1 AND u.id <> ?",
        (ADM, ignorar_id)).fetchone()[0]


def _validar(db, f, id_atual=None):
    """Valida o formulario. Devolve (dados_limpos, erros)."""
    erros = {}
    nome = f.get("nome")
    msg = erro_tamanho(nome, "o nome", 100, obrigatorio=True)
    if msg:
        erros["nome"] = msg

    login = f.get("login")
    msg = erro_login(login)
    if msg:
        erros["login"] = msg
    else:
        outro = db.execute("SELECT id FROM usuarios WHERE login = ? AND id <> ?", (login, id_atual or -1)).fetchone()
        if outro:
            erros["login"] = "Este login já está em uso."

    email = f.get("email")
    msg = erro_email(email)
    if msg:
        erros["email"] = msg

    senha = f.get("senha", "", strip=False)
    if id_atual is None or senha:
        msg = erro_senha_nova(senha)
        if msg:
            erros["senha"] = msg

    id_perfil = inteiro_ou_none(f.get("id_perfil"))
    if id_perfil is None:
        erros["id_perfil"] = "Selecione o perfil de acesso."
    elif db.execute("SELECT 1 FROM perfis WHERE id = ?", (id_perfil,)).fetchone() is None:
        erros["id_perfil"] = "Perfil inválido."

    id_depto = None
    if f.get("id_departamento"):
        id_depto = inteiro_ou_none(f.get("id_departamento"))
        if id_depto is None or db.execute("SELECT 1 FROM departamentos WHERE id = ?", (id_depto,)).fetchone() is None:
            erros["id_departamento"] = "Departamento inválido."

    data_cad = None
    if f.get("data_cadastro"):
        d = parse_data(f.get("data_cadastro"))
        if d is None:
            erros["data_cadastro"] = "Data de cadastro inválida."
        else:
            data_cad = d.isoformat()

    return {"nome": nome, "login": login, "email": email or None, "senha": senha, "id_perfil": id_perfil,
            "id_departamento": id_depto, "data_cadastro": data_cad}, erros


@bp.route("/usuarios", methods=["GET", "POST"])
@permissao("usuarios.gerir")
def listar():
    if request.method == "GET":
        return render_template("usuarios.html", **_contexto())

    db = database.get_db()
    f = Form(request.form)
    dados, erros = _validar(db, f)
    if erros:
        return render_template("usuarios.html", **_contexto(erros=erros, valores=montar_valores(request.form, CAMPOS)))

    ativo = 1 if f.booleano("ativo", False) else 0
    try:
        with transacao(db):
            cur = db.execute(
                "INSERT INTO usuarios (nome, login, senha_hash, email, ativo, data_cadastro, id_departamento) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (dados["nome"], dados["login"], seguranca.gerar_hash(dados["senha"]), dados["email"], ativo,
                 (dados["data_cadastro"] or hoje_iso()) + " 00:00:00", dados["id_departamento"]))
            db.execute("INSERT INTO usuarios_perfis (id_usuario, id_perfil) VALUES (?, ?)",
                       (cur.lastrowid, dados["id_perfil"]))
            auditoria.registrar(db, "usuario", cur.lastrowid, "criar", f"Usuário {dados['login']} criado")
    except sqlite3.IntegrityError:        # corrida: outro admin criou o mesmo login agora
        erros = {"login": "Este login já está em uso."}
        return render_template("usuarios.html", **_contexto(erros=erros, valores=montar_valores(request.form, CAMPOS)))
    flash("Usuário cadastrado com sucesso.", "sucesso")
    return redirect(url_for("usuarios.listar"))


bp.add_url_rule("/usuarios", endpoint="criar", view_func=listar, methods=["POST"])


@bp.route("/usuarios/<int:id>/editar", methods=["GET", "POST"])
@permissao("usuarios.gerir")
def editar(id):
    db = database.get_db()
    atual = _preparar(ou_404(db.execute(SELECT_USUARIO + " WHERE u.id = ?", (id,)).fetchone()))
    if request.method == "GET":
        return render_template("usuarios.html", **_contexto(item=atual))

    f = Form(request.form)
    dados, erros = _validar(db, f, id_atual=id)
    ativo = 1 if f.booleano("ativo", False) else 0

    # protecoes: nao se trancar para fora do sistema
    if not erros:
        sai_de_admin = atual["perfil"] == ADM and (ativo == 0 or dados["id_perfil"] != atual["id_perfil"])
        if id == g.usuario["id"] and ativo == 0:
            erros["ativo"] = "Você não pode inativar o seu próprio usuário."
        elif sai_de_admin and _admins_ativos_restantes(db, id) == 0:
            erros["id_perfil" if dados["id_perfil"] != atual["id_perfil"] else "ativo"] = \
                "Deve existir pelo menos um administrador ativo."
    if erros:
        return render_template("usuarios.html", **_contexto(item=atual, erros=erros,
                                                            valores=montar_valores(request.form, CAMPOS)))
    try:
        with transacao(db):
            db.execute("UPDATE usuarios SET nome = ?, login = ?, email = ?, ativo = ?, id_departamento = ?, "
                       "data_cadastro = COALESCE(?, data_cadastro) WHERE id = ?",
                       (dados["nome"], dados["login"], dados["email"], ativo, dados["id_departamento"],
                        (dados["data_cadastro"] + " 00:00:00") if dados["data_cadastro"] else None, id))
            if dados["senha"]:
                db.execute("UPDATE usuarios SET senha_hash = ? WHERE id = ?", (seguranca.gerar_hash(dados["senha"]), id))
            if dados["id_perfil"] != atual["id_perfil"]:
                db.execute("DELETE FROM usuarios_perfis WHERE id_usuario = ?", (id,))
                db.execute("INSERT INTO usuarios_perfis (id_usuario, id_perfil) VALUES (?, ?)", (id, dados["id_perfil"]))
            detalhe = f"Usuário {dados['login']} editado" + ("; senha alterada" if dados["senha"] else "")
            auditoria.registrar(db, "usuario", id, "editar", detalhe)
    except sqlite3.IntegrityError:
        erros = {"login": "Este login já está em uso."}
        return render_template("usuarios.html", **_contexto(item=atual, erros=erros,
                                                            valores=montar_valores(request.form, CAMPOS)))
    flash("Usuário atualizado com sucesso.", "sucesso")
    return redirect(url_for("usuarios.listar"))


@bp.route("/usuarios/<int:id>/excluir", methods=["POST"])
@permissao("usuarios.gerir")
def excluir(id):
    db = database.get_db()
    u = _preparar(ou_404(db.execute(SELECT_USUARIO + " WHERE u.id = ?", (id,)).fetchone()))
    try:
        if id == g.usuario["id"]:
            raise ErroNegocio("Você não pode excluir o seu próprio usuário.")
        if u["perfil"] == ADM and u["ativo"] and _admins_ativos_restantes(db, id) == 0:
            raise ErroNegocio("Não é possível excluir o último administrador ativo.")
        total, detalhe = contar_vinculos(db, [
            ("pedidos", "SELECT COUNT(*) FROM pedidos_manutencao WHERE id_usuario_solicitante = ?", id),
            ("ordens de serviço", "SELECT COUNT(*) FROM ordens_servico WHERE id_tecnico = ?", id),
            ("movimentações de estoque", "SELECT COUNT(*) FROM movimentacao_estoque_pecas WHERE id_usuario = ?", id),
        ])
        with transacao(db):
            if total:
                # tem historico: inativa em vez de apagar (nao perdemos o registro de quem fez o que)
                db.execute("UPDATE usuarios SET ativo = 0 WHERE id = ?", (id,))
                auditoria.registrar(db, "usuario", id, "inativar", f"Inativado (vínculos: {detalhe})")
                flash(f"O usuário possui vínculos ({detalhe}) e não pode ser excluído; foi inativado.", "aviso")
            else:
                db.execute("DELETE FROM usuarios WHERE id = ?", (id,))
                auditoria.registrar(db, "usuario", id, "excluir", f"Usuário {u['login']} excluído")
                flash("Usuário excluído com sucesso.", "sucesso")
    except ErroNegocio as e:
        flash_erro(e)
    except sqlite3.IntegrityError:
        flash("Não foi possível excluir: o usuário está em uso.", "erro")
    return redirect(url_for("usuarios.listar"))
