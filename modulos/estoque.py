"""
estoque.py
----------
Movimentacao de Estoque (entradas e saidas de pecas).

    /estoque                 GET (resumo + historico + formulario), POST (registrar)    estoque.listar
    /estoque/<id>/excluir    POST (estorna o saldo e apaga o movimento)                 estoque.excluir

Regras: Saida maior que o saldo e recusada (nada muda); Entrada nao altera o valor da peca;
excluir um movimento estorna o saldo (se nao deixar negativo); movimentos gerados por uma OS
so podem ser desfeitos pela propria OS. A logica fica em servicos/estoque.py.
"""

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

import database
from database import transacao
from modulos._comum import flash_erro, ou_404, selecionado, usuario_id
from servicos import auditoria
from servicos import estoque as srv
from servicos.consultas import filtro_busca, inteiro_ou_none, ordenacao, paginacao
from servicos.erros import ErroNegocio
from servicos.formatacao import data_hora_br, hoje, moeda, qtd_br
from servicos.formularios import Form, expandir_erros, montar_valores
from servicos.periodos import PERIODOS, inicio_do_periodo, periodo_valido
from servicos.permissoes import permissao, pode
from servicos.validacoes import erro_tamanho, validar_decimal

bp = Blueprint("estoque", __name__)

CAMPOS = ["tipo", "id_peca", "codigo_item", "quantidade", "valor_unitario", "documento_origem", "numero_documento",
          "observacao"]


def _resumo_do_mes(db):
    mes = hoje().strftime("%Y-%m")
    r = db.execute(
        "SELECT COALESCE(SUM(CASE WHEN tipo = 'Entrada' THEN quantidade * COALESCE(valor_unitario, 0) END), 0) AS ent, "
        "COALESCE(SUM(CASE WHEN tipo = 'Saída' THEN quantidade * COALESCE(valor_unitario, 0) END), 0) AS sai, "
        "COUNT(*) AS n FROM movimentacao_estoque_pecas WHERE substr(data, 1, 7) = ?", (mes,)).fetchone()
    ent, sai = round(r["ent"], 2), round(r["sai"], 2)
    return {"total_entradas": ent, "total_saidas": sai, "total_entradas_fmt": moeda(ent),
            "total_saidas_fmt": moeda(sai), "qtd_movimentos": r["n"]}


def _contexto(erros=None, valores=None):
    db = database.get_db()
    busca = request.args.get("busca", "").strip()
    tipo = srv.normalizar_tipo(selecionado(request.args, "tipo", "filtro_tipo")) or ""
    periodo_txt = selecionado(request.args, "periodo", "filtro_periodo")
    periodo = periodo_valido(periodo_txt, "") if periodo_txt else ""

    onde, params = [], []
    trecho, ps = filtro_busca(busca, ["p.nome", "p.codigo", "COALESCE(m.numero_documento, '')",
                                      "COALESCE(m.documento_origem, '')", "COALESCE(m.observacao, '')"])
    if trecho:
        onde.append(trecho)
        params += ps
    if tipo:
        onde.append("m.tipo = ?")
        params.append(tipo)
    if periodo:
        onde.append("substr(m.data, 1, 10) >= ?")
        params.append(inicio_do_periodo(periodo).isoformat())
    where = (" WHERE " + " AND ".join(onde)) if onde else ""
    juncao = (" FROM movimentacao_estoque_pecas m JOIN pecas p ON p.id = m.id_peca "
              "LEFT JOIN usuarios u ON u.id = m.id_usuario")
    total = db.execute("SELECT COUNT(*)" + juncao + where, params).fetchone()[0]
    pag = paginacao(request.args, total)
    ordem = ordenacao(request.args, {"data": "m.data", "peca": "p.nome", "tipo": "m.tipo",
                                     "quantidade": "m.quantidade"}, "m.data DESC, m.id DESC")
    linhas = db.execute(
        "SELECT m.id, m.id_peca, p.nome AS peca, p.codigo, m.tipo, m.quantidade, m.valor_unitario, m.data, "
        "m.documento_origem, m.numero_documento, m.observacao, m.id_os, u.nome AS usuario" + juncao + where +
        f" ORDER BY {ordem} LIMIT ? OFFSET ?", params + [pag["limite"], pag["deslocamento"]]).fetchall()
    pode_editar = pode("estoque.editar")
    itens = []
    for l in linhas:
        d = dict(l)
        valor = d["valor_unitario"] or 0
        d.update(peca_id=d["id_peca"], quantidade_fmt=qtd_br(d["quantidade"]), valor_unitario_fmt=moeda(valor),
                 valor_total=round(d["quantidade"] * valor, 2), valor_total_fmt=moeda(d["quantidade"] * valor),
                 data_fmt=data_hora_br(d["data"]), pode_excluir=pode_editar and d["id_os"] is None,
                 numero=d["numero_documento"] or "")
        itens.append(d)

    pecas = []
    for p in db.execute("SELECT id, codigo, nome, qtde_estoque, valor_unitario FROM pecas ORDER BY nome"):
        d = dict(p)
        d["qtde_fmt"] = qtd_br(d["qtde_estoque"])
        pecas.append(d)
    ctx = {"resumo": _resumo_do_mes(db), "itens": itens, "pecas": pecas, "tipos_documento": list(srv.DOCUMENTOS),
           "tipos": list(srv.TIPOS), "valores": valores, "erros": expandir_erros(erros or {}), "tipo": tipo,
           "busca": busca, "periodo": periodo, "filtro_tipo": tipo, "filtro_periodo": periodo,
           "periodos": PERIODOS, "total": total, "paginacao": pag, "pode_editar": pode_editar}
    ctx.update({k: pag[k] for k in ("pagina", "por_pagina", "total_paginas")})
    return ctx


@bp.route("/estoque", methods=["GET", "POST"])
@permissao("estoque.ver")
def listar():
    if request.method == "GET":
        return render_template("estoque.html", **_contexto())
    if not pode("estoque.editar"):
        abort(403)

    db = database.get_db()
    f = Form(request.form)
    erros = {}
    tipo = srv.normalizar_tipo(f.get("tipo"))
    if tipo is None:
        erros["tipo"] = "Selecione o tipo de movimento (Entrada ou Saída)."

    peca = None
    id_peca = inteiro_ou_none(f.get("id_peca"))
    if id_peca is not None:
        peca = db.execute("SELECT * FROM pecas WHERE id = ?", (id_peca,)).fetchone()
    if peca is None and f.get("codigo_item"):
        peca = db.execute("SELECT * FROM pecas WHERE codigo = ?", (f.get("codigo_item"),)).fetchone()
    if peca is None:
        erros["id_peca"] = "Selecione uma peça válida." if (f.get("id_peca") or f.get("codigo_item")) \
            else "Selecione a peça."

    qtd, msg = validar_decimal(f.get("quantidade"), "a quantidade", estrito=True)
    if msg:
        erros["quantidade"] = msg
    valor, msg = validar_decimal(f.get("valor_unitario"), "o valor unitário", obrigatorio=False)
    if msg:
        erros["valor_unitario"] = msg
    documento = srv.normalizar_documento(f.get("documento_origem"))
    if documento is None:
        erros["documento_origem"] = "Selecione o tipo de documento."
    numero = f.get("numero_documento")
    msg = erro_tamanho(numero, "o número do documento", 50)
    if msg:
        erros["numero_documento"] = msg
    obs = f.get("observacao")
    msg = erro_tamanho(obs, "a observação", 500)
    if msg:
        erros["observacao"] = msg

    if not erros:
        try:
            with transacao(db):
                id_mov = srv.registrar_movimento(
                    db, peca["id"], tipo, qtd, valor if valor else None, documento, numero or None, obs or None,
                    id_usuario=usuario_id())
                auditoria.registrar(db, "estoque", id_mov, "criar", f"{tipo} de {qtd_br(qtd)} × {peca['nome']}")
            flash(f"Movimento de {tipo.lower()} registrado: {qtd_br(qtd)} × {peca['nome']}.", "sucesso")
            return redirect(url_for("estoque.listar"))
        except ErroNegocio as e:
            erros[e.campo or "quantidade"] = e.mensagem
    return render_template("estoque.html", **_contexto(erros=erros, valores=montar_valores(request.form, CAMPOS)))


bp.add_url_rule("/estoque", endpoint="registrar", view_func=listar, methods=["POST"])


@bp.route("/estoque/<int:id>/excluir", methods=["POST"])
@permissao("estoque.editar")
def excluir(id):
    db = database.get_db()
    ou_404(db.execute("SELECT id FROM movimentacao_estoque_pecas WHERE id = ?", (id,)).fetchone())
    try:
        with transacao(db):
            m = srv.excluir_movimento(db, id)
            auditoria.registrar(db, "estoque", id, "excluir", f"Movimento de {m['tipo']} excluído (saldo estornado)")
        flash("Movimento excluído e saldo estornado.", "sucesso")
    except ErroNegocio as e:
        flash_erro(e)
    return redirect(url_for("estoque.listar"))
