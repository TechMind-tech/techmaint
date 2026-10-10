"""
relatorios.py
-------------
Relatorios (abas Ordens de Servico, Estoque, Financeiro, Fornecedores) e exportacoes.

    /relatorios                          GET  relatorios.pagina     relatorios.html
    /api/relatorios/<aba>                GET  relatorios.api        JSON {tabela, graficos}
    /relatorios/<aba>/exportar.<fmt>     GET  relatorios.exportar   pdf | xlsx | csv  (Administrador e Gestor)

Regras:
- cada aba exige uma permissao (estoque.ver, fornecedores.ver, financeiro.ver); a aba "os" e de todos
- Usuario Comum so ve as proprias OS (filtro por solicitante) e nenhum valor em R$
- quem nao tem `financeiro.ver` nao recebe colunas/graficos em R$
"""

from flask import Blueprint, Response, abort, jsonify, render_template, request

import database
from servicos import exportacao, indicadores
from servicos.consultas import inteiro_ou_none
from servicos.periodos import PERIODOS, ROTULOS, periodo_valido
from servicos.permissoes import ABAS_RELATORIO, aba_permitida, permissao, pode
from modulos._comum import usuario_id

bp = Blueprint("relatorios", __name__)

TITULOS_ABAS = {"os": "Ordens de Serviço", "estoque": "Estoque", "financeiro": "Financeiro",
                "fornecedores": "Fornecedores"}
FORMATOS = {"pdf", "xlsx", "csv"}


def _filtros():
    return {
        "periodo": periodo_valido(request.args.get("periodo"), "30d"),
        "departamento_id": inteiro_ou_none(request.args.get("departamento_id")),
        "tecnico_id": inteiro_ou_none(request.args.get("tecnico_id")),
    }


def _gerar(db, aba, filtros):
    # Quem nao ve o dashboard (Usuario Comum) enxerga apenas as OS dos proprios pedidos.
    solicitante = None if pode("dashboard.ver") else usuario_id()
    return indicadores.relatorio(db, aba, filtros["periodo"], filtros["departamento_id"], filtros["tecnico_id"],
                                 financeiro=pode("financeiro.ver"), solicitante=solicitante)


def _exigir_aba(aba):
    if aba not in ABAS_RELATORIO:
        abort(404)
    if not aba_permitida(aba):
        abort(403)


@bp.route("/relatorios")
@permissao("relatorios.ver")
def pagina():
    db = database.get_db()
    aba = request.args.get("aba", "os")
    if aba not in ABAS_RELATORIO:
        aba = "os"
    _exigir_aba(aba)
    filtros = _filtros()
    rel = _gerar(db, aba, filtros)
    departamentos = [dict(r) for r in db.execute("SELECT id, nome FROM departamentos ORDER BY nome")]
    tecnicos = [dict(r) for r in db.execute(
        "SELECT DISTINCT u.id, u.nome FROM usuarios u JOIN usuarios_perfis up ON up.id_usuario = u.id "
        "JOIN perfis p ON p.id = up.id_perfil WHERE u.ativo = 1 AND p.nome = 'Técnico' ORDER BY u.nome")]
    return render_template("relatorios.html", aba=aba, filtros=filtros, periodos=PERIODOS,
                           departamentos=departamentos, tecnicos=tecnicos,
                           tabela=rel["tabela"], graficos=rel["graficos"])


@bp.route("/api/relatorios/<aba>")
@permissao("relatorios.ver")
def api(aba):
    _exigir_aba(aba)
    rel = _gerar(database.get_db(), aba, _filtros())
    return jsonify({"aba": aba, "tabela": rel["tabela"], "graficos": rel["graficos"]})


def _filtros_texto(db, f):
    return [("Período", ROTULOS[f["periodo"]]),
            ("Departamento", indicadores._nome(db, "departamentos", "nome", f["departamento_id"]) or "Todos"),
            ("Técnico", indicadores._nome(db, "usuarios", "nome", f["tecnico_id"]) or "Todos")]


@bp.route("/relatorios/<aba>/exportar.<fmt>")
@permissao("relatorios.exportar")
def exportar(aba, fmt):
    if fmt not in FORMATOS:
        abort(404)
    _exigir_aba(aba)
    db = database.get_db()
    f = _filtros()
    rel = _gerar(db, aba, f)
    nome = f"relatorio_{aba}"
    if fmt == "csv":
        return Response(exportacao.gerar_csv({**rel["tabela"]}), mimetype="text/csv", headers={
            "Content-Type": exportacao.MIME_CSV,
            "Content-Disposition": f'attachment; filename="{exportacao.nome_arquivo(nome, "csv")}"'})
    doc = exportacao.doc_relatorio(TITULOS_ABAS[aba], rel, _filtros_texto(db, f))
    if fmt == "pdf":
        return Response(exportacao.gerar_pdf(doc), mimetype=exportacao.MIME_PDF, headers={
            "Content-Disposition": f'attachment; filename="{exportacao.nome_arquivo(nome, "pdf")}"'})
    return Response(exportacao.gerar_xlsx(doc), mimetype=exportacao.MIME_XLSX, headers={
        "Content-Disposition": f'attachment; filename="{exportacao.nome_arquivo(nome, "xlsx")}"'})
