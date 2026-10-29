"""
modulos/fornecedores/rotas.py
-----------------------------
SB-108 - CRUD de Fornecedores, com duas regras importantes:

  1. CNPJ validado de verdade (digitos verificadores, em validadores.py),
     salvo so com numeros e mostrado com mascara 00.000.000/0000-00;
  2. exclusao LOGICA: "apagar" so desativa. Da para reativar depois.

Rotas de TELA                              Rotas da API (JSON)
-------------                              -------------------
GET      /fornecedores/                    GET    /api/fornecedores   (?inativos=1)
GET/POST /fornecedores/novo                POST   /api/fornecedores
GET/POST /fornecedores/editar/<id>         GET    /api/fornecedores/<id>
POST     /fornecedores/desativar/<id>      PUT    /api/fornecedores/<id>
POST     /fornecedores/reativar/<id>       DELETE /api/fornecedores/<id>  (desativa)
"""

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for

import api
from seguranca import requer_permissao
from validadores import Validacao, formatar_cnpj

from . import dados

bp = Blueprint("fornecedores", __name__)


def validar(entrada, id_fornecedor=None):
    v = Validacao(entrada)
    v.texto("razao_social", obrigatorio=True, maximo=150, rotulo="a razao social")
    v.texto("nome_fantasia", maximo=100, rotulo="o nome fantasia")
    cnpj = v.cnpj("cnpj")
    v.email("email")
    v.texto("telefone", maximo=20, rotulo="o telefone")
    v.texto("contato", maximo=100, rotulo="o contato")
    v.texto("endereco", maximo=200, rotulo="o endereco")
    # CNPJ repetido: mensagem amigavel aqui, e o UNIQUE do banco como garantia.
    if "cnpj" not in v.erros and dados.cnpj_em_uso(cnpj, id_fornecedor):
        v.erro("cnpj", "Ja existe um fornecedor com este CNPJ.")
    return v


def para_json(linha):
    resposta = {campo: linha[campo] for campo in ["id"] + dados.CAMPOS}
    resposta["cnpj_formatado"] = formatar_cnpj(linha["cnpj"])
    resposta["ativo"] = bool(linha["ativo"])
    resposta["data_cadastro"] = linha["data_cadastro"]
    return resposta


def _form(titulo, item, erros, codigo=200):
    return render_template("fornecedores/form.html", titulo=titulo, item=item, erros=erros), codigo


# ---------------------------------------------------------------------------
# TELAS
# ---------------------------------------------------------------------------


@bp.route("/fornecedores/")
@requer_permissao("fornecedores:ver")
def listar():
    busca = request.args.get("busca", "").strip()
    inativos = request.args.get("inativos") == "1"
    return render_template("fornecedores/listar.html", fornecedores=dados.listar(busca, inativos),
                           busca=busca, inativos=inativos)


@bp.route("/fornecedores/novo", methods=["GET", "POST"])
@requer_permissao("fornecedores:editar")
def novo():
    if request.method == "POST":
        v = validar(request.form)
        if v.erros:
            flash("Corrija os campos destacados.", "erro")
            return _form("Novo fornecedor", request.form, v.erros, 422)
        dados.criar(v.dados)
        flash("Fornecedor criado.", "sucesso")
        return redirect(url_for("fornecedores.listar"))
    return _form("Novo fornecedor", None, {})


@bp.route("/fornecedores/editar/<int:id_fornecedor>", methods=["GET", "POST"])
@requer_permissao("fornecedores:editar")
def editar(id_fornecedor):
    fornecedor = dados.buscar(id_fornecedor)
    if fornecedor is None:
        flash("Fornecedor nao encontrado.", "erro")
        return redirect(url_for("fornecedores.listar"))

    if request.method == "POST":
        v = validar(request.form, id_fornecedor)
        if v.erros:
            flash("Corrija os campos destacados.", "erro")
            return _form("Editar fornecedor", request.form, v.erros, 422)
        dados.atualizar(id_fornecedor, v.dados)
        flash("Fornecedor atualizado.", "sucesso")
        return redirect(url_for("fornecedores.listar"))

    item = dict(fornecedor)
    item["cnpj"] = formatar_cnpj(item["cnpj"])  # mostra com mascara no campo
    return _form("Editar fornecedor", item, {})


@bp.route("/fornecedores/desativar/<int:id_fornecedor>", methods=["POST"])
@requer_permissao("fornecedores:editar")
def desativar(id_fornecedor):
    if dados.buscar(id_fornecedor) is None:
        flash("Fornecedor nao encontrado.", "erro")
    else:
        dados.definir_ativo(id_fornecedor, False)
        flash("Fornecedor desativado. O historico foi mantido.", "sucesso")
    return redirect(url_for("fornecedores.listar"))


@bp.route("/fornecedores/reativar/<int:id_fornecedor>", methods=["POST"])
@requer_permissao("fornecedores:editar")
def reativar(id_fornecedor):
    if dados.buscar(id_fornecedor) is None:
        flash("Fornecedor nao encontrado.", "erro")
    else:
        dados.definir_ativo(id_fornecedor, True)
        flash("Fornecedor reativado.", "sucesso")
    return redirect(url_for("fornecedores.listar", inativos=1))


# ---------------------------------------------------------------------------
# API JSON
# ---------------------------------------------------------------------------


@bp.route("/api/fornecedores")
@requer_permissao("fornecedores:ver")
def api_listar():
    busca = request.args.get("busca", "").strip()
    inativos = request.args.get("inativos") == "1"
    return jsonify([para_json(f) for f in dados.listar(busca, inativos)])


@bp.route("/api/fornecedores/<int:id_fornecedor>")
@requer_permissao("fornecedores:ver")
def api_buscar(id_fornecedor):
    fornecedor = dados.buscar(id_fornecedor)
    if fornecedor is None:
        return api.nao_encontrado("Fornecedor nao encontrado.")
    return jsonify(para_json(fornecedor))


@bp.route("/api/fornecedores", methods=["POST"])
@requer_permissao("fornecedores:editar")
def api_criar():
    v = validar(api.ler_json())
    if v.erros:
        return api.erro_validacao(v.erros)
    novo_id = dados.criar(v.dados)
    return jsonify(para_json(dados.buscar(novo_id))), 201


@bp.route("/api/fornecedores/<int:id_fornecedor>", methods=["PUT"])
@requer_permissao("fornecedores:editar")
def api_atualizar(id_fornecedor):
    if dados.buscar(id_fornecedor) is None:
        return api.nao_encontrado("Fornecedor nao encontrado.")
    v = validar(api.ler_json(), id_fornecedor)
    if v.erros:
        return api.erro_validacao(v.erros)
    dados.atualizar(id_fornecedor, v.dados)
    return jsonify(para_json(dados.buscar(id_fornecedor)))


@bp.route("/api/fornecedores/<int:id_fornecedor>", methods=["DELETE"])
@requer_permissao("fornecedores:editar")
def api_desativar(id_fornecedor):
    """DELETE na API tambem e exclusao logica: devolve o registro, agora inativo."""
    if dados.buscar(id_fornecedor) is None:
        return api.nao_encontrado("Fornecedor nao encontrado.")
    dados.definir_ativo(id_fornecedor, False)
    return jsonify(para_json(dados.buscar(id_fornecedor)))
