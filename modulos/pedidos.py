"""
pedidos.py
----------
Pedidos de Manutencao: o ponto de partida do fluxo (Pedido -> OS -> Fechamento).

    /pedidos                   GET        pedidos.listar        pedidos.html
    /pedidos/novo              GET, POST  pedidos.novo          pedido_form.html
    /pedidos/<id>              GET        pedidos.detalhe       pedido_detalhe.html
    /pedidos/<id>/editar       GET, POST  pedidos.editar        pedido_form.html
    /pedidos/<id>/cancelar     POST       pedidos.cancelar
    /pedidos/<id>/aprovar      POST       pedidos.aprovar
    /pedidos/<id>/abrir-os     GET, POST  pedidos.abrir_os      (leva para /os/nova ou abre a OS direto)

Perfis: todos abrem pedidos; Usuario Comum so ve os proprios; Tecnico edita; Gestor e
Administrador tambem cancelam e aprovam; Administrador e Tecnico abrem a OS.
"""

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

import database
from database import transacao
from modulos._comum import flash_erro, ou_404, selecionado, usuario_id
from modulos.ordens import SELECT_OS, preparar_os
from servicos import auditoria
from servicos import manutencao as srv
from servicos.consultas import filtro_busca, inteiro_ou_none, ordenacao, paginacao
from servicos.erros import ErroNegocio
from servicos.formatacao import data_br, data_iso, hoje, hoje_iso, normalizar
from servicos.formularios import Form, expandir_erros, montar_valores
from servicos.permissoes import COM, e_perfil, permissao, pode
from servicos.validacoes import erro_tamanho

bp = Blueprint("pedidos", __name__)

CAMPOS_FORM = ["id_equipamento", "id_departamento", "descricao_problema", "prioridade"]

SELECT_PEDIDO = """
    SELECT p.id, p.id_equipamento, e.descricao AS equipamento, e.codigo AS equipamento_codigo,
           p.id_departamento, d.nome AS departamento, p.data_solicitacao, p.solicitante,
           p.id_usuario_solicitante, p.descricao_problema, p.prioridade, p.status, p.aprovado_por, p.data_aprovacao,
           (SELECT os.id FROM ordens_servico os WHERE os.id_pedido = p.id AND os.status <> 'Cancelada'
             ORDER BY os.id DESC LIMIT 1) AS id_os
    FROM pedidos_manutencao p
    JOIN equipamentos e ON e.id = p.id_equipamento
    JOIN departamentos d ON d.id = p.id_departamento
"""

SLUGS_STATUS = {"aberto": "Aberto", "andamento": "Em andamento", "emandamento": "Em andamento",
                "concluido": "Concluído", "cancelado": "Cancelado"}
SLUGS_PRIORIDADE = {"baixa": "Baixa", "media": "Média", "alta": "Alta"}


def _slug(texto):
    return normalizar(texto).replace(" ", "").replace("-", "").replace("_", "")


def _so_proprios():
    return e_perfil(COM) and not pode("pedidos.editar")


def _preparar(linha):
    p = dict(linha)
    p["numero"] = srv.numero_pedido(p["id"])
    p["data_solicitacao_fmt"] = data_br(p["data_solicitacao"])
    p["data_solicitacao_iso"] = data_iso(p["data_solicitacao"])
    p["data_fmt"] = p["data_solicitacao_fmt"]
    p["aprovado"] = bool(p["aprovado_por"])
    p["data_aprovacao_fmt"] = data_br(p["data_aprovacao"]) if p["data_aprovacao"] else ""
    p["os_numero"] = srv.numero_os(p["id_os"]) if p["id_os"] else ""
    p["equipamento_id"], p["departamento_id"] = p["id_equipamento"], p["id_departamento"]
    return p


def _pedido_visivel(db, id):
    p = ou_404(db.execute(SELECT_PEDIDO + " WHERE p.id = ?", (id,)).fetchone())
    if _so_proprios() and p["id_usuario_solicitante"] != g.usuario["id"]:
        abort(403)
    return p


def _listas(db):
    equipamentos = [dict(e) for e in db.execute(
        "SELECT id, codigo, descricao FROM equipamentos WHERE status <> 'Baixado' ORDER BY descricao")]
    departamentos = [dict(d) for d in db.execute("SELECT id, nome FROM departamentos ORDER BY nome")]
    return equipamentos, departamentos


# ---------------------------------------------------------------------------
# Lista
# ---------------------------------------------------------------------------
@bp.route("/pedidos")
@permissao("pedidos.ver")
def listar():
    db = database.get_db()
    busca = request.args.get("busca", "").strip()
    status = SLUGS_STATUS.get(_slug(selecionado(request.args, "status", "filtro_status")), "")
    prioridade = SLUGS_PRIORIDADE.get(_slug(selecionado(request.args, "prioridade", "filtro_prioridade")), "")
    depto = inteiro_ou_none(selecionado(request.args, "departamento_id", "id_departamento", "departamento",
                                        "filtro_departamento"))

    base, base_params = [], []
    if _so_proprios():
        base.append("p.id_usuario_solicitante = ?")
        base_params.append(g.usuario["id"])
    onde, params = list(base), list(base_params)
    trecho, ps = filtro_busca(busca, ["e.descricao", "e.codigo", "p.solicitante", "d.nome", "'#' || p.id",
                                      "CAST(p.id AS TEXT)", "COALESCE(p.descricao_problema, '')"])
    if trecho:
        onde.append(trecho)
        params += ps
    if status:
        onde.append("p.status = ?")
        params.append(status)
    if prioridade:
        onde.append("p.prioridade = ?")
        params.append(prioridade)
    if depto:
        onde.append("p.id_departamento = ?")
        params.append(depto)
    where = (" WHERE " + " AND ".join(onde)) if onde else ""
    where_base = (" WHERE " + " AND ".join(base)) if base else ""

    juncoes = " FROM pedidos_manutencao p JOIN equipamentos e ON e.id = p.id_equipamento JOIN departamentos d ON d.id = p.id_departamento"
    total = db.execute("SELECT COUNT(*)" + juncoes + where, params).fetchone()[0]
    pag = paginacao(request.args, total)
    ordem = ordenacao(request.args, {"numero": "p.id", "equipamento": "e.descricao", "departamento": "d.nome",
                                     "solicitante": "p.solicitante", "prioridade": "p.prioridade",
                                     "status": "p.status", "data": "p.data_solicitacao"}, "p.id DESC")
    linhas = db.execute(SELECT_PEDIDO + where + f" ORDER BY {ordem} LIMIT ? OFFSET ?",
                        params + [pag["limite"], pag["deslocamento"]]).fetchall()

    contadores = {"aberto": 0, "andamento": 0, "concluido": 0, "cancelado": 0}
    chaves = {"Aberto": "aberto", "Em andamento": "andamento", "Concluído": "concluido", "Cancelado": "cancelado"}
    for r in db.execute("SELECT p.status, COUNT(*) AS n FROM pedidos_manutencao p" + where_base + " GROUP BY p.status",
                        base_params):
        contadores[chaves[r["status"]]] = r["n"]

    equipamentos, departamentos = _listas(db)
    ctx = {"itens": [_preparar(l) for l in linhas], "contadores": contadores, "busca": busca, "status": status,
           "prioridade": prioridade, "departamento_id": depto, "filtro_status": status,
           "filtro_prioridade": prioridade, "filtro_departamento": depto,
           "filtros": {"busca": busca, "status": status, "prioridade": prioridade, "departamento_id": depto},
           "status_opcoes": list(srv.STATUS_PEDIDO), "prioridades": list(srv.PRIORIDADES),
           "departamentos": departamentos, "equipamentos": equipamentos, "total": total, "paginacao": pag}
    ctx.update({k: pag[k] for k in ("pagina", "por_pagina", "total_paginas")})
    return render_template("pedidos.html", **ctx)


# ---------------------------------------------------------------------------
# Novo / editar
# ---------------------------------------------------------------------------
def _ctx_form(db, pedido=None, erros=None, valores=None):
    equipamentos, departamentos = _listas(db)
    if pedido and all(e["id"] != pedido["id_equipamento"] for e in equipamentos):
        equipamentos.insert(0, {"id": pedido["id_equipamento"], "codigo": pedido["equipamento_codigo"],
                                "descricao": pedido["equipamento"]})
    if valores is None:
        if pedido:
            valores = {"id_equipamento": pedido["id_equipamento"], "id_departamento": pedido["id_departamento"],
                       "descricao_problema": pedido["descricao_problema"] or "", "prioridade": pedido["prioridade"]}
        else:
            valores = {"id_equipamento": "", "id_departamento": g.usuario.get("id_departamento") or "",
                       "descricao_problema": "", "prioridade": "Média"}
    # data e solicitante: somente leitura (quem define e o servidor)
    valores = dict(valores)
    valores["solicitante"] = pedido["solicitante"] if pedido else g.usuario["nome"]
    valores["data_solicitacao"] = pedido["data_solicitacao_fmt"] if pedido else data_br(hoje_iso())
    valores["data_solicitacao_iso"] = pedido["data_solicitacao_iso"] if pedido else hoje_iso()
    return {"equipamentos": equipamentos, "departamentos": departamentos, "prioridades": list(srv.PRIORIDADES),
            "valores": valores, "erros": expandir_erros(erros or {}), "item": pedido, "pedido": pedido,
            "editando": pedido is not None, "solicitante": valores["solicitante"],
            "data_solicitacao": valores["data_solicitacao"], "data_solicitacao_iso": valores["data_solicitacao_iso"]}


def _validar(db, f):
    erros = {}
    id_equip = inteiro_ou_none(f.get("id_equipamento"))
    if id_equip is None:
        erros["id_equipamento"] = "Selecione o equipamento."
    else:
        e = db.execute("SELECT status FROM equipamentos WHERE id = ?", (id_equip,)).fetchone()
        if e is None:
            erros["id_equipamento"] = "Equipamento inválido."
        elif e["status"] == "Baixado":
            erros["id_equipamento"] = "Equipamento baixado não pode receber pedidos de manutenção."
    id_depto = inteiro_ou_none(f.get("id_departamento"))
    if id_depto is None:
        erros["id_departamento"] = "Selecione o departamento solicitante."
    elif db.execute("SELECT 1 FROM departamentos WHERE id = ?", (id_depto,)).fetchone() is None:
        erros["id_departamento"] = "Departamento inválido."
    descricao = f.get("descricao_problema")
    msg = erro_tamanho(descricao, "a descrição do problema", 500, obrigatorio=True)
    if msg:
        erros["descricao_problema"] = msg
    prioridade = SLUGS_PRIORIDADE.get(_slug(f.get("prioridade")), "")
    if not f.get("prioridade"):
        erros["prioridade"] = "Selecione a prioridade."
    elif not prioridade:
        erros["prioridade"] = "Prioridade inválida."
    return {"id_equipamento": id_equip, "id_departamento": id_depto, "descricao_problema": descricao,
            "prioridade": prioridade}, erros


@bp.route("/pedidos/novo", methods=["GET", "POST"])
@permissao("pedidos.criar")
def novo():
    db = database.get_db()
    if request.method == "GET":
        return render_template("pedido_form.html", **_ctx_form(db))
    dados, erros = _validar(db, Form(request.form))
    if erros:
        return render_template("pedido_form.html", **_ctx_form(db, erros=erros,
                                                                valores=montar_valores(request.form, CAMPOS_FORM)))
    with transacao(db):
        cur = db.execute(
            "INSERT INTO pedidos_manutencao (id_equipamento, id_departamento, data_solicitacao, solicitante, "
            "id_usuario_solicitante, descricao_problema, prioridade, status) VALUES (?, ?, ?, ?, ?, ?, ?, 'Aberto')",
            (dados["id_equipamento"], dados["id_departamento"], hoje_iso(), g.usuario["nome"], g.usuario["id"],
             dados["descricao_problema"], dados["prioridade"]))
        auditoria.registrar(db, "pedido", cur.lastrowid, "criar", f"Pedido aberto (prioridade {dados['prioridade']})")
    flash(f"Pedido {srv.numero_pedido(cur.lastrowid)} aberto com sucesso.", "sucesso")
    return redirect(url_for("pedidos.detalhe", id=cur.lastrowid))


@bp.route("/pedidos/<int:id>/editar", methods=["GET", "POST"])
@permissao("pedidos.editar")
def editar(id):
    db = database.get_db()
    pedido = _preparar(_pedido_visivel(db, id))
    if pedido["status"] not in ("Aberto", "Em andamento"):
        flash(f"O pedido {pedido['numero']} está {pedido['status'].lower()} e não pode ser editado.", "aviso")
        return redirect(url_for("pedidos.detalhe", id=id))
    if request.method == "GET":
        return render_template("pedido_form.html", **_ctx_form(db, pedido=pedido))
    dados, erros = _validar(db, Form(request.form))
    if erros:
        return render_template("pedido_form.html", **_ctx_form(db, pedido=pedido, erros=erros,
                                                                valores=montar_valores(request.form, CAMPOS_FORM)))
    with transacao(db):
        db.execute("UPDATE pedidos_manutencao SET id_equipamento = ?, id_departamento = ?, descricao_problema = ?, "
                   "prioridade = ? WHERE id = ?",
                   (dados["id_equipamento"], dados["id_departamento"], dados["descricao_problema"],
                    dados["prioridade"], id))
        if dados["id_equipamento"] != pedido["id_equipamento"]:
            # a OS ativa acompanha o novo equipamento
            db.execute("UPDATE ordens_servico SET id_equipamento = ? WHERE id_pedido = ? AND status IN ('Aberta', 'Em andamento')",
                       (dados["id_equipamento"], id))
            srv.sincronizar_equipamento(db, pedido["id_equipamento"])
            srv.sincronizar_equipamento(db, dados["id_equipamento"])
        auditoria.registrar(db, "pedido", id, "editar", f"Pedido editado (prioridade {dados['prioridade']})")
    flash(f"Pedido {pedido['numero']} atualizado com sucesso.", "sucesso")
    return redirect(url_for("pedidos.detalhe", id=id))


# ---------------------------------------------------------------------------
# Detalhe e acoes
# ---------------------------------------------------------------------------
@bp.route("/pedidos/<int:id>")
@permissao("pedidos.ver")
def detalhe(id):
    db = database.get_db()
    pedido = _preparar(_pedido_visivel(db, id))
    os_ = None
    if pedido["id_os"]:
        os_ = preparar_os(db.execute(SELECT_OS + " WHERE os.id = ?", (pedido["id_os"],)).fetchone())
    aberto = pedido["status"] == "Aberto"
    return render_template(
        "pedido_detalhe.html", pedido=pedido, os=os_, historico=auditoria.historico_de(db, "pedido", id),
        pode_editar=pode("pedidos.editar") and pedido["status"] in ("Aberto", "Em andamento"),
        pode_cancelar=pode("pedidos.cancelar") and aberto and os_ is None,
        pode_aprovar=pode("pedidos.aprovar") and pedido["status"] in ("Aberto", "Em andamento") and not pedido["aprovado"],
        pode_abrir_os=pode("pedidos.abrir_os") and aberto and os_ is None)


@bp.route("/pedidos/<int:id>/cancelar", methods=["POST"])
@permissao("pedidos.cancelar")
def cancelar(id):
    db = database.get_db()
    _pedido_visivel(db, id)
    try:
        with transacao(db):
            srv.cancelar_pedido(db, id)
        flash(f"Pedido {srv.numero_pedido(id)} cancelado.", "sucesso")
    except ErroNegocio as e:
        flash_erro(e)
    return redirect(url_for("pedidos.detalhe", id=id))


@bp.route("/pedidos/<int:id>/aprovar", methods=["POST"])
@permissao("pedidos.aprovar")
def aprovar(id):
    db = database.get_db()
    _pedido_visivel(db, id)
    try:
        with transacao(db):
            srv.aprovar_pedido(db, id, g.usuario["nome"])
        flash(f"Pedido {srv.numero_pedido(id)} aprovado.", "sucesso")
    except ErroNegocio as e:
        flash_erro(e)
    return redirect(url_for("pedidos.detalhe", id=id))


@bp.route("/pedidos/<int:id>/abrir-os", methods=["GET", "POST"])
@permissao("pedidos.abrir_os")
def abrir_os(id):
    """GET: leva ao formulario de nova OS ja com o pedido escolhido.
    POST: abre a OS direto, com o `id_tecnico` enviado ou (sem ele) o proprio usuario quando ele e Tecnico;
    caso contrario leva ao formulario para escolher o tecnico."""
    db = database.get_db()
    ou_404(db.execute("SELECT id FROM pedidos_manutencao WHERE id = ?", (id,)).fetchone())
    id_tecnico = inteiro_ou_none(Form(request.form).get("id_tecnico")) if request.method == "POST" else None
    if request.method == "POST" and not id_tecnico and "Técnico" in g.usuario["perfis"]:
        id_tecnico = usuario_id()
    if id_tecnico:
        try:
            with transacao(db):
                id_os = srv.abrir_os(db, id_tecnico, Form(request.form).get("observacao"), id_pedido=id)
            flash(f"{srv.numero_os(id_os)} aberta com sucesso.", "sucesso")
            return redirect(url_for("ordens.detalhe", id=id_os))
        except ErroNegocio as e:
            flash_erro(e)
            return redirect(url_for("pedidos.detalhe", id=id))
    return redirect(url_for("ordens.nova", pedido_id=id))
