"""
seguranca.py
------------
Quem esta logado, o que cada perfil pode fazer e a protecao CSRF.

RBAC (Role-Based Access Control), em uma frase: a permissao e dada ao
PERFIL, e a pessoa recebe PERFIS. Para saber se o Joao pode editar uma
maquina, a pergunta e: "algum perfil do Joao tem a permissao
'maquinas:editar'?"

    usuario --(tem)--> perfis --(tem)--> permissoes

A MATRIZ abaixo e a fonte da verdade. O seed.py copia ela para o banco
(tabelas perfis, permissoes e perfis_permissoes).
"""

import hmac
import secrets
from functools import wraps
from urllib.parse import urlsplit

from flask import abort, g, jsonify, redirect, request, session, url_for

# ---------------------------------------------------------------------------
# Perfis e permissoes
# ---------------------------------------------------------------------------

PERFIS = {
    "ADMINISTRADOR": "Acesso total, inclusive cadastro de usuarios e perfis.",
    "GESTOR": "Gerencia cadastros, estoque e aprova pedidos de manutencao.",
    "TECNICO": "Consulta cadastros e estoque; executa as ordens de servico.",
    "CLIENTE": "Consulta maquinas e departamentos; abre pedidos de manutencao.",
}

# Codigo da permissao = "<modulo>:<acao>". So duas acoes por enquanto:
#   ver    -> listar e consultar
#   editar -> criar, alterar, apagar/desativar
MODULOS = {
    "usuarios": "Usuarios",
    "departamentos": "Departamentos",
    "maquinas": "Maquinas",
    "pecas": "Pecas e estoque",
    "fornecedores": "Fornecedores",
    "prestadores": "Prestadores de servico",
}

PERMISSOES = {}
for _modulo, _nome in MODULOS.items():
    PERMISSOES[f"{_modulo}:ver"] = f"Consultar {_nome.lower()}"
    PERMISSOES[f"{_modulo}:editar"] = f"Cadastrar, alterar e remover {_nome.lower()}"

# Matriz perfil x permissao. Leia assim: "o GESTOR pode ...".
MATRIZ = {
    "ADMINISTRADOR": list(PERMISSOES),  # todas
    "GESTOR": [
        "usuarios:ver",
        "departamentos:ver", "departamentos:editar",
        "maquinas:ver", "maquinas:editar",
        "pecas:ver", "pecas:editar",
        "fornecedores:ver", "fornecedores:editar",
        "prestadores:ver", "prestadores:editar",
    ],
    "TECNICO": [
        "departamentos:ver",
        "maquinas:ver",
        "pecas:ver",
        "fornecedores:ver",
        "prestadores:ver",
    ],
    "CLIENTE": [
        "departamentos:ver",
        "maquinas:ver",
    ],
}


# ---------------------------------------------------------------------------
# Usuario logado
# ---------------------------------------------------------------------------


def eh_api():
    """A requisicao e para a API JSON? (tudo que comeca com /api/)"""
    return request.path.startswith("/api/")


def carregar_usuario_logado():
    """Roda antes de TODA requisicao (ver app.py, @app.before_request).

    Le o id guardado na sessao, busca o usuario no banco e guarda em `g`.
    `g` e um "bolso" do Flask que dura so uma requisicao: qualquer funcao
    pode ler g.usuario sem precisar receber como parametro.
    """
    # Import aqui dentro para evitar import circular
    # (o modulo de usuarios tambem importa este arquivo).
    from modulos.usuarios import dados as usuarios_dados

    g.usuario = None
    g.permissoes = set()

    id_usuario = session.get("id_usuario")
    if id_usuario is None:
        return

    usuario = usuarios_dados.buscar(id_usuario)
    # Usuario apagado ou desativado depois de logar: derruba a sessao.
    if usuario is None or not usuario["ativo"]:
        session.clear()
        return

    g.usuario = usuario
    g.permissoes = usuarios_dados.permissoes_do_usuario(id_usuario)


def pode(codigo):
    """True se o usuario logado tem a permissao. Usado nos templates
    para esconder botoes: {% if pode('maquinas:editar') %} ... {% endif %}

    ATENCAO: esconder o botao NAO e seguranca. A rota tambem precisa do
    @requer_permissao, porque qualquer um pode digitar a URL na mao.
    """
    return codigo in g.get("permissoes", set())


def _nao_logado():
    if eh_api():
        return jsonify(erro="Faca login para usar a API."), 401
    # Guarda para onde a pessoa queria ir, para voltar la depois do login.
    return redirect(url_for("usuarios.login", next=request.full_path.rstrip("?")))


def requer_login(funcao):
    """Decorador: so deixa entrar quem esta logado."""

    @wraps(funcao)  # preserva o nome da funcao original (o Flask precisa)
    def protegida(*args, **kwargs):
        if g.get("usuario") is None:
            return _nao_logado()
        return funcao(*args, **kwargs)

    return protegida


def requer_permissao(codigo):
    """Decorador: so deixa entrar quem tem a permissao `codigo`.

    Exemplo:
        @bp.route("/maquinas/novo", methods=["GET", "POST"])
        @requer_permissao("maquinas:editar")
        def novo():
            ...

    Nao logado -> vai para o login (ou 401 na API).
    Logado sem permissao -> 403 (Proibido).
    """

    def decorador(funcao):
        @wraps(funcao)
        def protegida(*args, **kwargs):
            if g.get("usuario") is None:
                return _nao_logado()
            if not pode(codigo):
                abort(403)
            return funcao(*args, **kwargs)

        return protegida

    return decorador


def destino_seguro(destino):
    """Aceita so enderecos DO PROPRIO SITE no parametro ?next=.

    Sem isso, alguem mandaria o link /login?next=https://site-falso.com e,
    depois do login, a vitima cairia no site falso (open redirect).
    """
    if not destino:
        return None
    partes = urlsplit(destino)
    if partes.scheme or partes.netloc or not destino.startswith("/") or destino.startswith("//"):
        return None
    return destino


# ---------------------------------------------------------------------------
# CSRF (Cross-Site Request Forgery)
#
# O ataque: um site malicioso tem um formulario escondido que envia um POST
# para o TechMaint. Como o navegador manda o cookie de sessao junto, o POST
# chegaria "como se fosse" a pessoa logada.
#
# A defesa: todo formulario leva um codigo secreto (token) que so o nosso
# site conhece, guardado na sessao. POST sem o token certo e recusado.
#
# Na API JSON a defesa e outra: exigimos Content-Type application/json.
# Um site de fora nao consegue mandar JSON para ca sem o navegador pedir
# licenca antes (CORS), e nos nao damos essa licenca.
# ---------------------------------------------------------------------------


def token_csrf():
    """Devolve o token da sessao (cria na primeira vez).
    Nos templates: <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
    """
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_hex(32)
    return session["csrf_token"]


def conferir_csrf():
    """Roda antes de toda requisicao. So age em metodos que alteram dados."""
    if request.method not in ("POST", "PUT", "PATCH", "DELETE"):
        return None

    if eh_api():
        if request.method in ("POST", "PUT", "PATCH") and not request.is_json:
            return jsonify(erro="Envie os dados como JSON (Content-Type: application/json)."), 415
        return None

    enviado = request.form.get("csrf_token", "")
    esperado = session.get("csrf_token", "")
    # compare_digest compara em tempo constante (evita ataque por tempo).
    if not esperado or not hmac.compare_digest(enviado, esperado):
        abort(400, description="Formulario expirado. Recarregue a pagina e tente de novo.")
    return None
