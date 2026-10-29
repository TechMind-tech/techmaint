"""
Testes exploratorios automatizados: fuzz de formularios, valores/datas extremas, concorrencia simples em saldo de estoque.

Rastreabilidade: SPEC §6 (validacao no servidor; 500 -> pagina amigavel), RNF Desempenho/Seguranca, SPEC §3 regra 2/3
(saldo nunca negativo), Projeto §7 (pedido 1:1 OS), unicidade de codigo/CNPJ.
Os de concorrencia usam o servidor REAL (threads) e sao marcados `lento`.
"""

import random
import re
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from fluxo_util import ALIASES_OS_PECA, add_peca, criar_pedido, abrir_os, peca_id, saldo
from helpers import (Bruto, USUARIOS_DEMO, consulta, contar, defaults_do_form, enviar, formularios, html_de, um)

CORPUS = [
    "", " ", "   ", "0", "-1", "-0", "1e999", "NaN", "Infinity", "9" * 40, "0.0000001", "1,5", "1.000,00", "١٢٣", "０１２",
    "a" * 300, "a" * 10000, "'", "\"", "\\", "';--", "' OR 1=1 --", "<script>alert(1)</script>", "{{7*7}}", "${7*7}", "%s%s%s%n",
    "\x00", "\x00abc", "\r\n", "‮", "🙂" * 20, "ç ã é ñ ü", "日本語", "null", "None", "true", "[]", "{}", "../../etc/passwd",
    "2026-02-30", "31/02/2026", "0000-00-00", "9999-12-31", "1900-01-01", "2026-13-45", "a@b", "a@b.c", "(11) 99999-9999",
    "00.000.000/0000-00", "12.345.678/0001-95", "99999-999", "ZZ",
]

FORMS = [  # (pagina que contem o formulario, perfil, filtro de action)
    ("/usuarios", "admin", None), ("/equipamentos", "admin", None), ("/pecas", "admin", None), ("/fornecedores/novo", "admin", None),
    ("/prestadores/novo", "admin", None), ("/departamentos", "admin", None), ("/pedidos/novo", "admin", None), ("/os/nova", "admin", None),
    ("/estoque", "admin", None), ("/configuracoes", "tecnico", None), ("/os/10234", "admin", "/pecas"), ("/os/10234", "admin", "/servicos"),
    ("/os/10234", "admin", "/apontamentos"),
]


def _fuzz_form(client, pagina, action_contem, rnd, rodadas):
    r = client.get(pagina)
    forms = [f for f in formularios(html_de(r)) if f.method == "post" and "csrf_token" in f.nomes]
    if action_contem:
        forms = [f for f in forms if action_contem in f.action and "/editar" not in f.action and "/excluir" not in f.action]
    form = max(forms, key=lambda f: len(f.campos))
    ruins = []
    for i in range(rodadas):
        payload = defaults_do_form(form)
        for c in form.campos:
            if not c.nome or c.nome == "csrf_token" or c.tipo == "hidden":
                continue
            if c.tag == "select" or c.tipo == "radio":
                if rnd.random() < 0.3:
                    payload[c.nome] = rnd.choice(CORPUS)
                continue
            if c.tipo == "checkbox":
                if rnd.random() < 0.5:
                    payload.pop(c.nome, None)
                continue
            payload[c.nome] = rnd.choice(CORPUS)
        resp = client.post(form.action or pagina, data=payload)
        if resp.status_code >= 500:
            ruins.append((resp.status_code, {k: (v[:40] if isinstance(v, str) else v) for k, v in payload.items() if k != "csrf_token"}))
    return ruins


@pytest.mark.lento
@pytest.mark.parametrize("pagina,perfil,action", FORMS, ids=[f"{p}{'|' + a if a else ''}" for p, _, a in FORMS])
def test_fuzz_de_formulario_nunca_gera_500(cliente_de, pagina, perfil, action):
    rnd = random.Random(20261026)
    ruins = _fuzz_form(cliente_de(perfil), pagina, action, rnd, 60)
    assert not ruins, f"{pagina}: {len(ruins)} respostas 5xx com entrada aleatoria (primeiras): {ruins[:2]}"
    assert consulta("PRAGMA foreign_key_check") == []
    assert um("PRAGMA integrity_check") == "ok"


@pytest.mark.lento
def test_fuzz_nao_deixa_saldo_negativo_nem_quantidade_invalida(cliente_de):
    rnd = random.Random(7)
    for _ in range(3):
        _fuzz_form(cliente_de("admin"), "/estoque", None, rnd, 40)
        _fuzz_form(cliente_de("admin"), "/os/10234", "/pecas", rnd, 40)
    assert contar("pecas", "qtde_estoque < 0") == 0, "Algum fuzz deixou saldo negativo"
    assert contar("itens_os", "quantidade <= 0") == 0
    assert contar("movimentacao_estoque_pecas", "quantidade <= 0") == 0
    assert contar("servicos_os", "valor_servico < 0") == 0
    assert contar("pecas", "valor_unitario < 0") == 0


@pytest.mark.parametrize("data", ["0000-00-00", "1900-01-01", "9999-12-31", "2026-02-30", "31/12/2026", "", "abc", "2026-1-1"])
def test_datas_extremas_em_apontamento(cliente_de, data):
    from fluxo_util import add_apontamento, pedido_com_os
    admin, tecnico = cliente_de("admin"), cliente_de("tecnico")
    _, oid = pedido_com_os(admin, tecnico)
    r = add_apontamento(tecnico, oid, data=data)
    assert r.status_code < 500
    assert contar("apontamentos_os", "id_os=? AND (data IS NULL OR data = '')", oid) == 0


def test_numeros_enormes_em_todas_as_rotas_de_id(admin):
    big = "9" * 50
    for url in (f"/pedidos/{big}", f"/os/{big}", f"/usuarios/{big}/editar", f"/equipamentos/{big}/editar", f"/pecas/{big}/editar",
                f"/api/subgrupos?grupo_id={big}", f"/api/dashboard?equipamento_id={big}&departamento_id={big}"):
        assert admin.get(url).status_code < 500, url


def test_busca_unicode_e_normalizacao(admin):
    """'Producao' (sem acento) idealmente acha 'Produção'; ao menos nao quebra."""
    r = admin.get("/equipamentos?busca=Producao")
    assert r.status_code == 200
    r = admin.get("/equipamentos?busca=produ%C3%A7%C3%A3o")
    assert r.status_code == 200


# --------------------------------------------------------------------------------------------- concorrencia (servidor real)

class Usuario:
    """Cliente HTTP real com cookies (requests) logado num perfil."""

    def __init__(self, base, chave="admin"):
        import requests
        self.base, self.s = base, requests.Session()
        login, senha, _ = USUARIOS_DEMO[chave]
        r = self.s.get(base + "/login")
        tok = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', r.text) or re.search(r'value="([^"]+)"[^>]*name="csrf_token"', r.text)
        self.csrf = tok.group(1)
        form = formularios(r.text)[0]
        campos = {c.nome: c for c in form.campos}
        un = next(n for n in campos if n in ("usuario", "login", "username"))
        sn = next(n for n in campos if "senha" in n or "pass" in n)
        r = self.s.post(base + "/login", data={"csrf_token": self.csrf, un: login, sn: senha}, allow_redirects=False)
        assert r.status_code in (302, 303), f"login falhou no servidor real: {r.status_code}"

    def token(self, url):
        r = self.s.get(self.base + url)
        m = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', r.text) or re.search(r'value="([^"]+)"[^>]*name="csrf_token"', r.text)
        return m.group(1) if m else self.csrf

    def post(self, url, data):
        data = dict(data)
        data.setdefault("csrf_token", self.csrf)
        return self.s.post(self.base + url, data=data, allow_redirects=False)


@pytest.fixture()
def http(servidor):
    return lambda chave="admin": Usuario(servidor.url, chave)


def _campo_estoque(u, pagina="/estoque"):
    """Descobre os nomes reais dos campos do formulario de movimentacao."""
    r = u.s.get(u.base + pagina)
    f = max([f for f in formularios(r.text) if f.method == "post" and "csrf_token" in f.nomes], key=lambda x: len(x.campos))
    return f, defaults_do_form(f)


@pytest.mark.lento
def test_concorrencia_saidas_de_estoque_nao_geram_saldo_negativo(servidor, http):
    db = servidor.db
    u0 = http("admin")
    f, base = _campo_estoque(u0)
    from helpers import _resolver_nome
    from fluxo_util import ALIASES_ESTOQUE
    pid = um("SELECT id FROM pecas WHERE nome='Filtro de Ar'", path=db)
    inicial = float(um("SELECT qtde_estoque FROM pecas WHERE id=?", pid, path=db))
    n = lambda k: _resolver_nome(f, ALIASES_ESTOQUE[k], k)
    pay = dict(base)
    pay.update({n("tipo"): "Saída", n("peca"): str(pid), n("quantidade"): "10", n("valor"): "1", n("documento"): "Pedido Interno", n("numero"): "PI-CONC"})
    usuarios = [http("admin") for _ in range(10)]
    barreira = threading.Barrier(len(usuarios))

    def tentar(u):
        barreira.wait()
        p = dict(pay)
        p["csrf_token"] = u.csrf
        return u.post("/estoque", p).status_code

    with ThreadPoolExecutor(len(usuarios)) as ex:
        codigos = list(ex.map(tentar, usuarios))
    assert all(c < 500 for c in codigos), f"500 em concorrencia: {codigos}"
    final = float(um("SELECT qtde_estoque FROM pecas WHERE id=?", pid, path=db))
    sucessos = um("SELECT COUNT(*) FROM movimentacao_estoque_pecas WHERE id_peca=? AND numero_documento='PI-CONC'", pid, path=db)
    assert final >= 0, f"Saldo NEGATIVO apos saidas concorrentes: {final}"
    assert sucessos <= int(inicial // 10), f"{sucessos} saidas de 10 aceitas com saldo inicial {inicial} (race condition)"
    assert final == inicial - 10 * sucessos, f"Saldo ({final}) inconsistente com as movimentacoes registradas ({sucessos} x 10)"


@pytest.mark.lento
def test_concorrencia_pecas_na_mesma_os_respeitam_o_saldo(servidor, http):
    db = servidor.db
    admin, tecnico = http("admin"), http("tecnico")
    from helpers import post as _p
    # cria pedido + OS via HTTP real
    f, base = _campo_estoque(admin, "/pedidos/novo")
    from helpers import _resolver_nome
    from fluxo_util import ALIASES_PEDIDO
    pay = dict(base)
    for k, v in (("equipamento", um("SELECT id FROM equipamentos WHERE descricao='BOMBA 2 (RESFRIADOR)'", path=db)),
                 ("departamento", um("SELECT id FROM departamentos WHERE nome='Utilidades'", path=db)),
                 ("descricao", "OS concorrente QA"), ("prioridade", "Média")):
        pay[_resolver_nome(f, ALIASES_PEDIDO[k], k)] = str(v)
    pay["csrf_token"] = admin.csrf
    assert admin.post("/pedidos/novo", pay).status_code in (302, 303)
    pid = um("SELECT id FROM pedidos_manutencao WHERE descricao_problema='OS concorrente QA'", path=db)
    assert tecnico.post(f"/pedidos/{pid}/abrir-os", {}).status_code in (302, 303)
    oid = um("SELECT id FROM ordens_servico WHERE id_pedido=?", pid, path=db)
    pecaid = um("SELECT id FROM pecas WHERE nome='Sensor Indutivo'", path=db)
    inicial = float(um("SELECT qtde_estoque FROM pecas WHERE id=?", pecaid, path=db))
    r = tecnico.s.get(tecnico.base + f"/os/{oid}")
    form = next(f for f in formularios(r.text) if f.method == "post" and "/pecas" in f.action and "/editar" not in f.action and "/excluir" not in f.action)
    campos = defaults_do_form(form)
    npeca = _resolver_nome(form, ["id_peca", "peca"], "peca")
    nq = _resolver_nome(form, ["quantidade", "qtde"], "quantidade")
    usuarios = [http("tecnico") for _ in range(8)]
    barreira = threading.Barrier(len(usuarios))
    qtd = int(inicial // 3) + 1          # 3 tentativas ja estouram o saldo

    def tentar(u):
        barreira.wait()
        p = dict(campos)
        p.update({npeca: str(pecaid), nq: str(qtd), "csrf_token": u.csrf})
        return u.post(form.action, p).status_code

    with ThreadPoolExecutor(len(usuarios)) as ex:
        codigos = list(ex.map(tentar, usuarios))
    assert all(c < 500 for c in codigos), codigos
    final = float(um("SELECT qtde_estoque FROM pecas WHERE id=?", pecaid, path=db))
    usados = float(um("SELECT COALESCE(SUM(quantidade),0) FROM itens_os WHERE id_os=? AND id_peca=?", oid, pecaid, path=db))
    assert final >= 0, f"Saldo negativo ({final}) com pecas lancadas em paralelo na mesma OS"
    assert final == inicial - usados, f"Saldo {final} != inicial {inicial} - usado {usados}"


@pytest.mark.lento
def test_concorrencia_abrir_os_do_mesmo_pedido_cria_so_uma(servidor, http):
    db = servidor.db
    pid = 1626
    usuarios = [http("tecnico") for _ in range(8)]
    barreira = threading.Barrier(len(usuarios))

    def tentar(u):
        barreira.wait()
        return u.post(f"/pedidos/{pid}/abrir-os", {}).status_code

    with ThreadPoolExecutor(len(usuarios)) as ex:
        codigos = list(ex.map(tentar, usuarios))
    assert all(c < 500 for c in codigos), codigos
    assert um("SELECT COUNT(*) FROM ordens_servico WHERE id_pedido=?", pid, path=db) == 1, "Pedido 1:1 OS violado sob concorrencia"


@pytest.mark.lento
def test_concorrencia_codigo_de_equipamento_unico(servidor, http):
    from helpers import escolher_form, montar_payload
    db = servidor.db
    u0 = http("admin")
    r = u0.s.get(u0.base + "/equipamentos")
    aliases = {"codigo": ["codigo"], "descricao": ["descricao"], "grupo": ["id_grupo", "grupo"], "subgrupo": ["id_subgrupo", "subgrupo"],
               "departamento": ["id_departamento", "departamento"], "status": ["status"]}
    dados = dict(codigo="QA.CONC.001", descricao="Equipamento concorrente", grupo="Produção", subgrupo="Injetoras",
                 departamento="Produção", status="Ativo")
    form = escolher_form(formularios(r.text), dados, aliases)
    pay = montar_payload(form, dados, aliases, estrito=False)
    usuarios = [http("admin") for _ in range(8)]
    barreira = threading.Barrier(len(usuarios))

    def tentar(u):
        barreira.wait()
        p = dict(pay)
        p["csrf_token"] = u.csrf
        return u.post(form.action or "/equipamentos", p).status_code

    with ThreadPoolExecutor(len(usuarios)) as ex:
        codigos = list(ex.map(tentar, usuarios))
    assert all(c < 500 for c in codigos), f"Corrida no codigo unico gerou erro 500 (IntegrityError sem tratamento): {codigos}"
    assert um("SELECT COUNT(*) FROM equipamentos WHERE codigo='QA.CONC.001'", path=db) == 1


@pytest.mark.lento
def test_rajada_de_leituras_nao_trava_o_banco(servidor, http):
    usuarios = [http("admin") for _ in range(10)]

    def ler(u):
        return [u.s.get(u.base + p).status_code for p in ("/dashboard", "/api/dashboard?periodo=12m", "/pedidos", "/os", "/pecas", "/estoque")]

    with ThreadPoolExecutor(len(usuarios)) as ex:
        resultados = list(ex.map(ler, usuarios))
    ruins = [c for r in resultados for c in r if c != 200]
    assert not ruins, f"Rajada de leituras paralelas gerou respostas != 200 ('database is locked'?): {ruins[:5]}"


@pytest.mark.lento
def test_escrita_e_leitura_simultaneas(servidor, http):
    db = servidor.db
    escritor = http("admin")
    leitores = [http("admin") for _ in range(4)]
    parar = threading.Event()
    erros = []

    def ler(u):
        while not parar.is_set():
            c = u.s.get(u.base + "/pecas").status_code
            if c >= 500:
                erros.append(c)

    ths = [threading.Thread(target=ler, args=(u,)) for u in leitores]
    for t in ths:
        t.start()
    f, base = _campo_estoque(escritor)
    from helpers import _resolver_nome
    from fluxo_util import ALIASES_ESTOQUE
    n = lambda k: _resolver_nome(f, ALIASES_ESTOQUE[k], k)
    pid = um("SELECT id FROM pecas WHERE nome='Correia V'", path=db)
    for i in range(15):
        p = dict(base)
        p.update({n("tipo"): "Entrada", n("peca"): str(pid), n("quantidade"): "1", n("valor"): "1", n("documento"): "Nota Fiscal", n("numero"): f"NF-RW-{i}"})
        p["csrf_token"] = escritor.csrf
        escritor.post("/estoque", p)
    parar.set()
    for t in ths:
        t.join()
    assert not erros, f"Leitores receberam 5xx durante escritas: {erros[:5]}"
    assert um("SELECT COUNT(*) FROM movimentacao_estoque_pecas WHERE numero_documento LIKE 'NF-RW-%'", path=db) == 15
