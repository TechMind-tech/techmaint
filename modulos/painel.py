"""
painel.py
---------
Pagina inicial, menu principal (cards) e Dashboard.

    /                           GET   painel.inicio          (redireciona para /dashboard ou /menu)
    /menu                       GET   painel.menu_principal  menu_principal.html
    /dashboard                  GET   painel.dashboard       dashboard.html
    /api/dashboard              GET   painel.api_dashboard   JSON (graficos + KPIs)
    /dashboard/exportar.pdf     GET   painel.exportar_pdf    (Administrador e Gestor)
    /dashboard/exportar.xlsx    GET   painel.exportar_xlsx   (Administrador e Gestor)

Os numeros vem de servicos/indicadores.py. Quem nao tem `financeiro.ver` nao recebe valores em R$.
"""

from flask import Blueprint, Response, jsonify, redirect, render_template, request, url_for

import database
from modulos._comum import ou_404
from servicos import exportacao, indicadores
from servicos.consultas import inteiro_ou_none
from servicos.periodos import PERIODOS, ROTULOS, periodo_valido
from servicos.permissoes import CARDS, MENU, permissao, pode

bp = Blueprint("painel", __name__)

PERIODO_PADRAO_DASHBOARD = "6m"


def _filtros():
    return {
        "periodo": periodo_valido(request.args.get("periodo"), PERIODO_PADRAO_DASHBOARD),
        "departamento_id": inteiro_ou_none(request.args.get("departamento_id")),
        "equipamento_id": inteiro_ou_none(request.args.get("equipamento_id")),
    }


def _dados(db, filtros):
    return indicadores.dashboard(db, filtros["periodo"], filtros["departamento_id"], filtros["equipamento_id"],
                                 financeiro=pode("financeiro.ver"))


def cards_do_usuario():
    """Os 6 cards do Menu Principal (Manual secao 5), so com o que o perfil pode abrir."""
    itens = {chave: (endpoint, perm) for _, lista in MENU for chave, _r, endpoint, _i, perm in lista}
    cards = []
    for chave, rotulo, descricao, icone, chaves in CARDS:
        alvo = next((itens[c][0] for c in chaves if c in itens and pode(itens[c][1])), None)
        if alvo:
            cards.append({"chave": chave, "rotulo": rotulo, "descricao": descricao, "icone": icone,
                          "endpoint": alvo, "url": url_for(alvo)})
    return cards


@bp.route("/")
def inicio():
    return redirect(url_for("painel.dashboard") if pode("dashboard.ver") else url_for("painel.menu_principal"))


@bp.route("/menu")
def menu_principal():
    return render_template("menu_principal.html", cards=cards_do_usuario())


@bp.route("/dashboard")
@permissao("dashboard.ver")
def dashboard():
    db = database.get_db()
    filtros = _filtros()
    dados = _dados(db, filtros)
    kpis = dict(dados["kpis"])
    # Para a tela, os 4 cartoes principais viram dicts {valor, valor_fmt, detalhe} (a API segue com numeros simples).
    por_chave = {c["chave"]: c for c in kpis["cards"]}
    kpis["pedidos_abertos"] = por_chave["pedidos_abertos"]
    kpis["os_andamento"] = por_chave["os_andamento"]
    kpis["os_concluidas"] = por_chave["os_concluidas_mes"]
    if "custo_total_mes" in por_chave:
        kpis["custo_total"] = por_chave["custo_total_mes"]
    departamentos = [dict(r) for r in db.execute("SELECT id, nome FROM departamentos ORDER BY nome")]
    equipamentos = [dict(r) for r in db.execute(
        "SELECT id, descricao AS nome FROM equipamentos WHERE status <> 'Baixado' ORDER BY descricao")]
    return render_template("dashboard.html", kpis=kpis, filtros=filtros, periodos=PERIODOS,
                           departamentos=departamentos, equipamentos=equipamentos,
                           titulo_periodo=dados["titulo_periodo"])


@bp.route("/api/dashboard")
@permissao("dashboard.ver")
def api_dashboard():
    return jsonify(_dados(database.get_db(), _filtros()))


def _filtros_texto(db, f):
    texto = [("Período", ROTULOS[f["periodo"]]),
             ("Departamento", indicadores._nome(db, "departamentos", "nome", f["departamento_id"]) or "Todos")]
    if f["equipamento_id"]:
        texto.append(("Equipamento", indicadores._nome(db, "equipamentos", "descricao", f["equipamento_id"]) or "Todos"))
    else:
        texto.append(("Equipamento", "Todos"))
    return texto


@bp.route("/dashboard/exportar.pdf")
@permissao("dashboard.exportar")
def exportar_pdf():
    db = database.get_db()
    f = _filtros()
    doc = exportacao.doc_dashboard(_dados(db, f), _filtros_texto(db, f))
    return Response(exportacao.gerar_pdf(doc), mimetype=exportacao.MIME_PDF, headers={
        "Content-Disposition": f'attachment; filename="{exportacao.nome_arquivo("dashboard", "pdf")}"'})


@bp.route("/dashboard/exportar.xlsx")
@permissao("dashboard.exportar")
def exportar_xlsx():
    db = database.get_db()
    f = _filtros()
    doc = exportacao.doc_dashboard(_dados(db, f), _filtros_texto(db, f))
    return Response(exportacao.gerar_xlsx(doc), mimetype=exportacao.MIME_XLSX, headers={
        "Content-Disposition": f'attachment; filename="{exportacao.nome_arquivo("dashboard", "xlsx")}"'})
