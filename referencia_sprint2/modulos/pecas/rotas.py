"""
modulos/pecas/rotas.py
----------------------
SB-106 - CRUD de Pecas + estoque minimo e maximo.

O formulario de peca ja traz os campos do estoque (minimo, maximo, local
e, so na criacao, a quantidade inicial). A listagem destaca em vermelho,
e com a palavra "Repor", quem esta abaixo do minimo. Cor sozinha nao
basta: tem gente daltonica.

Rotas de TELA                          Rotas da API (JSON)
-------------                          -------------------
GET      /pecas/                       GET    /api/pecas          (?alerta=1 ?maquina=ID)
GET/POST /pecas/novo                   POST   /api/pecas
GET/POST /pecas/editar/<id>            GET    /api/pecas/<id>
POST     /pecas/apagar/<id>            PUT    /api/pecas/<id>
                                       DELETE /api/pecas/<id>
"""

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for

import api
from modulos.maquinas import dados as maquinas_dados
from seguranca import requer_permissao
from validadores import Validacao, centavos_para_texto, somente_digitos

from . import dados
from .dados import SITUACOES

bp = Blueprint("pecas", __name__)


def validar(entrada, id_peca=None):
    criando = id_peca is None
    v = Validacao(entrada)
    v.texto("nome", obrigatorio=True, maximo=100, rotulo="o nome")
    codigo = v.texto("codigo", maximo=40, rotulo="o codigo")
    v.dinheiro("valor", rotulo="o valor unitario")
    id_maquina = v.inteiro("id_maquina", rotulo="a maquina")
    v.texto("local", maximo=80, rotulo="o local")

    # NCM: 8 digitos (classificacao fiscal da mercadoria). Opcional.
    ncm = somente_digitos(entrada.get("ncm"))
    if ncm and len(ncm) != 8:
        v.erro("ncm", "O NCM tem 8 digitos.")
    v.dados["ncm"] = ncm or None

    # Estoque. A quantidade atual so e informada na criacao (saldo inicial).
    if criando:
        v.inteiro("qtde_atual", minimo=0, rotulo="a quantidade inicial", padrao=0)
    minima = v.inteiro("qtde_minima", minimo=0, rotulo="o estoque minimo")
    maxima = v.inteiro("qtde_maxima", minimo=0, rotulo="o estoque maximo")
    if minima is not None and maxima is not None and "qtde_maxima" not in v.erros and maxima < minima:
        v.erro("qtde_maxima", "O estoque maximo nao pode ser menor que o minimo.")

    if codigo and dados.codigo_em_uso(codigo, id_peca):
        v.erro("codigo", "Ja existe uma peca com este codigo.")
    if id_maquina and maquinas_dados.buscar(id_maquina) is None:
        v.erro("id_maquina", "Maquina nao encontrada.")
    return v


def para_json(linha):
    return {
        "id": linha["id"],
        "nome": linha["nome"],
        "codigo": linha["codigo"],
        "ncm": linha["ncm"],
        # Na API o valor vai em centavos (inteiro), sem ambiguidade de
        # virgula/ponto. Quem mostra na tela divide por 100.
        "valor_centavos": linha["valor_centavos"],
        "id_maquina": linha["id_maquina"],
        "maquina": linha["maquina"],
        "estoque": {
            "atual": linha["qtde_atual"],
            "minimo": linha["qtde_minima"],
            "maximo": linha["qtde_maxima"],
            "local": linha["local"],
            "situacao": linha["situacao"],
            "sugestao_compra": linha["sugestao_compra"] if linha["situacao"] == "REPOR" else 0,
        },
    }


def _entrada_da_api(corpo):
    """Na API o valor chega em centavos (inteiro). Convertemos para o
    formato que a Validacao espera (reais), para usar a MESMA regra."""
    entrada = dict(corpo)
    if "valor_centavos" in corpo and "valor" not in corpo:
        centavos = corpo["valor_centavos"]
        # bool tambem e int no Python (True == 1), por isso a checagem extra.
        if isinstance(centavos, int) and not isinstance(centavos, bool):
            entrada["valor"] = centavos_para_texto(centavos)
        else:
            entrada["valor"] = "invalido"  # forca o erro de validacao
    estoque = corpo.get("estoque") or {}
    for campo_api, campo in [("atual", "qtde_atual"), ("minimo", "qtde_minima"),
                             ("maximo", "qtde_maxima"), ("local", "local")]:
        if campo_api in estoque and campo not in entrada:
            entrada[campo] = estoque[campo_api]
    return entrada


def _filtros():
    busca = request.args.get("busca", "").strip()
    maquina = request.args.get("maquina", type=int)
    so_alerta = request.args.get("alerta") == "1"
    return busca, maquina, so_alerta


def _form(titulo, item, erros, codigo=200, editando=False):
    return render_template(
        "pecas/form.html", titulo=titulo, item=item, erros=erros, editando=editando,
        maquinas=maquinas_dados.listar_para_escolha(),
    ), codigo


# ---------------------------------------------------------------------------
# TELAS
# ---------------------------------------------------------------------------


@bp.route("/pecas/")
@requer_permissao("pecas:ver")
def listar():
    busca, maquina, so_alerta = _filtros()
    return render_template(
        "pecas/listar.html",
        pecas=dados.listar(busca, maquina, so_alerta),
        maquinas=maquinas_dados.listar_para_escolha(),
        situacoes=SITUACOES,
        total_alertas=dados.contar_alertas(),
        busca=busca, maquina=maquina, so_alerta=so_alerta,
    )


@bp.route("/pecas/novo", methods=["GET", "POST"])
@requer_permissao("pecas:editar")
def novo():
    if request.method == "POST":
        v = validar(request.form)
        if v.erros:
            flash("Corrija os campos destacados.", "erro")
            return _form("Nova peca", request.form, v.erros, 422)
        dados.criar(v.dados)
        flash("Peca criada.", "sucesso")
        return redirect(url_for("pecas.listar"))

    if not maquinas_dados.listar_para_escolha():
        flash("Cadastre uma maquina antes de cadastrar pecas.", "erro")
        return redirect(url_for("maquinas.novo"))
    # Deixa a maquina ja escolhida quando vem de /pecas/novo?maquina=3
    return _form("Nova peca", {"id_maquina": request.args.get("maquina", type=int)}, {})


@bp.route("/pecas/editar/<int:id_peca>", methods=["GET", "POST"])
@requer_permissao("pecas:editar")
def editar(id_peca):
    peca = dados.buscar(id_peca)
    if peca is None:
        flash("Peca nao encontrada.", "erro")
        return redirect(url_for("pecas.listar"))

    if request.method == "POST":
        v = validar(request.form, id_peca)
        if v.erros:
            flash("Corrija os campos destacados.", "erro")
            # Junta o que foi digitado com a quantidade atual (que nao esta no form).
            item = {**dict(request.form), "qtde_atual": peca["qtde_atual"]}
            return _form("Editar peca", item, v.erros, 422, editando=True)
        dados.atualizar(id_peca, v.dados)
        flash("Peca atualizada.", "sucesso")
        return redirect(url_for("pecas.listar"))

    item = dict(peca)
    # O input mostra o valor em reais com virgula: 38,90
    item["valor"] = centavos_para_texto(item["valor_centavos"])
    return _form("Editar peca", item, {}, editando=True)


@bp.route("/pecas/apagar/<int:id_peca>", methods=["POST"])
@requer_permissao("pecas:editar")
def apagar(id_peca):
    if dados.buscar(id_peca) is None:
        flash("Peca nao encontrada.", "erro")
    else:
        dados.apagar(id_peca)
        flash("Peca apagada.", "sucesso")
    return redirect(url_for("pecas.listar"))


# ---------------------------------------------------------------------------
# API JSON
# ---------------------------------------------------------------------------


@bp.route("/api/pecas")
@requer_permissao("pecas:ver")
def api_listar():
    busca, maquina, so_alerta = _filtros()
    return jsonify([para_json(p) for p in dados.listar(busca, maquina, so_alerta)])


@bp.route("/api/pecas/<int:id_peca>")
@requer_permissao("pecas:ver")
def api_buscar(id_peca):
    peca = dados.buscar(id_peca)
    if peca is None:
        return api.nao_encontrado("Peca nao encontrada.")
    return jsonify(para_json(peca))


@bp.route("/api/pecas", methods=["POST"])
@requer_permissao("pecas:editar")
def api_criar():
    v = validar(_entrada_da_api(api.ler_json()))
    if v.erros:
        return api.erro_validacao(v.erros)
    novo_id = dados.criar(v.dados)
    return jsonify(para_json(dados.buscar(novo_id))), 201


@bp.route("/api/pecas/<int:id_peca>", methods=["PUT"])
@requer_permissao("pecas:editar")
def api_atualizar(id_peca):
    if dados.buscar(id_peca) is None:
        return api.nao_encontrado("Peca nao encontrada.")
    v = validar(_entrada_da_api(api.ler_json()), id_peca)
    if v.erros:
        return api.erro_validacao(v.erros)
    dados.atualizar(id_peca, v.dados)
    return jsonify(para_json(dados.buscar(id_peca)))


@bp.route("/api/pecas/<int:id_peca>", methods=["DELETE"])
@requer_permissao("pecas:editar")
def api_apagar(id_peca):
    if dados.buscar(id_peca) is None:
        return api.nao_encontrado("Peca nao encontrada.")
    dados.apagar(id_peca)
    return "", 204
