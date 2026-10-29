"""
modulos/departamentos/rotas.py
------------------------------
SB-104 - CRUD de Departamentos. E o MODULO DE REFERENCIA: todos os
outros (maquinas, pecas, fornecedores, prestadores) seguem esta mesma
estrutura. Leia este inteiro antes de mexer nos outros.

Rotas de TELA                               Rotas da API (JSON)
-------------                               -------------------
GET      /departamentos/                    GET    /api/departamentos
GET/POST /departamentos/novo                POST   /api/departamentos
GET/POST /departamentos/editar/<id>         GET    /api/departamentos/<id>
POST     /departamentos/apagar/<id>         PUT    /api/departamentos/<id>
                                            DELETE /api/departamentos/<id>

As duas colunas chamam as MESMAS funcoes: validar() e o dados.py.
A diferenca e so a resposta: a tela devolve HTML, a API devolve JSON.
"""

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for

import api
from seguranca import requer_permissao
from validadores import Validacao

from . import dados

bp = Blueprint("departamentos", __name__)


# ---------------------------------------------------------------------------
# Regras (valem para a tela e para a API)
# ---------------------------------------------------------------------------


def validar(entrada, id_departamento=None):
    """Confere os campos. `id_departamento` None = criando um novo."""
    v = Validacao(entrada)
    nome = v.texto("nome", obrigatorio=True, maximo=80, rotulo="o nome")
    v.texto("responsavel", maximo=100, rotulo="o responsavel")
    # Checar antes de gravar da uma mensagem clara. O UNIQUE da tabela
    # continua la como garantia final.
    if nome and dados.nome_em_uso(nome, id_departamento):
        v.erro("nome", "Ja existe um departamento com este nome.")
    return v


def motivo_para_nao_apagar(id_departamento):
    total = dados.total_maquinas(id_departamento)
    if total:
        return f"Este departamento tem {total} maquina(s). Mova ou apague as maquinas antes."
    return None


def para_json(linha):
    return {"id": linha["id"], "nome": linha["nome"], "responsavel": linha["responsavel"]}


# ---------------------------------------------------------------------------
# TELAS
# ---------------------------------------------------------------------------


@bp.route("/departamentos/")
@requer_permissao("departamentos:ver")
def listar():
    busca = request.args.get("busca", "").strip()
    return render_template(
        "departamentos/listar.html", departamentos=dados.listar(busca), busca=busca
    )


@bp.route("/departamentos/novo", methods=["GET", "POST"])
@requer_permissao("departamentos:editar")
def novo():
    if request.method == "POST":
        v = validar(request.form)
        if v.erros:
            flash("Corrija os campos destacados.", "erro")
            # Devolve o formulario com o que a pessoa ja tinha digitado.
            # 422 = "entendi o pedido, mas os dados estao errados".
            return render_template("departamentos/form.html", titulo="Novo departamento",
                                   item=request.form, erros=v.erros), 422
        dados.criar(v.dados["nome"], v.dados["responsavel"])
        flash("Departamento criado.", "sucesso")
        # Post/Redirect/Get: depois de gravar, SEMPRE redirecione.
        return redirect(url_for("departamentos.listar"))

    return render_template("departamentos/form.html", titulo="Novo departamento",
                           item=None, erros={})


@bp.route("/departamentos/editar/<int:id_departamento>", methods=["GET", "POST"])
@requer_permissao("departamentos:editar")
def editar(id_departamento):
    departamento = dados.buscar(id_departamento)
    if departamento is None:
        flash("Departamento nao encontrado.", "erro")
        return redirect(url_for("departamentos.listar"))

    if request.method == "POST":
        v = validar(request.form, id_departamento)
        if v.erros:
            flash("Corrija os campos destacados.", "erro")
            return render_template("departamentos/form.html", titulo="Editar departamento",
                                   item=request.form, erros=v.erros), 422
        dados.atualizar(id_departamento, v.dados["nome"], v.dados["responsavel"])
        flash("Departamento atualizado.", "sucesso")
        return redirect(url_for("departamentos.listar"))

    return render_template("departamentos/form.html", titulo="Editar departamento",
                           item=departamento, erros={})


@bp.route("/departamentos/apagar/<int:id_departamento>", methods=["POST"])
@requer_permissao("departamentos:editar")
def apagar(id_departamento):
    motivo = motivo_para_nao_apagar(id_departamento)
    if motivo:
        flash(motivo, "erro")
    else:
        dados.apagar(id_departamento)
        flash("Departamento apagado.", "sucesso")
    return redirect(url_for("departamentos.listar"))


# ---------------------------------------------------------------------------
# API JSON
# ---------------------------------------------------------------------------


@bp.route("/api/departamentos")
@requer_permissao("departamentos:ver")
def api_listar():
    busca = request.args.get("busca", "").strip()
    return jsonify([
        {**para_json(d), "total_maquinas": d["total_maquinas"]} for d in dados.listar(busca)
    ])


@bp.route("/api/departamentos/<int:id_departamento>")
@requer_permissao("departamentos:ver")
def api_buscar(id_departamento):
    departamento = dados.buscar(id_departamento)
    if departamento is None:
        return api.nao_encontrado("Departamento nao encontrado.")
    return jsonify(para_json(departamento))


@bp.route("/api/departamentos", methods=["POST"])
@requer_permissao("departamentos:editar")
def api_criar():
    v = validar(api.ler_json())
    if v.erros:
        return api.erro_validacao(v.erros)
    novo_id = dados.criar(v.dados["nome"], v.dados["responsavel"])
    # 201 Created: a resposta padrao quando um registro novo nasce.
    return jsonify(para_json(dados.buscar(novo_id))), 201


@bp.route("/api/departamentos/<int:id_departamento>", methods=["PUT"])
@requer_permissao("departamentos:editar")
def api_atualizar(id_departamento):
    if dados.buscar(id_departamento) is None:
        return api.nao_encontrado("Departamento nao encontrado.")
    v = validar(api.ler_json(), id_departamento)
    if v.erros:
        return api.erro_validacao(v.erros)
    dados.atualizar(id_departamento, v.dados["nome"], v.dados["responsavel"])
    return jsonify(para_json(dados.buscar(id_departamento)))


@bp.route("/api/departamentos/<int:id_departamento>", methods=["DELETE"])
@requer_permissao("departamentos:editar")
def api_apagar(id_departamento):
    if dados.buscar(id_departamento) is None:
        return api.nao_encontrado("Departamento nao encontrado.")
    motivo = motivo_para_nao_apagar(id_departamento)
    if motivo:
        return api.conflito(motivo)
    dados.apagar(id_departamento)
    # 204 No Content: deu certo e nao ha nada para devolver.
    return "", 204
