"""
modulos/prestadores/rotas.py
-----------------------------
SB-110 - CRUD de Prestadores de Servico.

E quase igual ao de prestadores, de proposito: a validacao do CNPJ e
IMPORTADA de validadores.py (nunca copiada e colada), e a exclusao e
LOGICA. A listagem mostra so os ativos, com a opcao "mostrar inativos".

Rotas de TELA                              Rotas da API (JSON)
-------------                              -------------------
GET      /prestadores/                    GET    /api/prestadores   (?inativos=1)
GET/POST /prestadores/novo                POST   /api/prestadores
GET/POST /prestadores/editar/<id>         GET    /api/prestadores/<id>
POST     /prestadores/desativar/<id>      PUT    /api/prestadores/<id>
POST     /prestadores/reativar/<id>       DELETE /api/prestadores/<id>  (desativa)
"""

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for

import api
from seguranca import requer_permissao
from validadores import Validacao, formatar_cnpj

from . import dados

bp = Blueprint("prestadores", __name__)


def validar(entrada, id_prestador=None):
    v = Validacao(entrada)
    v.texto("razao_social", obrigatorio=True, maximo=150, rotulo="a razao social")
    cnpj = v.cnpj("cnpj")
    v.texto("especialidade", maximo=80, rotulo="a especialidade")
    v.email("email")
    v.texto("telefone", maximo=20, rotulo="o telefone")
    v.texto("contato", maximo=100, rotulo="o contato")
    # CNPJ repetido: mensagem amigavel aqui, e o UNIQUE do banco como garantia.
    if "cnpj" not in v.erros and dados.cnpj_em_uso(cnpj, id_prestador):
        v.erro("cnpj", "Ja existe um prestador com este CNPJ.")
    return v


def para_json(linha):
    resposta = {campo: linha[campo] for campo in ["id"] + dados.CAMPOS}
    resposta["cnpj_formatado"] = formatar_cnpj(linha["cnpj"])
    resposta["ativo"] = bool(linha["ativo"])
    resposta["data_cadastro"] = linha["data_cadastro"]
    return resposta


def _form(titulo, item, erros, codigo=200):
    return render_template("prestadores/form.html", titulo=titulo, item=item, erros=erros), codigo


# ---------------------------------------------------------------------------
# TELAS
# ---------------------------------------------------------------------------


@bp.route("/prestadores/")
@requer_permissao("prestadores:ver")
def listar():
    busca = request.args.get("busca", "").strip()
    inativos = request.args.get("inativos") == "1"
    return render_template("prestadores/listar.html", prestadores=dados.listar(busca, inativos),
                           busca=busca, inativos=inativos)


@bp.route("/prestadores/novo", methods=["GET", "POST"])
@requer_permissao("prestadores:editar")
def novo():
    if request.method == "POST":
        v = validar(request.form)
        if v.erros:
            flash("Corrija os campos destacados.", "erro")
            return _form("Novo prestador de servico", request.form, v.erros, 422)
        dados.criar(v.dados)
        flash("Prestador criado.", "sucesso")
        return redirect(url_for("prestadores.listar"))
    return _form("Novo prestador de servico", None, {})


@bp.route("/prestadores/editar/<int:id_prestador>", methods=["GET", "POST"])
@requer_permissao("prestadores:editar")
def editar(id_prestador):
    prestador = dados.buscar(id_prestador)
    if prestador is None:
        flash("Prestador nao encontrado.", "erro")
        return redirect(url_for("prestadores.listar"))

    if request.method == "POST":
        v = validar(request.form, id_prestador)
        if v.erros:
            flash("Corrija os campos destacados.", "erro")
            return _form("Editar prestador de servico", request.form, v.erros, 422)
        dados.atualizar(id_prestador, v.dados)
        flash("Prestador atualizado.", "sucesso")
        return redirect(url_for("prestadores.listar"))

    item = dict(prestador)
    item["cnpj"] = formatar_cnpj(item["cnpj"])  # mostra com mascara no campo
    return _form("Editar prestador de servico", item, {})


@bp.route("/prestadores/desativar/<int:id_prestador>", methods=["POST"])
@requer_permissao("prestadores:editar")
def desativar(id_prestador):
    if dados.buscar(id_prestador) is None:
        flash("Prestador nao encontrado.", "erro")
    else:
        dados.definir_ativo(id_prestador, False)
        flash("Prestador desativado. O historico foi mantido.", "sucesso")
    return redirect(url_for("prestadores.listar"))


@bp.route("/prestadores/reativar/<int:id_prestador>", methods=["POST"])
@requer_permissao("prestadores:editar")
def reativar(id_prestador):
    if dados.buscar(id_prestador) is None:
        flash("Prestador nao encontrado.", "erro")
    else:
        dados.definir_ativo(id_prestador, True)
        flash("Prestador reativado.", "sucesso")
    return redirect(url_for("prestadores.listar", inativos=1))


# ---------------------------------------------------------------------------
# API JSON
# ---------------------------------------------------------------------------


@bp.route("/api/prestadores")
@requer_permissao("prestadores:ver")
def api_listar():
    busca = request.args.get("busca", "").strip()
    inativos = request.args.get("inativos") == "1"
    return jsonify([para_json(f) for f in dados.listar(busca, inativos)])


@bp.route("/api/prestadores/<int:id_prestador>")
@requer_permissao("prestadores:ver")
def api_buscar(id_prestador):
    prestador = dados.buscar(id_prestador)
    if prestador is None:
        return api.nao_encontrado("Prestador nao encontrado.")
    return jsonify(para_json(prestador))


@bp.route("/api/prestadores", methods=["POST"])
@requer_permissao("prestadores:editar")
def api_criar():
    v = validar(api.ler_json())
    if v.erros:
        return api.erro_validacao(v.erros)
    novo_id = dados.criar(v.dados)
    return jsonify(para_json(dados.buscar(novo_id))), 201


@bp.route("/api/prestadores/<int:id_prestador>", methods=["PUT"])
@requer_permissao("prestadores:editar")
def api_atualizar(id_prestador):
    if dados.buscar(id_prestador) is None:
        return api.nao_encontrado("Prestador nao encontrado.")
    v = validar(api.ler_json(), id_prestador)
    if v.erros:
        return api.erro_validacao(v.erros)
    dados.atualizar(id_prestador, v.dados)
    return jsonify(para_json(dados.buscar(id_prestador)))


@bp.route("/api/prestadores/<int:id_prestador>", methods=["DELETE"])
@requer_permissao("prestadores:editar")
def api_desativar(id_prestador):
    """DELETE na API tambem e exclusao logica: devolve o registro, agora inativo."""
    if dados.buscar(id_prestador) is None:
        return api.nao_encontrado("Prestador nao encontrado.")
    dados.definir_ativo(id_prestador, False)
    return jsonify(para_json(dados.buscar(id_prestador)))
