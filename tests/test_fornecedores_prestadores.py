"""
CRUD de Fornecedores e Prestadores de Servico (Manual §1.4, Figma 13-14, SPEC §3 regra 6, §4).

Os dois modulos "seguem a mesma logica" (Manual 1.4: observacao) -> mesma bateria parametrizada.
Rastreabilidade: RF Gestao de fornecedores/prestadores (Projeto §5/§15b), Manual 1.4 (Razao Social, Fantasia, CNPJ, IE,
Endereco, Telefone, Email, Ativo; Salvar/Editar/Excluir; listagem ativos/inativos), SPEC §3.6 (CNPJ com digito verificador,
UF na lista, e-mail valido; CNPJ unico), SPEC §4 (+ Novo, filtro_ativo todos|ativos|inativos, busca de CEP offline).
"""

import pathlib
import re

import pytest

from helpers import (Bruto, PAYLOADS_HOSTIS, assert_exibido_com_seguranca, assert_rejeitado, assert_sucesso_post,
                     cnpj_invalido, consulta, contar, enviar, executa, formularios, gerar_cnpj, html_de, linha, post,
                     so_digitos, texto_visivel, unico, um)

REPO = pathlib.Path(__file__).resolve().parent.parent

ALIASES = {
    "razao": ["razao_social", "razao"], "fantasia": ["nome_fantasia", "fantasia"], "cnpj": ["cnpj"],
    "ie": ["inscricao_estadual", "ie"], "telefone": ["telefone", "fone"], "email": ["email", "e_mail"],
    "cep": ["cep"], "logradouro": ["logradouro", "endereco"], "numero": ["numero"], "complemento": ["complemento"],
    "bairro": ["bairro"], "municipio": ["municipio", "cidade"], "uf": ["uf", "estado"], "ativo": ["ativo"],
    "especialidade": ["especialidade"],
}

MODULOS = {
    "fornecedores": dict(base="/fornecedores", tabela="fornecedores", seed_razao="TecManutenções LTDA", outro_seed="Construservice S.A.",
                         extra={}),
    "prestadores": dict(base="/prestadores", tabela="prestadores_servico", seed_razao="TecServiços Ltda", outro_seed="Hidro Masters ME",
                        extra={"especialidade": "Mecânica Geral"}),
}


@pytest.fixture(params=list(MODULOS), ids=list(MODULOS))
def mod(request):
    return type("M", (), MODULOS[request.param])


def payload(mod, **kw):
    n = unico("F")
    base = dict(razao=f"Empresa QA {n} LTDA", fantasia=f"QA {n}", cnpj=gerar_cnpj(), ie="123456789", telefone="(11) 3456-7890",
                email=f"contato@{n}.com.br", cep="13201-000", logradouro="Rua das Flores", numero="100", complemento="Sala 2",
                bairro="Centro", municipio="Jundiaí", uf="SP", ativo=True)
    base.update(mod.extra)
    base.update(kw)
    return base


def criar(c, mod, **kw):
    d = payload(mod, **kw)
    return d, enviar(c, f"{mod.base}/novo", d, ALIASES, estrito=False)


def reg(mod, razao):
    return linha(f"SELECT * FROM {mod.tabela} WHERE razao_social=?", razao)


# --------------------------------------------------------------------------------------------- lista

def test_lista_mostra_seed_botao_novo_e_contagem(admin, mod):
    r = admin.get(mod.base)
    assert r.status_code == 200
    t = texto_visivel(html_de(r))
    assert mod.seed_razao in t and mod.outro_seed in t
    assert "Novo" in t, "Botao '+ Novo ...' (SPEC §4)"
    assert "3" in t, "Contagem de registros no rodape (Figma 13/14)"


def test_lista_de_prestadores_mostra_codigo_pst_e_especialidade(admin):
    t = texto_visivel(html_de(admin.get("/prestadores")))
    for trecho in ("PST-001", "PST-002", "PST-003", "Mecânica Geral", "Elétrica Industrial", "Hidráulica", "2 ativo"):
        assert trecho in t, f"Figma 14: {trecho!r} ausente"


def test_lista_de_fornecedores_mostra_cnpj_e_telefone(admin):
    t = texto_visivel(html_de(admin.get("/fornecedores")))
    assert "12.345.678/0001-90" in t or "12345678000190" in t
    assert "(11)" in t


def test_cnpj_exibido_formatado(admin, mod):
    d, r = criar(admin, mod)
    t = texto_visivel(html_de(admin.get(f"{mod.base}?busca={d['razao'][:12]}")))
    assert d["cnpj"] in t, f"CNPJ deveria ser exibido mascarado {d['cnpj']} (Figma 13)"


# --------------------------------------------------------------------------------------------- criar

def test_formulario_novo_tem_todos_os_campos_do_documento(admin, mod):
    r = admin.get(f"{mod.base}/novo")
    assert r.status_code == 200
    forms = [f for f in formularios(html_de(r)) if f.method == "post" and "csrf_token" in f.nomes]
    f = max(forms, key=lambda x: len(x.campos))
    nomes = " ".join(f.nomes).lower()
    for campo in ("razao", "fantasia", "cnpj", "inscricao", "telefone", "email", "cep", "logradouro", "numero",
                  "complemento", "bairro", "municipio", "uf", "ativo"):
        assert campo in nomes, f"Campo {campo!r} ausente do formulario (Projeto §6 Fornecedores). Campos: {f.nomes}"
    if mod.tabela == "prestadores_servico":
        assert "especialidade" in nomes
    uf = next(c for c in f.campos if c.nome == "uf")
    assert {"SP", "RJ", "MG", "RS", "PR", "SC", "BA", "PE", "CE"} <= {o["valor"] for o in uf.opcoes} | {o["rotulo"] for o in uf.opcoes}


def test_criar_valido(admin, mod):
    d, r = criar(admin, mod)
    assert_sucesso_post(r, "criar")
    x = reg(mod, d["razao"])
    assert x, "nao gravou"
    assert so_digitos(x["cnpj"]) == so_digitos(d["cnpj"])
    assert x["uf"] == "SP" and x["email"] == d["email"] and x["ativo"] in (1, True, "1", "S")
    assert so_digitos(x["cep"]) == "13201000"


def test_criar_apenas_com_obrigatorios(admin, mod):
    d = dict(razao="Minima QA " + unico("m"), cnpj=gerar_cnpj(), **mod.extra)
    r = enviar(admin, f"{mod.base}/novo", d, ALIASES, estrito=False)
    assert_sucesso_post(r, "criar so com razao social + CNPJ (demais campos opcionais no modelo)")


def test_cnpj_sem_mascara_e_aceito_e_normalizado(admin, mod):
    d = payload(mod, cnpj=gerar_cnpj(formatado=False))
    r = enviar(admin, f"{mod.base}/novo", d, ALIASES, estrito=False)
    assert_sucesso_post(r, "cnpj so digitos")
    assert so_digitos(reg(mod, d["razao"])["cnpj"]) == d["cnpj"]


def test_inativo_nao_aparece_como_ativo(admin, mod):
    d, _ = criar(admin, mod, ativo=False)
    assert reg(mod, d["razao"])["ativo"] in (0, False, "0", "N")


INVALIDOS = [
    ("razao_vazia", dict(razao="")),
    ("razao_so_espacos", dict(razao="   ")),
    ("cnpj_vazio", dict(cnpj="")),
    ("cnpj_digito_errado", dict(cnpj="__DV__")),
    ("cnpj_curto", dict(cnpj="12.345.678/0001")),
    ("cnpj_longo", dict(cnpj="12.345.678/0001-9900")),
    ("cnpj_letras", dict(cnpj="AB.CDE.FGH/IJKL-MN")),
    ("cnpj_zeros", dict(cnpj="00.000.000/0000-00")),
    ("cnpj_repetido_11", dict(cnpj="11.111.111/1111-11")),
    ("uf_invalida", dict(uf=Bruto("XX"))),
    ("uf_minuscula_lixo", dict(uf=Bruto("s"))),
    ("uf_tres_letras", dict(uf=Bruto("SPP"))),
    ("email_invalido", dict(email="sem-arroba")),
    ("email_sem_dominio", dict(email="a@")),
    ("email_com_espaco", dict(email="a b@c.com")),
]


@pytest.mark.parametrize("nome,mudanca", INVALIDOS, ids=[i[0] for i in INVALIDOS])
def test_validacoes_na_criacao(admin, mod, nome, mudanca):
    mudanca = {k: (cnpj_invalido() if v == "__DV__" else v) for k, v in mudanca.items()}
    d = payload(mod, **mudanca)
    antes = contar(mod.tabela)
    r = enviar(admin, f"{mod.base}/novo", d, ALIASES, estrito=False)
    assert_rejeitado(r, f"{mod.tabela} invalido ({nome})")
    assert contar(mod.tabela) == antes, f"{nome}: registro invalido foi GRAVADO"
    assert d["razao"] in html_de(r) or nome.startswith("razao"), "form re-renderizado deve preservar a razao social digitada"


def test_mensagem_de_cnpj_invalido(admin, mod):
    r = enviar(admin, f"{mod.base}/novo", payload(mod, cnpj=cnpj_invalido()), ALIASES, estrito=False)
    t = texto_visivel(html_de(r)).lower()
    assert "cnpj" in t and ("inválid" in t or "invalid" in t), "Mensagem clara de CNPJ invalido esperada"


def test_cnpj_duplicado_exato(admin, mod):
    d, _ = criar(admin, mod)
    antes = contar(mod.tabela)
    r = enviar(admin, f"{mod.base}/novo", payload(mod, cnpj=d["cnpj"]), ALIASES, estrito=False)
    assert_rejeitado(r, "CNPJ duplicado")
    assert contar(mod.tabela) == antes


def test_cnpj_duplicado_com_mascara_diferente(admin, mod):
    d, _ = criar(admin, mod, cnpj=gerar_cnpj(formatado=True))
    antes = contar(mod.tabela)
    r = enviar(admin, f"{mod.base}/novo", payload(mod, cnpj=so_digitos(d["cnpj"])), ALIASES, estrito=False)
    assert_rejeitado(r, "mesmo CNPJ, so digitos x mascara")
    assert contar(mod.tabela) == antes, "CNPJ duplicado passou por diferenca de mascara (deveria normalizar)"


def test_mesma_razao_social_com_cnpj_diferente_e_permitida(admin, mod):
    d, _ = criar(admin, mod)
    r = enviar(admin, f"{mod.base}/novo", payload(mod, razao=d["razao"]), ALIASES, estrito=False)
    assert r.status_code < 500   # CNPJ e a chave de unicidade (Projeto §6), nao a razao social


def test_cnpj_do_seed_ja_existente_e_rejeitado(admin, mod):
    existente = um(f"SELECT cnpj FROM {mod.tabela} ORDER BY id LIMIT 1")
    d = payload(mod, cnpj=existente)
    antes = contar(mod.tabela)
    r = enviar(admin, f"{mod.base}/novo", d, ALIASES, estrito=False)
    assert r.status_code < 500
    assert contar(mod.tabela) == antes, "CNPJ do seed duplicado foi aceito"


def test_campos_longos_nao_quebram(admin, mod):
    d = payload(mod, logradouro="R" * 5000, complemento="C" * 5000, razao="X" * 5000)
    r = enviar(admin, f"{mod.base}/novo", d, ALIASES, estrito=False)
    assert r.status_code < 500


# --------------------------------------------------------------------------------------------- busca e filtros

def test_busca_por_razao_cnpj_e_fantasia(admin, mod):
    d, _ = criar(admin, mod, razao="Zeta Unica Industria", fantasia="ZETAFANTASIA")
    for termo in ("Zeta Unica", "zeta unica", "ZETAFANTASIA", so_digitos(d["cnpj"]), d["cnpj"]):
        h = html_de(admin.get(f"{mod.base}", query_string={"busca": termo}))
        assert "Zeta Unica Industria" in h, f"busca por {termo!r} nao achou o registro"
    assert mod.seed_razao not in html_de(admin.get(mod.base, query_string={"busca": "Zeta Unica"}))


def test_filtro_ativos_inativos(admin, mod):
    d, _ = criar(admin, mod, razao="Inativa Qa Corp", ativo=False)
    d2, _ = criar(admin, mod, razao="Ativa Qa Corp", ativo=True)
    h_ativos = html_de(admin.get(mod.base, query_string={"ativo": "ativos", "filtro_ativo": "ativos", "status": "ativos"}))
    h_inativos = html_de(admin.get(mod.base, query_string={"ativo": "inativos", "filtro_ativo": "inativos", "status": "inativos"}))
    assert "Ativa Qa Corp" in h_ativos and "Inativa Qa Corp" not in h_ativos, "filtro 'ativos' (SPEC §4 filtro_ativo)"
    assert "Inativa Qa Corp" in h_inativos and "Ativa Qa Corp" not in h_inativos.replace("Inativa Qa Corp", ""), "filtro 'inativos'"


def test_filtro_todos_mostra_ambos(admin, mod):
    criar(admin, mod, razao="Inativa Todos Qa", ativo=False)
    h = html_de(admin.get(mod.base, query_string={"ativo": "todos", "filtro_ativo": "todos"}))
    assert "Inativa Todos Qa" in h


def test_busca_com_caracteres_especiais(admin, mod):
    for b in PAYLOADS_HOSTIS + ["%", "_", "'", '"', "\\"]:
        r = admin.get(mod.base, query_string={"busca": b})
        assert r.status_code < 500, f"busca {b!r} -> {r.status_code}"
        if "<" in b:
            assert b not in html_de(r)


# --------------------------------------------------------------------------------------------- editar

def test_editar(admin, mod):
    d, _ = criar(admin, mod)
    x = reg(mod, d["razao"])
    r = enviar(admin, f"{mod.base}/{x['id']}/editar", {"razao": d["razao"] + " EDITADA", "telefone": "(19) 99999-0000", "uf": "RJ"},
               ALIASES, estrito=False)
    assert_sucesso_post(r, "editar")
    y = linha(f"SELECT * FROM {mod.tabela} WHERE id=?", x["id"])
    assert y["razao_social"].endswith("EDITADA") and y["uf"] == "RJ"
    assert so_digitos(y["cnpj"]) == so_digitos(d["cnpj"]), "CNPJ nao pode mudar sem querer na edicao"


def test_formulario_de_edicao_preenchido(admin, mod):
    x = linha(f"SELECT * FROM {mod.tabela} ORDER BY id LIMIT 1")
    h = html_de(admin.get(f"{mod.base}/{x['id']}/editar"))
    assert x["razao_social"] in h


def test_editar_cnpj_para_invalido_ou_duplicado(admin, mod):
    d, _ = criar(admin, mod)
    x = reg(mod, d["razao"])
    outro = um(f"SELECT cnpj FROM {mod.tabela} WHERE id <> ? ORDER BY id LIMIT 1", x["id"])
    for ruim in (cnpj_invalido(), outro):
        r = enviar(admin, f"{mod.base}/{x['id']}/editar", {"cnpj": ruim}, ALIASES, estrito=False)
        assert_rejeitado(r, f"editar CNPJ para {ruim}")
    assert so_digitos(linha(f"SELECT cnpj FROM {mod.tabela} WHERE id=?", x["id"])["cnpj"]) == so_digitos(d["cnpj"])


def test_editar_mantendo_cnpj_nao_acusa_duplicidade(admin, mod):
    d, _ = criar(admin, mod)
    x = reg(mod, d["razao"])
    r = enviar(admin, f"{mod.base}/{x['id']}/editar", {"fantasia": "Outra Fantasia"}, ALIASES, estrito=False)
    assert_sucesso_post(r, "editar sem mudar CNPJ")


def test_inativar_pela_edicao(admin, mod):
    d, _ = criar(admin, mod)
    x = reg(mod, d["razao"])
    enviar(admin, f"{mod.base}/{x['id']}/editar", {"ativo": False}, ALIASES, estrito=False)
    assert linha(f"SELECT ativo FROM {mod.tabela} WHERE id=?", x["id"])["ativo"] in (0, False, "0", "N")


def test_inexistente_da_404(admin, mod):
    assert admin.get(f"{mod.base}/999999/editar").status_code == 404
    assert post(admin, f"{mod.base}/999999/excluir").status_code in (404, 302, 303)


# --------------------------------------------------------------------------------------------- excluir

def test_excluir_sem_vinculos(admin, mod):
    d, _ = criar(admin, mod)
    x = reg(mod, d["razao"])
    assert_sucesso_post(post(admin, f"{mod.base}/{x['id']}/excluir"), "excluir")
    assert reg(mod, d["razao"]) is None


def test_excluir_so_por_post(admin, mod):
    x = um(f"SELECT id FROM {mod.tabela} LIMIT 1")
    assert admin.get(f"{mod.base}/{x}/excluir").status_code == 405


def test_excluir_fornecedor_com_nota_fiscal_e_bloqueado(admin):
    fid = um("SELECT id FROM fornecedores ORDER BY id LIMIT 1")
    executa("INSERT INTO notas_fiscais (id_fornecedor, numero_nf, data_emissao, data_entrada, valor_total_nf) "
            "VALUES (?, 1001, date('now'), date('now'), 100)", fid)
    r = post(admin, f"/fornecedores/{fid}/excluir", seguir=True)
    assert r.status_code == 200
    assert linha("SELECT * FROM fornecedores WHERE id=?", fid), "Fornecedor com NF foi apagado (SPEC §3: inativar)"
    t = texto_visivel(html_de(r)).lower()
    assert "vínculo" in t or "vinculo" in t or "inativ" in t or "não é possível" in t or "nao e possivel" in t
    assert consulta("PRAGMA foreign_key_check") == []


def test_excluir_prestador_com_servico_em_os_e_bloqueado(admin):
    row = linha("SELECT id_prestador FROM servicos_os WHERE id_prestador IS NOT NULL LIMIT 1")
    if row is None:
        pid = um("SELECT id FROM prestadores_servico ORDER BY id LIMIT 1")
        os_id = um("SELECT id FROM ordens_servico ORDER BY id LIMIT 1")
        executa("INSERT INTO servicos_os (id_os, descricao_servico, valor_servico, id_prestador) VALUES (?, 'servico qa', 10, ?)", os_id, pid)
    else:
        pid = row["id_prestador"]
    r = post(admin, f"/prestadores/{pid}/excluir", seguir=True)
    assert r.status_code == 200
    assert linha("SELECT * FROM prestadores_servico WHERE id=?", pid), "Prestador vinculado a servico de OS foi apagado"
    assert consulta("PRAGMA foreign_key_check") == []


# --------------------------------------------------------------------------------------------- CEP offline

def test_front_nao_chama_api_externa_de_cep():
    achados = []
    for f in list((REPO / "templates").glob("*.html")) + [p for p in (REPO / "static").rglob("*.js") if "vendor" not in p.parts]:
        txt = f.read_text(encoding="utf-8", errors="ignore").lower()
        for termo in ("viacep", "brasilapi", "cep.awesomeapi", "publica.cnpj", "receitaws", "api.postmon"):
            if termo in txt:
                achados.append((f.name, termo))
    assert not achados, f"Busca de CEP deve ser offline (SPEC §5/§1: sem rede em runtime): {achados}"


# --------------------------------------------------------------------------------------------- injecao / permissao

@pytest.mark.parametrize("bruto", PAYLOADS_HOSTIS)
def test_razao_hostil_escapada(admin, mod, bruto):
    d = payload(mod, razao=bruto)
    r = enviar(admin, f"{mod.base}/novo", d, ALIASES, estrito=False)
    assert r.status_code < 500
    if reg(mod, bruto):
        assert_exibido_com_seguranca(html_de(admin.get(mod.base)), bruto, f"lista de {mod.tabela}")
    assert contar(mod.tabela) >= 3


@pytest.mark.parametrize("perfil", ["gestor", "tecnico"])
def test_gestor_e_tecnico_so_veem(cliente_de, mod, perfil):
    c = cliente_de(perfil)
    r = c.get(mod.base)
    assert r.status_code == 200
    h = html_de(r)
    assert "/novo" not in h, f"{perfil} so 'ver' (SPEC §2): botao + Novo nao deveria aparecer"
    assert "/excluir" not in h
    assert mod.seed_razao in h


def test_usuario_comum_sem_acesso(comum, mod):
    assert comum.get(mod.base).status_code == 403


def test_auditoria(admin, mod):
    d, _ = criar(admin, mod)
    x = reg(mod, d["razao"])
    post(admin, f"{mod.base}/{x['id']}/excluir")
    assert contar("historico_alteracoes", "id_entidade=? AND (lower(entidade) LIKE 'forn%' OR lower(entidade) LIKE 'prest%')", x["id"]) >= 2
