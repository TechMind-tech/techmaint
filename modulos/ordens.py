"""
ordens.py
---------
Ordens de Servico (OS). Fluxo: Pedido -> OS -> pecas/servicos/apontamentos -> Fechar OS.

    /os                                   GET                 ordens.listar          os_lista.html
    /os/nova                              GET, POST           ordens.nova            os_form.html
    /os/<id>                              GET                 ordens.detalhe         os_detalhe.html
    /os/<id>/editar                       GET, POST           ordens.editar          os_form.html
    /os/<id>/pecas                        POST                ordens.adicionar_peca
    /os/<id>/pecas/<item>/editar          POST                ordens.editar_peca
    /os/<id>/pecas/<item>/excluir         POST                ordens.excluir_peca
    /os/<id>/servicos                     POST                ordens.adicionar_servico
    /os/<id>/servicos/<sid>/excluir       POST                ordens.excluir_servico
    /os/<id>/apontamentos                 POST                ordens.adicionar_apontamento
    /os/<id>/apontamentos/<aid>/excluir   POST                ordens.excluir_apontamento
    /os/<id>/fechar | /excluir | /reabrir POST                ordens.fechar / excluir / reabrir

As regras (estoque, status do pedido e do equipamento) ficam em servicos/manutencao.py.
Perfis: Administrador e Tecnico fazem tudo; Gestor ve e fecha; Usuario Comum so consulta as proprias.
"""

from datetime import date

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

import database
from database import transacao
from modulos._comum import flash_erro, ou_404, selecionado, usuario_id, usuario_nome
from servicos import alertas as srv_alertas
from servicos import auditoria
from servicos import manutencao as srv
from servicos.consultas import filtro_busca, inteiro_ou_none, ordenacao, paginacao
from servicos.erros import ErroNegocio
from servicos.formatacao import (data_br, data_hora_br, data_iso, hoje, hoje_iso, moeda, normalizar, parse_data,
                                 qtd_br)
from servicos.formularios import Form, expandir_erros, montar_valores
from servicos.permissoes import COM, e_perfil, permissao, pode
from servicos.validacoes import erro_tamanho, validar_decimal

bp = Blueprint("ordens", __name__)

CAMPOS_FORM = ["id_pedido", "id_tecnico", "observacao", "status", "id_equipamento"]

SELECT_OS = """
    SELECT os.id, os.id_pedido, os.id_equipamento, os.data_abertura, os.data_fechamento, os.id_tecnico,
           COALESCE(u.nome, os.responsavel) AS tecnico, os.responsavel, os.status, os.observacao,
           p.prioridade, p.solicitante, p.descricao_problema, p.id_usuario_solicitante, p.status AS status_pedido,
           e.descricao AS equipamento, e.codigo AS equipamento_codigo,
           COALESCE(p.id_departamento, e.id_departamento) AS id_departamento, d.nome AS departamento
    FROM ordens_servico os
    LEFT JOIN usuarios u ON u.id = os.id_tecnico
    LEFT JOIN pedidos_manutencao p ON p.id = os.id_pedido
    LEFT JOIN equipamentos e ON e.id = os.id_equipamento
    LEFT JOIN departamentos d ON d.id = COALESCE(p.id_departamento, e.id_departamento)
"""

SLUGS_STATUS = {"aberta": "Aberta", "andamento": "Em andamento", "emandamento": "Em andamento",
                "concluida": "Concluída", "cancelada": "Cancelada"}


def _slug(texto):
    return normalizar(texto).replace(" ", "").replace("-", "").replace("_", "")


def _so_proprias():
    """Usuario Comum (sem poder de gestao) ve apenas as OS dos proprios pedidos."""
    return e_perfil(COM) and not pode("os.gerir") and not pode("os.fechar")


def preparar_os(linha, dias_limite=None):
    """Linha do banco -> dict para a tela (numero, datas formatadas, atraso)."""
    o = dict(linha)
    o["numero"] = srv.numero_os(o["id"])
    o["pedido_numero"] = srv.numero_pedido(o["id_pedido"]) if o["id_pedido"] else ""
    o["data_abertura_fmt"] = data_br(o["data_abertura"])
    o["data_abertura_hora_fmt"] = data_hora_br(o["data_abertura"])
    o["data_abertura_iso"] = data_iso(o["data_abertura"])
    o["data_fechamento_fmt"] = data_br(o["data_fechamento"]) if o["data_fechamento"] else ""
    o["data_fechamento_iso"] = data_iso(o["data_fechamento"])
    o["pedido_id"], o["tecnico_id"] = o["id_pedido"], o["id_tecnico"]
    dias = (hoje() - date.fromisoformat(o["data_abertura"][:10])).days
    o["dias_aberta"] = max(dias, 0) if o["status"] in srv.OS_ABERTAS else 0
    limite = srv_alertas.dias_limite_os() if dias_limite is None else dias_limite
    o["atrasada"] = o["status"] in srv.OS_ABERTAS and dias > limite
    return o


def _tecnicos(db):
    return [dict(t) for t in db.execute(
        "SELECT u.id, u.nome FROM usuarios u JOIN usuarios_perfis up ON up.id_usuario = u.id "
        "JOIN perfis p ON p.id = up.id_perfil WHERE p.nome = 'Técnico' AND u.ativo = 1 ORDER BY u.nome")]


def _os_visivel(db, id_os):
    """Busca a OS respeitando a regra do Usuario Comum (so as proprias -> 403)."""
    os_ = ou_404(db.execute(SELECT_OS + " WHERE os.id = ?", (id_os,)).fetchone())
    if _so_proprias():
        from flask import g
        if os_["id_usuario_solicitante"] != g.usuario["id"]:
            abort(403)
    return os_


def _pedidos_disponiveis(db, incluir_id=None):
    linhas = db.execute(
        "SELECT p.id, p.prioridade, p.data_solicitacao, p.solicitante, e.descricao AS equipamento, "
        "d.nome AS departamento FROM pedidos_manutencao p JOIN equipamentos e ON e.id = p.id_equipamento "
        "JOIN departamentos d ON d.id = p.id_departamento "
        "WHERE p.status = 'Aberto' AND NOT EXISTS (SELECT 1 FROM ordens_servico os "
        "WHERE os.id_pedido = p.id AND os.status <> 'Cancelada') ORDER BY p.id DESC").fetchall()
    resultado = []
    for p in linhas:
        d = dict(p)
        d["numero"] = srv.numero_pedido(p["id"])
        d["rotulo"] = f"{d['numero']} | {p['equipamento']} ({p['prioridade']})"
        d["data_solicitacao_fmt"] = data_br(p["data_solicitacao"])
        resultado.append(d)
    return resultado


# ---------------------------------------------------------------------------
# Lista
# ---------------------------------------------------------------------------
@bp.route("/os")
@permissao("os.ver")
def listar():
    from flask import g
    db = database.get_db()
    busca = request.args.get("busca", "").strip()
    status_txt = selecionado(request.args, "status", "filtro_status")
    status = SLUGS_STATUS.get(_slug(status_txt), "")
    tecnico_id = inteiro_ou_none(selecionado(request.args, "tecnico_id", "id_tecnico", "tecnico"))

    base, base_params = [], []
    if _so_proprias():
        base.append("p.id_usuario_solicitante = ?")
        base_params.append(g.usuario["id"])
    onde, params = list(base), list(base_params)
    trecho, ps = filtro_busca(busca, ["'OS-' || os.id", "CAST(os.id AS TEXT)", "'#' || p.id", "e.descricao", "e.codigo",
                                      "COALESCE(u.nome, os.responsavel, '')", "p.solicitante"])
    if trecho:
        onde.append(trecho)
        params += ps
    if status:
        onde.append("os.status = ?")
        params.append(status)
    if tecnico_id:
        onde.append("os.id_tecnico = ?")
        params.append(tecnico_id)
    where = (" WHERE " + " AND ".join(onde)) if onde else ""
    where_base = (" WHERE " + " AND ".join(base)) if base else ""

    total = db.execute(f"SELECT COUNT(*) FROM ordens_servico os LEFT JOIN usuarios u ON u.id = os.id_tecnico "
                       f"LEFT JOIN pedidos_manutencao p ON p.id = os.id_pedido "
                       f"LEFT JOIN equipamentos e ON e.id = os.id_equipamento{where}", params).fetchone()[0]
    pag = paginacao(request.args, total)
    ordem = ordenacao(request.args, {"numero": "os.id", "abertura": "os.data_abertura", "status": "os.status",
                                     "tecnico": "tecnico"}, "os.id DESC")
    linhas = db.execute(SELECT_OS + where + f" ORDER BY {ordem} LIMIT ? OFFSET ?",
                        params + [pag["limite"], pag["deslocamento"]]).fetchall()
    dias = srv_alertas.dias_limite_os(db)

    resumo = {"aberta": 0, "andamento": 0, "concluida": 0, "cancelada": 0}
    chaves = {"Aberta": "aberta", "Em andamento": "andamento", "Concluída": "concluida", "Cancelada": "cancelada"}
    for r in db.execute("SELECT os.status, COUNT(*) AS n FROM ordens_servico os "
                        "LEFT JOIN pedidos_manutencao p ON p.id = os.id_pedido" + where_base + " GROUP BY os.status",
                        base_params):
        resumo[chaves[r["status"]]] = r["n"]

    sem_os_sql = ("SELECT COUNT(*) FROM pedidos_manutencao p WHERE p.status = 'Aberto' AND NOT EXISTS "
                  "(SELECT 1 FROM ordens_servico os WHERE os.id_pedido = p.id AND os.status <> 'Cancelada')")
    sem_os_params = []
    if _so_proprias():
        sem_os_sql += " AND p.id_usuario_solicitante = ?"
        sem_os_params.append(g.usuario["id"])
    pedidos_sem_os = db.execute(sem_os_sql, sem_os_params).fetchone()[0]

    ctx = {"itens": [preparar_os(l, dias) for l in linhas], "resumo": resumo, "pedidos_sem_os": pedidos_sem_os,
           "status": status, "tecnico_id": tecnico_id, "busca": busca, "filtro_status": status,
           "filtro_tecnico": tecnico_id, "tecnicos": _tecnicos(db), "status_opcoes": list(srv.STATUS_OS),
           "total": total, "paginacao": pag}
    ctx.update({k: pag[k] for k in ("pagina", "por_pagina", "total_paginas")})
    return render_template("os_lista.html", **ctx)


# ---------------------------------------------------------------------------
# Nova OS / editar OS
# ---------------------------------------------------------------------------
def _ctx_form(db, os_=None, erros=None, valores=None, pedido_id=None):
    from flask import g
    disponiveis = _pedidos_disponiveis(db)
    if os_ and os_["id_pedido"] and all(p["id"] != os_["id_pedido"] for p in disponiveis):
        disponiveis.insert(0, {"id": os_["id_pedido"], "numero": os_["pedido_numero"],
                               "equipamento": os_["equipamento"], "rotulo": f"{os_['pedido_numero']} | {os_['equipamento']}"})
    tecnicos = _tecnicos(db)
    if valores is None:
        valores = {}
        if os_:
            valores = {"id_pedido": os_["id_pedido"] or "", "id_tecnico": os_["id_tecnico"] or "",
                       "observacao": os_["observacao"] or "", "status": os_["status"],
                       "id_equipamento": os_["id_equipamento"] or ""}
        else:
            padrao_tec = g.usuario["id"] if any(t["id"] == g.usuario["id"] for t in tecnicos) else \
                (tecnicos[0]["id"] if tecnicos else "")
            valores = {"id_pedido": pedido_id or "", "id_tecnico": padrao_tec, "observacao": "", "id_equipamento": ""}
    equipamentos = [dict(e) for e in db.execute(
        "SELECT id, codigo, descricao FROM equipamentos WHERE status <> 'Baixado' ORDER BY descricao")]
    return {"pedidos_disponiveis": disponiveis, "tecnicos": tecnicos, "valores": valores,
            "erros": expandir_erros(erros or {}), "pedido_id": pedido_id, "os": os_, "item": os_,
            "equipamentos": equipamentos, "status_opcoes": ["Aberta", "Em andamento", "Cancelada"],
            "editando": os_ is not None}


@bp.route("/os/nova", methods=["GET", "POST"])
@permissao("os.gerir")
def nova():
    db = database.get_db()
    pedido_id = inteiro_ou_none(selecionado(request.args, "pedido_id", "id_pedido", "pedido"))
    if request.method == "GET":
        return render_template("os_form.html", **_ctx_form(db, pedido_id=pedido_id))

    f = Form(request.form)
    id_pedido = inteiro_ou_none(f.get("id_pedido"))
    id_tecnico = inteiro_ou_none(f.get("id_tecnico"))
    id_equip = inteiro_ou_none(f.get("id_equipamento"))
    observacao = f.get("observacao")
    erros = {}
    if id_tecnico is None:
        erros["id_tecnico"] = "Selecione o técnico responsável."
    msg = erro_tamanho(observacao, "as observações", 500)
    if msg:
        erros["observacao"] = msg
    if f.get("id_pedido") and id_pedido is None:
        erros["id_pedido"] = "Pedido inválido."
    if f.get("id_equipamento") and (id_equip is None or db.execute(
            "SELECT 1 FROM equipamentos WHERE id = ?", (id_equip,)).fetchone() is None):
        erros["id_equipamento"] = "Equipamento inválido."
    novo_id = None
    if not erros:
        try:
            with transacao(db):
                novo_id = srv.abrir_os(db, id_tecnico, observacao, id_pedido=id_pedido, id_equipamento=id_equip)
        except ErroNegocio as e:
            erros[e.campo or "id_pedido"] = e.mensagem
    if erros:
        return render_template("os_form.html", **_ctx_form(db, erros=erros, valores=montar_valores(request.form, CAMPOS_FORM),
                                                           pedido_id=id_pedido))
    flash(f"{srv.numero_os(novo_id)} aberta com sucesso.", "sucesso")
    return redirect(url_for("ordens.detalhe", id=novo_id))


@bp.route("/os/<int:id>/editar", methods=["GET", "POST"])
@permissao("os.gerir")
def editar(id):
    db = database.get_db()
    os_ = preparar_os(ou_404(db.execute(SELECT_OS + " WHERE os.id = ?", (id,)).fetchone()))
    if os_["status"] not in srv.OS_ABERTAS:
        flash(f"A {os_['numero']} está {os_['status'].lower()} e é somente leitura.", "aviso")
        return redirect(url_for("ordens.detalhe", id=id))
    if request.method == "GET":
        return render_template("os_form.html", **_ctx_form(db, os_=os_))

    f = Form(request.form)
    id_tecnico = inteiro_ou_none(f.get("id_tecnico"))
    status = f.get("status") or os_["status"]
    observacao = f.get("observacao")
    id_equip = inteiro_ou_none(f.get("id_equipamento"))
    erros = {}
    if id_tecnico is None:
        erros["id_tecnico"] = "Selecione o técnico responsável."
    msg = erro_tamanho(observacao, "as observações", 500)
    if msg:
        erros["observacao"] = msg
    if not erros:
        try:
            with transacao(db):
                srv.alterar_os(db, id, id_tecnico, observacao, status, id_equipamento=id_equip)
        except ErroNegocio as e:
            erros[e.campo or "status"] = e.mensagem
    if erros:
        return render_template("os_form.html", **_ctx_form(db, os_=os_, erros=erros,
                                                           valores=montar_valores(request.form, CAMPOS_FORM)))
    flash(f"{os_['numero']} atualizada com sucesso.", "sucesso")
    return redirect(url_for("ordens.detalhe", id=id))


# ---------------------------------------------------------------------------
# Detalhe
# ---------------------------------------------------------------------------
@bp.route("/os/<int:id>")
@permissao("os.ver")
def detalhe(id):
    return _renderizar_detalhe(id)


def _renderizar_detalhe(id, erros=None, valores=None, status=200):
    """Monta a pagina da OS. Os formularios de peca/servico/apontamento, quando recusados, voltam
    para ca com `erros` (campo -> mensagem) e `valores` (o que a pessoa digitou), HTTP 200."""
    db = database.get_db()
    os_ = preparar_os(_os_visivel(db, id))
    restrito = _so_proprias()            # Usuario Comum: so o status (sem valores nem pecas)

    itens, servicos, apontamentos = [], [], []
    totais = {"pecas": 0.0, "servicos": 0.0, "geral": 0.0}
    if not restrito:
        for i in db.execute("SELECT i.id, i.id_peca, p.nome AS peca, p.codigo AS peca_codigo, i.quantidade, "
                            "i.valor_unitario, i.valor_total FROM itens_os i JOIN pecas p ON p.id = i.id_peca "
                            "WHERE i.id_os = ? ORDER BY i.id", (id,)):
            d = dict(i)
            d.update(quantidade_fmt=qtd_br(d["quantidade"]), valor_unitario_fmt=moeda(d["valor_unitario"]),
                     valor_total_fmt=moeda(d["valor_total"]))
            itens.append(d)
        for s in db.execute("SELECT s.id, s.descricao_servico, s.valor_servico, s.id_prestador, "
                            "pr.razao_social AS prestador FROM servicos_os s "
                            "LEFT JOIN prestadores_servico pr ON pr.id = s.id_prestador WHERE s.id_os = ? ORDER BY s.id",
                            (id,)):
            d = dict(s)
            d["valor_servico_fmt"] = moeda(d["valor_servico"])
            servicos.append(d)
        totais = srv.totais_os(db, id)
    for a in db.execute("SELECT * FROM apontamentos_os WHERE id_os = ? ORDER BY data, id", (id,)):
        d = dict(a)
        d.update(data_fmt=data_br(d["data"]), data_iso=data_iso(d["data"]),
                 horas_fmt=qtd_br(d["horas_trabalhadas"]) if d["horas_trabalhadas"] is not None else "")
        apontamentos.append(d)
    totais.update(pecas_fmt=moeda(totais["pecas"]), servicos_fmt=moeda(totais["servicos"]),
                  geral_fmt=moeda(totais["geral"]))

    editavel = os_["status"] in srv.OS_ABERTAS
    gerencia = pode("os.gerir") and editavel
    pecas_disp, prestadores = [], []
    if gerencia:
        for p in db.execute("SELECT p.id, p.codigo, p.nome, p.qtde_estoque, p.valor_unitario, p.id_equipamento "
                            "FROM pecas p ORDER BY (p.id_equipamento = ?) DESC, p.nome",
                            (os_["id_equipamento"] or -1,)):
            d = dict(p)
            d.update(qtde_fmt=qtd_br(d["qtde_estoque"]), valor_unitario_fmt=moeda(d["valor_unitario"]),
                     do_equipamento=d["id_equipamento"] == os_["id_equipamento"])
            pecas_disp.append(d)
        prestadores = [dict(p) for p in db.execute(
            "SELECT id, razao_social, razao_social AS nome, especialidade FROM prestadores_servico "
            "WHERE ativo = 1 ORDER BY razao_social")]

    pedido = None
    if os_["id_pedido"]:
        pedido = {"id": os_["id_pedido"], "numero": os_["pedido_numero"], "status": os_["status_pedido"],
                  "prioridade": os_["prioridade"], "solicitante": os_["solicitante"],
                  "descricao_problema": os_["descricao_problema"]}
    return render_template(
        "os_detalhe.html", os=os_, pedido=pedido, itens_os=itens, servicos_os=servicos, apontamentos=apontamentos,
        pecas_disponiveis=pecas_disp, prestadores=prestadores, tipos_apontamento=srv.TIPOS_APONTAMENTO, totais=totais,
        somente_leitura=not gerencia, pode_editar=gerencia, pode_fechar=pode("os.fechar") and editavel,
        pode_reabrir=pode("os.reabrir") and os_["status"] == "Concluída", pode_excluir=gerencia,
        visao_restrita=restrito, hoje_iso=hoje_iso(), status_opcoes=["Aberta", "Em andamento", "Cancelada"],
        historico=[] if restrito else auditoria.historico_de(db, "os", id), erros=expandir_erros(erros or {}),
        valores=valores or {}), status


# ---------------------------------------------------------------------------
# Acoes (POST) sobre a OS. Sucesso ou erro: volta para a pagina da OS com um aviso.
# ---------------------------------------------------------------------------
AVISO_OS_VAZIA = "OS fechada sem peças, serviços ou apontamentos."


def _executar(id, acao, mensagem_ok):
    """Roda `acao(db)` dentro de uma transacao. Devolve (True, None) ou (False, mensagem_de_erro).
    Se `acao` devolver um texto, ele vira um aviso (nao bloqueia) depois da mensagem de sucesso."""
    db = database.get_db()
    ou_404(db.execute("SELECT id FROM ordens_servico WHERE id = ?", (id,)).fetchone())
    try:
        with transacao(db):
            resultado = acao(db)
        flash(mensagem_ok, "sucesso")
        if isinstance(resultado, str):
            flash(resultado, "aviso")
        return True, None
    except ErroNegocio as e:
        return False, e


def _simples(id, acao, mensagem_ok):
    """Acao sem formulario (excluir, fechar...): o resultado vira um aviso e volta para a pagina da OS."""
    ok, erro = _executar(id, acao, mensagem_ok)
    if not ok:
        flash_erro(erro)
    return ok


def _recusado(id, mensagem, campo=None):
    """Formulario da OS recusado: a mesma pagina volta (HTTP 200) com o aviso e o erro no campo."""
    flash(mensagem, "erro")
    return _renderizar_detalhe(id, erros={campo or "geral": mensagem}, valores=request.form)


def _formulario(id, acao, mensagem_ok, campo_padrao=None):
    ok, erro = _executar(id, acao, mensagem_ok)
    if ok:
        return redirect(url_for("ordens.detalhe", id=id))
    return _recusado(id, erro.mensagem, erro.campo or campo_padrao)


@bp.route("/os/<int:id>/pecas", methods=["POST"])
@permissao("os.gerir")
def adicionar_peca(id):
    ou_404(database.get_db().execute("SELECT id FROM ordens_servico WHERE id = ?", (id,)).fetchone())
    f = Form(request.form)
    id_peca = inteiro_ou_none(f.get("id_peca"))
    qtd, msg = validar_decimal(f.get("quantidade"), "a quantidade", estrito=True)
    if id_peca is None:
        return _recusado(id, "Selecione uma peça.", "id_peca")
    if msg:
        return _recusado(id, msg, "quantidade")
    return _formulario(id, lambda db: srv.adicionar_peca(db, id, id_peca, qtd, usuario_id()), "Peça adicionada à OS.",
                       "quantidade")


@bp.route("/os/<int:id>/pecas/<int:item>/editar", methods=["POST"])
@permissao("os.gerir")
def editar_peca(id, item):
    ou_404(database.get_db().execute("SELECT id FROM ordens_servico WHERE id = ?", (id,)).fetchone())
    qtd, msg = validar_decimal(Form(request.form).get("quantidade"), "a quantidade", estrito=True)
    if msg:
        return _recusado(id, msg, "quantidade")
    return _formulario(id, lambda db: srv.editar_peca(db, id, item, qtd, usuario_id()),
                       "Quantidade da peça atualizada.", "quantidade")


@bp.route("/os/<int:id>/pecas/<int:item>/excluir", methods=["POST"])
@permissao("os.gerir")
def excluir_peca(id, item):
    _simples(id, lambda db: srv.excluir_peca(db, id, item, usuario_id()), "Peça removida da OS (estoque estornado).")
    return redirect(url_for("ordens.detalhe", id=id))


@bp.route("/os/<int:id>/servicos", methods=["POST"])
@permissao("os.gerir")
def adicionar_servico(id):
    f = Form(request.form)
    descricao = f.get("descricao_servico")
    msg_desc = erro_tamanho(descricao, "a descrição do serviço", 200, obrigatorio=True)
    valor, msg_val = validar_decimal(f.get("valor_servico") if f.tem("valor_servico") else "0", "o valor do serviço")
    id_prestador = inteiro_ou_none(f.get("id_prestador"))
    ou_404(database.get_db().execute("SELECT id FROM ordens_servico WHERE id = ?", (id,)).fetchone())
    if msg_desc:
        return _recusado(id, msg_desc, "descricao_servico")
    if msg_val:
        return _recusado(id, msg_val, "valor_servico")
    return _formulario(id, lambda db: srv.adicionar_servico(db, id, descricao, valor, id_prestador),
                       "Serviço adicionado à OS.", "descricao_servico")


@bp.route("/os/<int:id>/servicos/<int:sid>/excluir", methods=["POST"])
@permissao("os.gerir")
def excluir_servico(id, sid):
    _simples(id, lambda db: srv.excluir_servico(db, id, sid), "Serviço removido da OS.")
    return redirect(url_for("ordens.detalhe", id=id))


@bp.route("/os/<int:id>/apontamentos", methods=["POST"])
@permissao("os.gerir")
def adicionar_apontamento(id):
    f = Form(request.form)
    erro = None
    d = parse_data(f.get("data"))
    if not f.get("data"):
        erro = "Informe a data do apontamento."
    elif d is None:
        erro = "Data do apontamento inválida."
    horas, msg = validar_decimal(f.get("horas_trabalhadas"), "as horas trabalhadas", maximo=999)
    erro = erro or msg
    tipo = f.get("tipo")
    if tipo and tipo not in srv.TIPOS_APONTAMENTO:
        erro = erro or "Tipo de apontamento inválido."
    obs = f.get("observacao")
    erro = erro or erro_tamanho(obs, "a observação", 500)
    tecnico = f.get("tecnico") or usuario_nome()
    erro = erro or erro_tamanho(tecnico, "o técnico", 100)
    ou_404(database.get_db().execute("SELECT id FROM ordens_servico WHERE id = ?", (id,)).fetchone())
    if erro:
        return _recusado(id, erro, "horas_trabalhadas")
    return _formulario(id, lambda db: srv.adicionar_apontamento(db, id, d.isoformat(), tecnico, horas, tipo or None, obs),
                       "Apontamento registrado.", "horas_trabalhadas")


@bp.route("/os/<int:id>/apontamentos/<int:aid>/excluir", methods=["POST"])
@permissao("os.gerir")
def excluir_apontamento(id, aid):
    _simples(id, lambda db: srv.excluir_apontamento(db, id, aid), "Apontamento removido.")
    return redirect(url_for("ordens.detalhe", id=id))


@bp.route("/os/<int:id>/fechar", methods=["POST"])
@permissao("os.fechar")
def fechar(id):
    _simples(id, lambda db: AVISO_OS_VAZIA if srv.fechar_os(db, id) else None,
             f"{srv.numero_os(id)} fechada com sucesso.")
    return redirect(url_for("ordens.detalhe", id=id))


@bp.route("/os/<int:id>/reabrir", methods=["POST"])
@permissao("os.reabrir")
def reabrir(id):
    _simples(id, lambda db: srv.reabrir_os(db, id), f"{srv.numero_os(id)} reaberta.")
    return redirect(url_for("ordens.detalhe", id=id))


@bp.route("/os/<int:id>/excluir", methods=["POST"])
@permissao("os.gerir")
def excluir(id):
    if _simples(id, lambda db: srv.excluir_os(db, id), f"{srv.numero_os(id)} excluída."):
        return redirect(url_for("ordens.listar"))
    return redirect(url_for("ordens.detalhe", id=id))
