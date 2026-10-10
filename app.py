"""
app.py
------
A fabrica da aplicacao: `criar_app()` monta o Flask, liga os modulos (Blueprints),
a seguranca (login, permissoes, CSRF) e as paginas de erro.

Rota = um endereco do navegador ligado a uma funcao Python. As rotas de cada area
ficam em `modulos/` (um arquivo por area); aqui ficam so as pecas que valem para o
sistema inteiro.

Fluxo de uma pagina:
    navegador -> before_request (login, CSRF) -> rota (modulos/*.py) -> banco -> template (templates/)

Para rodar:
    python seed.py     # (opcional) dados de demonstracao
    python app.py      # http://127.0.0.1:5000
"""

import logging
import os
import secrets
import sqlite3
from datetime import timedelta

from flask import (Flask, g, jsonify, redirect, render_template, request, session, url_for)
from jinja2 import TemplateNotFound
from werkzeug.exceptions import HTTPException
from werkzeug.routing import IntegerConverter

import database
import modulos
from servicos import alertas as srv_alertas
from servicos import permissoes as perm
from servicos import seguranca
from servicos.formatacao import agora, data_br, iniciais, moeda

log = logging.getLogger("techmaint")

# Paginas que podem ser abertas sem login.
ENDPOINTS_PUBLICOS = {"static", "auth.login", "auth.recuperar_senha", "auth.redefinir_senha"}

TITULOS_ERRO = {
    400: ("Requisição inválida", "Não foi possível processar o envio. Volte, recarregue a página e tente de novo."),
    403: ("Acesso negado", "Você não tem permissão para acessar esta página."),
    404: ("Página não encontrada", "O endereço que você tentou abrir não existe ou foi removido."),
    405: ("Método não permitido", "Esta página não aceita esse tipo de requisição."),
    409: ("Conflito de dados", "Os dados enviados conflitam com registros existentes (duplicidade ou vínculo)."),
    413: ("Envio muito grande", "O conteúdo enviado ultrapassa o tamanho permitido."),
    500: ("Algo deu errado", "Ocorreu um erro inesperado. Já registramos o problema; tente novamente em instantes."),
}


def configurar_logs():
    """Logs simples no terminal (auditoria e erros). Nao duplica handlers."""
    raiz = logging.getLogger("techmaint")
    if not raiz.handlers:
        h = logging.StreamHandler()
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        raiz.addHandler(h)
        raiz.setLevel(logging.INFO)
        raiz.propagate = False


class IdSeguro(IntegerConverter):
    """`<int:id>` que recusa numeros maiores que o INTEGER do SQLite (vira 404 em vez de erro 500)."""

    def __init__(self, map, fixed_digits=0, min=None, max=None, signed=False):
        super().__init__(map, fixed_digits=fixed_digits, min=min, max=2 ** 63 - 1, signed=signed)


def criar_app(config=None):
    """Monta e devolve a aplicacao. `config` (dict) sobrescreve configuracoes — usado nos testes."""
    configurar_logs()
    app = Flask(__name__)
    config = dict(config or {})

    # --- chave secreta: vem do ambiente, nunca do codigo -------------------
    chave = config.get("SECRET_KEY") or os.environ.get("TECHMAINT_SECRET_KEY")
    modo_dev = os.environ.get("FLASK_DEBUG", "").lower() in ("1", "true", "on") or config.get("TESTING")
    if not chave:
        if modo_dev:
            chave = "chave-somente-para-desenvolvimento"      # so em modo dev/teste
        else:
            chave = secrets.token_hex(32)                      # aleatoria: as sessoes caem ao reiniciar
            log.warning("TECHMAINT_SECRET_KEY nao definida: usando chave aleatoria (sessoes nao sobrevivem a reinicios).")

    app.config.update(
        SECRET_KEY=chave,
        MAX_CONTENT_LENGTH=2 * 1024 * 1024,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("TECHMAINT_COOKIE_SEGURO") == "1",   # ligar em HTTPS
        PERMANENT_SESSION_LIFETIME=timedelta(days=30),                          # "Lembrar-me"
        TEMPLATES_AUTO_RELOAD=bool(modo_dev),
    )
    app.config.update(config)
    app.json.ensure_ascii = False
    app.json.sort_keys = False
    app.url_map.converters["int"] = IdSeguro      # ids gigantes -> 404
    app.url_map.merge_slashes = False             # '//' nao e redirecionado: caminho estranho -> 404

    # Garante que o banco existe com as tabelas (idempotente).
    with app.app_context():
        database.init_db()

    app.teardown_appcontext(database.fechar_db)
    app.before_request(antes_da_requisicao)
    app.after_request(depois_da_requisicao)
    app.context_processor(contexto_global)
    registrar_erros(app)
    modulos.registrar_blueprints(app)

    # Funcoes extras para os templates (alem do contexto acima).
    app.jinja_env.globals.update(pode=perm.pode, moeda=moeda, data_br=data_br)
    return app


# ---------------------------------------------------------------------------
# Antes de cada requisicao: quem e o usuario? pode entrar? o CSRF confere?
# ---------------------------------------------------------------------------
def carregar_usuario():
    """Le o usuario da sessao. Inativo ou apagado = sessao descartada."""
    g.usuario = None
    uid = session.get("usuario_id")
    if not uid:
        return
    db = database.get_db()
    u = db.execute(
        "SELECT u.id, u.nome, u.login, u.email, u.tema, u.idioma, u.id_departamento, d.nome AS depto "
        "FROM usuarios u LEFT JOIN departamentos d ON d.id = u.id_departamento "
        "WHERE u.id = ? AND u.ativo = 1", (uid,)).fetchone()
    perfis = db.execute("SELECT p.id, p.nome FROM usuarios_perfis up JOIN perfis p ON p.id = up.id_perfil "
                        "WHERE up.id_usuario = ? ORDER BY p.id", (uid,)).fetchall() if u else []
    if u is None or not perfis:
        session.clear()
        return
    g.usuario = {
        "id": u["id"], "nome": u["nome"], "login": u["login"], "email": u["email"],
        "perfil": perfis[0]["nome"], "id_perfil": perfis[0]["id"], "perfis": [p["nome"] for p in perfis],
        "depto": u["depto"], "id_departamento": u["id_departamento"],
        "iniciais": iniciais(u["nome"]), "tema": u["tema"], "idioma": u["idioma"],
    }


def antes_da_requisicao():
    endpoint = request.endpoint
    if endpoint == "static":
        return None
    carregar_usuario()

    # 1) Login obrigatorio (exceto paginas publicas e URLs que nao existem -> 404)
    if endpoint is not None and endpoint not in ENDPOINTS_PUBLICOS and g.usuario is None:
        destino = url_for("auth.login")
        if request.method == "GET":
            caminho = request.full_path.rstrip("?")
            return redirect(url_for("auth.login", proximo=caminho))
        return redirect(destino)

    # 2) CSRF em todo POST/PUT/PATCH/DELETE
    if request.method in ("POST", "PUT", "PATCH", "DELETE") and endpoint is not None:
        if not seguranca.csrf_valido():
            log.warning("CSRF invalido em %s %s", request.method, request.path)
            return pagina_erro(400, "Sessão expirada ou formulário inválido",
                               "Não foi possível confirmar a origem do envio (token de segurança). "
                               "Recarregue a página e tente de novo.")
    return None


# Politica de seguranca de conteudo: tudo so do proprio servidor, sem script inline.
# 'unsafe-inline' fica SO em style-src porque as telas usam atributos style="..." (barras de progresso etc.);
# `data:` em img-src por causa do icone SVG embutido no CSS.
CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
       "font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; "
       "frame-ancestors 'none'")


def depois_da_requisicao(resposta):
    """Cabecalhos de seguranca e cache (nao guardar paginas internas no navegador)."""
    resposta.headers.setdefault("X-Content-Type-Options", "nosniff")
    resposta.headers.setdefault("X-Frame-Options", "DENY")
    resposta.headers.setdefault("Referrer-Policy", "same-origin")
    resposta.headers.setdefault("Content-Security-Policy", CSP)
    if request.endpoint != "static":
        resposta.headers.setdefault("Cache-Control", "no-store")
    return resposta


# ---------------------------------------------------------------------------
# Variaveis disponiveis em TODOS os templates
# ---------------------------------------------------------------------------
def contexto_global():
    usuario = getattr(g, "usuario", None)
    endpoint = request.endpoint if request else None
    menu, alertas = [], {"total": 0, "itens": []}
    if usuario is not None:
        try:
            menu = perm.menu_do_usuario(endpoint)
            alertas = srv_alertas.calcular(database.get_db(), usuario)
        except Exception:      # um alerta com problema nao pode derrubar a pagina
            log.exception("Falha ao montar menu/alertas")
    return {
        "usuario_atual": usuario,
        "menu": menu,
        "endpoint_atual": endpoint,
        "alertas": alertas,
        "csrf_token": seguranca.csrf_token,
        "tema": (usuario or {}).get("tema") or "claro",
        "agora": agora(),
        "permissoes": perm.permissoes_do_usuario(usuario) if usuario else [],
    }


# ---------------------------------------------------------------------------
# Paginas de erro (sem stack trace para o usuario)
# ---------------------------------------------------------------------------
def pagina_erro(codigo, titulo=None, mensagem=None):
    padrao = TITULOS_ERRO.get(codigo, TITULOS_ERRO[500])
    titulo = titulo or padrao[0]
    mensagem = mensagem or padrao[1]
    quer_json = request.path.startswith("/api/") or \
        request.accept_mimetypes.best == "application/json"
    if quer_json:
        resposta = jsonify({"erro": titulo, "mensagem": mensagem, "codigo": codigo})
        resposta.status_code = codigo
        return resposta
    modelo = {403: "403.html", 400: "403.html", 404: "404.html"}.get(codigo, "500.html")
    try:
        return render_template(modelo, codigo=codigo, titulo=titulo, mensagem=mensagem), codigo
    except TemplateNotFound:
        pass
    except Exception:
        log.exception("Falha ao renderizar a pagina de erro %s", codigo)
    # Plano B (sem template): HTML minimo, com texto escapado.
    from markupsafe import escape
    corpo = (f"<!doctype html><html lang='pt-BR'><meta charset='utf-8'><title>{escape(titulo)}</title>"
             f"<body style='font-family:sans-serif;margin:3rem'><h1>{escape(titulo)}</h1>"
             f"<p>{escape(mensagem)}</p><p><a href='/'>Voltar ao início</a></p></body></html>")
    return corpo, codigo


def registrar_erros(app):
    @app.errorhandler(HTTPException)
    def erro_http(e):
        return pagina_erro(e.code or 500)

    @app.errorhandler(sqlite3.IntegrityError)
    def erro_integridade(e):
        log.warning("Violacao de integridade: %s", e)
        return pagina_erro(409)

    @app.errorhandler(Exception)
    def erro_inesperado(e):
        # Stack trace so no log; o usuario ve uma pagina amigavel.
        log.exception("Erro nao tratado em %s %s", request.method, request.path)
        try:
            if database.get_db().in_transaction:
                database.get_db().execute("ROLLBACK")
        except Exception:
            pass
        if app.debug and not app.testing:
            raise e
        return pagina_erro(500)


# `app` pronto para `flask --app app run`, `python app.py` e para os testes (`import app`).
app = criar_app()


if __name__ == "__main__":
    # Entrada de desenvolvimento. (O link de "Esqueci minha senha" vai so para o log deste terminal.)
    modo_debug = os.environ.get("FLASK_DEBUG", "").lower() in ("1", "true", "on")
    with app.app_context():
        db = database.get_db()
        if db.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0] == 0:
            log.warning("Banco vazio: rode `python seed.py` para criar os usuarios de demonstracao.")
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", 5000)), debug=modo_debug)
