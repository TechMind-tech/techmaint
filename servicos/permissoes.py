"""
permissoes.py
-------------
Quem pode fazer o que. A matriz abaixo e a "fonte da verdade" (SPEC secao 2);
o init_db() copia as chaves para as tabelas `permissoes` / `perfis_permissoes`.

Como usar numa rota:

    @bp.route("/equipamentos")
    @permissao("equipamentos.ver")
    def listar(): ...

- Nao logado          -> redireciona para /login?proximo=...   (302)
- Logado sem permissao -> pagina 403
"""

from functools import wraps

from flask import abort, g

ADM = "Administrador"
TEC = "Técnico"
GES = "Gestor"
COM = "Usuário Comum"

# Ordem usada nos cards da tela de usuarios (Figma).
PERFIS = {
    ADM: "Acesso total ao sistema, inclusive usuários e perfis.",
    TEC: "Acesso a equipamentos, peças, OS e movimentação de estoque.",
    GES: "Acompanha, aprova pedidos e consulta relatórios.",
    COM: "Abre pedidos de manutenção e acompanha o status das próprias OS.",
}

TODOS = {ADM, TEC, GES, COM}

# chave da permissao -> perfis que possuem
MATRIZ = {
    "dashboard.ver":        {ADM, GES, TEC},
    "dashboard.exportar":   {ADM, GES},
    "relatorios.exportar":  {ADM, GES},
    "financeiro.ver":       {ADM, GES},          # valores em R$ no dashboard/relatorios
    "usuarios.gerir":       {ADM},
    "equipamentos.ver":     {ADM, GES, TEC},
    "equipamentos.editar":  {ADM, TEC},
    "pecas.ver":            {ADM, GES, TEC},
    "pecas.editar":         {ADM, TEC},
    "fornecedores.ver":     {ADM, GES, TEC},
    "fornecedores.editar":  {ADM},
    "prestadores.ver":      {ADM, GES, TEC},
    "prestadores.editar":   {ADM},
    "departamentos.ver":    {ADM, GES, TEC},
    "departamentos.editar": {ADM},
    "pedidos.ver":          TODOS,               # Usuario Comum ve so os proprios
    "pedidos.criar":        TODOS,
    "pedidos.editar":       {ADM, GES, TEC},
    "pedidos.cancelar":     {ADM, GES},
    "pedidos.aprovar":      {ADM, GES},
    "pedidos.abrir_os":     {ADM, TEC},
    "os.ver":               TODOS,               # Usuario Comum ve so as proprias
    "os.gerir":             {ADM, TEC},
    "os.fechar":            {ADM, GES, TEC},
    "os.reabrir":           {ADM},
    "estoque.ver":          {ADM, GES, TEC},
    "estoque.editar":       {ADM, TEC},
    "relatorios.ver":       TODOS,               # a aba "Ordens" e liberada para todos
    "configuracoes.ver":    TODOS,
}

# Abas de relatorio -> permissao extra exigida
ABAS_RELATORIO = {
    "os": None,                       # todos (Usuario Comum so ve as proprias OS)
    "estoque": "estoque.ver",
    "fornecedores": "fornecedores.ver",
    "financeiro": "financeiro.ver",
}

# Menu lateral: (secao, [(chave, rotulo, endpoint, icone, permissao)])
MENU = [
    ("Principal", [
        ("dashboard", "Dashboard", "painel.dashboard", "layout-dashboard", "dashboard.ver"),
    ]),
    ("Cadastros", [
        ("usuarios", "Usuários e Perfis", "usuarios.listar", "users", "usuarios.gerir"),
        ("equipamentos", "Equipamentos", "equipamentos.listar", "cpu", "equipamentos.ver"),
        ("pecas", "Peças", "pecas.listar", "wrench", "pecas.ver"),
        ("fornecedores", "Fornecedores", "fornecedores.listar", "building", "fornecedores.ver"),
        ("prestadores", "Prestadores de Serviço", "prestadores.listar", "briefcase-user", "prestadores.ver"),
        ("departamentos", "Departamentos", "departamentos.listar", "briefcase", "departamentos.ver"),
    ]),
    ("Processos", [
        ("pedidos", "Pedidos de Manutenção", "pedidos.listar", "clipboard-list", "pedidos.ver"),
        ("os", "Ordens de Serviço", "ordens.listar", "settings", "os.ver"),
        ("estoque", "Movim. de Estoque", "estoque.listar", "boxes", "estoque.ver"),
    ]),
    ("Análise", [
        ("relatorios", "Relatórios", "relatorios.pagina", "bar-chart", "relatorios.ver"),
    ]),
    ("Conta", [
        ("configuracoes", "Configurações", "configuracoes.pagina", "settings-2", "configuracoes.ver"),
    ]),
]

# Cards da tela /menu (Manual secao 5). `itens` = chaves do MENU que o card agrupa.
CARDS = [
    ("cadastros", "Cadastros", "Usuários, equipamentos, peças, fornecedores e departamentos.", "users",
     ["usuarios", "equipamentos", "pecas", "fornecedores", "prestadores", "departamentos"]),
    ("os", "Ordens de Serviço", "Abra, acompanhe e feche ordens de serviço.", "settings", ["os"]),
    ("estoque", "Estoque", "Entradas e saídas de peças e materiais.", "boxes", ["estoque"]),
    ("pedidos", "Pedidos de Manutenção", "Solicite e acompanhe manutenções.", "clipboard-list", ["pedidos"]),
    ("relatorios", "Relatórios", "Análises detalhadas e exportação de dados.", "bar-chart", ["relatorios"]),
    ("dashboard", "Dashboard", "Indicadores e gráficos gerenciais.", "layout-dashboard", ["dashboard"]),
]


def perfis_do_usuario(usuario=None):
    usuario = usuario if usuario is not None else getattr(g, "usuario", None)
    return (usuario or {}).get("perfis", [])


def pode(chave, usuario=None):
    """True se algum perfil do usuario tem a permissao `chave`."""
    permitidos = MATRIZ.get(chave, set())
    return any(p in permitidos for p in perfis_do_usuario(usuario))


def permissoes_do_usuario(usuario=None):
    return sorted(c for c in MATRIZ if pode(c, usuario))


def aba_permitida(aba, usuario=None):
    if aba not in ABAS_RELATORIO:
        return False
    extra = ABAS_RELATORIO[aba]
    return pode("relatorios.ver", usuario) and (extra is None or pode(extra, usuario))


def e_perfil(*nomes, usuario=None):
    return any(p in nomes for p in perfis_do_usuario(usuario))


def permissao(chave):
    """Decorator: exige a permissao `chave` (o login ja foi exigido pelo before_request)."""
    def decorador(funcao):
        @wraps(funcao)
        def interna(*args, **kwargs):
            if getattr(g, "usuario", None) is None or not pode(chave):
                abort(403)
            return funcao(*args, **kwargs)
        return interna
    return decorador


def menu_do_usuario(endpoint_atual=None):
    """Menu ja filtrado pelo perfil, no formato do contrato (secao -> itens)."""
    from flask import url_for
    bp_atual = (endpoint_atual or "").split(".")[0]
    resultado = []
    for secao, itens in MENU:
        visiveis = []
        for chave, rotulo, endpoint, icone, perm in itens:
            if pode(perm):
                visiveis.append({
                    "chave": chave, "rotulo": rotulo, "endpoint": endpoint, "icone": icone,
                    "url": url_for(endpoint), "ativo": bp_atual == endpoint.split(".")[0],
                })
        if visiveis:
            resultado.append({"secao": secao, "itens": visiveis})
    return resultado
