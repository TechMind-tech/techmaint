"""
Configuracoes do usuario (perfil, senha, idioma, tema) e alertas do sino do cabecalho.

Rastreabilidade: Manual 6.2 (Configuracoes/Usuario: Perfil, Senha, Idioma, Tema; Alterar dados, Sair do sistema),
SPEC §2 (todos os perfis acessam), §3 regra 5 (alertas: estoque baixo, OS atrasada > 7 dias, pedido Alta sem OS),
§4 (/configuracoes; idiomas en/es desabilitados 'em breve'; temas claro|escuro; `alertas` em todos os templates), §5 (tema escuro).
"""

import datetime
import re

import pytest
from werkzeug.security import check_password_hash

from fluxo_util import abrir_os, add_peca, criar_pedido, fechar_os, os_row, peca_id
from helpers import (Bruto, assert_rejeitado, assert_sucesso_post, contar, enviar, executa, fazer_login, formularios, html_de, linha,
                     post, texto_visivel, unico, um, criar_usuario_db, PAYLOADS_HOSTIS, assert_exibido_com_seguranca)

ALIASES = {
    "nome": ["nome"], "email": ["email"], "senha_atual": ["senha_atual", "atual"], "nova": ["nova_senha", "senha_nova", "nova"],
    "confirmar": ["confirmar_senha", "confirmacao", "confirmar", "repetir"], "idioma": ["idioma"], "tema": ["tema"],
}


# --------------------------------------------------------------------------------------------- configuracoes

@pytest.mark.parametrize("perfil", ["admin", "gestor", "tecnico", "comum"])
def test_todos_os_perfis_acessam_configuracoes(cliente_de, perfil):
    r = cliente_de(perfil).get("/configuracoes")
    assert r.status_code == 200
    t = texto_visivel(html_de(r))
    for trecho in ("Configurações", "Perfil", "Senha", "Idioma", "Tema", "Sair"):
        assert trecho.lower() in t.lower(), f"{perfil}: {trecho!r} ausente (Manual 6.2)"


def test_configuracoes_mostra_dados_do_usuario(tecnico):
    h = html_de(tecnico.get("/configuracoes"))
    assert "Maria Técnica" in h and "tecnico@techmaint.com" in h


def test_idiomas_en_e_es_desabilitados_em_breve(admin):
    h = html_de(admin.get("/configuracoes"))
    forms = formularios(h)
    campo = next((c for f in forms for c in f.campos if c.nome == "idioma"), None)
    assert campo, "Seletor de idioma ausente"
    rot = {o["valor"]: o["rotulo"] for o in campo.opcoes}
    assert "pt-BR" in rot
    assert "em breve" in texto_visivel(h).lower(), "en/es devem aparecer como 'em breve' (SPEC §4)"
    assert re.search(r"disabled", h), "Opcoes en/es devem estar desabilitadas"


def test_atualizar_nome_e_email(tecnico):
    r = enviar(tecnico, "/configuracoes", {"nome": "Maria T. Atualizada", "email": "maria.nova@techmaint.com"}, ALIASES,
               estrito=False, action_contem=None)
    assert r.status_code in (302, 303, 200)
    u = linha("SELECT * FROM usuarios WHERE login='tecnico'")
    assert u["nome"] == "Maria T. Atualizada" and u["email"] == "maria.nova@techmaint.com"
    assert "Maria T. Atualizada" in texto_visivel(html_de(tecnico.get("/menu"))), "Cabecalho deve refletir o novo nome"


@pytest.mark.parametrize("campo,valor", [("email", "invalido"), ("email", "a@"), ("nome", ""), ("nome", "   ")])
def test_validacoes_do_perfil(tecnico, campo, valor):
    antes = linha("SELECT nome, email FROM usuarios WHERE login='tecnico'")
    r = enviar(tecnico, "/configuracoes", {campo: valor}, ALIASES, estrito=False)
    assert r.status_code in (200, 400, 422), f"HTTP {r.status_code}"
    assert linha("SELECT nome, email FROM usuarios WHERE login='tecnico'") == antes


def test_nome_hostil_no_perfil_e_escapado_no_cabecalho(tecnico):
    bruto = "<img src=x onerror=alert(1)>"
    enviar(tecnico, "/configuracoes", {"nome": bruto}, ALIASES, estrito=False)
    for p in ("/menu", "/dashboard", "/configuracoes"):
        h = html_de(tecnico.get(p))
        assert bruto not in h, f"Nome do usuario sem escape no cabecalho de {p}"


def test_trocar_senha(app):
    login = unico("cfg")
    criar_usuario_db(login, "senhaAntiga1", "Técnico")
    c = app.test_client()
    fazer_login(c, login, "senhaAntiga1")
    r = enviar(c, "/configuracoes", {"senha_atual": "senhaAntiga1", "nova": "senhaNova123", "confirmar": "senhaNova123"}, ALIASES, estrito=False,
               action_contem=None)
    assert r.status_code in (302, 303, 200)
    assert check_password_hash(um("SELECT senha_hash FROM usuarios WHERE login=?", login), "senhaNova123")
    assert fazer_login(app.test_client(), login, "senhaNova123").status_code in (302, 303)
    assert fazer_login(app.test_client(), login, "senhaAntiga1").status_code not in (302, 303)


@pytest.mark.parametrize("nome,dados", [
    ("senha_atual_errada", dict(senha_atual="errada", nova="senhaNova123", confirmar="senhaNova123")),
    ("senha_atual_vazia", dict(senha_atual="", nova="senhaNova123", confirmar="senhaNova123")),
    ("nova_curta", dict(senha_atual="senhaAntiga1", nova="curta", confirmar="curta")),
    ("confirmacao_diferente", dict(senha_atual="senhaAntiga1", nova="senhaNova123", confirmar="outraCoisa99")),
    ("nova_igual_a_atual", dict(senha_atual="senhaAntiga1", nova="senhaAntiga1", confirmar="senhaAntiga1")),
])
def test_validacoes_de_troca_de_senha(app, nome, dados):
    login = unico("cfv")
    criar_usuario_db(login, "senhaAntiga1", "Técnico")
    c = app.test_client()
    fazer_login(c, login, "senhaAntiga1")
    antes = um("SELECT senha_hash FROM usuarios WHERE login=?", login)
    r = enviar(c, "/configuracoes", dados, ALIASES, estrito=False)
    assert r.status_code < 500
    if nome == "nova_igual_a_atual":
        return  # decisao de contrato: aceitar ou rejeitar; so exige nao quebrar
    assert um("SELECT senha_hash FROM usuarios WHERE login=?", login) == antes, f"{nome}: a senha foi trocada indevidamente"
    assert "senhaAntiga1" not in html_de(r) and "senhaNova123" not in html_de(r), "senha ecoada no HTML"


def test_trocar_senha_sem_informar_a_atual_nao_funciona(tecnico):
    antes = um("SELECT senha_hash FROM usuarios WHERE login='tecnico'")
    post(tecnico, "/configuracoes", {"nova_senha": "hackeada123", "confirmar_senha": "hackeada123"})
    assert um("SELECT senha_hash FROM usuarios WHERE login='tecnico'") == antes


def test_tema_escuro_persiste_e_aplica_data_theme(admin):
    h0 = html_de(admin.get("/menu"))
    assert re.search(r'<html[^>]*data-theme="(claro|light)"', h0), f"Tema padrao claro via data-theme no <html>: {h0[:200]!r}"
    enviar(admin, "/configuracoes", {"tema": "escuro"}, ALIASES, estrito=False)
    assert um("SELECT tema FROM usuarios WHERE login='admin'") == "escuro"
    for p in ("/menu", "/dashboard", "/pedidos", "/configuracoes"):
        assert re.search(r'<html[^>]*data-theme="(escuro|dark)"', html_de(admin.get(p))), f"tema escuro nao aplicado em {p}"


def test_tema_e_por_usuario(app):
    a, b = app.test_client(), app.test_client()
    from helpers import logar_como
    logar_como(a, "admin")
    logar_como(b, "tecnico")
    enviar(a, "/configuracoes", {"tema": "escuro"}, ALIASES, estrito=False)
    assert re.search(r'data-theme="(claro|light)"', html_de(b.get("/menu"))), "Tema de um usuario vazou para outro"


def test_tema_persiste_entre_logins(app):
    from helpers import logar_como
    a = app.test_client()
    logar_como(a, "gestor")
    enviar(a, "/configuracoes", {"tema": "escuro"}, ALIASES, estrito=False)
    post(a, "/logout")
    a2 = app.test_client()
    logar_como(a2, "gestor")
    assert re.search(r'data-theme="(escuro|dark)"', html_de(a2.get("/menu")))


@pytest.mark.parametrize("valor", ["roxo", "", "<script>", "claro; DROP TABLE usuarios"])
def test_tema_invalido_e_rejeitado(admin, valor):
    r = enviar(admin, "/configuracoes", {"tema": Bruto(valor)}, ALIASES, estrito=False)
    assert r.status_code < 500
    assert um("SELECT tema FROM usuarios WHERE login='admin'") in ("claro", "escuro")
    assert um("SELECT tema FROM usuarios WHERE login='admin'") != valor


@pytest.mark.parametrize("idioma", ["en", "es", "xx", ""])
def test_idioma_nao_funcional_nao_e_aceito(admin, idioma):
    enviar(admin, "/configuracoes", {"idioma": Bruto(idioma)}, ALIASES, estrito=False)
    assert um("SELECT idioma FROM usuarios WHERE login='admin'") == "pt-BR", f"idioma {idioma!r} deveria ser rejeitado (so pt-BR funcional)"


def test_tela_de_login_ignora_tema_de_usuario(anonimo):
    assert anonimo.get("/login").status_code == 200


# --------------------------------------------------------------------------------------------- alertas (sino)

def _alertas(c, pagina="/menu"):
    """Texto so do painel do sino (nao do flash nem do corpo da pagina, que podem citar a mesma peca/pedido)."""
    h = html_de(c.get(pagina))
    m = re.search(r'suspenso__titulo">Alertas</p>(.*?)</details>', h, re.S)
    assert m, "Painel do sino de alertas (cabecalho) nao encontrado"
    return texto_visivel(m.group(1))


def test_sino_do_cabecalho_existe_com_contador(admin):
    h = html_de(admin.get("/menu"))
    assert re.search(r'(aria-label|title)="[^"]*(alerta|notifica)', h, re.I) or "bell" in h.lower() or "sino" in h.lower(), \
        "Sino de alertas no cabecalho (Figma 03, SPEC §3.5) nao encontrado"


def test_alerta_de_estoque_baixo(admin):
    assert "Filtro de Ar" in _alertas(admin), "Peca com estoque abaixo do minimo deve aparecer nos alertas (SPEC §3.5)"


def test_alerta_some_quando_o_estoque_e_reposto(admin):
    from fluxo_util import ALIASES_ESTOQUE
    enviar(admin, "/estoque", dict(tipo="Entrada", peca="Filtro de Ar", quantidade="20", valor="32", documento="Nota Fiscal", numero="NF-9"),
           ALIASES_ESTOQUE, estrito=False)
    assert "Filtro de Ar" not in _alertas(admin), "Alerta de estoque baixo persistiu depois da reposicao"


def test_alerta_aparece_quando_uma_baixa_deixa_a_peca_abaixo_do_minimo(admin, tecnico):
    pid_ped = criar_pedido(admin)
    _, oid = abrir_os(tecnico, pid_ped)
    assert "Correia V" not in _alertas(admin)
    add_peca(tecnico, oid, "Correia V", "199")     # 200 -> 1 (< minimo)
    assert "Correia V" in _alertas(admin), "Peca cujo saldo caiu abaixo do minimo deve entrar nos alertas"


def test_alerta_de_pedido_alta_sem_os(admin, tecnico):
    pid = criar_pedido(admin, prioridade="Alta", descricao="Urgente QA")
    assert f"#{pid}" in _alertas(admin), "Pedido Aberto de prioridade Alta sem OS deve alertar (SPEC §3.5)"
    abrir_os(tecnico, pid)
    assert f"#{pid}" not in _alertas(admin), "Alerta deve sumir depois que a OS e aberta"


def test_pedido_de_prioridade_baixa_nao_gera_alerta(admin):
    pid = criar_pedido(admin, prioridade="Baixa")
    assert f"#{pid}" not in _alertas(admin)


def test_alerta_de_os_atrasada(admin):
    atras = (datetime.date.today() - datetime.timedelta(days=10)).isoformat() + " 08:00:00"
    executa("UPDATE ordens_servico SET data_abertura=? WHERE id=10234", atras)
    assert "OS-10234" in _alertas(admin), "OS aberta ha mais de 7 dias sem fechar deve alertar (SPEC §3.5)"


@pytest.mark.parametrize("dias,deve_alertar", [(6, False), (7, False), (8, True), (9, True)])
def test_limite_de_os_atrasada_e_mais_de_7_dias(admin, dias, deve_alertar):
    """SPEC §3.5: 'aberta ha MAIS de 7 dias' -> 7 dias exatos ainda nao alerta; 8 alerta."""
    data = (datetime.date.today() - datetime.timedelta(days=dias)).isoformat() + " 08:00:00"
    executa("UPDATE ordens_servico SET data_abertura=? WHERE id=10234", data)
    assert ("OS-10234" in _alertas(admin)) == deve_alertar, f"OS aberta ha {dias} dias: alerta deveria ser {deve_alertar}"


def test_os_recente_nao_e_atrasada(admin):
    recente = (datetime.date.today() - datetime.timedelta(days=3)).isoformat() + " 08:00:00"
    executa("UPDATE ordens_servico SET data_abertura=? WHERE id=10234", recente)
    assert "OS-10234" not in _alertas(admin)


def test_os_fechada_nao_e_atrasada(admin, tecnico):
    atras = (datetime.date.today() - datetime.timedelta(days=30)).isoformat() + " 08:00:00"
    executa("UPDATE ordens_servico SET data_abertura=? WHERE id=10234", atras)
    assert "OS-10234" in _alertas(admin)
    fechar_os(tecnico, 10234)
    assert "OS-10234" not in _alertas(admin)


def test_alertas_levam_a_uma_url_valida(admin):
    h = html_de(admin.get("/menu"))
    links = set(re.findall(r'href="(/(?:pecas|os|pedidos)[^"]*)"', h))
    assert links, "Itens de alerta deveriam ter link (SPEC §4: itens com url)"
    for u in links:
        assert admin.get(u, follow_redirects=True).status_code == 200, f"Link de alerta quebrado: {u}"


def test_alertas_aparecem_em_todas_as_paginas(admin):
    for p in ("/menu", "/dashboard", "/pecas", "/pedidos", "/os", "/configuracoes"):
        assert "Filtro de Ar" in _alertas(admin, p), f"Sino/alertas ausentes em {p}"


def test_usuario_comum_nao_ve_alertas_de_estoque(comum):
    assert "Filtro de Ar" not in _alertas(comum), "Alerta de estoque nao e do escopo do Usuario Comum (sem acesso a estoque)"


def test_alerta_com_nome_hostil_e_escapado(admin):
    executa("UPDATE pecas SET nome='<img src=x onerror=alert(1)>' WHERE nome='Filtro de Ar'")
    h = html_de(admin.get("/menu"))
    assert "<img src=x onerror=alert(1)>" not in h
