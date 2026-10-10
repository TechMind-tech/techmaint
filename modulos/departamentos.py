"""
departamentos.py
----------------
Cadastro de Departamentos (Administrador edita; Gestor e Tecnico apenas consultam).

    /departamentos                 GET (lista + formulario), POST (criar)   departamentos.listar / .criar
    /departamentos/<id>/editar     GET, POST                                departamentos.editar
    /departamentos/<id>/excluir    POST                                     departamentos.excluir

O "Responsavel" pode ser escolhido na lista de usuarios (`responsavel_id`) ou digitado
(`responsavel_nome`).
"""

import sqlite3

from flask import Blueprint, flash, redirect, render_template, request, url_for

import database
from database import transacao
from modulos._comum import flash_erro, ou_404
from servicos import auditoria
from servicos.consultas import contar_vinculos, filtro_busca, inteiro_ou_none, mensagem_vinculos, paginacao
from servicos.erros import ErroNegocio
from servicos.formularios import Form, expandir_erros, montar_valores
from servicos.permissoes import permissao, pode
from servicos.validacoes import erro_tamanho

bp = Blueprint("departamentos", __name__)

CAMPOS = ["nome", "responsavel_id", "responsavel_nome"]

SELECT_DEPTO = """
    SELECT d.id, d.nome, d.responsavel_id, d.responsavel_nome,
           COALESCE(u.nome, d.responsavel_nome) AS responsavel
    FROM departamentos d LEFT JOIN usuarios u ON u.id = d.responsavel_id
"""


def _contexto(item=None, erros=None, valores=None):
    db = database.get_db()
    busca = request.args.get("busca", "").strip()
    trecho, params = filtro_busca(busca, ["d.nome", "COALESCE(u.nome, d.responsavel_nome, '')"])
    where = f" WHERE {trecho}" if trecho else ""
    total = db.execute("SELECT COUNT(*) FROM departamentos d LEFT JOIN usuarios u ON u.id = d.responsavel_id" + where,
                       params).fetchone()[0]
    pag = paginacao(request.args, total)
    itens = [dict(l) for l in db.execute(SELECT_DEPTO + where + " ORDER BY d.id LIMIT ? OFFSET ?",
                                         params + [pag["limite"], pag["deslocamento"]])]
    usuarios = [dict(u) for u in db.execute("SELECT id, nome, login FROM usuarios WHERE ativo = 1 ORDER BY nome")]
    ctx = {"itens": itens, "item": item, "usuarios": usuarios, "busca": busca, "total": total,
           "erros": expandir_erros(erros or {}), "valores": valores, "paginacao": pag}
    ctx.update({k: pag[k] for k in ("pagina", "por_pagina", "total_paginas")})
    return ctx


def _validar(db, f, id_atual=None):
    erros = {}
    nome = f.get("nome")
    msg = erro_tamanho(nome, "o nome do departamento", 100, obrigatorio=True)
    if msg:
        erros["nome"] = msg
    elif db.execute("SELECT 1 FROM departamentos WHERE nome = ? AND id <> ?", (nome, id_atual or -1)).fetchone():
        erros["nome"] = "Já existe um departamento com este nome."

    responsavel_id, responsavel_nome = None, f.get("responsavel_nome") or None
    if f.get("responsavel_id"):
        responsavel_id = inteiro_ou_none(f.get("responsavel_id"))
        u = db.execute("SELECT nome FROM usuarios WHERE id = ?", (responsavel_id or -1,)).fetchone()
        if u is None:
            erros["responsavel_id"] = "Responsável inválido."
        else:
            responsavel_nome = u["nome"]
    msg = erro_tamanho(responsavel_nome, "o responsável", 100)
    if msg:
        erros["responsavel_nome"] = msg
    return {"nome": nome, "responsavel_id": responsavel_id, "responsavel_nome": responsavel_nome}, erros


@bp.route("/departamentos", methods=["GET", "POST"])
@permissao("departamentos.ver")
def listar():
    if request.method == "GET":
        return render_template("departamentos.html", **_contexto())
    if not pode("departamentos.editar"):
        from flask import abort
        abort(403)
    db = database.get_db()
    dados, erros = _validar(db, Form(request.form))
    if erros:
        return render_template("departamentos.html", **_contexto(erros=erros, valores=montar_valores(request.form, CAMPOS)))
    try:
        with transacao(db):
            cur = db.execute("INSERT INTO departamentos (nome, responsavel_id, responsavel_nome) VALUES (?, ?, ?)",
                             (dados["nome"], dados["responsavel_id"], dados["responsavel_nome"]))
            auditoria.registrar(db, "departamento", cur.lastrowid, "criar", f"Departamento {dados['nome']} criado")
    except sqlite3.IntegrityError:
        return render_template("departamentos.html", **_contexto(
            erros={"nome": "Já existe um departamento com este nome."}, valores=montar_valores(request.form, CAMPOS)))
    flash("Departamento cadastrado com sucesso.", "sucesso")
    return redirect(url_for("departamentos.listar"))


bp.add_url_rule("/departamentos", endpoint="criar", view_func=listar, methods=["POST"])


@bp.route("/departamentos/<int:id>/editar", methods=["GET", "POST"])
@permissao("departamentos.editar")
def editar(id):
    db = database.get_db()
    atual = dict(ou_404(db.execute(SELECT_DEPTO + " WHERE d.id = ?", (id,)).fetchone()))
    if request.method == "GET":
        return render_template("departamentos.html", **_contexto(item=atual))
    dados, erros = _validar(db, Form(request.form), id_atual=id)
    if erros:
        return render_template("departamentos.html", **_contexto(item=atual, erros=erros,
                                                                 valores=montar_valores(request.form, CAMPOS)))
    try:
        with transacao(db):
            db.execute("UPDATE departamentos SET nome = ?, responsavel_id = ?, responsavel_nome = ? WHERE id = ?",
                       (dados["nome"], dados["responsavel_id"], dados["responsavel_nome"], id))
            auditoria.registrar(db, "departamento", id, "editar", f"Departamento {dados['nome']} editado")
    except sqlite3.IntegrityError:
        return render_template("departamentos.html", **_contexto(
            item=atual, erros={"nome": "Já existe um departamento com este nome."},
            valores=montar_valores(request.form, CAMPOS)))
    flash("Departamento atualizado com sucesso.", "sucesso")
    return redirect(url_for("departamentos.listar"))


@bp.route("/departamentos/<int:id>/excluir", methods=["POST"])
@permissao("departamentos.editar")
def excluir(id):
    db = database.get_db()
    d = ou_404(db.execute("SELECT id, nome FROM departamentos WHERE id = ?", (id,)).fetchone())
    try:
        total, detalhe = contar_vinculos(db, [
            ("usuários", "SELECT COUNT(*) FROM usuarios WHERE id_departamento = ?", id),
            ("equipamentos", "SELECT COUNT(*) FROM equipamentos WHERE id_departamento = ?", id),
            ("pedidos", "SELECT COUNT(*) FROM pedidos_manutencao WHERE id_departamento = ?", id),
        ])
        if total:
            raise ErroNegocio(mensagem_vinculos(total, detalhe))
        with transacao(db):
            db.execute("DELETE FROM estoque_equipamentos WHERE id_departamento = ?", (id,))
            db.execute("DELETE FROM movimentacao_equipamentos WHERE id_departamento = ?", (id,))
            db.execute("DELETE FROM departamentos WHERE id = ?", (id,))
            auditoria.registrar(db, "departamento", id, "excluir", f"Departamento {d['nome']} excluído")
        flash("Departamento excluído com sucesso.", "sucesso")
    except ErroNegocio as e:
        flash_erro(e)
    except sqlite3.IntegrityError:
        flash("Não é possível excluir: o departamento está em uso.", "erro")
    return redirect(url_for("departamentos.listar"))
