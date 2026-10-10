"""
conftest.py - fixtures da suite de QA do TechMaint.

Estrategia de isolamento de banco:
  1. Uma vez por sessao, constroi um "banco modelo" (init_db + seed.py) num diretorio temporario.
  2. A cada teste, copia o modelo por cima do arquivo apontado por TECHMAINT_DB e cria um app novo
     com `criar_app()`. Assim cada teste parte do seed limpo, mesmo que o app guarde o caminho do
     banco em cache. Nada e gravado dentro do repositorio.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(Path(__file__).resolve().parent))

os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "/opt/pw-browsers")

_DIR_SESSAO = Path(tempfile.mkdtemp(prefix="techmaint_qa_"))
DB_TESTE = str(_DIR_SESSAO / "teste.db")
DB_MODELO = str(_DIR_SESSAO / "modelo.db")
os.environ["TECHMAINT_DB"] = DB_TESTE
os.environ["TECHMAINT_SECRET_KEY"] = "chave-so-para-os-testes-do-qa"
os.environ.pop("FLASK_DEBUG", None)

from helpers import PERFIS, USUARIOS_DEMO, logar_como  # noqa: E402


# ---------------------------------------------------------------------------
# Marcadores / relatorio
# ---------------------------------------------------------------------------

def pytest_configure(config):
    config.addinivalue_line("markers", "e2e: testes de navegador (Playwright + chromium)")
    config.addinivalue_line("markers", "lento: testes demorados (concorrencia, fuzz)")


def pytest_sessionfinish(session, exitstatus):
    shutil.rmtree(_DIR_SESSAO, ignore_errors=True)


# ---------------------------------------------------------------------------
# Banco
# ---------------------------------------------------------------------------

def _rodar(cmd, env_extra, cwd=REPO, timeout=180):
    env = dict(os.environ)
    env.update(env_extra)
    return subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout)


def construir_banco(caminho: str, *, com_seed: bool = True) -> None:
    """Cria o banco em `caminho` rodando o init_db()/seed.py REAIS (em subprocesso)."""
    for suf in ("", "-wal", "-shm", "-journal"):
        try:
            os.remove(caminho + suf)
        except FileNotFoundError:
            pass
    if not (REPO / "database.py").exists():
        pytest.fail("Contrato ausente: database.py (init_db) nao existe (SPEC §1).", pytrace=False)
    env = {"TECHMAINT_DB": caminho}
    r = _rodar([sys.executable, "-c", "import database; database.init_db()"], env)
    if r.returncode != 0:
        pytest.fail("Contrato ausente/quebrado: `database.init_db()` falhou.\n" + r.stderr[-1500:], pytrace=False)
    if com_seed:
        if not (REPO / "seed.py").exists():
            pytest.fail("Contrato ausente: seed.py nao existe (SPEC §1/§3).", pytrace=False)
        r = _rodar([sys.executable, "seed.py"], env)
        if r.returncode != 0:
            pytest.fail("`python seed.py` falhou:\n" + (r.stdout + r.stderr)[-2000:], pytrace=False)


@pytest.fixture(scope="session")
def banco_modelo():
    construir_banco(DB_MODELO)
    return DB_MODELO


def _limpar_arquivos_db(caminho: str):
    for suf in ("", "-wal", "-shm", "-journal"):
        try:
            os.remove(caminho + suf)
        except FileNotFoundError:
            pass


@pytest.fixture()
def banco(banco_modelo):
    """Banco do teste = copia limpa do modelo (seed). Retorna o caminho."""
    _limpar_arquivos_db(DB_TESTE)
    shutil.copyfile(banco_modelo, DB_TESTE)
    os.environ["TECHMAINT_DB"] = DB_TESTE
    yield DB_TESTE
    _limpar_arquivos_db(DB_TESTE)


@pytest.fixture()
def banco_vazio():
    """Banco so com as tabelas (init_db), sem seed."""
    _limpar_arquivos_db(DB_TESTE)
    construir_banco(DB_TESTE, com_seed=False)
    yield DB_TESTE
    _limpar_arquivos_db(DB_TESTE)


# ---------------------------------------------------------------------------
# App e clients
# ---------------------------------------------------------------------------

def _criar_app():
    if not (REPO / "app.py").exists():
        pytest.fail("Contrato ausente: app.py nao existe (SPEC §1).", pytrace=False)
    import importlib

    try:
        mod = importlib.import_module("app")
    except Exception as e:  # noqa: BLE001
        pytest.fail(f"`import app` falhou: {type(e).__name__}: {e}", pytrace=False)
    if not hasattr(mod, "criar_app"):
        pytest.fail("Contrato ausente: app.py deve expor a fabrica `criar_app()` (SPEC §1).", pytrace=False)
    app = mod.criar_app()
    app.config.update(TESTING=True, PROPAGATE_EXCEPTIONS=False)
    return app


@pytest.fixture()
def app(banco):
    return _criar_app()


@pytest.fixture()
def anonimo(app):
    return app.test_client()


@pytest.fixture()
def cliente_de(app):
    """Fabrica: cliente_de('admin') -> test client ja autenticado (um por perfil, por teste)."""
    cache = {}

    def _fabrica(chave: str):
        if chave not in cache:
            c = app.test_client()
            logar_como(c, chave)
            cache[chave] = c
        return cache[chave]

    return _fabrica


@pytest.fixture()
def admin(cliente_de):
    return cliente_de("admin")


@pytest.fixture()
def tecnico(cliente_de):
    return cliente_de("tecnico")


@pytest.fixture()
def gestor(cliente_de):
    return cliente_de("gestor")


@pytest.fixture()
def comum(cliente_de):
    return cliente_de("comum")


# ---------------------------------------------------------------------------
# Servidor real (para Playwright e testes de concorrencia)
# ---------------------------------------------------------------------------

def porta_livre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def servidor(banco_modelo, tmp_path_factory):
    """Sobe o app numa porta livre com banco temporario proprio. Retorna a URL base."""
    d = tmp_path_factory.mktemp("srv")
    db = str(d / "servidor.db")
    shutil.copyfile(banco_modelo, db)
    porta = porta_livre()
    env = dict(os.environ)
    env.update({"TECHMAINT_DB": db, "PYTHONUNBUFFERED": "1", "PORT": str(porta), "FLASK_RUN_PORT": str(porta)})
    env.pop("FLASK_DEBUG", None)
    codigo = (
        "import app as m; "
        f"m.app.run(host='127.0.0.1', port={porta}, threaded=True, use_reloader=False, debug=False)"
    )
    log = open(d / "servidor.log", "w")
    proc = subprocess.Popen([sys.executable, "-c", codigo], cwd=REPO, env=env, stdout=log, stderr=subprocess.STDOUT)
    base = f"http://127.0.0.1:{porta}"
    limite = time.time() + 40
    ok = False
    while time.time() < limite:
        if proc.poll() is not None:
            break
        try:
            with socket.create_connection(("127.0.0.1", porta), timeout=0.5):
                ok = True
                break
        except OSError:
            time.sleep(0.3)
    if not ok:
        proc.kill()
        log.close()
        pytest.fail("O servidor nao subiu:\n" + (d / "servidor.log").read_text()[-2000:], pytrace=False)
    info = type("Servidor", (), {"url": base, "db": db, "porta": porta, "log": str(d / "servidor.log")})
    yield info
    proc.terminate()
    try:
        proc.wait(timeout=8)
    except subprocess.TimeoutExpired:
        proc.kill()
    log.close()
