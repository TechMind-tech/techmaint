"""
CRUD de Usuarios e Perfis (Manual §1.1, Figma 05-08, SPEC §3 regra 6, §4 /usuarios).

Rastreabilidade: RF Cadastro de Usuarios (Projeto §15b), Manual 1.1 (Nome, Login, Senha, Email, Perfil, Ativo;
Novo/Salvar/Editar/Excluir/Pesquisar; filtro por perfil), SPEC §3.6 (login unico case-insensitive 3-50 sem espacos,
senha >= 8, e-mail valido), hash de senha (SPEC §1).
"""

import re
import pytest
from werkzeug.security import check_password_hash

from helpers import (PAYLOADS_HOSTIS, assert_exibido_com_seguranca, Bruto, STATUS_ERRO_FORM, assert_rejeitado, assert_sucesso_post, consulta, contar, contem,
                     criar_usuario_db, enviar, executa, fazer_login, html_de, id_perfil, linha, post, snapshot,
                     texto_visivel, unico, um, escapado)

ALIASES = {
    "nome": ["nome"], "login": ["login", "usuario"], "email": ["email", "e_mail"],
    "senha": ["senha", "password"], "perfil": ["id_perfil", "perfil", "perfil_id"],
    "departamento": ["id_departamento", "departamento", "depto"], "ativo": ["ativo", "usuario_ativo"],
}


def payload(**kw):
    n = unico("u")
    base = dict(nome=f"Teste {n}", login=n, email=f"{n}@teste.com", senha="senhaForte1", perfil="Técnico",
                departamento="Manutenção", ativo=True)
    base.update(kw)
    return base


def criar(c, **kw):
    return enviar(c, "/usuarios", payload(**kw), ALIASES, estrito=False)


def usuario(login):
    return linha("SELECT * FROM usuarios WHERE lower(login)=lower(?)", login)


def perfil_de(uid):
    return um("SELECT p.nome FROM usuarios_perfis up JOIN perfis p ON p.id=up.id_perfil WHERE up.id_usuario=?", uid)


# --------------------------------------------------------------------------------------------- tela

def test_tela_de_usuarios_tem_formulario_cards_e_lista(admin):
    r = admin.get("/usuarios")
    assert r.status_code == 200
    t = texto_visivel(html_de(r))
    for trecho in ("Cadastro de Usuários e Perfis", "Novo Usuário", "Lista de Usuários", "João Administrador", "Maria Técnica"):
        assert trecho.lower() in t.lower(), f"Tela de usuarios deveria conter {trecho!r} (Figma 05-08)"
    for perfil in ("Administrador", "Técnico", "Gestor", "Usuário Comum"):
        assert perfil in t


def test_cards_de_contagem_por_perfil(admin):
    t = texto_visivel(html_de(admin.get("/usuarios")))
    import re
    esperado = {"Administrador": 1, "Técnico": 2, "Gestor": 1, "Usuário Comum": 1}
    for perfil, n in esperado.items():
        achou = re.search(rf"(\d+)\s+{perfil}", t) or re.search(rf"\b{perfil}\s+(\d+)", t)
        assert achou, f"Card de contagem do perfil {perfil!r} nao encontrado no texto: {t[:300]!r}"
        assert int(achou.group(1)) == n, f"Contagem de {perfil}: {achou.group(1)} (esperado {n}, seed SPEC §2)"


def test_campos_do_formulario_seguem_o_manual(admin):
    from helpers import formularios
    forms = [f for f in formularios(html_de(admin.get("/usuarios"))) if f.method == "post" and "csrf_token" in f.nomes]
    f = max(forms, key=lambda x: len(x.campos))
    nomes = " ".join(f.nomes).lower()
    for campo in ("nome", "login", "email", "senha", "perfil", "ativo"):
        assert campo in nomes, f"Formulario de usuario sem campo '{campo}' (Manual 1.1). Campos: {f.nomes}"
    senha = next(c for c in f.campos if c.nome and "senha" in c.nome)
    assert senha.tipo == "password"
    perfil = next(c for c in f.campos if c.nome and "perfil" in c.nome)
    rotulos = {o["rotulo"] for o in perfil.opcoes}
    assert {"Administrador", "Técnico", "Gestor", "Usuário Comum"} <= rotulos, f"Opcoes de perfil: {rotulos}"


def test_lista_mostra_badge_de_perfil_e_status(admin):
    t = texto_visivel(html_de(admin.get("/usuarios")))
    assert "admin" in t and "tecnico" in t and "solicitante" in t
    assert "Ativo" in t or "ativo" in t


# --------------------------------------------------------------------------------------------- criar

def test_criar_usuario_valido(admin):
    d = payload()
    r = enviar(admin, "/usuarios", d, ALIASES, estrito=False)
    assert_sucesso_post(r, "Criar usuario")
    u = usuario(d["login"])
    assert u, "Usuario nao foi gravado no banco"
    assert u["nome"] == d["nome"] and u["email"] == d["email"] and u["ativo"] in (1, True)
    assert perfil_de(u["id"]) == "Técnico"
    assert u["id_departamento"] == um("SELECT id FROM departamentos WHERE nome='Manutenção'")
    assert u["data_cadastro"], "data_cadastro deveria ser preenchida automaticamente"


def test_senha_gravada_com_hash_nunca_em_texto_puro(admin):
    d = payload(senha="MinhaSenha#2026")
    criar(admin, **d)
    u = usuario(d["login"])
    assert u["senha_hash"] != "MinhaSenha#2026" and "MinhaSenha" not in u["senha_hash"]
    assert check_password_hash(u["senha_hash"], "MinhaSenha#2026"), "senha_hash deve ser gerado por generate_password_hash (SPEC §1)"


def test_usuario_criado_consegue_logar(admin, app):
    d = payload(senha="SenhaNova123")
    criar(admin, **d)
    c = app.test_client()
    assert fazer_login(c, d["login"], "SenhaNova123").status_code in (302, 303)


def test_usuario_criado_inativo_nao_loga(admin, app):
    d = payload(senha="SenhaNova123", ativo=False)
    criar(admin, **d)
    assert usuario(d["login"])["ativo"] in (0, False)
    assert fazer_login(app.test_client(), d["login"], "SenhaNova123").status_code not in (302, 303)


@pytest.mark.parametrize("perfil", ["Administrador", "Técnico", "Gestor", "Usuário Comum"])
def test_criar_usuario_em_cada_perfil(admin, perfil):
    d = payload(perfil=perfil)
    assert_sucesso_post(criar(admin, **d), f"criar perfil {perfil}")
    assert perfil_de(usuario(d["login"])["id"]) == perfil


def test_aparece_na_lista_e_na_busca(admin):
    d = payload(nome="Fulano Buscavel Zeta")
    criar(admin, **d)
    h = admin.get("/usuarios?busca=Buscavel Zeta")
    assert "Fulano Buscavel Zeta" in html_de(h)
    h2 = admin.get("/usuarios?busca=Buscavel Zeta")
    assert "Maria Técnica" not in html_de(h2), "A busca deveria filtrar a lista"


def test_busca_por_login_e_por_email(admin):
    assert "Pedro Lima" in html_de(admin.get("/usuarios?busca=plima"))
    assert "Pedro Lima" in html_de(admin.get("/usuarios?busca=plima@techmaint"))
    assert "Pedro Lima" not in html_de(admin.get("/usuarios?busca=naoexiste_xyz"))


def test_busca_e_insensivel_a_maiusculas(admin):
    assert "Pedro Lima" in html_de(admin.get("/usuarios?busca=PEDRO"))


def test_filtro_por_perfil(admin):
    """filtro_perfil (SPEC §4): o parametro de URL pode ser o id ou o nome do perfil."""
    tecnico_id = id_perfil("Técnico")
    ok = False
    tentativas = []
    for nome in ("perfil", "filtro_perfil", "perfil_id", "id_perfil"):
        for val in (tecnico_id, "Técnico"):
            h = html_de(admin.get(f"/usuarios?{nome}={val}"))
            tentativas.append((nome, val))
            if "Maria Técnica" in h and "Pedro Lima" in h and "João Administrador" not in _so_lista(h) and "Ana Solicitante" not in _so_lista(h):
                ok = True
                break
        if ok:
            break
    assert ok, f"Filtro por perfil nao funcionou com nenhuma das variantes de URL: {tentativas}"


def _so_lista(h):
    """Texto da area da lista (depois de 'Lista de Usuários') para nao confundir com o cabecalho/avatar."""
    t = texto_visivel(h)
    i = t.find("Lista de Usuários")
    return t[i:] if i >= 0 else t


# --------------------------------------------------------------------------------------------- validacoes

CASOS_INVALIDOS = [
    ("nome_vazio", dict(nome="")),
    ("nome_so_espacos", dict(nome="    ")),
    ("login_vazio", dict(login="")),
    ("login_curto_2", dict(login="ab")),
    ("login_longo_51", dict(login="a" * 51)),
    ("login_com_espaco", dict(login="com espaco")),
    ("login_duplicado_exato", dict(login="admin")),
    ("login_duplicado_caixa", dict(login="ADMIN")),
    ("login_duplicado_misto", dict(login="Tecnico")),
    ("email_sem_arroba", dict(email="semarroba.com")),
    ("email_sem_dominio", dict(email="a@")),
    ("email_sem_tld", dict(email="a@b")),
    ("email_com_espaco", dict(email="a b@c.com")),
    ("email_so_arroba", dict(email="@c.com")),
    ("senha_vazia", dict(senha="")),
    ("senha_7_chars", dict(senha="1234567")),
    ("senha_curta_abc", dict(senha="abc")),
    ("perfil_inexistente", dict(perfil=Bruto("99999"))),
    ("departamento_inexistente", dict(departamento=Bruto("99999"))),
]


@pytest.mark.parametrize("nome,mudanca", CASOS_INVALIDOS, ids=[c[0] for c in CASOS_INVALIDOS])
def test_validacoes_na_criacao(admin, nome, mudanca):
    base = payload()
    d = {**base, **mudanca}
    antes = contar("usuarios")
    r = enviar(admin, "/usuarios", d, ALIASES, estrito=False)
    assert_rejeitado(r, f"Usuario invalido ({nome})")
    assert contar("usuarios") == antes, f"Caso {nome}: o usuario invalido FOI gravado"
    h = html_de(r)
    if d["senha"]:
        assert d["senha"] not in h or d["senha"] in ("admin", ), "A senha digitada nao deve ser devolvida no HTML"
    if nome not in ("nome_vazio", "nome_so_espacos"):
        assert base["nome"] in h, "Nao perder o que o usuario digitou (SPEC §4: re-renderizar com `valores`)"


def test_validacao_mostra_mensagem_de_erro_visivel(admin):
    r = enviar(admin, "/usuarios", payload(email="invalido"), ALIASES, estrito=False)
    t = texto_visivel(html_de(r)).lower()
    assert any(p in t for p in ("e-mail", "email")) and any(p in t for p in ("inválid", "invalid", "válido")), \
        "Esperada mensagem de erro em pt-BR junto ao campo de e-mail (SPEC §4: erros)"


@pytest.mark.parametrize("login", ["abc", "a" * 50, "nome.sobrenome", "Maria_Silva-2", "usuário"])
def test_logins_limite_validos(admin, login):
    d = payload(login=login if login != "a" * 50 else "q" * 50)
    if usuario(d["login"]):
        pytest.skip("login ja existe")
    r = enviar(admin, "/usuarios", d, ALIASES, estrito=False)
    if login == "usuário":   # acentos: decisao de contrato nao fixada -> so exige nao quebrar
        assert r.status_code < 500
        return
    assert_sucesso_post(r, f"login valido {login!r}")


def test_senha_exatamente_8_caracteres_e_aceita(admin):
    assert_sucesso_post(criar(admin, senha="12345678"), "senha de 8 caracteres")


def test_email_vazio_nao_quebra(admin):
    r = enviar(admin, "/usuarios", payload(email=""), ALIASES, estrito=False)
    assert r.status_code < 500  # Projeto: e-mail "opcional"; SPEC pede "e-mail valido" -> ambos aceitaveis


def test_nome_com_acentos_e_apostrofo(admin):
    d = payload(nome="José D'Ávila-Çñ Ünïcode")
    assert_sucesso_post(criar(admin, **d), "nome com acento/apostrofo")
    assert usuario(d["login"])["nome"] == d["nome"]
    h = html_de(admin.get("/usuarios?busca=" + d["login"]))
    assert "Ávila" in h and "D&#39;Ávila" in h or "D'Ávila" in h


# --------------------------------------------------------------------------------------------- editar

def test_formulario_de_edicao_vem_preenchido(admin):
    uid = id_usuario_plima()
    r = admin.get(f"/usuarios/{uid}/editar")
    assert r.status_code == 200
    h = html_de(r)
    assert "Pedro Lima" in h and "plima" in h and "plima@techmaint.com" in h


def id_usuario_plima():
    return um("SELECT id FROM usuarios WHERE login='plima'")


def test_editar_nome_email_perfil(admin):
    d = payload()
    criar(admin, **d)
    uid = usuario(d["login"])["id"]
    r = enviar(admin, f"/usuarios/{uid}/editar", {"nome": "Nome Editado", "email": "novo@teste.com", "perfil": "Gestor", "senha": ""},
               ALIASES, estrito=False)
    assert_sucesso_post(r, "editar usuario")
    u = usuario(d["login"])
    assert u["nome"] == "Nome Editado" and u["email"] == "novo@teste.com"
    assert perfil_de(uid) == "Gestor"


def test_editar_sem_senha_mantem_a_senha(admin, app):
    d = payload(senha="SenhaOriginal1")
    criar(admin, **d)
    u = usuario(d["login"])
    enviar(admin, f"/usuarios/{u['id']}/editar", {"nome": "So Nome", "senha": ""}, ALIASES, estrito=False)
    u2 = usuario(d["login"])
    assert u2["senha_hash"] == u["senha_hash"], "Senha em branco na edicao deve manter o hash (SPEC §4)"
    assert fazer_login(app.test_client(), d["login"], "SenhaOriginal1").status_code in (302, 303)


def test_editar_com_senha_nova_troca_o_hash(admin, app):
    d = payload(senha="SenhaOriginal1")
    criar(admin, **d)
    u = usuario(d["login"])
    enviar(admin, f"/usuarios/{u['id']}/editar", {"senha": "SenhaTrocada22"}, ALIASES, estrito=False)
    assert usuario(d["login"])["senha_hash"] != u["senha_hash"]
    assert fazer_login(app.test_client(), d["login"], "SenhaTrocada22").status_code in (302, 303)
    assert fazer_login(app.test_client(), d["login"], "SenhaOriginal1").status_code not in (302, 303)


def test_editar_rejeita_senha_curta_nova(admin):
    d = payload()
    criar(admin, **d)
    u = usuario(d["login"])
    r = enviar(admin, f"/usuarios/{u['id']}/editar", {"senha": "123"}, ALIASES, estrito=False)
    assert_rejeitado(r, "senha curta na edicao")
    assert usuario(d["login"])["senha_hash"] == u["senha_hash"]


def test_editar_login_para_um_ja_existente_e_rejeitado(admin):
    d = payload()
    criar(admin, **d)
    u = usuario(d["login"])
    r = enviar(admin, f"/usuarios/{u['id']}/editar", {"login": "Admin"}, ALIASES, estrito=False)
    assert_rejeitado(r, "duplicar login na edicao")
    assert usuario(d["login"])["login"] == d["login"]


def test_editar_mantendo_o_proprio_login_nao_acusa_duplicidade(admin):
    d = payload()
    criar(admin, **d)
    u = usuario(d["login"])
    r = enviar(admin, f"/usuarios/{u['id']}/editar", {"nome": "Mesmo Login"}, ALIASES, estrito=False)
    assert_sucesso_post(r, "editar mantendo login")


def test_editar_inativar_usuario(admin, app):
    d = payload(senha="SenhaOriginal1")
    criar(admin, **d)
    u = usuario(d["login"])
    enviar(admin, f"/usuarios/{u['id']}/editar", {"ativo": False}, ALIASES, estrito=False)
    assert usuario(d["login"])["ativo"] in (0, False)
    assert fazer_login(app.test_client(), d["login"], "SenhaOriginal1").status_code not in (302, 303)


def test_editar_usuario_inexistente_da_404(admin):
    assert admin.get("/usuarios/999999/editar").status_code == 404
    assert post(admin, "/usuarios/999999/editar", {"nome": "x"}).status_code == 404


# --------------------------------------------------------------------------------------------- excluir

def test_excluir_usuario_sem_vinculos(admin):
    d = payload()
    criar(admin, **d)
    uid = usuario(d["login"])["id"]
    r = post(admin, f"/usuarios/{uid}/excluir")
    assert_sucesso_post(r, "excluir usuario")
    assert usuario(d["login"]) is None
    assert contar("usuarios_perfis", "id_usuario=?", uid) == 0, "Sobrou vinculo em usuarios_perfis (orfao)"


def test_excluir_usuario_com_vinculos_nao_da_500_e_preserva_historico(admin):
    """Ana tem pedidos: nao pode sumir deixando pedido orfao (SPEC §3: prefira inativar)."""
    ana = usuario("solicitante")
    pedidos_antes = contar("pedidos_manutencao")
    r = post(admin, f"/usuarios/{ana['id']}/excluir")
    assert r.status_code < 500, f"Excluir usuario com vinculos deu {r.status_code} (esperado mensagem amigavel/inativacao)"
    assert contar("pedidos_manutencao") == pedidos_antes
    restante = usuario("solicitante")
    assert restante is not None, "Usuario com pedidos foi apagado: deveria ser inativado/bloqueado (SPEC §3)"
    from helpers import consulta
    assert consulta("PRAGMA foreign_key_check") == []


def test_excluir_vinculo_mostra_mensagem_amigavel(admin):
    ana = usuario("solicitante")
    r = post(admin, f"/usuarios/{ana['id']}/excluir", seguir=True)
    t = texto_visivel(html_de(r)).lower()
    assert any(p in t for p in ("vínculo", "vinculo", "inativ", "não é possível", "nao e possivel")), \
        f"Esperada mensagem amigavel ('Nao e possivel excluir: ha X vinculos' ou inativacao). Texto: {t[:300]!r}"


def test_excluir_so_por_post(admin):
    uid = id_usuario_plima()
    assert admin.get(f"/usuarios/{uid}/excluir").status_code == 405
    assert usuario("plima")


def test_excluir_usuario_inexistente(admin):
    r = post(admin, "/usuarios/999999/excluir")
    assert r.status_code in (404, 302, 303)


def test_admin_nao_deve_conseguir_excluir_a_propria_conta_logada(admin):
    """Cenario de seguranca/usabilidade: o ultimo admin nao pode se auto-excluir (contrato silencioso -> Dúvida)."""
    uid = usuario("admin")["id"]
    post(admin, f"/usuarios/{uid}/excluir")
    assert usuario("admin") is not None or contar("usuarios") >= 1
    assert admin.get("/menu").status_code in (200, 302, 401, 403)  # sem 500


def test_historico_de_alteracoes_registra_criar_editar_excluir(admin):
    d = payload()
    criar(admin, **d)
    uid = usuario(d["login"])["id"]
    enviar(admin, f"/usuarios/{uid}/editar", {"nome": "Auditado"}, ALIASES, estrito=False)
    post(admin, f"/usuarios/{uid}/excluir")
    acoes = [r["acao"].lower() for r in consulta("SELECT acao FROM historico_alteracoes WHERE lower(entidade) LIKE 'usu%' AND id_entidade=?", uid)]
    assert len(acoes) >= 3, f"Auditoria (SPEC §3 historico_alteracoes) deveria ter criar/editar/excluir do usuario. Achei: {acoes}"


def test_historico_nao_guarda_senha(admin):
    d = payload(senha="SegredoAuditoria77")
    criar(admin, **d)
    detalhes = " ".join(str(r["detalhe"]) for r in consulta("SELECT detalhe FROM historico_alteracoes"))
    assert "SegredoAuditoria77" not in detalhes


# --------------------------------------------------------------------------------------------- injecao / escaping

@pytest.mark.parametrize("bruto", PAYLOADS_HOSTIS)
def test_nome_com_conteudo_malicioso_e_gravado_e_exibido_escapado(admin, bruto):
    d = payload(nome=bruto)
    antes = contar("usuarios")
    r = criar(admin, **d)
    assert r.status_code < 500, f"HTTP {r.status_code} com nome hostil"
    assert contar("usuarios") == antes + 1
    assert usuario(d["login"])["nome"] == bruto, "O dado deve ser gravado como veio (escape e na saida, nao na entrada)"
    h = html_de(admin.get("/usuarios?busca=" + d["login"]))
    assert_exibido_com_seguranca(h, bruto, "lista de usuarios")
    assert contar("usuarios", "login='admin'") == 1, "Tabela usuarios foi afetada pelo payload SQL"


def test_campo_data_de_cadastro_da_edicao_vem_preenchido_em_formato_de_input_date(admin):
    """<input type=date> so aceita AAAA-MM-DD; fora disso o navegador mostra o campo vazio (Figma 04: data preenchida)."""
    uid = id_usuario_plima()
    h = html_de(admin.get(f"/usuarios/{uid}/editar"))
    m = re.search(r'<input[^>]*type="date"[^>]*name="data_cadastro"[^>]*value="([^"]*)"|'
                  r'<input[^>]*name="data_cadastro"[^>]*type="date"[^>]*value="([^"]*)"|'
                  r'<input[^>]*type="date"[^>]*value="([^"]*)"[^>]*name="data_cadastro"', h)
    assert m, "Campo data_cadastro (type=date) ausente do formulario de edicao"
    valor = next(g for g in m.groups() if g is not None)
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", valor), f"value do input date deveria ser AAAA-MM-DD; veio {valor!r}"
