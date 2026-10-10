"""
pecas.py
--------
Cadastro de Pecas (Administrador e Tecnico editam; Gestor consulta).

    /pecas                   GET (lista + formulario), POST (criar)     pecas.listar / .criar
    /pecas/<id>/editar       GET, POST                                  pecas.editar
    /pecas/<id>/excluir      POST                                       pecas.excluir
    /pecas/<id>/estoque      POST  ("Atualizar estoque": gera movimento) pecas.atualizar_estoque

"Baixo" = qtde_estoque < estoque_minimo. Toda mudanca de saldo gera uma linha em
movimentacao_estoque_pecas (rastreabilidade).
"""

import re
import sqlite3

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

import database
from database import transacao
from modulos._comum import flash_erro, ou_404, selecionado, usuario_id
from servicos import auditoria
from servicos import estoque as srv_estoque
from servicos.consultas import (contar_vinculos, filtro_busca, inteiro_ou_none, mensagem_vinculos, ordenacao,
                                paginacao)
from servicos.erros import ErroNegocio
from servicos.formatacao import moeda, qtd_br
from servicos.formularios import Form, expandir_erros, montar_valores
from servicos.permissoes import permissao, pode
from servicos.validacoes import erro_ncm, erro_tamanho, so_digitos, validar_decimal

bp = Blueprint("pecas", __name__)

CAMPOS = ["codigo", "nome", "id_equipamento", "valor_unitario", "qtde_estoque", "ncm", "estoque_minimo"]

SELECT_PECA = """
    SELECT p.id, p.codigo, p.nome, p.id_equipamento, e.descricao AS equipamento, e.codigo AS equipamento_codigo,
           p.ncm, p.valor_unitario, p.qtde_estoque, p.estoque_minimo
    FROM pecas p JOIN equipamentos e ON e.id = p.id_equipamento
"""


def _preparar(linha):
    p = dict(linha)
    p["valor_unitario_fmt"] = moeda(p["valor_unitario"])
    p["qtde_fmt"] = qtd_br(p["qtde_estoque"])
    p["estoque_minimo_fmt"] = qtd_br(p["estoque_minimo"])
    p["baixo"] = p["qtde_estoque"] < p["estoque_minimo"]
    p["equipamento_id"] = p["id_equipamento"]
    return p


def _equipamentos(db):
    return [dict(e) for e in db.execute("SELECT id, codigo, descricao FROM equipamentos ORDER BY descricao")]


def _contexto(item=None, erros=None, valores=None):
    db = database.get_db()
    busca = request.args.get("busca", "").strip()
    filtro_equip = selecionado(request.args, "equipamento", "equipamento_id", "id_equipamento", "filtro_equipamento")
    if filtro_equip.lower() in ("todos", "todas"):
        filtro_equip = ""
    onde, params = [], []
    trecho, ps = filtro_busca(busca, ["p.nome", "p.codigo", "e.descricao"])
    if trecho:
        onde.append(trecho)
        params += ps
    if filtro_equip:
        onde.append("p.id_equipamento = ?")
        params.append(inteiro_ou_none(filtro_equip) or -1)
    if request.args.get("estoque") == "baixo":
        onde.append("p.qtde_estoque < p.estoque_minimo")
    where = (" WHERE " + " AND ".join(onde)) if onde else ""
    total = db.execute("SELECT COUNT(*) FROM pecas p JOIN equipamentos e ON e.id = p.id_equipamento" + where,
                       params).fetchone()[0]
    pag = paginacao(request.args, total)
    ordem = ordenacao(request.args, {"nome": "p.nome", "codigo": "p.codigo", "equipamento": "e.descricao",
                                     "valor": "p.valor_unitario", "estoque": "p.qtde_estoque"}, "p.nome")
    linhas = db.execute(SELECT_PECA + where + f" ORDER BY {ordem} LIMIT ? OFFSET ?",
                        params + [pag["limite"], pag["deslocamento"]]).fetchall()
    ctx = {"itens": [_preparar(l) for l in linhas], "item": item, "equipamentos": _equipamentos(db),
           "filtro_equipamento": filtro_equip, "busca": busca, "total": total,
           "erros": expandir_erros(erros or {}), "valores": valores, "paginacao": pag}
    ctx.update({k: pag[k] for k in ("pagina", "por_pagina", "total_paginas")})
    return ctx


def _validar(db, f, id_atual=None):
    erros = {}
    nome = f.get("nome")
    msg = erro_tamanho(nome, "o nome da peça", 200, obrigatorio=True)
    if msg:
        erros["nome"] = msg

    codigo = f.get("codigo") or None
    if codigo:
        msg = erro_tamanho(codigo, "o código", 50)
        if msg:
            erros["codigo"] = msg
        elif db.execute("SELECT 1 FROM pecas WHERE codigo = ? AND id <> ?", (codigo, id_atual or -1)).fetchone():
            erros["codigo"] = "Já existe uma peça com este código."

    id_equip = inteiro_ou_none(f.get("id_equipamento"))
    if id_equip is None:
        erros["id_equipamento"] = "Selecione o equipamento vinculado."
    elif db.execute("SELECT 1 FROM equipamentos WHERE id = ?", (id_equip,)).fetchone() is None:
        erros["id_equipamento"] = "Equipamento inválido."

    valor, msg = validar_decimal(f.get("valor_unitario"), "o valor unitário")
    if msg:
        erros["valor_unitario"] = msg
    qtde, msg = validar_decimal(f.get("qtde_estoque") if f.tem("qtde_estoque") else "0", "a quantidade em estoque",
                                obrigatorio=False)
    if msg:
        erros["qtde_estoque"] = msg
    minimo, msg = validar_decimal(f.get("estoque_minimo"), "o estoque mínimo", obrigatorio=False)
    if msg:
        erros["estoque_minimo"] = msg
    msg = erro_ncm(f.get("ncm"))
    if msg:
        erros["ncm"] = msg
    return {"nome": nome, "codigo": codigo, "id_equipamento": id_equip, "valor_unitario": valor,
            "qtde_estoque": qtde if qtde is not None else 0.0, "estoque_minimo": minimo,
            "ncm": so_digitos(f.get("ncm")) or None}, erros


def _gerar_codigo(db, id_peca):
    """Codigo automatico quando o usuario nao informa: PEC-0007."""
    return f"PEC-{id_peca:04d}"


@bp.route("/pecas", methods=["GET", "POST"])
@permissao("pecas.ver")
def listar():
    if request.method == "GET":
        return render_template("pecas.html", **_contexto())
    if not pode("pecas.editar"):
        abort(403)
    db = database.get_db()
    dados, erros = _validar(db, Form(request.form))
    if erros:
        return render_template("pecas.html", **_contexto(erros=erros, valores=montar_valores(request.form, CAMPOS)))
    try:
        with transacao(db):
            minimo = dados["estoque_minimo"] if dados["estoque_minimo"] is not None else 5
            cur = db.execute(
                "INSERT INTO pecas (codigo, id_equipamento, nome, ncm, valor_unitario, qtde_estoque, estoque_minimo) "
                "VALUES (?, ?, ?, ?, ?, 0, ?)",
                (dados["codigo"], dados["id_equipamento"], dados["nome"], dados["ncm"], dados["valor_unitario"], minimo))
            id_peca = cur.lastrowid
            if not dados["codigo"]:
                db.execute("UPDATE pecas SET codigo = ? WHERE id = ?", (_gerar_codigo(db, id_peca), id_peca))
            srv_estoque.garantir_linha_estoque(db, id_peca)
            if dados["qtde_estoque"] > 0:      # saldo inicial entra como movimento de Entrada
                srv_estoque.registrar_movimento(
                    db, id_peca, "Entrada", dados["qtde_estoque"], dados["valor_unitario"], "Pedido Interno",
                    "ESTOQUE-INICIAL", "Saldo inicial informado no cadastro da peça", id_usuario=usuario_id())
            auditoria.registrar(db, "peca", id_peca, "criar", f"Peça {dados['nome']} criada")
    except sqlite3.IntegrityError:
        return render_template("pecas.html", **_contexto(
            erros={"codigo": "Já existe uma peça com este código."}, valores=montar_valores(request.form, CAMPOS)))
    except ErroNegocio as e:
        return render_template("pecas.html", **_contexto(erros={e.campo or "nome": e.mensagem},
                                                          valores=montar_valores(request.form, CAMPOS)))
    flash("Peça cadastrada com sucesso.", "sucesso")
    return redirect(url_for("pecas.listar"))


bp.add_url_rule("/pecas", endpoint="criar", view_func=listar, methods=["POST"])


@bp.route("/pecas/<int:id>/editar", methods=["GET", "POST"])
@permissao("pecas.editar")
def editar(id):
    db = database.get_db()
    atual = _preparar(ou_404(db.execute(SELECT_PECA + " WHERE p.id = ?", (id,)).fetchone()))
    if request.method == "GET":
        return render_template("pecas.html", **_contexto(item=atual))
    f = Form(request.form)
    dados, erros = _validar(db, f, id_atual=id)
    if erros:
        return render_template("pecas.html", **_contexto(item=atual, erros=erros,
                                                          valores=montar_valores(request.form, CAMPOS)))
    try:
        with transacao(db):
            minimo = dados["estoque_minimo"] if dados["estoque_minimo"] is not None else atual["estoque_minimo"]
            db.execute("UPDATE pecas SET codigo = COALESCE(?, codigo), id_equipamento = ?, nome = ?, ncm = ?, "
                       "valor_unitario = ?, estoque_minimo = ? WHERE id = ?",
                       (dados["codigo"], dados["id_equipamento"], dados["nome"], dados["ncm"],
                        dados["valor_unitario"], minimo, id))
            # Se o saldo foi digitado diferente do atual, registra o ajuste como movimento.
            if f.tem("qtde_estoque"):
                delta = srv_estoque.arredondar(dados["qtde_estoque"] - atual["qtde_estoque"])
                if delta != 0:
                    srv_estoque.registrar_movimento(
                        db, id, "Entrada" if delta > 0 else "Saída", abs(delta), dados["valor_unitario"],
                        "Pedido Interno", "AJUSTE", "Ajuste manual no cadastro da peça", id_usuario=usuario_id())
            srv_estoque.garantir_linha_estoque(db, id)
            auditoria.registrar(db, "peca", id, "editar", f"Peça {dados['nome']} editada")
    except sqlite3.IntegrityError:
        return render_template("pecas.html", **_contexto(
            item=atual, erros={"codigo": "Já existe uma peça com este código."},
            valores=montar_valores(request.form, CAMPOS)))
    flash("Peça atualizada com sucesso.", "sucesso")
    return redirect(url_for("pecas.listar"))


@bp.route("/pecas/<int:id>/excluir", methods=["POST"])
@permissao("pecas.editar")
def excluir(id):
    db = database.get_db()
    p = ou_404(db.execute("SELECT id, nome FROM pecas WHERE id = ?", (id,)).fetchone())
    try:
        total, detalhe = contar_vinculos(db, [
            ("ordens de serviço", "SELECT COUNT(*) FROM itens_os WHERE id_peca = ?", id),
            ("notas fiscais", "SELECT COUNT(*) FROM itens_nota_fiscal WHERE id_peca = ?", id),
            ("movimentos de OS/NF", "SELECT COUNT(*) FROM movimentacao_estoque_pecas WHERE id_peca = ? "
                                    "AND (id_os IS NOT NULL OR id_nota_fiscal IS NOT NULL "
                                    "OR documento_origem IN ('Ordem de Serviço', 'Nota Fiscal'))", id),
        ])
        if total:
            raise ErroNegocio(mensagem_vinculos(total, detalhe))
        with transacao(db):
            # sobram so movimentos manuais ("Pedido Interno"): saem junto com a peca
            db.execute("DELETE FROM movimentacao_estoque_pecas WHERE id_peca = ?", (id,))
            db.execute("DELETE FROM pecas WHERE id = ?", (id,))
            auditoria.registrar(db, "peca", id, "excluir", f"Peça {p['nome']} excluída")
        flash("Peça excluída com sucesso.", "sucesso")
    except ErroNegocio as e:
        flash_erro(e)
    except sqlite3.IntegrityError:
        flash("Não é possível excluir: a peça está em uso.", "erro")
    return redirect(url_for("pecas.listar"))


@bp.route("/pecas/<int:id>/estoque", methods=["POST"])
@permissao("pecas.editar")
def atualizar_estoque(id):
    """Ajuste rapido: `tipo` (Entrada/Saída) + `quantidade`, OU `nova_quantidade` (saldo final)."""
    db = database.get_db()
    p = ou_404(db.execute("SELECT * FROM pecas WHERE id = ?", (id,)).fetchone())
    f = Form(request.form)
    obs = f.get("observacao") or "Ajuste rápido de estoque"
    try:
        tipo = srv_estoque.normalizar_tipo(f.get("tipo")) if f.get("tipo") else None
        if f.get("tipo") and tipo is None:
            raise ErroNegocio("Tipo de movimento inválido (use Entrada ou Saída).")
        if tipo:
            qtd, msg = validar_decimal(f.get("quantidade"), "a quantidade", estrito=True)
            if msg:
                raise ErroNegocio(msg)
            delta_tipo, delta_qtd = tipo, qtd
        else:
            alvo_txt = f.get("nova_quantidade") or (request.form.get("quantidade") or "").strip()
            novo, msg = validar_decimal(alvo_txt, "a nova quantidade em estoque")
            if msg:
                raise ErroNegocio(msg)
            delta = srv_estoque.arredondar(novo - p["qtde_estoque"])
            if delta == 0:
                flash("O estoque já está com essa quantidade; nada foi alterado.", "info")
                return redirect(url_for("pecas.listar"))
            delta_tipo, delta_qtd = ("Entrada" if delta > 0 else "Saída"), abs(delta)
        with transacao(db):
            srv_estoque.registrar_movimento(db, id, delta_tipo, delta_qtd, p["valor_unitario"], "Pedido Interno",
                                            "AJUSTE", obs, id_usuario=usuario_id())
            auditoria.registrar(db, "peca", id, "estoque", f"{delta_tipo} de {qtd_br(delta_qtd)} ({p['nome']})")
        flash(f"Estoque de “{p['nome']}” atualizado.", "sucesso")
    except ErroNegocio as e:
        flash_erro(e)
    return redirect(url_for("pecas.listar"))
