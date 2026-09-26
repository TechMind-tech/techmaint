"""
app.py
------
O ponto de partida da aplicacao. Aqui a gente:

  1. cria o app Flask
  2. registra os MODULOS (cada um com as suas rotas, em modulos/)
  3. liga o que vale para todas as paginas: usuario logado, CSRF,
     filtros de formatacao e paginas de erro

As rotas de cada assunto NAO ficam mais aqui: ficam em
modulos/<assunto>/rotas.py. Isso e o que o README chamava de
"quando passar de tres ou quatro entidades, vale estudar Blueprints".

Fluxo de uma pagina:
    navegador -> rota (modulos/x/rotas.py) -> SQL (modulos/x/dados.py) -> banco
                        |
                        v
                 template (templates/x/) -> HTML pronto -> navegador

Para rodar:
    python app.py
"""

import os
import sqlite3

from flask import Flask, g, jsonify, render_template

import database
import seed
from modulos.departamentos.rotas import bp as departamentos_bp
from modulos.fornecedores.rotas import bp as fornecedores_bp
from modulos.maquinas.rotas import bp as maquinas_bp
from modulos.pecas import dados as pecas_dados
from modulos.pecas.rotas import bp as pecas_bp
from modulos.prestadores.rotas import bp as prestadores_bp
from modulos.usuarios.rotas import bp as usuarios_bp
from seguranca import (carregar_usuario_logado, conferir_csrf, eh_api, pode,
                       requer_login, token_csrf)
from validadores import formatar_cnpj

app = Flask(__name__)

# Chave que assina o cookie da sessao (e por isso o login funciona).
# Em producao ela vem de uma variavel de ambiente, nunca do codigo.
app.secret_key = os.environ.get("TECHMAINT_SECRET_KEY", "troque-esta-chave-em-producao")

# SameSite=Lax: o navegador nao manda o cookie da sessao em POST vindo de
# outro site. Mais uma camada contra CSRF, junto com o token.
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
# Mantem os campos do JSON na ordem em que foram escritos (nao alfabetica).
app.json.sort_keys = False


# ---------------------------------------------------------------------------
# 1. Modulos (Blueprints)
# ---------------------------------------------------------------------------
app.register_blueprint(usuarios_bp)       # SB-102
app.register_blueprint(departamentos_bp)  # SB-103 / SB-104
app.register_blueprint(maquinas_bp)       # SB-103 / SB-104
app.register_blueprint(pecas_bp)          # SB-105 / SB-106
app.register_blueprint(fornecedores_bp)   # SB-107 / SB-108
app.register_blueprint(prestadores_bp)    # SB-109 / SB-110


# ---------------------------------------------------------------------------
# 2. Antes de TODA requisicao
# ---------------------------------------------------------------------------
@app.before_request
def antes_de_cada_requisicao():
    carregar_usuario_logado()  # preenche g.usuario e g.permissoes
    return conferir_csrf()     # recusa POST sem token (ou API sem JSON)


# ---------------------------------------------------------------------------
# 3. Coisas disponiveis em TODOS os templates
# ---------------------------------------------------------------------------
@app.context_processor
def variaveis_dos_templates():
    return {
        "usuario_logado": g.get("usuario"),
        "pode": pode,               # {% if pode('maquinas:editar') %}
    }


# csrf_token() vira uma funcao GLOBAL do Jinja (e nao do context_processor)
# porque as macros de _macros.html tambem precisam dela, e macro importada
# nao enxerga as variaveis do context_processor.
app.jinja_env.globals["csrf_token"] = token_csrf


@app.template_filter("moeda")
def filtro_moeda(centavos):
    """{{ peca.valor_centavos | moeda }}  ->  R$ 1.234,56"""
    centavos = centavos or 0
    texto = f"{centavos / 100:,.2f}"  # 1,234.56 (formato americano)
    # troca , por . e . por , usando um X de "ponte"
    texto = texto.replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {texto}"


@app.template_filter("cnpj")
def filtro_cnpj(numeros):
    """{{ fornecedor.cnpj | cnpj }}  ->  12.345.678/0001-95"""
    return formatar_cnpj(numeros)


# ---------------------------------------------------------------------------
# 4. Pagina inicial
# ---------------------------------------------------------------------------
@app.route("/")
@requer_login
def inicio():
    alertas = pecas_dados.contar_alertas() if pode("pecas:ver") else None
    return render_template("inicio.html", alertas=alertas)


# ---------------------------------------------------------------------------
# 5. Paginas de erro
#
# Na API o erro volta em JSON; nas telas, uma pagina amigavel (nunca o
# "stack trace", que assusta o usuario e entrega detalhes para atacantes).
# ---------------------------------------------------------------------------
MENSAGENS_DE_ERRO = {
    400: "Requisicao invalida.",
    403: "Seu perfil nao tem permissao para acessar esta pagina.",
    404: "Pagina nao encontrada.",
    405: "Metodo nao permitido para este endereco.",
    409: "Esta operacao conflita com dados ja cadastrados.",
    500: "Erro interno. Tente de novo em instantes.",
}


def responder_erro(codigo, descricao=None):
    mensagem = descricao or MENSAGENS_DE_ERRO.get(codigo, "Erro.")
    if eh_api():
        return jsonify(erro=mensagem), codigo
    return render_template("erros/erro.html", codigo=codigo, mensagem=mensagem), codigo


@app.errorhandler(400)
@app.errorhandler(403)
@app.errorhandler(404)
@app.errorhandler(405)
def erro_http(erro):
    # A descricao padrao do Werkzeug vem em ingles; so usamos a nossa
    # quando a rota passou uma descricao propria no abort(..., description=).
    padrao = type(erro).description
    descricao = erro.description if erro.description != padrao else None
    return responder_erro(erro.code, descricao)


@app.errorhandler(sqlite3.IntegrityError)
def erro_integridade(erro):
    """Rede de seguranca: se alguma regra do banco (UNIQUE, FOREIGN KEY,
    CHECK) recusar a gravacao e a rota nao tiver tratado antes, mostramos
    uma mensagem amigavel em vez do erro 500."""
    return responder_erro(409)


@app.errorhandler(500)
def erro_interno(erro):
    return responder_erro(500)


if __name__ == "__main__":
    # Garante que as tabelas existem e que da para entrar no sistema
    # (perfis, permissoes e um administrador, se ainda nao houver ninguem).
    database.criar_tabelas()
    seed.garantir_acesso_inicial()
    # debug=True recarrega o servidor a cada alteracao de arquivo e
    # mostra o erro completo na tela. Use so no seu computador.
    app.run(debug=True)
