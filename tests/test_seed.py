"""
Seed de demonstracao (SPEC §3 "Dados de demonstracao") e idempotencia.

Rastreabilidade: SPEC §3 (seed), §2 (usuarios demo), apoio §1-§3 (grupos/subgrupos/equipamentos).
"""

import os
import subprocess
import sys

import pytest
from werkzeug.security import check_password_hash

from conftest import DB_TESTE, REPO, construir_banco
from dados_apoio import EQUIPAMENTOS, GRUPOS, SUBGRUPOS, SUBGRUPOS_POR_GRUPO
from helpers import (USUARIOS_DEMO, coluna, consulta, contar, id_perfil, linha, tabelas, um)

TABELAS_ESPERADAS = [
    "usuarios", "perfis", "permissoes", "usuarios_perfis", "perfis_permissoes", "departamentos", "fornecedores",
    "prestadores_servico", "grupos", "subgrupos", "equipamentos", "pecas", "notas_fiscais", "itens_nota_fiscal",
    "estoque_pecas", "movimentacao_estoque_pecas", "estoque_equipamentos", "movimentacao_equipamentos",
    "pedidos_manutencao", "ordens_servico", "itens_os", "servicos_os", "apontamentos_os", "historico_alteracoes",
    "parametros",
]


def test_schema_tem_todas_as_tabelas_do_contrato(banco):
    existentes = set(tabelas())
    faltando = [t for t in TABELAS_ESPERADAS if t not in existentes]
    assert not faltando, f"Tabelas do modelo (SPEC §3) ausentes no schema: {faltando}"


def test_integridade_referencial_do_seed(banco):
    assert um("PRAGMA integrity_check") == "ok"
    assert consulta("PRAGMA foreign_key_check") == [], "O seed deixou chaves estrangeiras quebradas"


def test_perfis_e_permissoes(banco):
    col = coluna("perfis", "nome", "nome_perfil", "perfil")
    nomes = {r[col] for r in consulta(f"SELECT {col} FROM perfis")}
    assert nomes == {"Administrador", "Técnico", "Gestor", "Usuário Comum"}
    assert contar("permissoes") > 0, "Tabela permissoes vazia"
    assert contar("perfis_permissoes") > 0, "Tabela perfis_permissoes vazia"


def test_grupos_do_apoio(banco):
    col = coluna("grupos", "nome", "grupo")
    nomes = [r[col] for r in consulta(f"SELECT {col} FROM grupos ORDER BY id")]
    assert len(nomes) == 15, f"Esperados 15 grupos (apoio §1), achei {len(nomes)}"
    assert set(nomes) == set(GRUPOS), f"Grupos divergem do apoio: faltam {set(GRUPOS) - set(nomes)}, sobram {set(nomes) - set(GRUPOS)}"


def test_subgrupos_do_apoio(banco):
    cs = coluna("subgrupos", "nome", "subgrupo")
    cg = coluna("grupos", "nome", "grupo")
    linhas = consulta(f"SELECT s.{cs} AS sub, g.{cg} AS grp FROM subgrupos s JOIN grupos g ON g.id = s.id_grupo")
    assert len(linhas) == 149, f"Esperados 149 subgrupos (apoio §2), achei {len(linhas)}"
    obtido = {(r["sub"], r["grp"]) for r in linhas}
    esperado = set(SUBGRUPOS)
    assert obtido == esperado, f"Subgrupos divergem: faltam {sorted(esperado - obtido)[:5]}, sobram {sorted(obtido - esperado)[:5]}"


def test_subgrupos_por_grupo_batem(banco):
    cg = coluna("grupos", "nome", "grupo")
    r = consulta(f"SELECT g.{cg} AS grp, COUNT(*) AS n FROM subgrupos s JOIN grupos g ON g.id = s.id_grupo GROUP BY g.id")
    assert {x["grp"]: x["n"] for x in r} == SUBGRUPOS_POR_GRUPO


def test_todos_os_equipamentos_do_apoio_foram_semeados(banco):
    cods = {r["codigo"]: r for r in consulta("SELECT * FROM equipamentos")}
    faltando = [c for c, _ in EQUIPAMENTOS if c not in cods]
    assert not faltando, f"Equipamentos do apoio §3 ausentes no seed ({len(faltando)} de {len(EQUIPAMENTOS)}): {faltando[:10]}"
    divergentes = [(c, d) for c, d in EQUIPAMENTOS if not cods[c]["descricao"].upper().startswith(d.upper()[:15])]
    assert not divergentes, f"Descricao difere do apoio para: {divergentes[:5]}"


@pytest.mark.parametrize("descricao,grupo,subgrupo", [
    ("BOMBA 1 (RESFRIADOR)", "Infraestrutura", "Bombas"),
    ("INJETORA 02 - YIZUMI", "Produção", "Injetoras"),
    ("EMPILHADEIRA HYSTER 2014", "Logística", "Empilhadeiras"),
    ("COMPRESSOR METALPLAN", "Infraestrutura", "Compressores"),
    ("BANBURY 1 - CILINDRO ABERTO", "Produção", "Bambury"),
    ("BATERIA 01 - NOBREAK 03", "TI", "Nobreaks"),  # apoio §3, linha 07.000.0060,
    ("PAQUIMETRO 02", "Laboratório / Qualidade", "Metrologia"),
    ("TRANSFORMADOR 40 KVA TKS", "Infraestrutura", "Transformadores"),
])
def test_equipamento_com_grupo_e_subgrupo_coerentes(banco, descricao, grupo, subgrupo):
    cg, cs = coluna("grupos", "nome", "grupo"), coluna("subgrupos", "nome", "subgrupo")
    r = linha(f"SELECT g.{cg} AS g, s.{cs} AS s FROM equipamentos e JOIN grupos g ON g.id=e.id_grupo "
              f"JOIN subgrupos s ON s.id=e.id_subgrupo WHERE e.descricao = ?", descricao)
    assert r, f"Equipamento {descricao!r} nao encontrado no seed"
    assert (r["g"], r["s"]) == (grupo, subgrupo)


def test_subgrupo_de_cada_equipamento_pertence_ao_seu_grupo(banco):
    ruins = consulta("SELECT e.codigo FROM equipamentos e JOIN subgrupos s ON s.id=e.id_subgrupo WHERE s.id_grupo <> e.id_grupo")
    assert not ruins, f"Equipamentos com subgrupo de outro grupo: {ruins[:5]}"


def test_equipamentos_tem_status_validos_e_departamento(banco):
    status = {r["status"] for r in consulta("SELECT DISTINCT status FROM equipamentos")}
    assert status <= {"Ativo", "Em manutenção", "Baixado"}, f"Status invalidos: {status}"
    assert {"Ativo", "Em manutenção", "Baixado"} <= status, f"O seed deveria ter alguns Em manutenção/Baixado (SPEC §3): {status}"
    assert contar("equipamentos", "id_departamento IS NULL") == 0, "Equipamentos sem departamento"
    assert contar("equipamentos") >= len(EQUIPAMENTOS)


def test_departamentos_do_figma(banco):
    esperados = {"Produção": "Roberto Alves", "Manutenção": "João Silva", "Logística": "Fernanda Costa",
                 "Utilidades": "Paulo Menezes", "Administração": "Carla Mendes"}
    r = {d["nome"]: d for d in consulta("SELECT * FROM departamentos")}
    for nome, resp in esperados.items():
        assert nome in r, f"Departamento {nome!r} ausente do seed"
        assert resp in (r[nome].get("responsavel_nome") or ""), f"Responsavel de {nome}: {r[nome].get('responsavel_nome')!r} (esperado {resp})"
    assert "TI" in r, "Departamento TI ausente (SPEC §3)"


def test_departamentos_usados_pelos_equipamentos_existem(banco):
    for nome in ("Produção", "Infraestrutura", "Logística", "Utilidades"):
        # pedidos do Figma usam estes departamentos (#1626 -> Infraestrutura)
        assert contar("departamentos", "nome = ?", nome) == 1, f"Departamento {nome!r} ausente (usado pelos pedidos do Figma)"


@pytest.mark.parametrize("chave", list(USUARIOS_DEMO))
def test_usuarios_de_demonstracao(banco, chave):
    login, senha, perfil = USUARIOS_DEMO[chave]
    u = linha("SELECT * FROM usuarios WHERE login = ?", login)
    assert u, f"Usuario demo {login!r} nao foi criado pelo seed (SPEC §2)"
    assert u["ativo"] in (1, True, "1")
    assert check_password_hash(u["senha_hash"], senha), f"Hash de {login} nao confere com a senha de demonstracao"
    assert senha not in u["senha_hash"], "senha em texto puro no banco"
    pc = coluna("perfis", "nome", "nome_perfil", "perfil")
    nome_perfil = um(f"SELECT p.{pc} FROM usuarios_perfis up JOIN perfis p ON p.id=up.id_perfil WHERE up.id_usuario=?", u["id"])
    assert nome_perfil == perfil


def test_nomes_e_departamentos_dos_usuarios_demo(banco):
    esperado = {"admin": ("João Administrador", "TI"), "tecnico": ("Maria Técnica", "Manutenção"),
                "gestor": ("Carlos Gestor", "Produção"), "solicitante": ("Ana Solicitante", "Produção"),
                "plima": ("Pedro Lima", "Manutenção")}
    for login, (nome, depto) in esperado.items():
        r = linha("SELECT u.nome, d.nome AS depto FROM usuarios u LEFT JOIN departamentos d ON d.id=u.id_departamento WHERE u.login=?", login)
        assert r and (r["nome"], r["depto"]) == (nome, depto), f"{login}: {r}"


def test_pecas_do_figma(banco):
    esperado = {"Rolamento 6204": (15.0, 120), "Sensor Indutivo": (25.5, 50), "Correia V": (8.0, 200), "Filtro de Ar": (32.0, 30)}
    for nome, (valor, qtd) in esperado.items():
        p = linha("SELECT * FROM pecas WHERE nome = ?", nome)
        assert p, f"Peca {nome!r} ausente"
        assert (float(p["valor_unitario"]), float(p["qtde_estoque"])) == (valor, qtd), f"{nome}: {p}"
        assert p["id_equipamento"], f"{nome} sem equipamento vinculado"


def test_apenas_filtro_de_ar_esta_com_estoque_baixo(banco):
    baixas = consulta("SELECT nome, qtde_estoque, estoque_minimo FROM pecas WHERE qtde_estoque < estoque_minimo")
    assert [b["nome"] for b in baixas] == ["Filtro de Ar"], f"Esperado so Filtro de Ar abaixo do minimo (SPEC §3): {baixas}"
    assert float(baixas[0]["estoque_minimo"]) == 40


def test_estoque_pecas_coerente_com_pecas(banco):
    col = coluna("estoque_pecas", "qtde_atual", "saldo", "quantidade")
    divergentes = consulta(f"SELECT p.nome, p.qtde_estoque, e.{col} AS saldo FROM pecas p JOIN estoque_pecas e ON e.id_peca=p.id "
                           f"WHERE p.qtde_estoque <> e.{col}")
    assert not divergentes, f"estoque_pecas incoerente com pecas.qtde_estoque (SPEC §3): {divergentes[:5]}"


def test_fornecedores_do_figma(banco):
    esperado = {"TecManutenções LTDA": "12345678000190", "Construservice S.A.": "98765432000110", "Elétrica Forte ME": "11222333000144"}
    for razao, cnpj in esperado.items():
        f = linha("SELECT * FROM fornecedores WHERE razao_social = ?", razao)
        assert f, f"Fornecedor {razao!r} ausente"
        digitos = "".join(c for c in f["cnpj"] if c.isdigit())
        assert len(digitos) == 14, f"CNPJ de {razao} deveria ter 14 digitos: {f['cnpj']!r}"
        # o seed pode usar CNPJ valido equivalente (SPEC §3): so conferimos o fornecedor, nao os digitos
    assert contar("fornecedores") >= 3


def test_prestadores_do_figma(banco):
    r = consulta("SELECT razao_social, especialidade, ativo FROM prestadores_servico ORDER BY id")
    nomes = [x["razao_social"] for x in r]
    for n in ("TecServiços Ltda", "Elétrica Forte ME", "Hidro Masters ME"):
        assert n in nomes, f"Prestador {n!r} ausente: {nomes}"
    esp = {x["razao_social"]: x["especialidade"] for x in r}
    assert esp["TecServiços Ltda"] == "Mecânica Geral"
    assert esp["Elétrica Forte ME"] == "Elétrica Industrial"
    assert esp["Hidro Masters ME"] == "Hidráulica"
    assert len(r) == 3 and sum(1 for x in r if x["ativo"]) == 2, "Figma: 3 prestadores, 2 ativos"


def test_pedidos_do_figma(banco):
    esperado = {
        1623: ("BOMBA 1 (RESFRIADOR)", "Utilidades", "Ana Solicitante", "Em andamento", "Alta"),
        1624: ("INJETORA 02 - YIZUMI", "Produção", "Ana Solicitante", "Aberto", None),
        1625: ("EMPILHADEIRA HYSTER 2014", "Logística", "Carlos Gestor", "Concluído", "Baixa"),
        1626: ("COMPRESSOR METALPLAN", "Infraestrutura", "Ana Solicitante", "Aberto", None),
    }
    for pid, (equip, depto, solic, status, prio) in esperado.items():
        r = linha("SELECT p.*, e.descricao AS eq, d.nome AS dep FROM pedidos_manutencao p JOIN equipamentos e ON e.id=p.id_equipamento "
                  "JOIN departamentos d ON d.id=p.id_departamento WHERE p.id=?", pid)
        assert r, f"Pedido #{pid} ausente (ids de seed comecam em 1621, SPEC §3)"
        assert r["eq"].startswith(equip) and r["dep"] == depto and r["solicitante"] == solic and r["status"] == status, f"#{pid}: {r}"
        if prio:
            assert r["prioridade"] == prio, f"#{pid} prioridade {r['prioridade']}"
    assert linha("SELECT * FROM pedidos_manutencao WHERE id=1621"), "Pedido extra #1621 (ligado a OS-10232) ausente"


def test_ordens_de_servico_do_figma(banco):
    esperado = {10234: (1623, "Em andamento", "2026-09-12"), 10233: (1625, "Concluída", "2026-09-10"), 10232: (1621, "Aberta", "2026-09-08")}
    for oid, (ped, status, data) in esperado.items():
        o = linha("SELECT * FROM ordens_servico WHERE id=?", oid)
        assert o, f"OS-{oid} ausente (ids de seed comecam em 10232, SPEC §3)"
        assert o["id_pedido"] == ped and o["status"] == status and str(o["data_abertura"]).startswith(data), f"OS-{oid}: {o}"
    o34 = linha("SELECT * FROM ordens_servico WHERE id=10234")
    tec = um("SELECT nome FROM usuarios WHERE id=?", o34["id_tecnico"])
    assert tec == "Maria Técnica"


def test_historico_de_12_meses_para_os_graficos(banco):
    meses = {r["m"] for r in consulta("SELECT substr(data_abertura,1,7) AS m FROM ordens_servico")}
    assert len(meses) >= 10, f"Seed deveria cobrir ~12 meses de OS para os graficos (SPEC §3). Meses com OS: {sorted(meses)}"
    assert contar("ordens_servico") >= 24, "Dezenas de OS esperadas no seed (SPEC §3)"
    assert contar("pedidos_manutencao") >= 24
    assert contar("itens_os") >= 10, "Seed sem pecas usadas em OS: grafico 'Pecas mais utilizadas' ficaria vazio"
    assert contar("servicos_os") >= 5
    assert contar("apontamentos_os") >= 5


def test_parametros_de_meta_e_orcamento(banco):
    cols = {r["name"] for r in consulta("PRAGMA table_info(parametros)")}
    chave = "chave" if "chave" in cols else ("nome" if "nome" in cols else None)
    assert chave, f"parametros sem coluna chave/nome: {cols}"
    val = "valor" if "valor" in cols else None
    assert val, f"parametros sem coluna valor: {cols}"
    p = {}
    for r in consulta("SELECT * FROM parametros"):
        try:
            p[r[chave]] = float(r[val])
        except (TypeError, ValueError):
            pass  # parametros nao numericos (ex.: data de referencia) sao ignorados aqui
    assert p.get("meta_os_mes") == 20 and p.get("orcamento_mes") == 40000, p


def test_movimentacoes_do_seed_tem_entradas_e_saidas(banco):
    tipos = {r["t"] for r in consulta("SELECT DISTINCT tipo AS t FROM movimentacao_estoque_pecas")}
    assert {"Entrada", "Saída"} <= tipos, f"Movimentacoes devem ter Entrada e Saída: {tipos}"
    docs = {r["d"] for r in consulta("SELECT DISTINCT documento_origem AS d FROM movimentacao_estoque_pecas")}
    assert docs <= {"Nota Fiscal", "Ordem de Serviço", "Pedido Interno"}, docs


def test_historico_de_alteracoes_existe(banco):
    cols = {r["name"] for r in consulta("PRAGMA table_info(historico_alteracoes)")}
    for c in ("entidade", "id_entidade", "acao", "usuario", "data", "detalhe"):
        assert c in cols, f"historico_alteracoes sem coluna {c} (SPEC §3). Colunas: {cols}"


# ---------------------------------------------------------------------------
# Idempotencia
# ---------------------------------------------------------------------------

def _contagens(path):
    return {t: um(f"SELECT COUNT(*) FROM {t}", path=path) for t in tabelas(path) if not t.startswith("sqlite_")}


def test_seed_e_idempotente(banco_vazio):
    env = dict(os.environ, TECHMAINT_DB=DB_TESTE)
    r1 = subprocess.run([sys.executable, "seed.py"], cwd=REPO, env=env, capture_output=True, text=True, timeout=180)
    assert r1.returncode == 0, r1.stderr[-1500:]
    antes = _contagens(DB_TESTE)
    r2 = subprocess.run([sys.executable, "seed.py"], cwd=REPO, env=env, capture_output=True, text=True, timeout=180)
    assert r2.returncode == 0, f"Segunda execucao do seed falhou (nao idempotente): {r2.stderr[-1500:]}"
    depois = _contagens(DB_TESTE)
    diff = {t: (antes[t], depois[t]) for t in antes if antes[t] != depois.get(t)}
    assert not diff, f"Seed duplicou/alterou linhas na 2a execucao {{tabela: (antes, depois)}}: {diff}"
    assert antes["grupos"] == 15 and antes["subgrupos"] == 149


def test_seed_nao_sobrescreve_alteracoes_do_usuario(banco):
    """Rodar o seed de novo nao deve voltar senha/nome alterados nem apagar dados criados."""
    from helpers import executa
    executa("UPDATE departamentos SET responsavel_nome = 'Mudado Pelo Usuario' WHERE nome = 'Logística'")
    executa("INSERT INTO departamentos (nome, responsavel_nome) VALUES ('Depto Criado Pelo QA', 'x')")
    env = dict(os.environ, TECHMAINT_DB=DB_TESTE)
    r = subprocess.run([sys.executable, "seed.py"], cwd=REPO, env=env, capture_output=True, text=True, timeout=180)
    assert r.returncode == 0, r.stderr[-1500:]
    assert contar("departamentos", "nome = 'Depto Criado Pelo QA'") == 1, "Seed apagou dado criado pelo usuario"
    assert contar("departamentos", "nome = 'Logística'") == 1


def test_init_db_e_idempotente(banco):
    env = dict(os.environ, TECHMAINT_DB=DB_TESTE)
    antes = _contagens(DB_TESTE)
    r = subprocess.run([sys.executable, "-c", "import database; database.init_db(); database.init_db()"], cwd=REPO,
                       env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-1500:]
    assert _contagens(DB_TESTE) == antes
