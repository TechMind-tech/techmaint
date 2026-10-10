"""
equipamentos.py
---------------
Cadastro de Equipamentos/Maquinas (Administrador e Tecnico editam; Gestor consulta).

    /equipamentos                 GET (lista + formulario), POST (criar)   equipamentos.listar / .criar
    /equipamentos/<id>/editar     GET, POST                                equipamentos.editar
    /equipamentos/<id>/excluir    POST                                     equipamentos.excluir
    /api/subgrupos?grupo_id=      GET (JSON)                               equipamentos.api_subgrupos

O Subgrupo depende do Grupo: a tela busca os subgrupos do grupo escolhido em /api/subgrupos.
"""

import sqlite3

from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, url_for

import database
from database import transacao
from modulos._comum import flash_erro, ou_404, selecionado
from servicos import auditoria
from servicos.consultas import (contar_vinculos, filtro_busca, inteiro_ou_none, mensagem_vinculos, ordenacao,
                                paginacao)
from servicos.erros import ErroNegocio
from servicos.formatacao import moeda
from servicos.formularios import Form, expandir_erros, montar_valores
from servicos.manutencao import STATUS_EQUIPAMENTO, garantir_estoque_equipamento
from servicos.permissoes import permissao, pode
from servicos.validacoes import erro_ncm, erro_tamanho, so_digitos, validar_decimal, validar_inteiro

bp = Blueprint("equipamentos", __name__)

CAMPOS = ["codigo", "descricao", "id_grupo", "id_subgrupo", "id_departamento", "status", "vida_util_meses",
          "valor_residual_padrao", "ncm", "controla_depreciacao", "patrimoniado"]

SELECT_EQUIP = """
    SELECT e.id, e.codigo, e.descricao, e.ncm, e.id_grupo, g.nome AS grupo, e.id_subgrupo, s.nome AS subgrupo,
           e.id_departamento, d.nome AS departamento, e.status, e.controla_depreciacao, e.patrimoniado,
           e.vida_util_meses, e.valor_residual_padrao
    FROM equipamentos e
    JOIN grupos g ON g.id = e.id_grupo
    JOIN subgrupos s ON s.id = e.id_subgrupo
    LEFT JOIN departamentos d ON d.id = e.id_departamento
"""

CLASSES_STATUS = {"Ativo": "ativo", "Em manutenção": "manutencao", "Baixado": "baixado"}


def _preparar(linha):
    e = dict(linha)
    e["controla_depreciacao"] = bool(e["controla_depreciacao"])
    e["patrimoniado"] = bool(e["patrimoniado"])
    e["valor_residual_fmt"] = moeda(e["valor_residual_padrao"]) if e["valor_residual_padrao"] is not None else ""
    e["status_classe"] = CLASSES_STATUS.get(e["status"], "")
    e["grupo_subgrupo"] = f"{e['grupo']} / {e['subgrupo']}"
    e["grupo_id"], e["subgrupo_id"], e["departamento_id"] = e["id_grupo"], e["id_subgrupo"], e["id_departamento"]
    return e


def _subgrupos_do_grupo(db, id_grupo):
    return [dict(s) for s in db.execute(
        "SELECT id, nome, id_grupo FROM subgrupos WHERE id_grupo = ? ORDER BY nome", (id_grupo,))]


def _contexto(item=None, erros=None, valores=None):
    db = database.get_db()
    busca = request.args.get("busca", "").strip()
    filtro_grupo = selecionado(request.args, "grupo", "grupo_id", "id_grupo", "filtro_grupo")
    filtro_status = selecionado(request.args, "status", "filtro_status")
    if filtro_grupo.lower() in ("todos", "todas"):
        filtro_grupo = ""
    if filtro_status.lower() in ("todos", "todas"):
        filtro_status = ""

    onde, params = [], []
    trecho, ps = filtro_busca(busca, ["e.codigo", "e.descricao"])
    if trecho:
        onde.append(trecho)
        params += ps
    if filtro_grupo:
        onde.append("(e.id_grupo = ? OR g.nome = ?)")
        params += [inteiro_ou_none(filtro_grupo) or -1, filtro_grupo]
    if filtro_status:
        onde.append("e.status = ?")
        params.append(filtro_status)
    where = (" WHERE " + " AND ".join(onde)) if onde else ""

    total = db.execute("SELECT COUNT(*) FROM equipamentos e JOIN grupos g ON g.id = e.id_grupo" + where,
                       params).fetchone()[0]
    pag = paginacao(request.args, total)
    ordem = ordenacao(request.args, {"codigo": "e.codigo", "descricao": "e.descricao", "grupo": "g.nome",
                                     "departamento": "d.nome", "status": "e.status"}, "e.codigo")
    linhas = db.execute(SELECT_EQUIP + where + f" ORDER BY {ordem} LIMIT ? OFFSET ?",
                        params + [pag["limite"], pag["deslocamento"]]).fetchall()

    grupos = [dict(g, grupo=g["nome"]) for g in db.execute("SELECT id, nome FROM grupos ORDER BY nome")]
    # Todos os subgrupos (com `id_grupo`): sem JavaScript o select continua utilizavel e o servidor valida
    # se o subgrupo pertence ao grupo. Com JavaScript, a tela troca as opcoes por /api/subgrupos?grupo_id=.
    subgrupos = [dict(s) for s in db.execute("SELECT id, nome, id_grupo FROM subgrupos ORDER BY nome, id_grupo")]
    departamentos = [dict(d) for d in db.execute("SELECT id, nome FROM departamentos ORDER BY nome")]

    ctx = {
        "itens": [_preparar(l) for l in linhas], "item": item, "grupos": grupos, "subgrupos": subgrupos,
        "departamentos": departamentos, "status_opcoes": list(STATUS_EQUIPAMENTO), "total": total,
        "filtro_grupo": filtro_grupo, "filtro_status": filtro_status, "busca": busca,
        "erros": expandir_erros(erros or {}), "valores": valores, "paginacao": pag,
    }
    ctx.update({k: pag[k] for k in ("pagina", "por_pagina", "total_paginas")})
    return ctx


def _validar(db, f, id_atual=None):
    erros = {}
    codigo = f.get("codigo")
    msg = erro_tamanho(codigo, "o código", 50, obrigatorio=True)
    if msg:
        erros["codigo"] = msg
    elif db.execute("SELECT 1 FROM equipamentos WHERE codigo = ? AND id <> ?", (codigo, id_atual or -1)).fetchone():
        erros["codigo"] = "Já existe um equipamento com este código."

    descricao = f.get("descricao")
    msg = erro_tamanho(descricao, "a descrição", 200, obrigatorio=True)
    if msg:
        erros["descricao"] = msg

    id_grupo = inteiro_ou_none(f.get("id_grupo"))
    if id_grupo is None:
        erros["id_grupo"] = "Selecione o grupo."
    elif db.execute("SELECT 1 FROM grupos WHERE id = ?", (id_grupo,)).fetchone() is None:
        erros["id_grupo"] = "Grupo inválido."

    id_subgrupo = inteiro_ou_none(f.get("id_subgrupo"))
    if id_subgrupo is None:
        erros["id_subgrupo"] = "Selecione o subgrupo."
    elif "id_grupo" not in erros:
        sub = db.execute("SELECT id_grupo FROM subgrupos WHERE id = ?", (id_subgrupo,)).fetchone()
        if sub is None:
            erros["id_subgrupo"] = "Subgrupo inválido."
        elif sub["id_grupo"] != id_grupo:
            erros["id_subgrupo"] = "O subgrupo não pertence ao grupo selecionado."

    id_depto = None
    if f.get("id_departamento"):
        id_depto = inteiro_ou_none(f.get("id_departamento"))
        if id_depto is None or db.execute("SELECT 1 FROM departamentos WHERE id = ?", (id_depto,)).fetchone() is None:
            erros["id_departamento"] = "Departamento inválido."

    status = f.get("status") or "Ativo"
    if status not in STATUS_EQUIPAMENTO:
        erros["status"] = "Status inválido."

    msg = erro_ncm(f.get("ncm"))
    if msg:
        erros["ncm"] = msg
    vida, msg = validar_inteiro(f.get("vida_util_meses"), "a vida útil (meses)", minimo=0, maximo=1200)
    if msg:
        erros["vida_util_meses"] = msg
    residual, msg = validar_decimal(f.get("valor_residual_padrao"), "o valor residual", obrigatorio=False)
    if msg:
        erros["valor_residual_padrao"] = msg

    return {
        "codigo": codigo, "descricao": descricao, "id_grupo": id_grupo, "id_subgrupo": id_subgrupo,
        "id_departamento": id_depto, "status": status, "ncm": so_digitos(f.get("ncm")) or None,
        "vida_util_meses": vida, "valor_residual_padrao": residual,
        "controla_depreciacao": 1 if f.booleano("controla_depreciacao", False) else 0,
        "patrimoniado": 1 if f.booleano("patrimoniado", False) else 0,
    }, erros


@bp.route("/equipamentos", methods=["GET", "POST"])
@permissao("equipamentos.ver")
def listar():
    if request.method == "GET":
        return render_template("equipamentos.html", **_contexto())
    if not pode("equipamentos.editar"):
        abort(403)
    db = database.get_db()
    dados, erros = _validar(db, Form(request.form))
    if erros:
        return render_template("equipamentos.html", **_contexto(erros=erros, valores=montar_valores(request.form, CAMPOS)))
    try:
        with transacao(db):
            cur = db.execute(
                "INSERT INTO equipamentos (codigo, descricao, ncm, id_grupo, id_subgrupo, id_departamento, status, "
                "controla_depreciacao, patrimoniado, vida_util_meses, valor_residual_padrao) "
                "VALUES (:codigo, :descricao, :ncm, :id_grupo, :id_subgrupo, :id_departamento, :status, "
                ":controla_depreciacao, :patrimoniado, :vida_util_meses, :valor_residual_padrao)", dados)
            garantir_estoque_equipamento(db, cur.lastrowid)
            auditoria.registrar(db, "equipamento", cur.lastrowid, "criar", f"Equipamento {dados['codigo']} criado")
    except sqlite3.IntegrityError:
        return render_template("equipamentos.html", **_contexto(
            erros={"codigo": "Já existe um equipamento com este código."}, valores=montar_valores(request.form, CAMPOS)))
    flash("Equipamento cadastrado com sucesso.", "sucesso")
    return redirect(url_for("equipamentos.listar"))


bp.add_url_rule("/equipamentos", endpoint="criar", view_func=listar, methods=["POST"])


@bp.route("/equipamentos/<int:id>/editar", methods=["GET", "POST"])
@permissao("equipamentos.editar")
def editar(id):
    db = database.get_db()
    atual = _preparar(ou_404(db.execute(SELECT_EQUIP + " WHERE e.id = ?", (id,)).fetchone()))
    if request.method == "GET":
        return render_template("equipamentos.html", **_contexto(item=atual))
    dados, erros = _validar(db, Form(request.form), id_atual=id)
    if erros:
        return render_template("equipamentos.html", **_contexto(item=atual, erros=erros,
                                                                valores=montar_valores(request.form, CAMPOS)))
    try:
        with transacao(db):
            dados["id"] = id
            db.execute(
                "UPDATE equipamentos SET codigo = :codigo, descricao = :descricao, ncm = :ncm, id_grupo = :id_grupo, "
                "id_subgrupo = :id_subgrupo, id_departamento = :id_departamento, status = :status, "
                "controla_depreciacao = :controla_depreciacao, patrimoniado = :patrimoniado, "
                "vida_util_meses = :vida_util_meses, valor_residual_padrao = :valor_residual_padrao WHERE id = :id",
                dados)
            garantir_estoque_equipamento(db, id)
            detalhe = f"Equipamento {dados['codigo']} editado"
            if dados["status"] != atual["status"]:
                detalhe += f"; status {atual['status']} → {dados['status']}"
            auditoria.registrar(db, "equipamento", id, "editar", detalhe)
    except sqlite3.IntegrityError:
        return render_template("equipamentos.html", **_contexto(
            item=atual, erros={"codigo": "Já existe um equipamento com este código."},
            valores=montar_valores(request.form, CAMPOS)))
    flash("Equipamento atualizado com sucesso.", "sucesso")
    return redirect(url_for("equipamentos.listar"))


@bp.route("/equipamentos/<int:id>/excluir", methods=["POST"])
@permissao("equipamentos.editar")
def excluir(id):
    db = database.get_db()
    e = ou_404(db.execute("SELECT id, codigo FROM equipamentos WHERE id = ?", (id,)).fetchone())
    try:
        total, detalhe = contar_vinculos(db, [
            ("peças", "SELECT COUNT(*) FROM pecas WHERE id_equipamento = ?", id),
            ("pedidos", "SELECT COUNT(*) FROM pedidos_manutencao WHERE id_equipamento = ?", id),
            ("ordens de serviço", "SELECT COUNT(*) FROM ordens_servico WHERE id_equipamento = ?", id),
        ])
        if total:
            raise ErroNegocio(mensagem_vinculos(total, detalhe))
        with transacao(db):
            db.execute("DELETE FROM equipamentos WHERE id = ?", (id,))      # estoque/movimentos do equipamento: CASCADE
            auditoria.registrar(db, "equipamento", id, "excluir", f"Equipamento {e['codigo']} excluído")
        flash("Equipamento excluído com sucesso.", "sucesso")
    except ErroNegocio as erro:
        flash_erro(erro)
    except sqlite3.IntegrityError:
        flash("Não é possível excluir: o equipamento está em uso.", "erro")
    return redirect(url_for("equipamentos.listar"))


@bp.route("/api/subgrupos")
@permissao("equipamentos.ver")
def api_subgrupos():
    """Subgrupos de um grupo, para o select dependente: [{"id": 1, "nome": "CLPs"}, ...]"""
    id_grupo = inteiro_ou_none(request.args.get("grupo_id") or request.args.get("id_grupo") or request.args.get("grupo"))
    if id_grupo is None:
        return jsonify([])
    db = database.get_db()
    return jsonify([{"id": s["id"], "nome": s["nome"]} for s in _subgrupos_do_grupo(db, id_grupo)])
