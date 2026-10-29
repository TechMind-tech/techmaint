"""
Dashboard, Relatorios e APIs JSON (Manual §3, Figma 03-04 e 20-21, SPEC §4 /dashboard, /api/dashboard, /relatorios, /api/relatorios/<aba>).

Rastreabilidade: Projeto §8 (indicadores: tempo medio de atendimento, custo por maquina, pecas mais usadas, status das ordens),
RF "Emissao de Relatorios: financeiros, operacionais e de manutencao, filtros por data, categoria e maquina" (§15b),
Manual 3.1 (filtros periodo/departamento/equipamento; Exportar PDF/Excel, Atualizar) e 3.2 (estoque, fornecedores/prestadores,
OS por status/tecnico/departamento, financeiro por OS/equipamento), apoio §4 (periodos: 7 dias, 30 dias, 6 meses, ano).
"""

import re

import pytest

from helpers import consulta, contar, html_de, numero, texto_visivel, um

PERIODOS = ["7d", "30d", "6m", "12m"]
ABAS = ["os", "estoque", "financeiro", "fornecedores"]
CHAVES_GRAFICOS_DASH = ["tempo_medio", "custo_por_maquina", "pecas_mais_usadas", "status_ordens"]


def _dash(c, qs=""):
    r = c.get("/api/dashboard" + (("?" + qs) if qs else ""))
    assert r.status_code == 200, f"/api/dashboard?{qs} -> {r.status_code}"
    assert r.mimetype == "application/json"
    return r.get_json()


def _total_ordens(j):
    return sum(x["valor"] for x in j["status_ordens"])


# --------------------------------------------------------------------------------------------- pagina do dashboard

def test_tela_do_dashboard(admin):
    r = admin.get("/dashboard")
    assert r.status_code == 200
    t = texto_visivel(html_de(r))
    for trecho in ("Dashboard de Indicadores", "Exportar PDF", "Exportar Excel", "Atualizar", "Pedidos Abertos", "OS em Andamento",
                   "OS Concluídas/Mês", "Custo Total do Mês", "Tempo Médio de Atendimento", "Custo por Máquina",
                   "Peças Mais Utilizadas", "Status das Ordens"):
        assert trecho.lower() in t.lower(), f"Figma 03/04: {trecho!r} ausente do dashboard"


def test_dashboard_tem_filtros_periodo_departamento_equipamento(admin):
    from helpers import formularios
    h = html_de(admin.get("/dashboard"))
    nomes = " ".join(n for f in formularios(h) for n in f.nomes).lower()
    selects = {c.nome: c for f in formularios(h) for c in f.campos if c.tag == "select"}
    assert any("periodo" in n for n in selects), f"Filtro de periodo ausente (Manual 3.1). Selects: {list(selects)}"
    assert any("departamento" in n for n in selects), "Filtro de departamento ausente"
    assert any("equipamento" in n for n in selects), "Filtro de equipamento ausente"


def test_dashboard_usa_canvas_dos_graficos_e_chartjs_local(admin):
    h = html_de(admin.get("/dashboard"))
    assert h.count("<canvas") >= 4, "4 graficos (canvas) esperados (Manual 3.1)"
    srcs = re.findall(r'<script[^>]+src="([^"]+)"', h)
    assert any("chart" in s.lower() for s in srcs), f"Chart.js nao carregado: {srcs}"
    assert all(s.startswith("/") or s.startswith("{{") for s in srcs), f"Script externo (CDN) no dashboard: {srcs}"


def test_dashboard_graficos_tem_versao_tabular_acessivel(admin):
    h = html_de(admin.get("/dashboard"))
    assert "sr-only" in h or "<details" in h, "SPEC §5: cada grafico deve ter versao tabular acessivel (table.sr-only ou details)"
    assert h.count("<table") >= 4 or h.count("<details") >= 4


def test_dashboard_kpis_nao_sao_os_numeros_fixos_do_figma(admin):
    """12/5/18/R$ 32.500 sao so o Figma; o sistema real calcula do banco (SPEC §3)."""
    j = _dash(admin)
    kp = j["kpis"]
    abertos = contar("pedidos_manutencao", "status='Aberto'")
    assert any(v == abertos for v in kp.values() if isinstance(v, (int, float))), f"kpis nao contem o numero de abertos do banco ({abertos}): {kp}"


# --------------------------------------------------------------------------------------------- /api/dashboard shape

def test_api_dashboard_shape(admin):
    j = _dash(admin)
    for k in CHAVES_GRAFICOS_DASH + ["kpis"]:
        assert k in j, f"/api/dashboard sem a chave {k!r} (SPEC §4). Chaves: {list(j)}"
    assert isinstance(j["kpis"], dict) and j["kpis"]
    for k in CHAVES_GRAFICOS_DASH:
        assert isinstance(j[k], list), f"{k} deve ser lista"
        for item in j[k]:
            assert set(item) >= {"rotulo", "valor"}, f"{k}: item sem rotulo/valor: {item}"
            assert isinstance(item["rotulo"], str) and isinstance(item["valor"], (int, float)), f"{k}: tipos invalidos {item}"


def test_api_dashboard_com_seed_traz_dados_em_todos_os_graficos_12m(admin):
    j = _dash(admin, "periodo=12m")
    assert len(j["tempo_medio"]) >= 6, f"Tempo medio: esperado ~12 pontos mensais com o historico do seed, veio {len(j['tempo_medio'])}"
    assert len(j["custo_por_maquina"]) >= 3
    assert len(j["pecas_mais_usadas"]) >= 3
    assert len({x["rotulo"] for x in j["status_ordens"]}) >= 3
    assert all(x["valor"] >= 0 for k in CHAVES_GRAFICOS_DASH for x in j[k])


def test_periodos_sao_monotonicos(admin):
    tot = [_total_ordens(_dash(admin, f"periodo={p}")) for p in PERIODOS]
    assert tot == sorted(tot), f"Quanto maior o periodo, mais (ou igual) OS: {dict(zip(PERIODOS, tot))}"
    assert tot[-1] > tot[0], "12m deveria ter mais OS que 7d com o historico do seed"


def test_periodo_padrao_e_valido(admin):
    j = _dash(admin)
    assert _total_ordens(j) >= 0


@pytest.mark.parametrize("qs", ["periodo=xx", "periodo=", "periodo=999d", "departamento_id=abc", "departamento_id=99999",
                                "equipamento_id=99999", "equipamento_id=-1", "periodo=7d&departamento_id=1 OR 1=1",
                                "periodo=%27%3B--", "equipamento_id=" + "9" * 30])
def test_api_dashboard_entradas_invalidas_nao_quebram(admin, qs):
    r = admin.get("/api/dashboard?" + qs)
    assert r.status_code in (200, 400), f"{qs} -> HTTP {r.status_code}"
    if r.status_code == 200:
        j = r.get_json()
        assert set(CHAVES_GRAFICOS_DASH) <= set(j)


def test_filtro_por_departamento_reduz_e_particiona(admin):
    total = _total_ordens(_dash(admin, "periodo=12m"))
    partes = {}
    for d in consulta("SELECT id, nome FROM departamentos"):
        partes[d["nome"]] = _total_ordens(_dash(admin, f"periodo=12m&departamento_id={d['id']}"))
    assert all(v <= total for v in partes.values()), partes
    assert any(0 < v < total for v in partes.values()), f"Filtro de departamento nao filtra: total={total} {partes}"
    assert sum(partes.values()) <= total, "A soma por departamento nao pode passar do total (cada OS tem 1 departamento)"


def test_filtro_por_equipamento(admin):
    eqid = um("SELECT p.id_equipamento FROM ordens_servico o JOIN pedidos_manutencao p ON p.id=o.id_pedido GROUP BY p.id_equipamento ORDER BY COUNT(*) DESC LIMIT 1")
    total = _total_ordens(_dash(admin, "periodo=12m"))
    filtrado = _total_ordens(_dash(admin, f"periodo=12m&equipamento_id={eqid}"))
    assert 0 < filtrado < total, f"Filtro por equipamento nao filtrou: {filtrado} de {total}"
    n = um("SELECT COUNT(*) FROM ordens_servico o JOIN pedidos_manutencao p ON p.id=o.id_pedido WHERE p.id_equipamento=? "
           "AND date(o.data_abertura) >= date('now','-12 months')", eqid)
    assert filtrado == n, f"OS do equipamento no periodo: API {filtrado} x banco {n}"


def test_filtros_combinados_departamento_e_equipamento(admin):
    eq = consulta("SELECT p.id_equipamento e, p.id_departamento d FROM ordens_servico o JOIN pedidos_manutencao p ON p.id=o.id_pedido LIMIT 1")[0]
    j = _dash(admin, f"periodo=12m&equipamento_id={eq['e']}&departamento_id={eq['d']}")
    assert _total_ordens(j) >= 1
    outro = um("SELECT id FROM departamentos WHERE id <> ? LIMIT 1", eq["d"])
    assert _total_ordens(_dash(admin, f"periodo=12m&equipamento_id={eq['e']}&departamento_id={outro}")) <= _total_ordens(j)


def test_distribuicao_de_status_bate_com_o_banco(admin):
    j = _dash(admin, "periodo=12m")
    banco = {r["status"]: r["n"] for r in consulta("SELECT status, COUNT(*) n FROM ordens_servico WHERE date(data_abertura) >= date('now','-12 months') GROUP BY status")}
    tela = {x["rotulo"].lower(): x["valor"] for x in j["status_ordens"]}
    for status, n in banco.items():
        achados = [v for k, v in tela.items() if k.startswith(status.lower()[:6])]
        assert achados and achados[0] == n, f"status_ordens[{status}]: API {achados} x banco {n}"


def test_custo_por_maquina_bate_com_o_banco(admin):
    j = _dash(admin, "periodo=12m")
    soma_api = sum(x["valor"] for x in j["custo_por_maquina"])
    pecas = um("SELECT COALESCE(SUM(i.valor_total),0) FROM itens_os i JOIN ordens_servico o ON o.id=i.id_os WHERE date(o.data_abertura) >= date('now','-12 months')")
    serv = um("SELECT COALESCE(SUM(s.valor_servico),0) FROM servicos_os s JOIN ordens_servico o ON o.id=s.id_os WHERE date(o.data_abertura) >= date('now','-12 months')")
    total_banco = float(pecas) + float(serv)
    assert soma_api <= total_banco + 0.01, "A API nao pode somar mais que o banco"
    assert soma_api >= total_banco * 0.5, f"Custo por maquina (top N) muito abaixo do custo total do banco: {soma_api} x {total_banco}"
    valores = [x["valor"] for x in j["custo_por_maquina"]]
    assert valores == sorted(valores, reverse=True), "Custo por maquina deve vir ordenado (maior primeiro)"


def test_pecas_mais_usadas_bate_com_o_banco(admin):
    j = _dash(admin, "periodo=12m")
    top = consulta("SELECT p.nome, SUM(i.quantidade) q FROM itens_os i JOIN pecas p ON p.id=i.id_peca JOIN ordens_servico o ON o.id=i.id_os "
                   "WHERE date(o.data_abertura) >= date('now','-12 months') GROUP BY p.id ORDER BY q DESC")
    assert top, "seed sem itens de OS"
    primeiro = j["pecas_mais_usadas"][0]
    assert top[0]["nome"].lower()[:8] in primeiro["rotulo"].lower() or primeiro["valor"] == float(top[0]["q"]), \
        f"Peca mais usada: API {primeiro} x banco {top[0]}"
    valores = [x["valor"] for x in j["pecas_mais_usadas"]]
    assert valores == sorted(valores, reverse=True)


def test_tempo_medio_so_considera_os_fechadas_e_nunca_negativo(admin):
    j = _dash(admin, "periodo=12m")
    assert all(x["valor"] >= 0 for x in j["tempo_medio"]), "Tempo medio negativo"
    rotulos = [x["rotulo"] for x in j["tempo_medio"]]
    assert len(rotulos) == len(set(rotulos)), "Pontos duplicados na serie de tempo"


def test_dashboard_sem_dados_nao_quebra(admin):
    from helpers import executa
    executa("DELETE FROM apontamentos_os")
    executa("DELETE FROM servicos_os")
    executa("DELETE FROM itens_os")
    executa("DELETE FROM ordens_servico")
    j = _dash(admin, "periodo=12m")
    assert all(isinstance(j[k], list) for k in CHAVES_GRAFICOS_DASH)
    assert admin.get("/dashboard").status_code == 200, "Dashboard com banco sem OS nao pode quebrar (estado vazio)"


def test_dashboard_exige_login(anonimo):
    assert anonimo.get("/api/dashboard").status_code in (302, 401)


# --------------------------------------------------------------------------------------------- relatorios (pagina)

def test_tela_de_relatorios(admin):
    r = admin.get("/relatorios")
    assert r.status_code == 200
    t = texto_visivel(html_de(r))
    for trecho in ("Relatórios e Dashboards", "Exportar PDF", "Exportar Excel", "Período", "Departamento", "Técnico", "Atualizar",
                   "Ordens de Serviço", "Estoque", "Financeiro", "Fornecedores", "OS por Técnico", "Custo por Técnico",
                   "Relatório Detalhado de OS", "Status", "Qtd. OS", "Custo Total"):
        assert trecho.lower() in t.lower(), f"Figma 20/21: {trecho!r} ausente"


@pytest.mark.parametrize("aba", ABAS)
def test_cada_aba_carrega(admin, aba):
    r = admin.get(f"/relatorios?aba={aba}")
    assert r.status_code == 200
    t = texto_visivel(html_de(r))
    assert t, "pagina vazia"


def test_aba_invalida_cai_na_padrao_ou_404(admin):
    r = admin.get("/relatorios?aba=hacker")
    assert r.status_code in (200, 404)


def test_filtros_do_relatorio_listam_departamentos_e_tecnicos(admin):
    from helpers import formularios
    forms = formularios(html_de(admin.get("/relatorios")))
    sel = {c.nome: c for f in forms for c in f.campos if c.tag == "select"}
    dep = next(c for n, c in sel.items() if n and "depart" in n)
    tec = next(c for n, c in sel.items() if n and "tecnico" in n)
    per = next(c for n, c in sel.items() if n and "periodo" in n)
    assert {"Todos", "Produção", "Manutenção", "Logística"} <= {o["rotulo"] for o in dep.opcoes}
    assert {"Maria Técnica", "Pedro Lima"} <= {o["rotulo"] for o in tec.opcoes}
    assert len(per.opcoes) == 4, f"Periodos (apoio §4): Ultimos 7 dias, 30 dias, 6 meses, ultimo ano. Veio {[o['rotulo'] for o in per.opcoes]}"


# --------------------------------------------------------------------------------------------- /api/relatorios

def _api(c, aba, qs=""):
    r = c.get(f"/api/relatorios/{aba}" + (("?" + qs) if qs else ""))
    assert r.status_code == 200, f"/api/relatorios/{aba}?{qs} -> {r.status_code}"
    assert r.mimetype == "application/json"
    return r.get_json()


@pytest.mark.parametrize("aba", ABAS)
def test_api_relatorios_shape(admin, aba):
    j = _api(admin, aba, "periodo=12m")
    assert "tabela" in j and "graficos" in j, f"/api/relatorios/{aba}: esperado {{tabela, graficos}} (SPEC §4). Chaves: {list(j)}"
    tb = j["tabela"]
    assert set(tb) >= {"colunas", "linhas"}, f"tabela sem colunas/linhas: {list(tb)}"
    assert isinstance(tb["colunas"], list) and tb["colunas"] and isinstance(tb["linhas"], list)
    for ln in tb["linhas"]:
        assert len(ln) == len(tb["colunas"]), f"linha com {len(ln)} celulas para {len(tb['colunas'])} colunas: {ln}"
    assert "rodape" in tb
    assert isinstance(j["graficos"], list)
    for g in j["graficos"]:
        assert set(g) >= {"id", "titulo", "tipo", "rotulos", "valores"}, f"grafico incompleto: {list(g)}"
        assert len(g["rotulos"]) == len(g["valores"]), f"grafico {g['id']}: rotulos x valores com tamanhos diferentes"
        assert all(isinstance(v, (int, float)) for v in g["valores"])


def test_aba_os_tem_as_colunas_do_figma_e_graficos_por_tecnico(admin):
    j = _api(admin, "os", "periodo=12m")
    cols = [str(c).lower() for c in j["tabela"]["colunas"]]
    for c in ("status", "técnico", "qtd", "custo"):
        assert any(c in x for x in cols), f"Coluna {c!r} ausente: {cols} (Figma 21)"
    titulos = " | ".join(g["titulo"].lower() for g in j["graficos"])
    assert "os por técnico" in titulos and "custo por técnico" in titulos, f"Graficos: {titulos}"
    assert j["tabela"]["linhas"], "Relatorio de OS vazio com o seed de 12 meses"


def test_aba_os_bate_com_o_banco(admin):
    j = _api(admin, "os", "periodo=12m")
    cols = [str(c).lower() for c in j["tabela"]["colunas"]]
    iq = next(i for i, c in enumerate(cols) if "qtd" in c)
    soma = sum(numero(ln[iq]) for ln in j["tabela"]["linhas"])
    n = um("SELECT COUNT(*) FROM ordens_servico WHERE date(data_abertura) >= date('now','-12 months')")
    assert soma == n, f"Soma de 'Qtd. OS' ({soma}) deve igualar as OS do periodo ({n})"
    ic = next(i for i, c in enumerate(cols) if "custo" in c)
    custo = sum(numero(ln[ic]) for ln in j["tabela"]["linhas"] if str(ln[ic]).strip() not in ("", "—", "-"))
    pecas = um("SELECT COALESCE(SUM(i.valor_total),0) FROM itens_os i JOIN ordens_servico o ON o.id=i.id_os WHERE date(o.data_abertura) >= date('now','-12 months')")
    serv = um("SELECT COALESCE(SUM(s.valor_servico),0) FROM servicos_os s JOIN ordens_servico o ON o.id=s.id_os WHERE date(o.data_abertura) >= date('now','-12 months')")
    assert abs(custo - float(pecas) - float(serv)) < 0.05, f"Custo total do relatorio ({custo}) x banco ({float(pecas) + float(serv)})"


def test_aba_os_filtra_por_tecnico_e_departamento(admin):
    tid = um("SELECT id FROM usuarios WHERE login='tecnico'")
    tudo = _api(admin, "os", "periodo=12m")
    so_maria = _api(admin, "os", f"periodo=12m&tecnico_id={tid}")
    assert len(so_maria["tabela"]["linhas"]) <= len(tudo["tabela"]["linhas"])
    assert all("Maria" in " ".join(map(str, ln)) for ln in so_maria["tabela"]["linhas"]), "Filtro de tecnico deixou passar outro tecnico"
    did = um("SELECT id FROM departamentos WHERE nome='Produção'")
    dep = _api(admin, "os", f"periodo=12m&departamento_id={did}")
    cols = [str(c).lower() for c in dep["tabela"]["colunas"]]
    iq = next(i for i, c in enumerate(cols) if "qtd" in c)
    n = um("SELECT COUNT(*) FROM ordens_servico o JOIN pedidos_manutencao p ON p.id=o.id_pedido WHERE p.id_departamento=? AND date(o.data_abertura) >= date('now','-12 months')", did)
    assert sum(numero(ln[iq]) for ln in dep["tabela"]["linhas"]) == n


def test_periodo_7d_tem_menos_que_12m(admin):
    def qtd(p):
        j = _api(admin, "os", f"periodo={p}")
        cols = [str(c).lower() for c in j["tabela"]["colunas"]]
        iq = next(i for i, c in enumerate(cols) if "qtd" in c)
        return sum(numero(ln[iq]) for ln in j["tabela"]["linhas"])
    assert qtd("7d") <= qtd("30d") <= qtd("6m") <= qtd("12m")


def test_aba_estoque_lista_pecas_e_marca_baixo(admin):
    j = _api(admin, "estoque")
    txt = " ".join(" ".join(map(str, ln)) for ln in j["tabela"]["linhas"])
    for p in ("Rolamento 6204", "Sensor Indutivo", "Correia V", "Filtro de Ar"):
        assert p in txt, f"Peca {p} ausente do relatorio de estoque"
    linha_filtro = next(ln for ln in j["tabela"]["linhas"] if "Filtro de Ar" in " ".join(map(str, ln)))
    assert "baixo" in " ".join(map(str, linha_filtro)).lower(), "O relatorio de estoque deve sinalizar o estoque Baixo (RF alertas)"


def test_aba_fornecedores_lista_fornecedores_e_prestadores(admin):
    j = _api(admin, "fornecedores")
    txt = " ".join(" ".join(map(str, ln)) for ln in j["tabela"]["linhas"])
    for n in ("TecManutenções LTDA", "Construservice S.A.", "TecServiços Ltda", "Hidro Masters ME"):
        assert n in txt, f"{n} ausente do relatorio de fornecedores e prestadores (Manual 3.2)"


def test_aba_financeiro_custos_por_os_e_equipamento(admin):
    j = _api(admin, "financeiro", "periodo=12m")
    assert j["tabela"]["linhas"], "Financeiro vazio"
    txt = " ".join(" ".join(map(str, ln)) for ln in j["tabela"]["linhas"])
    assert "R$" in txt or re.search(r"\d+[.,]\d\d", txt)


@pytest.mark.parametrize("aba", ABAS)
@pytest.mark.parametrize("qs", ["periodo=zzz", "departamento_id=abc", "tecnico_id=99999", "periodo=7d&departamento_id=99999&tecnico_id=99999",
                                "departamento_id=1%27%20OR%201=1--"])
def test_api_relatorios_entradas_invalidas(admin, aba, qs):
    r = admin.get(f"/api/relatorios/{aba}?{qs}")
    assert r.status_code in (200, 400), f"{aba}?{qs} -> {r.status_code}"
    if r.status_code == 200:
        assert set(r.get_json()) >= {"tabela", "graficos"}


def test_api_relatorios_aba_inexistente(admin):
    assert admin.get("/api/relatorios/inexistente").status_code in (400, 404)
    assert admin.get("/api/relatorios/%27%3BDROP").status_code in (400, 404)


def test_api_relatorios_exige_login(anonimo):
    assert anonimo.get("/api/relatorios/os").status_code in (302, 401)


def test_resultado_vazio_nao_quebra(admin):
    j = _api(admin, "os", "periodo=7d&departamento_id=99999")
    assert j["tabela"]["linhas"] == [] or isinstance(j["tabela"]["linhas"], list)
    r = admin.get("/relatorios?aba=os&periodo=7d&departamento_id=99999")
    assert r.status_code == 200
    t = texto_visivel(html_de(r)).lower()
    assert any(x in t for x in ("nenhum", "sem dados", "nao ha", "não há")), "Estado vazio amigavel esperado no relatorio sem resultado (SPEC §5)"


def test_usuario_comum_ve_so_relatorio_de_atendimento_via_api(comum):
    j = _api(comum, "os")
    assert "tabela" in j
    cols = " ".join(map(str, j["tabela"]["colunas"])).lower()
    assert "custo" not in cols, "Usuario Comum so ve relatorio de atendimento: sem coluna de custo"
    txt = " ".join(" ".join(map(str, ln)) for ln in j["tabela"]["linhas"])
    assert "R$" not in txt, "Valores financeiros vazaram para o Usuario Comum"


def test_tecnico_nao_ve_custos_no_relatorio_de_os(tecnico):
    j = _api(tecnico, "os")
    cols = " ".join(map(str, j["tabela"]["colunas"])).lower()
    txt = " ".join(" ".join(map(str, ln)) for ln in j["tabela"]["linhas"])
    assert "custo" not in cols and "R$" not in txt, "Tecnico: relatorios 'sem financeiro' (SPEC §2)"
    assert all("custo" not in g["titulo"].lower() for g in j["graficos"]), "Grafico de custo exposto ao Tecnico"
