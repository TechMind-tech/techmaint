"""
indicadores.py (servicos)
-------------------------
Os numeros do Dashboard e dos Relatorios. Tudo e calculado do banco (nada fixo).

- `dashboard(...)`  -> KPIs + os 4 graficos (tempo medio, custo por maquina, pecas mais usadas, status)
- `relatorio(...)`  -> tabela + graficos de uma aba (os, estoque, financeiro, fornecedores)

As funcoes devolvem dicts simples: servem tanto para as paginas quanto para as APIs
JSON e para as exportacoes (PDF/Excel/CSV).

Regras de visibilidade: quem nao tem a permissao `financeiro.ver` (Tecnico, Usuario Comum)
nao recebe NENHUM valor em R$.
"""

from datetime import date, timedelta

import database
from servicos.formatacao import MESES, MESES_CURTOS, data_br, hoje, moeda, qtd_br, soma_meses
from servicos.periodos import ROTULOS, inicio_do_periodo
from servicos import alertas as srv_alertas

# Custo de uma OS = pecas + servicos (subconsultas fixas, escritas aqui no codigo)
CUSTO_OS = ("(COALESCE((SELECT SUM(valor_total) FROM itens_os WHERE id_os = os.id), 0) + "
            "COALESCE((SELECT SUM(valor_servico) FROM servicos_os WHERE id_os = os.id), 0))")
CUSTO_PECAS_OS = "COALESCE((SELECT SUM(valor_total) FROM itens_os WHERE id_os = os.id), 0)"
CUSTO_SERVICOS_OS = "COALESCE((SELECT SUM(valor_servico) FROM servicos_os WHERE id_os = os.id), 0)"
DEPTO_OS = "COALESCE(p.id_departamento, e.id_departamento)"

BASE_OS = ("FROM ordens_servico os LEFT JOIN pedidos_manutencao p ON p.id = os.id_pedido "
           "LEFT JOIN equipamentos e ON e.id = os.id_equipamento LEFT JOIN usuarios u ON u.id = os.id_tecnico")

ORDEM_STATUS = ["Aberta", "Em andamento", "Concluída", "Cancelada"]
TOP_N = 8


# ---------------------------------------------------------------------------
# Periodos divididos em "baldes" (pontos do grafico de linha)
# ---------------------------------------------------------------------------
def baldes(periodo, ref=None):
    """Divide o periodo em intervalos: 7d -> dias; 30d -> semanas; 6m/12m -> meses."""
    ref = ref or hoje()
    inicio = inicio_do_periodo(periodo, ref)
    lista = []
    if periodo == "7d":
        for i in range(7):
            d = inicio + timedelta(days=i)
            lista.append({"rotulo": d.strftime("%d/%m"), "inicio": d, "fim": d})
    elif periodo == "30d":
        i = 0
        while inicio + timedelta(days=i * 7) <= ref:
            ini = inicio + timedelta(days=i * 7)
            fim = min(ini + timedelta(days=6), ref)
            lista.append({"rotulo": ini.strftime("%d/%m"), "inicio": ini, "fim": fim})
            i += 1
    else:
        n = 6 if periodo == "6m" else 12
        for i in range(n):
            ini = soma_meses(inicio, i)
            fim = soma_meses(ini, 1) - timedelta(days=1)
            rotulo = MESES_CURTOS[ini.month - 1] + (f"/{str(ini.year)[2:]}" if periodo == "12m" else "")
            lista.append({"rotulo": rotulo, "inicio": ini, "fim": min(fim, ref)})
    return lista


def _indice(baldes_, dia):
    for i, b in enumerate(baldes_):
        if b["inicio"] <= dia <= b["fim"]:
            return i
    return None


def _data(texto):
    return date.fromisoformat(str(texto)[:10])


# ---------------------------------------------------------------------------
# Filtros
# ---------------------------------------------------------------------------
def _condicoes_os(periodo_inicio=None, depto=None, equip=None, tecnico=None, solicitante=None, campo_data="os.data_abertura"):
    onde, params = [], []
    if periodo_inicio is not None:
        onde.append(f"substr({campo_data}, 1, 10) >= ?")
        params.append(periodo_inicio.isoformat())
    if depto:
        onde.append(f"{DEPTO_OS} = ?")
        params.append(depto)
    if equip:
        onde.append("os.id_equipamento = ?")
        params.append(equip)
    if tecnico:
        onde.append("os.id_tecnico = ?")
        params.append(tecnico)
    if solicitante:
        onde.append("p.id_usuario_solicitante = ?")
        params.append(solicitante)
    return onde, params


def _where(onde, extra=None):
    todas = list(onde) + (extra or [])
    return (" WHERE " + " AND ".join(todas)) if todas else ""


def _nome(db, tabela, coluna, id_):
    if not id_:
        return None
    # `tabela` e `coluna` sao fixos no codigo (chamadas abaixo), nunca vem do usuario
    r = db.execute(f"SELECT {coluna} FROM {tabela} WHERE id = ?", (id_,)).fetchone()
    return r[0] if r else None


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
def kpis_dashboard(db, depto=None, equip=None, financeiro=True):
    ref = hoje()
    mes_inicio = ref.replace(day=1)
    semana_inicio = ref - timedelta(days=6)

    # pedidos (depto e equipamento do proprio pedido)
    cond_p, par_p = [], []
    if depto:
        cond_p.append("p.id_departamento = ?")
        par_p.append(depto)
    if equip:
        cond_p.append("p.id_equipamento = ?")
        par_p.append(equip)
    abertos = db.execute("SELECT COUNT(*) FROM pedidos_manutencao p" + _where(cond_p, ["p.status = 'Aberto'"]),
                         par_p).fetchone()[0]
    semana = db.execute("SELECT COUNT(*) FROM pedidos_manutencao p" + _where(cond_p, ["p.data_solicitacao >= ?"]),
                        par_p + [semana_inicio.isoformat()]).fetchone()[0]

    onde, par = _condicoes_os(depto=depto, equip=equip)
    andamento = db.execute("SELECT COUNT(*) " + BASE_OS + _where(onde, ["os.status = 'Em andamento'"]), par).fetchone()[0]
    limite = (ref - timedelta(days=srv_alertas.dias_limite_os(db))).isoformat()
    atrasadas = db.execute("SELECT COUNT(*) " + BASE_OS + _where(
        onde, ["os.status IN ('Aberta', 'Em andamento')", "substr(os.data_abertura, 1, 10) < ?"]),
        par + [limite]).fetchone()[0]
    concluidas = db.execute("SELECT COUNT(*) " + BASE_OS + _where(
        onde, ["os.status = 'Concluída'", "substr(os.data_fechamento, 1, 10) >= ?"]),
        par + [mes_inicio.isoformat()]).fetchone()[0]
    custo = None
    if financeiro:
        custo = round(db.execute(f"SELECT COALESCE(SUM({CUSTO_OS}), 0) " + BASE_OS + _where(
            onde, ["os.status <> 'Cancelada'", "substr(os.data_abertura, 1, 10) >= ?"]),
            par + [mes_inicio.isoformat()]).fetchone()[0], 2)

    meta = int(database.parametro_numero("meta_os_mes", 20, db))
    orcamento = database.parametro_numero("orcamento_mes", 40000, db)
    k = {
        "pedidos_abertos": abertos, "pedidos_abertos_semana": semana, "os_andamento": andamento,
        "os_atrasadas": atrasadas, "os_concluidas_mes": concluidas, "meta_os_mes": meta,
        "custo_total_mes": custo, "custo_total_mes_fmt": moeda(custo) if custo is not None else "",
        "orcamento_mes": orcamento if financeiro else None,
        "orcamento_mes_fmt": moeda(orcamento) if financeiro else "", "financeiro_visivel": bool(financeiro),
    }
    cards = [
        {"chave": "pedidos_abertos", "titulo": "Pedidos Abertos", "valor": abertos, "valor_fmt": str(abertos),
         "detalhe": f"+{semana} esta semana", "cor": "marinho"},
        {"chave": "os_andamento", "titulo": "OS em Andamento", "valor": andamento, "valor_fmt": str(andamento),
         "detalhe": f"{atrasadas} atrasada(s)" if atrasadas else "Nenhuma atrasada", "cor": "laranja"},
        {"chave": "os_concluidas_mes", "titulo": "OS Concluídas/Mês", "valor": concluidas,
         "valor_fmt": str(concluidas), "detalhe": f"Meta: {meta}", "cor": "verde"},
    ]
    if financeiro:
        orc_txt = f"R$ {int(orcamento // 1000)}k" if orcamento % 1000 == 0 else moeda(orcamento)
        cards.append({"chave": "custo_total_mes", "titulo": "Custo Total do Mês", "valor": custo,
                      "valor_fmt": moeda(custo).replace(",00", ""), "detalhe": f"Orçamento: {orc_txt}", "cor": "ciano"})
    k["cards"] = cards
    return k


def titulo_periodo(db, periodo, depto=None, equip=None):
    partes = [ROTULOS.get(periodo, "")]
    partes.append(_nome(db, "departamentos", "nome", depto) or "Todos os departamentos")
    if equip:
        partes.append(_nome(db, "equipamentos", "descricao", equip) or "")
    return " · ".join(p for p in partes if p)


def dashboard(db, periodo, depto=None, equip=None, financeiro=True):
    """Dados completos do dashboard (formato de /api/dashboard)."""
    ref = hoje()
    inicio = inicio_do_periodo(periodo, ref)

    # --- tempo medio de atendimento (horas) por balde: OS concluidas, abertura -> fechamento
    bs = baldes(periodo, ref)
    onde, par = _condicoes_os(periodo_inicio=inicio, depto=depto, equip=equip, campo_data="os.data_fechamento")
    soma, qtd = [0.0] * len(bs), [0] * len(bs)
    for r in db.execute("SELECT os.data_abertura, os.data_fechamento " + BASE_OS + _where(
            onde, ["os.status = 'Concluída'", "os.data_fechamento IS NOT NULL"]), par):
        i = _indice(bs, _data(r["data_fechamento"]))
        if i is not None:
            horas = (_dt(r["data_fechamento"]) - _dt(r["data_abertura"])).total_seconds() / 3600
            soma[i] += max(horas, 0)
            qtd[i] += 1
    tempo_medio = [{"rotulo": b["rotulo"], "valor": round(soma[i] / qtd[i], 1) if qtd[i] else 0}
                   for i, b in enumerate(bs)]

    # --- custo por maquina (so quem ve financeiro)
    onde, par = _condicoes_os(periodo_inicio=inicio, depto=depto, equip=equip)
    custo_maquina = []
    if financeiro:
        for r in db.execute(
                f"SELECT e.descricao AS rotulo, SUM({CUSTO_OS}) AS valor " + BASE_OS +
                _where(onde, ["os.status <> 'Cancelada'", "os.id_equipamento IS NOT NULL"]) +
                " GROUP BY os.id_equipamento HAVING valor > 0 ORDER BY valor DESC LIMIT ?", par + [TOP_N]):
            custo_maquina.append({"rotulo": r["rotulo"], "valor": round(r["valor"], 2)})

    # --- pecas mais usadas (quantidade)
    pecas = [{"rotulo": r["rotulo"], "valor": round(r["valor"], 3) if r["valor"] % 1 else int(r["valor"])}
             for r in db.execute(
                 "SELECT pc.nome AS rotulo, SUM(i.quantidade) AS valor FROM itens_os i "
                 "JOIN pecas pc ON pc.id = i.id_peca JOIN ordens_servico os ON os.id = i.id_os "
                 "LEFT JOIN pedidos_manutencao p ON p.id = os.id_pedido LEFT JOIN equipamentos e ON e.id = os.id_equipamento "
                 + _where(onde, ["os.status <> 'Cancelada'"]) +
                 " GROUP BY pc.id ORDER BY valor DESC, pc.nome LIMIT ?", par + [TOP_N])]

    # --- status das ordens
    contagem = {s: 0 for s in ORDEM_STATUS}
    for r in db.execute("SELECT os.status, COUNT(*) AS n " + BASE_OS + _where(onde) + " GROUP BY os.status", par):
        contagem[r["status"]] = r["n"]
    status = [{"rotulo": s, "valor": contagem[s]} for s in ORDEM_STATUS]

    return {
        "tempo_medio": tempo_medio, "custo_por_maquina": custo_maquina, "pecas_mais_usadas": pecas,
        "status_ordens": status, "kpis": kpis_dashboard(db, depto, equip, financeiro),
        "titulo_periodo": titulo_periodo(db, periodo, depto, equip),
    }


def _dt(texto):
    from datetime import datetime
    t = str(texto)
    return datetime.strptime(t[:19], "%Y-%m-%d %H:%M:%S") if len(t) >= 19 else datetime.strptime(t[:10], "%Y-%m-%d")


# ---------------------------------------------------------------------------
# Relatorios
# ---------------------------------------------------------------------------
def _tabela(titulo, colunas, linhas, rodape=None, alinhamentos=None):
    return {"titulo": titulo, "colunas": colunas, "linhas": linhas, "rodape": rodape or [],
            "alinhamentos": alinhamentos or ["esq"] * len(colunas)}


def _grafico(id_, titulo, tipo, rotulos, valores, unidade=""):
    return {"id": id_, "titulo": titulo, "tipo": tipo, "rotulos": rotulos, "valores": valores, "unidade": unidade}


def _custo_txt(valor):
    return moeda(valor) if valor else "—"


def relatorio(db, aba, periodo, depto=None, tecnico=None, financeiro=True, solicitante=None):
    """Tabela + graficos de uma aba. `solicitante` restringe as OS ao dono (Usuario Comum)."""
    inicio = inicio_do_periodo(periodo)
    if aba == "os":
        return _rel_os(db, inicio, depto, tecnico, financeiro, solicitante)
    if aba == "estoque":
        return _rel_estoque(db, inicio, depto, financeiro)
    if aba == "financeiro":
        return _rel_financeiro(db, periodo, inicio, depto, tecnico)
    if aba == "fornecedores":
        return _rel_fornecedores(db, inicio, financeiro)
    raise ValueError(f"Aba de relatório desconhecida: {aba}")


def _rel_os(db, inicio, depto, tecnico, financeiro, solicitante):
    onde, par = _condicoes_os(periodo_inicio=inicio, depto=depto, tecnico=tecnico, solicitante=solicitante)
    linhas_sql = db.execute(
        f"SELECT os.status, COALESCE(u.nome, os.responsavel, 'Sem técnico') AS tecnico, COUNT(*) AS qtd, "
        f"SUM({CUSTO_OS}) AS custo " + BASE_OS + _where(onde) + " GROUP BY os.status, tecnico "
        "ORDER BY CASE os.status WHEN 'Aberta' THEN 1 WHEN 'Em andamento' THEN 2 WHEN 'Concluída' THEN 3 ELSE 4 END, tecnico",
        par).fetchall()
    colunas = ["Status", "Técnico", "Qtd. OS"] + (["Custo total"] if financeiro else [])
    alin = ["esq", "esq", "dir"] + (["dir"] if financeiro else [])
    linhas = []
    for r in linhas_sql:
        linha = [r["status"], r["tecnico"], str(r["qtd"])]
        if financeiro:
            linha.append(_custo_txt(round(r["custo"], 2)))
        linhas.append(linha)
    total_qtd = sum(r["qtd"] for r in linhas_sql)
    rodape = ["Total", "", str(total_qtd)] + ([moeda(sum(r["custo"] for r in linhas_sql))] if financeiro else [])

    por_tecnico = db.execute(
        f"SELECT COALESCE(u.nome, os.responsavel, 'Sem técnico') AS tecnico, COUNT(*) AS qtd, "
        f"SUM(CASE WHEN os.status <> 'Cancelada' THEN {CUSTO_OS} ELSE 0 END) AS custo " + BASE_OS + _where(onde) +
        " GROUP BY tecnico ORDER BY qtd DESC, tecnico", par).fetchall()
    graficos = [_grafico("os_por_tecnico", "OS por Técnico", "bar", [r["tecnico"] for r in por_tecnico],
                         [r["qtd"] for r in por_tecnico])]
    if financeiro:
        graficos.append(_grafico("custo_por_tecnico", "Custo por Técnico (R$)", "bar", [r["tecnico"] for r in por_tecnico],
                                 [round(r["custo"], 2) for r in por_tecnico], "R$"))
    return {"tabela": _tabela("Relatório Detalhado de OS", colunas, linhas, rodape, alin), "graficos": graficos}


def _rel_estoque(db, inicio, depto, financeiro):
    onde, par = [], []
    if depto:
        onde.append("e.id_departamento = ?")
        par.append(depto)
    pecas = db.execute(
        "SELECT p.codigo, p.nome, e.descricao AS equipamento, p.qtde_estoque, p.estoque_minimo, p.valor_unitario "
        "FROM pecas p JOIN equipamentos e ON e.id = p.id_equipamento" + _where(onde) + " ORDER BY p.nome", par).fetchall()
    colunas = ["Código", "Peça", "Equipamento", "Saldo", "Mínimo", "Situação"] + (["Valor em estoque"] if financeiro else [])
    alin = ["esq", "esq", "esq", "dir", "dir", "esq"] + (["dir"] if financeiro else [])
    linhas, total_valor = [], 0.0
    for p in pecas:
        valor = round(p["qtde_estoque"] * p["valor_unitario"], 2)
        total_valor += valor
        linha = [p["codigo"] or "", p["nome"], p["equipamento"], qtd_br(p["qtde_estoque"]), qtd_br(p["estoque_minimo"]),
                 "Baixo" if p["qtde_estoque"] < p["estoque_minimo"] else "OK"]
        if financeiro:
            linha.append(moeda(valor))
        linhas.append(linha)
    rodape = ["Total", "", f"{len(pecas)} peça(s)", qtd_br(sum(p["qtde_estoque"] for p in pecas)), "", ""] + \
        ([moeda(total_valor)] if financeiro else [])

    top = sorted(pecas, key=lambda p: p["qtde_estoque"], reverse=True)[:10]
    mov = db.execute(
        "SELECT m.tipo, SUM(m.quantidade) AS qtd, SUM(m.quantidade * COALESCE(m.valor_unitario, 0)) AS valor "
        "FROM movimentacao_estoque_pecas m JOIN pecas p ON p.id = m.id_peca JOIN equipamentos e ON e.id = p.id_equipamento"
        + _where(onde, ["substr(m.data, 1, 10) >= ?"]) + " GROUP BY m.tipo", par + [inicio.isoformat()]).fetchall()
    por_tipo = {r["tipo"]: r for r in mov}
    graficos = [
        _grafico("saldo_pecas", "Saldo por Peça (maiores saldos)", "bar", [p["nome"] for p in top],
                 [p["qtde_estoque"] for p in top]),
        _grafico("movimentos_qtd", "Movimentações no período (unidades)", "bar", ["Entradas", "Saídas"],
                 [round(por_tipo["Entrada"]["qtd"], 3) if "Entrada" in por_tipo else 0,
                  round(por_tipo["Saída"]["qtd"], 3) if "Saída" in por_tipo else 0]),
    ]
    if financeiro:
        graficos.append(_grafico("movimentos_valor", "Valor movimentado no período (R$)", "bar", ["Entradas", "Saídas"],
                                 [round(por_tipo["Entrada"]["valor"], 2) if "Entrada" in por_tipo else 0,
                                  round(por_tipo["Saída"]["valor"], 2) if "Saída" in por_tipo else 0], "R$"))
    status_equip = {r["status"]: r["n"] for r in db.execute(
        "SELECT e.status, COUNT(*) AS n FROM equipamentos e" + _where(onde) + " GROUP BY e.status", par)}
    graficos.append(_grafico("equipamentos_status", "Equipamentos por status", "doughnut",
                             ["Ativo", "Em manutenção", "Baixado"],
                             [status_equip.get("Ativo", 0), status_equip.get("Em manutenção", 0), status_equip.get("Baixado", 0)]))
    return {"tabela": _tabela("Relatório de Estoque de Peças", colunas, linhas, rodape, alin), "graficos": graficos}


def _rel_financeiro(db, periodo, inicio, depto, tecnico):
    onde, par = _condicoes_os(periodo_inicio=inicio, depto=depto, tecnico=tecnico)
    onde_v = onde + ["os.status <> 'Cancelada'"]
    linhas_sql = db.execute(
        f"SELECT os.id, os.status, os.data_abertura, COALESCE(e.descricao, 'Sem equipamento') AS equipamento, "
        f"COALESCE(d.nome, '—') AS departamento, COALESCE(u.nome, os.responsavel, '—') AS tecnico, "
        f"{CUSTO_PECAS_OS} AS pecas, {CUSTO_SERVICOS_OS} AS servicos " + BASE_OS +
        f" LEFT JOIN departamentos d ON d.id = {DEPTO_OS}" + _where(onde_v) + " ORDER BY (pecas + servicos) DESC, os.id DESC",
        par).fetchall()
    colunas = ["OS", "Abertura", "Equipamento", "Departamento", "Técnico", "Status", "Peças", "Serviços", "Total"]
    alin = ["esq", "esq", "esq", "esq", "esq", "esq", "dir", "dir", "dir"]
    linhas = [[f"OS-{r['id']}", data_br(r["data_abertura"]), r["equipamento"], r["departamento"], r["tecnico"],
               r["status"], moeda(r["pecas"]), moeda(r["servicos"]), moeda(r["pecas"] + r["servicos"])]
              for r in linhas_sql]
    tp, ts = sum(r["pecas"] for r in linhas_sql), sum(r["servicos"] for r in linhas_sql)
    rodape = ["Total", "", "", "", "", f"{len(linhas_sql)} OS", moeda(tp), moeda(ts), moeda(tp + ts)]

    por_equip = db.execute(
        f"SELECT COALESCE(e.descricao, 'Sem equipamento') AS rotulo, SUM({CUSTO_OS}) AS valor " + BASE_OS +
        _where(onde_v) + " GROUP BY os.id_equipamento HAVING valor > 0 ORDER BY valor DESC LIMIT 10", par).fetchall()
    bs = baldes(periodo)
    soma = [0.0] * len(bs)
    for r in linhas_sql:
        i = _indice(bs, _data(r["data_abertura"]))
        if i is not None:
            soma[i] += r["pecas"] + r["servicos"]
    graficos = [
        _grafico("custo_por_equipamento", "Custo por Equipamento (R$)", "bar", [r["rotulo"] for r in por_equip],
                 [round(r["valor"], 2) for r in por_equip], "R$"),
        _grafico("custo_no_periodo", "Custo ao longo do período (R$)", "line", [b["rotulo"] for b in bs],
                 [round(v, 2) for v in soma], "R$"),
    ]
    return {"tabela": _tabela("Relatório Financeiro: Custos por OS", colunas, linhas, rodape, alin), "graficos": graficos}


def _rel_fornecedores(db, inicio, financeiro):
    ini = inicio.isoformat()
    linhas, rodape_qtd = [], 0
    colunas = ["Tipo", "Razão social", "CNPJ", "Telefone", "UF", "Status", "Movimento"] + (["Valor no período"] if financeiro else [])
    alin = ["esq", "esq", "esq", "esq", "esq", "esq", "dir"] + (["dir"] if financeiro else [])
    from servicos.formatacao import cnpj_fmt
    nomes_f, qtd_f, val_f, nomes_p, qtd_p, val_p = [], [], [], [], [], []
    total_valor = 0.0
    for f in db.execute(
            "SELECT f.razao_social, f.cnpj, f.telefone, f.uf, f.ativo, COUNT(n.id) AS qtd, "
            "COALESCE(SUM(n.valor_total_nf), 0) AS valor FROM fornecedores f LEFT JOIN notas_fiscais n "
            "ON n.id_fornecedor = f.id AND substr(COALESCE(n.data_entrada, n.data_emissao), 1, 10) >= ? "
            "GROUP BY f.id ORDER BY f.razao_social", (ini,)):
        linha = ["Fornecedor", f["razao_social"], cnpj_fmt(f["cnpj"]), f["telefone"] or "", f["uf"] or "",
                 "Ativo" if f["ativo"] else "Inativo", f"{f['qtd']} NF"]
        if financeiro:
            linha.append(moeda(f["valor"]))
        total_valor += f["valor"]
        rodape_qtd += f["qtd"]
        linhas.append(linha)
        nomes_f.append(f["razao_social"]); qtd_f.append(f["qtd"]); val_f.append(round(f["valor"], 2))
    for p in db.execute(
            "SELECT pr.razao_social, pr.cnpj, pr.telefone, pr.uf, pr.ativo, COUNT(s.id) AS qtd, "
            "COALESCE(SUM(s.valor_servico), 0) AS valor FROM prestadores_servico pr "
            "LEFT JOIN servicos_os s ON s.id_prestador = pr.id AND s.id_os IN "
            "(SELECT id FROM ordens_servico WHERE substr(data_abertura, 1, 10) >= ? AND status <> 'Cancelada') "
            "GROUP BY pr.id ORDER BY pr.razao_social", (ini,)):
        linha = ["Prestador", p["razao_social"], cnpj_fmt(p["cnpj"]), p["telefone"] or "", p["uf"] or "",
                 "Ativo" if p["ativo"] else "Inativo", f"{p['qtd']} serviço(s)"]
        if financeiro:
            linha.append(moeda(p["valor"]))
        total_valor += p["valor"]
        rodape_qtd += p["qtd"]
        linhas.append(linha)
        nomes_p.append(p["razao_social"]); qtd_p.append(p["qtd"]); val_p.append(round(p["valor"], 2))
    rodape = ["Total", f"{len(linhas)} cadastro(s)", "", "", "", "", str(rodape_qtd)] + ([moeda(total_valor)] if financeiro else [])
    graficos = [_grafico("nf_por_fornecedor", "Notas fiscais por fornecedor", "bar", nomes_f, qtd_f),
                _grafico("servicos_por_prestador", "Serviços por prestador", "bar", nomes_p, qtd_p)]
    if financeiro:
        graficos.append(_grafico("valor_por_fornecedor", "Valor de NF por fornecedor (R$)", "bar", nomes_f, val_f, "R$"))
        graficos.append(_grafico("valor_por_prestador", "Valor de serviços por prestador (R$)", "bar", nomes_p, val_p, "R$"))
    return {"tabela": _tabela("Fornecedores e Prestadores de Serviço", colunas, linhas, rodape, alin), "graficos": graficos}
