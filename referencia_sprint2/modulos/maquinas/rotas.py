"""
modulos/maquinas/rotas.py
-------------------------
SB-104 - CRUD de Maquinas. Mesma estrutura de departamentos/rotas.py,
com duas novidades:

  1. um campo que aponta para OUTRA tabela (id_departamento), escolhido
     num <select> montado a partir do banco;
  2. filtros na listagem (departamento e status), que vao na URL:
     /maquinas/?departamento=2&status=PARADO

Rotas de TELA                          Rotas da API (JSON)
-------------                          -------------------
GET      /maquinas/                    GET    /api/maquinas
GET/POST /maquinas/novo                POST   /api/maquinas
GET/POST /maquinas/editar/<id>         GET    /api/maquinas/<id>
POST     /maquinas/apagar/<id>         PUT    /api/maquinas/<id>
                                       DELETE /api/maquinas/<id>
"""

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for

import api
from modulos.departamentos import dados as departamentos_dados
from seguranca import requer_permissao
from validadores import Validacao

from . import dados
from .dados import STATUS

bp = Blueprint("maquinas", __name__)


def validar(entrada, id_maquina=None):
    v = Validacao(entrada)
    v.texto("nome", obrigatorio=True, maximo=100, rotulo="o nome")
    patrimonio = v.texto("patrimonio", maximo=30, rotulo="o patrimonio")
    v.texto("fabricante", maximo=60, rotulo="o fabricante")
    v.texto("modelo", maximo=60, rotulo="o modelo")
    id_departamento = v.inteiro("id_departamento", rotulo="o departamento")
    v.escolha("status", STATUS, rotulo="status", padrao="OPERANDO")

    if patrimonio and dados.patrimonio_em_uso(patrimonio, id_maquina):
        v.erro("patrimonio", "Ja existe uma maquina com este patrimonio.")
    # A chave estrangeira precisa apontar para um departamento que EXISTE.
    if id_departamento and departamentos_dados.buscar(id_departamento) is None:
        v.erro("id_departamento", "Departamento nao encontrado.")
    return v


def motivo_para_nao_apagar(id_maquina):
    total = dados.total_pecas(id_maquina)
    if total:
        return f"Esta maquina tem {total} peca(s) cadastrada(s). Apague as pecas antes."
    return None


def para_json(linha):
    return {
        "id": linha["id"],
        "nome": linha["nome"],
        "patrimonio": linha["patrimonio"],
        "fabricante": linha["fabricante"],
        "modelo": linha["modelo"],
        "id_departamento": linha["id_departamento"],
        "departamento": linha["departamento"],
        "status": linha["status"],
    }


def _filtros():
    """Le os filtros da URL. Valor invalido e simplesmente ignorado."""
    busca = request.args.get("busca", "").strip()
    departamento = request.args.get("departamento", type=int)
    status = request.args.get("status")
    if status not in STATUS:
        status = None
    return busca, departamento, status


def _form(titulo, item, erros, codigo=200):
    """Renderiza o formulario. Separado porque as 4 chamadas eram iguais."""
    return render_template(
        "maquinas/form.html", titulo=titulo, item=item, erros=erros,
        departamentos=departamentos_dados.listar_para_escolha(), status_possiveis=STATUS,
    ), codigo


# ---------------------------------------------------------------------------
# TELAS
# ---------------------------------------------------------------------------


@bp.route("/maquinas/")
@requer_permissao("maquinas:ver")
def listar():
    busca, departamento, status = _filtros()
    return render_template(
        "maquinas/listar.html",
        maquinas=dados.listar(busca, departamento, status),
        departamentos=departamentos_dados.listar_para_escolha(),
        status_possiveis=STATUS,
        busca=busca, departamento=departamento, status=status,
    )


@bp.route("/maquinas/novo", methods=["GET", "POST"])
@requer_permissao("maquinas:editar")
def novo():
    if request.method == "POST":
        v = validar(request.form)
        if v.erros:
            flash("Corrija os campos destacados.", "erro")
            return _form("Nova maquina", request.form, v.erros, 422)
        dados.criar(v.dados)
        flash("Maquina criada.", "sucesso")
        return redirect(url_for("maquinas.listar"))

    if not departamentos_dados.listar_para_escolha():
        flash("Cadastre um departamento antes de cadastrar maquinas.", "erro")
        return redirect(url_for("departamentos.novo"))
    return _form("Nova maquina", None, {})


@bp.route("/maquinas/editar/<int:id_maquina>", methods=["GET", "POST"])
@requer_permissao("maquinas:editar")
def editar(id_maquina):
    maquina = dados.buscar(id_maquina)
    if maquina is None:
        flash("Maquina nao encontrada.", "erro")
        return redirect(url_for("maquinas.listar"))

    if request.method == "POST":
        v = validar(request.form, id_maquina)
        if v.erros:
            flash("Corrija os campos destacados.", "erro")
            return _form("Editar maquina", request.form, v.erros, 422)
        dados.atualizar(id_maquina, v.dados)
        flash("Maquina atualizada.", "sucesso")
        return redirect(url_for("maquinas.listar"))

    return _form("Editar maquina", maquina, {})


@bp.route("/maquinas/apagar/<int:id_maquina>", methods=["POST"])
@requer_permissao("maquinas:editar")
def apagar(id_maquina):
    motivo = motivo_para_nao_apagar(id_maquina)
    if motivo:
        flash(motivo, "erro")
    else:
        dados.apagar(id_maquina)
        flash("Maquina apagada.", "sucesso")
    return redirect(url_for("maquinas.listar"))


# ---------------------------------------------------------------------------
# API JSON
# ---------------------------------------------------------------------------


@bp.route("/api/maquinas")
@requer_permissao("maquinas:ver")
def api_listar():
    busca, departamento, status = _filtros()
    return jsonify([para_json(m) for m in dados.listar(busca, departamento, status)])


@bp.route("/api/maquinas/<int:id_maquina>")
@requer_permissao("maquinas:ver")
def api_buscar(id_maquina):
    maquina = dados.buscar(id_maquina)
    if maquina is None:
        return api.nao_encontrado("Maquina nao encontrada.")
    return jsonify(para_json(maquina))


@bp.route("/api/maquinas", methods=["POST"])
@requer_permissao("maquinas:editar")
def api_criar():
    v = validar(api.ler_json())
    if v.erros:
        return api.erro_validacao(v.erros)
    novo_id = dados.criar(v.dados)
    return jsonify(para_json(dados.buscar(novo_id))), 201


@bp.route("/api/maquinas/<int:id_maquina>", methods=["PUT"])
@requer_permissao("maquinas:editar")
def api_atualizar(id_maquina):
    if dados.buscar(id_maquina) is None:
        return api.nao_encontrado("Maquina nao encontrada.")
    v = validar(api.ler_json(), id_maquina)
    if v.erros:
        return api.erro_validacao(v.erros)
    dados.atualizar(id_maquina, v.dados)
    return jsonify(para_json(dados.buscar(id_maquina)))


@bp.route("/api/maquinas/<int:id_maquina>", methods=["DELETE"])
@requer_permissao("maquinas:editar")
def api_apagar(id_maquina):
    if dados.buscar(id_maquina) is None:
        return api.nao_encontrado("Maquina nao encontrada.")
    motivo = motivo_para_nao_apagar(id_maquina)
    if motivo:
        return api.conflito(motivo)
    dados.apagar(id_maquina)
    return "", 204
