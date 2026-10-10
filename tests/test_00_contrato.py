"""
Contrato estrutural (SPEC §1, §4, §5): arquivos, rotas registradas e higiene estatica do codigo.

Estes testes falham de forma clara quando um entregavel prometido na SPEC nao existe.
Rastreabilidade: RNF Manutencao/Escalabilidade (modular), RNF Seguranca, SPEC §1.
"""

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

MODULOS = ["auth", "painel", "usuarios", "equipamentos", "pecas", "fornecedores", "prestadores",
           "departamentos", "pedidos", "ordens", "estoque", "relatorios", "configuracoes"]

TEMPLATES = ["base.html", "base_auth.html", "login.html", "recuperar_senha.html", "redefinir_senha.html",
             "menu_principal.html", "dashboard.html", "usuarios.html", "equipamentos.html", "pecas.html",
             "fornecedores.html", "fornecedor_form.html", "prestadores.html", "prestador_form.html",
             "departamentos.html", "pedidos.html", "pedido_form.html", "pedido_detalhe.html", "os_lista.html",
             "os_form.html", "os_detalhe.html", "estoque.html", "relatorios.html", "configuracoes.html",
             "403.html", "404.html", "500.html"]

# endpoint -> (metodos que devem existir)  (SPEC §4)
ENDPOINTS = {
    "auth.login": {"GET", "POST"}, "auth.logout": {"POST"}, "auth.recuperar_senha": {"GET", "POST"},
    "painel.inicio": {"GET"}, "painel.menu_principal": {"GET"}, "painel.dashboard": {"GET"},
    "painel.api_dashboard": {"GET"}, "painel.exportar_pdf": {"GET"}, "painel.exportar_xlsx": {"GET"},
    "usuarios.listar": {"GET", "POST"}, "usuarios.editar": {"GET", "POST"}, "usuarios.excluir": {"POST"},
    "equipamentos.listar": {"GET", "POST"}, "equipamentos.editar": {"GET", "POST"},
    "equipamentos.excluir": {"POST"}, "equipamentos.api_subgrupos": {"GET"},
    "pecas.listar": {"GET", "POST"}, "pecas.editar": {"GET", "POST"}, "pecas.excluir": {"POST"},
    "fornecedores.listar": {"GET"}, "fornecedores.novo": {"GET", "POST"}, "fornecedores.editar": {"GET", "POST"},
    "fornecedores.excluir": {"POST"},
    "prestadores.listar": {"GET"}, "prestadores.novo": {"GET", "POST"}, "prestadores.editar": {"GET", "POST"},
    "prestadores.excluir": {"POST"},
    "departamentos.listar": {"GET", "POST"}, "departamentos.editar": {"GET", "POST"},
    "departamentos.excluir": {"POST"},
    "pedidos.listar": {"GET"}, "pedidos.novo": {"GET", "POST"}, "pedidos.detalhe": {"GET"},
    "pedidos.editar": {"GET", "POST"}, "pedidos.cancelar": {"POST"}, "pedidos.aprovar": {"POST"},
    "ordens.listar": {"GET"}, "ordens.nova": {"GET", "POST"}, "ordens.detalhe": {"GET"},
    "ordens.editar": {"GET", "POST"}, "ordens.adicionar_peca": {"POST"}, "ordens.fechar": {"POST"},
    "ordens.excluir": {"POST"},
    "estoque.listar": {"GET", "POST"}, "estoque.excluir": {"POST"},
    "relatorios.pagina": {"GET"}, "relatorios.api": {"GET"}, "relatorios.exportar": {"GET"},
    "configuracoes.pagina": {"GET", "POST"},
}


def test_arquivos_do_backend_existem():
    faltando = [f for f in ["app.py", "database.py", "schema.sql", "seed.py", "requirements.txt", "README.md"]
                if not (REPO / f).exists()]
    assert not faltando, f"Arquivos do Dev ausentes (SPEC §1): {faltando}"


def test_pacote_modulos_tem_um_blueprint_por_modulo():
    ausentes = [m for m in MODULOS if not (REPO / "modulos" / f"{m}.py").exists()]
    assert not ausentes, f"Faltam modulos/*.py (SPEC §1): {ausentes}"
    assert (REPO / "servicos").is_dir(), "Falta o pacote servicos/ (regras de negocio e exportacao) - SPEC §1"
    assert (REPO / "dados").is_dir(), "Falta a pasta dados/ (JSON de grupos/subgrupos/equipamentos) - SPEC §1"


def test_templates_do_contrato_existem():
    ausentes = [t for t in TEMPLATES if not (REPO / "templates" / t).exists()]
    assert not ausentes, f"Templates ausentes (SPEC §4): {ausentes}"


def test_chartjs_e_fontes_empacotados_localmente():
    vend = REPO / "static" / "vendor"
    assert vend.is_dir(), "static/vendor/ nao existe (Chart.js local, SPEC §1)"
    js = [p for p in vend.rglob("*.js") if "chart" in p.name.lower()]
    assert js, "Chart.js nao esta em static/vendor/ (precisa funcionar offline, SPEC §1)"
    assert js[0].stat().st_size > 50_000, f"{js[0].name} parece incompleto ({js[0].stat().st_size} bytes)"


def test_requirements_lista_dependencias_minimas():
    txt = (REPO / "requirements.txt").read_text().lower()
    for pkg in ("flask", "openpyxl", "reportlab"):
        assert pkg in txt, f"requirements.txt deveria listar {pkg} (SPEC §1/§8)"


def test_readme_documenta_usuarios_de_demonstracao():
    txt = (REPO / "README.md").read_text(encoding="utf-8").lower()
    for login in ("admin", "tecnico", "gestor", "solicitante", "plima"):
        assert login in txt, f"README deveria documentar o usuario de demonstracao '{login}' (SPEC §2)"
    assert "seed.py" in txt, "README deveria explicar como rodar `python seed.py` (SPEC §8)"


def test_endpoints_registrados(app):
    regras = {}
    for r in app.url_map.iter_rules():
        regras.setdefault(r.endpoint, set()).update(r.methods - {"HEAD", "OPTIONS"})
    faltando = [e for e in ENDPOINTS if e not in regras]
    assert not faltando, f"Endpoints do contrato (SPEC §4) nao registrados: {faltando}. Registrados: {sorted(regras)}"
    metodos_ruins = {e: (m, sorted(regras[e])) for e, m in ENDPOINTS.items() if not m <= regras[e]}
    assert not metodos_ruins, f"Endpoint sem os metodos HTTP do contrato {{endpoint: (esperado, obtido)}}: {metodos_ruins}"


def test_urls_do_contrato(app):
    urls = {r.rule for r in app.url_map.iter_rules()}
    esperadas = ["/login", "/logout", "/recuperar-senha", "/menu", "/dashboard", "/api/dashboard",
                 "/dashboard/exportar.pdf", "/dashboard/exportar.xlsx", "/usuarios", "/equipamentos",
                 "/api/subgrupos", "/pecas", "/fornecedores", "/fornecedores/novo", "/prestadores",
                 "/departamentos", "/pedidos", "/pedidos/novo", "/os", "/os/nova", "/estoque", "/relatorios",
                 "/configuracoes"]
    faltando = [u for u in esperadas if u not in urls]
    assert not faltando, f"URLs do contrato ausentes: {faltando}"
    padroes = [r"/usuarios/<int:\w+>/editar", r"/pedidos/<int:\w+>/abrir-os", r"/os/<int:\w+>/fechar",
               r"/os/<int:\w+>/pecas", r"/relatorios/<[^>]+>/exportar", r"/redefinir-senha/<"]
    for p in padroes:
        assert any(re.search(p, u) for u in urls), f"Nenhuma rota casa com o padrao do contrato: {p}"


def _fontes_python():
    arquivos = [REPO / "app.py", REPO / "database.py", REPO / "seed.py"]
    for pasta in ("modulos", "servicos"):
        arquivos += list((REPO / pasta).glob("*.py")) if (REPO / pasta).is_dir() else []
    return [a for a in arquivos if a.exists()]


def test_sem_segredo_fixo_no_codigo():
    ruins = []
    for f in _fontes_python():
        for n, l in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"secret_key\s*=\s*[\"'][^\"']+[\"']", l, re.I) or re.search(r"SECRET_KEY[\"']?\]?\s*=\s*[\"'][^\"']{6,}[\"']", l):
                ruins.append(f"{f.name}:{n}: {l.strip()}")
    assert not ruins, ("SECRET_KEY nao pode ser literal no codigo (deve vir de TECHMAINT_SECRET_KEY, SPEC §1). "
                       f"Ocorrencias: {ruins}")


def test_sql_sem_concatenacao_de_entrada_do_usuario():
    """Analise por AST: execute() com f-string/concatenacao/format/% nao pode interpolar valor que venha
    direto de `request` (args/form/values/json). Identificadores internos (tabela, ordem via whitelist,
    where montado com '?') sao aceitos; a whitelist de ORDER BY e coberta por test_exploratorio/test_seguranca."""
    import ast
    suspeitos = []
    for f in _fontes_python():
        if f.name == "seed.py":
            continue
        arvore = ast.parse(f.read_text(encoding="utf-8"))
        for no in ast.walk(arvore):
            if not (isinstance(no, ast.Call) and isinstance(no.func, ast.Attribute)
                    and no.func.attr in ("execute", "executemany", "executescript") and no.args):
                continue
            sql = no.args[0]
            dinamico = isinstance(sql, (ast.JoinedStr, ast.BinOp)) or (
                isinstance(sql, ast.Call) and isinstance(sql.func, ast.Attribute) and sql.func.attr == "format")
            if not dinamico:
                continue
            nomes = {n.id for n in ast.walk(sql) if isinstance(n, ast.Name)}
            if "request" in nomes or "form" in nomes or "args" in nomes:
                suspeitos.append(f"{f.name}:{no.lineno}")
    assert not suspeitos, ("SQL deve ser sempre parametrizado (SPEC §1): execute() interpola dado de request em "
                           f"{suspeitos}")


def test_templates_sem_safe_em_dado_do_usuario():
    ruins = []
    for t in (REPO / "templates").glob("*.html"):
        for n, l in enumerate(t.read_text(encoding="utf-8").splitlines(), 1):
            if t.name == "_icones.html" and "_ICONES.get(" in l:
                continue  # SVG de dicionario constante interno (nome desconhecido cai num circulo literal)
            if re.search(r"\|\s*safe\b", l) or "Markup(" in l or "autoescape false" in l:
                ruins.append(f"{t.name}:{n}: {l.strip()[:120]}")
    assert not ruins, f"Uso de |safe/Markup/autoescape off nos templates (SPEC §1: nunca em dado do usuario): {ruins}"


def test_nenhuma_dependencia_de_cdn_no_front():
    """Sistema precisa funcionar offline (SPEC §1/§5): sem http(s):// externo em templates/CSS/JS proprios."""
    permitido = ("www.w3.org", "localhost", "127.0.0.1")
    ruins = []
    arquivos = list((REPO / "templates").glob("*.html"))
    for ext in ("css", "js"):
        arquivos += [p for p in (REPO / "static").rglob(f"*.{ext}") if "vendor" not in p.parts]
    for f in arquivos:
        txt = f.read_text(encoding="utf-8", errors="ignore")
        txt = re.sub(r"\{#.*?#\}|<!--.*?-->|/\*.*?\*/", "", txt, flags=re.S)  # comentarios nao carregam rede
        for m in re.finditer(r"https?://([\w.\-]+)", txt):
            if not m.group(1).startswith(permitido):
                ruins.append(f"{f.relative_to(REPO)}: {m.group(0)}")
    assert not ruins, f"Referencias a recursos externos (CDN/Google Fonts...) - SPEC §1: {sorted(set(ruins))[:15]}"


def test_vendor_css_e_js_sem_urls_externas_carregaveis():
    """@import url(http...) / src=http em vendor local carregaria rede em runtime."""
    ruins = []
    for f in (REPO / "static").rglob("*.css"):
        txt = f.read_text(encoding="utf-8", errors="ignore")
        for m in re.finditer(r"@import\s+url\(\s*[\"']?(https?://[^)\"']+)", txt):
            ruins.append(f"{f.relative_to(REPO)}: {m.group(1)}")
        for m in re.finditer(r"url\(\s*[\"']?(https?://[^)\"']+)", txt):
            ruins.append(f"{f.relative_to(REPO)}: {m.group(1)}")
    assert not ruins, f"CSS carrega recurso externo: {ruins[:10]}"


def test_nenhum_banco_ou_lixo_dentro_do_repo():
    # *.db na raiz e ignorado pelo .gitignore (banco local de quem roda o app); fora da raiz e lixo.
    lixo = [p for p in REPO.rglob("*") if p.suffix in (".db", ".sqlite", ".sqlite3") and ".git" not in p.parts
            and ".venv" not in p.parts and p.parent != REPO]
    assert not lixo, f"Arquivos de banco fora da raiz do repositorio (usar diretorio temporario): {lixo}"
    assert "*.db" in (REPO / ".gitignore").read_text(), ".gitignore deve ignorar *.db"
