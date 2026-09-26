"""
tests/conftest.py
-----------------
"Fixtures" do pytest: preparacao que os testes pedem pelo nome do parametro.

Cada teste ganha um banco NOVO e descartavel (na pasta temporaria do
pytest), ja com perfis, permissoes, o admin e os dados de exemplo.
Assim um teste nunca atrapalha o outro, e o seu techmaint.db nao e tocado.

Para rodar todos os testes:
    python -m pytest
"""

import pytest

import database
import seed
from app import app as aplicacao

SENHA_ADMIN = seed.SENHA_ADMIN
SENHA_EXEMPLOS = seed.SENHA_EXEMPLOS


@pytest.fixture
def app(tmp_path, monkeypatch):
    # monkeypatch troca o valor so durante o teste e desfaz sozinho depois.
    monkeypatch.setattr(database, "NOME_DO_BANCO", str(tmp_path / "teste.db"))
    database.criar_tabelas()
    seed.garantir_acesso_inicial()
    seed.carregar_exemplos()
    aplicacao.config["TESTING"] = True
    return aplicacao


@pytest.fixture
def cliente(app):
    """Um "navegador de mentira" que faz requisicoes no app."""
    return app.test_client()


def token(cliente):
    """Devolve o token CSRF da sessao do cliente (cria se nao existir)."""
    with cliente.session_transaction() as sessao:
        sessao.setdefault("csrf_token", "token-de-teste")
        return sessao["csrf_token"]


def logar(cliente, login, senha=None):
    senha = senha or (SENHA_ADMIN if login == "admin" else SENHA_EXEMPLOS)
    return cliente.post("/login", data={"login": login, "senha": senha, "csrf_token": token(cliente)})


def postar(cliente, url, dados=None):
    """POST de formulario ja com o token CSRF."""
    dados = dict(dados or {})
    dados["csrf_token"] = token(cliente)
    return cliente.post(url, data=dados)


@pytest.fixture
def admin(cliente):
    logar(cliente, "admin")
    return cliente


@pytest.fixture
def gestor(cliente):
    logar(cliente, "gestor")
    return cliente


@pytest.fixture
def tecnico(cliente):
    logar(cliente, "tecnico")
    return cliente


@pytest.fixture
def cliente_perfil(cliente):
    logar(cliente, "cliente")
    return cliente
