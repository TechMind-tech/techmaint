"""
helpers.py - utilitarios compartilhados pela suite de QA do TechMaint.

Principio: os testes sao escritos a partir do CONTRATO (SPEC.md), nao do codigo.
Por isso os helpers sao tolerantes com detalhes que a SPEC nao fixa (nome exato dos
campos de formulario, onde o token CSRF aparece, etc.) e, quando algo do contrato
nao existe, falham com uma mensagem dizendo exatamente O QUE faltou.

Conteudo:
    - leitura de HTML (formularios, texto visivel, links)
    - envio de formularios "como o navegador" (defaults + campos preenchidos + CSRF)
    - login por perfil
    - acesso direto ao SQLite temporario para conferir o estado
    - validacao de CNPJ (para gerar CNPJs validos/invalidos nos testes)
"""

from __future__ import annotations

import html as _html
import itertools
import os
import re
import sqlite3
import unicodedata
from html.parser import HTMLParser
from urllib.parse import quote, urlparse

# ---------------------------------------------------------------------------
# Constantes do contrato (SPEC.md)
# ---------------------------------------------------------------------------

#: chave logica -> (login, senha, perfil)
USUARIOS_DEMO = {
    "admin": ("admin", "admin123", "Administrador"),
    "tecnico": ("tecnico", "tecnico123", "Técnico"),
    "gestor": ("gestor", "gestor123", "Gestor"),
    "comum": ("solicitante", "solicitante123", "Usuário Comum"),
    "plima": ("plima", "plima123", "Técnico"),
}
PERFIS = ["admin", "gestor", "tecnico", "comum"]
PERFIL_NOMES = ["Administrador", "Técnico", "Gestor", "Usuário Comum"]

MSG_LOGIN_INVALIDO = "Usuário ou senha inválidos."
MSG_CAMPOS_VAZIOS = "Preencha todos os campos."

_contador = itertools.count(1)


def unico(prefixo: str = "qa") -> str:
    """Texto unico (sem espacos) para nomes/logins nao colidirem entre testes."""
    return f"{prefixo}{os.getpid() % 1000}x{next(_contador)}"


# ---------------------------------------------------------------------------
# Texto / normalizacao
# ---------------------------------------------------------------------------

def normalizar(txt: str) -> str:
    """minusculo, sem acento e so [a-z0-9] -> usado para casar nomes de campos/rotulos."""
    txt = unicodedata.normalize("NFKD", str(txt or "")).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "", txt.lower())


def html_de(resp) -> str:
    return resp.get_data(as_text=True)


class _Texto(HTMLParser):
    """Extrai so o texto visivel (ignora script/style/template)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.partes: list[str] = []
        self._ignorar = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "template", "noscript"):
            self._ignorar += 1
        if tag in ("br", "p", "div", "li", "tr", "td", "th", "h1", "h2", "h3", "option"):
            self.partes.append(" ")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "template", "noscript") and self._ignorar:
            self._ignorar -= 1

    def handle_data(self, data):
        if not self._ignorar:
            self.partes.append(data)


def texto_visivel(html: str) -> str:
    p = _Texto()
    p.feed(html)
    return re.sub(r"\s+", " ", "".join(p.partes)).strip()


def contem(html: str, trecho: str) -> bool:
    """True se `trecho` aparece no texto visivel (insensivel a espacos extras)."""
    return re.sub(r"\s+", " ", trecho).strip() in texto_visivel(html)


def contem_ci(html: str, trecho: str) -> bool:
    return normalizar(trecho) in normalizar(texto_visivel(html))


# ---------------------------------------------------------------------------
# Parser de formularios
# ---------------------------------------------------------------------------

class Campo:
    def __init__(self, tag, nome, tipo, valor, marcado, obrigatorio, desabilitado, somente_leitura, id_):
        self.tag = tag
        self.nome = nome
        self.tipo = tipo
        self.valor = valor
        self.marcado = marcado
        self.obrigatorio = obrigatorio
        self.desabilitado = desabilitado
        self.somente_leitura = somente_leitura
        self.id = id_
        self.rotulo = ""
        # opcoes: lista de dicts {valor, rotulo, selecionado}  (select) ou radios agrupados
        self.opcoes: list[dict] = []

    def __repr__(self):
        return f"<Campo {self.tag}:{self.tipo} name={self.nome!r}>"


class Form:
    def __init__(self, action, method, id_, classe):
        self.action = action or ""
        self.method = (method or "get").lower()
        self.id = id_
        self.classe = classe
        self.campos: list[Campo] = []
        self.botoes: list[dict] = []   # {nome, valor, texto}

    @property
    def nomes(self):
        return [c.nome for c in self.campos if c.nome]

    def campo(self, nome):
        for c in self.campos:
            if c.nome == nome:
                return c
        return None


class _ParserForms(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.forms: list[Form] = []
        self.atual: Form | None = None
        self._select: Campo | None = None
        self._option: dict | None = None
        self._textarea: Campo | None = None
        self._label_for: str | None = None
        self._label_buf: list[str] | None = None
        self._label_ids_inside: list[Campo] = []
        self.rotulos_por_id: dict[str, str] = {}
        self._botao: dict | None = None

    # -- helpers
    @staticmethod
    def _a(attrs):
        return {k: (v if v is not None else "") for k, v in attrs}

    def handle_starttag(self, tag, attrs):
        a = self._a(attrs)
        if tag == "form":
            self.atual = Form(a.get("action"), a.get("method"), a.get("id"), a.get("class"))
            self.forms.append(self.atual)
            return
        if tag == "label":
            self._label_for = a.get("for")
            self._label_buf = []
            self._label_ids_inside = []
            return
        if self.atual is None:
            return
        if tag == "input":
            tipo = (a.get("type") or "text").lower()
            if tipo in ("submit", "button", "image", "reset"):
                self.atual.botoes.append({"nome": a.get("name"), "valor": a.get("value", ""), "texto": a.get("value", "")})
                return
            c = Campo("input", a.get("name"), tipo, a.get("value"), "checked" in a, "required" in a,
                      "disabled" in a, "readonly" in a, a.get("id"))
            if tipo in ("checkbox",) and c.valor is None:
                c.valor = "on"
            if tipo == "radio":
                existente = next((x for x in self.atual.campos if x.nome == c.nome and x.tipo == "radio"), None)
                alvo = existente or c
                alvo.opcoes.append({"valor": c.valor or "on", "rotulo": "", "selecionado": c.marcado, "id": c.id})
                if existente is None:
                    self.atual.campos.append(alvo)
                if self._label_buf is not None:
                    self._label_ids_inside.append(("radio", alvo, len(alvo.opcoes) - 1))
                return
            self.atual.campos.append(c)
            if self._label_buf is not None:
                self._label_ids_inside.append(("campo", c, None))
        elif tag == "select":
            c = Campo("select", a.get("name"), "select", None, False, "required" in a, "disabled" in a, False, a.get("id"))
            self._select = c
            self.atual.campos.append(c)
            if self._label_buf is not None:
                self._label_ids_inside.append(("campo", c, None))
        elif tag == "option" and self._select is not None:
            self._option = {"valor": a.get("value"), "rotulo": "", "selecionado": "selected" in a, "_sem_valor": "value" not in a}
            self._select.opcoes.append(self._option)
        elif tag == "textarea":
            c = Campo("textarea", a.get("name"), "textarea", "", False, "required" in a, "disabled" in a,
                      "readonly" in a, a.get("id"))
            self._textarea = c
            self.atual.campos.append(c)
            if self._label_buf is not None:
                self._label_ids_inside.append(("campo", c, None))
        elif tag == "button":
            self._botao = {"nome": a.get("name"), "valor": a.get("value", ""), "texto": "", "tipo": a.get("type", "submit")}
            self.atual.botoes.append(self._botao)

    def handle_endtag(self, tag):
        if tag == "form":
            self.atual = None
        elif tag == "select":
            self._select = None
            self._option = None
        elif tag == "option":
            self._option = None
        elif tag == "textarea":
            self._textarea = None
        elif tag == "button":
            self._botao = None
        elif tag == "label" and self._label_buf is not None:
            texto = re.sub(r"\s+", " ", "".join(self._label_buf)).strip()
            if self._label_for:
                self.rotulos_por_id[self._label_for] = texto
            for tipo, c, idx in self._label_ids_inside:
                if tipo == "radio":
                    c.opcoes[idx]["rotulo"] = texto
                else:
                    c.rotulo = c.rotulo or texto
            self._label_buf = None
            self._label_for = None
            self._label_ids_inside = []

    def handle_data(self, data):
        if self._label_buf is not None:
            self._label_buf.append(data)
        if self._option is not None:
            self._option["rotulo"] += data
        elif self._textarea is not None:
            self._textarea.valor += data
        elif self._botao is not None:
            self._botao["texto"] += data


def _finalizar(parser: _ParserForms) -> list[Form]:
    for f in parser.forms:
        for c in f.campos:
            for o in c.opcoes:
                o["rotulo"] = re.sub(r"\s+", " ", o["rotulo"]).strip()
                if o.get("_sem_valor") or o.get("valor") is None:
                    o["valor"] = o["rotulo"]
            if c.id and c.id in parser.rotulos_por_id:
                c.rotulo = parser.rotulos_por_id[c.id]
            if c.tipo == "radio":
                for o in c.opcoes:
                    if o.get("id") in parser.rotulos_por_id and not o["rotulo"]:
                        o["rotulo"] = parser.rotulos_por_id[o["id"]]
        for b in f.botoes:
            b["texto"] = re.sub(r"\s+", " ", b.get("texto", "")).strip()
    return parser.forms


def formularios(html: str) -> list[Form]:
    p = _ParserForms()
    p.feed(html)
    return _finalizar(p)


# ---------------------------------------------------------------------------
# Envio de formularios
# ---------------------------------------------------------------------------

class Bruto(str):
    """Valor enviado exatamente como esta, sem mapear para as opcoes de um <select>."""


class ContratoAusente(AssertionError):
    """Algo prometido pela SPEC nao existe (mensagem explica o que)."""


def _resolver_nome(form: Form, aliases: list[str], logico: str) -> str | None:
    nomes = [n for n in form.nomes if n]
    for al in aliases:
        if al in nomes:
            return al
    for al in aliases:
        na = normalizar(al)
        for n in nomes:
            if normalizar(n) == na:
                return n
    for al in aliases:
        na = normalizar(al)
        for n in nomes:
            if na and na in normalizar(n):
                return n
    return None


def _resolver_opcao(campo: Campo, valor):
    if isinstance(valor, Bruto):
        return str(valor)
    v = str(valor)
    for o in campo.opcoes:
        if o["valor"] == v:
            return o["valor"]
    nv = normalizar(v)
    for o in campo.opcoes:
        if normalizar(o["rotulo"]) == nv or normalizar(o["valor"]) == nv:
            return o["valor"]
    for o in campo.opcoes:
        if nv and nv in normalizar(o["rotulo"]):
            return o["valor"]
    # Select dependente (Subgrupo depende do Grupo, SPEC §3.7): o HTML so traz as opcoes do grupo padrao e o JS
    # recarrega via /api/subgrupos. Um navegador enviaria o id escolhido apos o refresh; emulamos resolvendo no banco.
    if campo.nome and "subgrupo" in campo.nome.lower():
        try:
            r = um("SELECT id FROM subgrupos WHERE lower(nome) = lower(?)", v)
            if r is not None:
                return str(r)
        except Exception:
            pass
    opcoes = [f"{o['valor']}={o['rotulo']}" for o in campo.opcoes][:15]
    raise ContratoAusente(
        f"A opcao {v!r} nao existe no campo {campo.nome!r}. Opcoes disponiveis (ate 15): {opcoes}"
    )


def defaults_do_form(form: Form) -> dict:
    """O que o navegador enviaria sem o usuario mexer em nada."""
    dados: dict = {}
    for c in form.campos:
        if not c.nome or c.desabilitado:
            continue
        if c.tipo == "checkbox":
            if c.marcado:
                dados[c.nome] = c.valor
        elif c.tipo == "radio":
            sel = next((o for o in c.opcoes if o["selecionado"]), None)
            if sel:
                dados[c.nome] = sel["valor"]
        elif c.tag == "select":
            sel = next((o for o in c.opcoes if o["selecionado"]), None)
            if sel is None and c.opcoes:
                sel = c.opcoes[0]
            if sel is not None:
                dados[c.nome] = sel["valor"]
        elif c.tipo == "date":
            # Navegador: <input type=date> com valor fora de AAAA-MM-DD e "sanitizado" para vazio.
            v = c.valor or ""
            dados[c.nome] = v if re.fullmatch(r"\d{4}-\d{2}-\d{2}", v) else ""
        else:
            dados[c.nome] = c.valor if c.valor is not None else ""
    return dados


def montar_payload(form: Form, dados: dict, aliases: dict[str, list[str]] | None = None,
                   *, estrito: bool = True) -> dict:
    """Aplica `dados` (chaves logicas) sobre os defaults do formulario."""
    aliases = aliases or {}
    payload = defaults_do_form(form)
    for logico, valor in dados.items():
        cands = aliases.get(logico, [logico])
        nome = _resolver_nome(form, cands, logico)
        if nome is None:
            if estrito:
                raise ContratoAusente(
                    f"Campo '{logico}' nao encontrado no formulario (action={form.action!r}). "
                    f"Procurei por {cands}. Campos presentes: {form.nomes}"
                )
            continue
        campo = form.campo(nome)
        if valor is None:
            payload.pop(nome, None)
        elif campo.tipo == "checkbox":
            if valor:
                payload[nome] = campo.valor or "on"
            else:
                payload.pop(nome, None)
        elif campo.tipo == "radio" or campo.tag == "select":
            payload[nome] = _resolver_opcao(campo, valor)
        else:
            payload[nome] = str(valor)
    return payload


def escolher_form(forms: list[Form], dados: dict, aliases: dict | None = None, *,
                  metodo: str = "post", action_contem: str | None = None) -> Form:
    """Escolhe o formulario da pagina que melhor atende os campos logicos informados."""
    aliases = aliases or {}
    candidatos = [f for f in forms if f.method == metodo]
    if action_contem:
        filtrados = [f for f in candidatos if action_contem in f.action]
        candidatos = filtrados or candidatos
    if not candidatos:
        raise ContratoAusente(f"Nenhum <form method={metodo}> encontrado na pagina (forms: "
                              f"{[(f.method, f.action) for f in forms]}).")
    melhor, melhor_score = None, -1
    for f in candidatos:
        score = sum(1 for k in dados if _resolver_nome(f, aliases.get(k, [k]), k))
        # desempate: forms com mais campos e que tenham csrf
        score = score * 1000 + len(f.campos) + (5 if "csrf_token" in f.nomes else 0)
        if score > melhor_score:
            melhor, melhor_score = f, score
    return melhor


def extrair_csrf(html: str) -> str | None:
    m = re.search(r'name=["\']csrf_token["\'][^>]*value=["\']([^"\']+)["\']', html)
    if not m:
        m = re.search(r'value=["\']([^"\']+)["\'][^>]*name=["\']csrf_token["\']', html)
    if not m:
        m = re.search(r'<meta[^>]+name=["\']csrf[-_]token["\'][^>]+content=["\']([^"\']+)["\']', html)
    if not m:
        m = re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']csrf[-_]token["\']', html)
    return m.group(1) if m else None


def csrf_da_sessao(client) -> str | None:
    try:
        with client.session_transaction() as s:
            for k in ("csrf_token", "_csrf_token", "csrf", "_csrf"):
                if s.get(k):
                    return s[k]
    except Exception:  # noqa: BLE001
        return None
    return None


def obter_csrf(client, url: str | None = None) -> str:
    """Token CSRF valido para a sessao atual do client (tolerante quanto a onde ele fica)."""
    tok = csrf_da_sessao(client)
    if tok:
        return tok
    for u in ([url] if url else []) + ["/login", "/configuracoes", "/menu"]:
        r = client.get(u, follow_redirects=True)
        tok = extrair_csrf(html_de(r)) or csrf_da_sessao(client)
        if tok:
            return tok
    raise ContratoAusente(
        "Nao encontrei o token CSRF: esperado <input type=hidden name=csrf_token value=...> nos formularios "
        "(SPEC §1/§4) ou na sessao."
    )


def post(client, url: str, dados: dict | None = None, *, csrf: bool | str = True, seguir: bool = False,
         **kw):
    """POST cru com CSRF automatico (csrf=False -> sem token; csrf='x' -> token especifico)."""
    dados = dict(dados or {})
    if csrf is True:
        dados.setdefault("csrf_token", obter_csrf(client))
    elif isinstance(csrf, str):
        dados["csrf_token"] = csrf
    return client.post(url, data=dados, follow_redirects=seguir, **kw)


def enviar(client, pagina: str, dados: dict, aliases: dict | None = None, *, post_url: str | None = None,
           seguir: bool = False, action_contem: str | None = None, estrito: bool = True,
           get_seguindo: bool = True, extras: dict | None = None):
    """Abre `pagina` (GET), localiza o formulario, preenche e envia (POST) como um navegador.

    Retorna a resposta do POST. O formulario usado fica em `resp.form_usado`,
    o payload em `resp.payload_enviado`.
    """
    r = client.get(pagina, follow_redirects=get_seguindo)
    if r.status_code != 200:
        raise ContratoAusente(f"GET {pagina} devolveu {r.status_code} (esperado 200 para abrir o formulario).")
    forms = formularios(html_de(r))
    form = escolher_form(forms, dados, aliases, action_contem=action_contem)
    payload = montar_payload(form, dados, aliases, estrito=estrito)
    if extras:
        payload.update(extras)
    if "csrf_token" not in payload:
        payload["csrf_token"] = obter_csrf(client, pagina)
    alvo = post_url or (form.action or pagina)
    resp = client.post(alvo, data=payload, follow_redirects=seguir)
    resp.form_usado = form
    resp.payload_enviado = payload
    return resp


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------

ALIASES_LOGIN = {
    "usuario": ["usuario", "login", "username", "user"],
    "senha": ["senha", "password", "pass"],
    "lembrar": ["lembrar", "lembrar_me", "remember"],
}


def fazer_login(client, usuario: str, senha: str, *, proximo: str | None = None, seguir: bool = False,
                lembrar: bool | None = None):
    url = "/login" + (f"?proximo={quote(proximo, safe='')}" if proximo else "")
    dados = {"usuario": usuario, "senha": senha}
    if lembrar is not None:
        dados["lembrar"] = lembrar
    return enviar(client, url, dados, ALIASES_LOGIN, seguir=seguir, post_url=None,
                  action_contem=None, estrito=False)


def logar_como(client, chave: str):
    login, senha, _ = USUARIOS_DEMO[chave]
    r = fazer_login(client, login, senha, seguir=False)
    if r.status_code not in (302, 303):
        raise AssertionError(
            f"Login de demonstracao '{login}/{senha}' (perfil {chave}) falhou: HTTP {r.status_code}. "
            f"O seed deveria criar esse usuario (SPEC §2). Trecho: {texto_visivel(html_de(r))[:200]!r}"
        )
    return r


# ---------------------------------------------------------------------------
# Banco de dados (SQLite temporario do teste)
# ---------------------------------------------------------------------------

def caminho_db() -> str:
    return os.environ["TECHMAINT_DB"]


def conectar(path: str | None = None) -> sqlite3.Connection:
    con = sqlite3.connect(path or caminho_db(), timeout=15)
    con.row_factory = sqlite3.Row
    return con


def consulta(sql: str, *params, path: str | None = None) -> list[dict]:
    con = conectar(path)
    try:
        return [dict(r) for r in con.execute(sql, params).fetchall()]
    except sqlite3.OperationalError as e:
        raise ContratoAusente(f"Consulta no banco falhou ({e}). SQL: {sql}. "
                              f"Confira schema.sql contra a SPEC §3.") from e
    finally:
        con.close()


def um(sql: str, *params, path: str | None = None):
    """Primeira coluna da primeira linha (ou None)."""
    con = conectar(path)
    try:
        row = con.execute(sql, params).fetchone()
        return None if row is None else row[0]
    except sqlite3.OperationalError as e:
        raise ContratoAusente(f"Consulta no banco falhou ({e}). SQL: {sql}. "
                              f"Confira schema.sql contra a SPEC §3.") from e
    finally:
        con.close()


def linha(sql: str, *params, path: str | None = None) -> dict | None:
    r = consulta(sql, *params, path=path)
    return r[0] if r else None


def executa(sql: str, *params, path: str | None = None) -> int:
    con = conectar(path)
    try:
        cur = con.execute(sql, params)
        con.commit()
        return cur.lastrowid
    finally:
        con.close()


def contar(tabela: str, onde: str = "1=1", *params) -> int:
    return um(f"SELECT COUNT(*) FROM {tabela} WHERE {onde}", *params)


def tabelas(path: str | None = None) -> list[str]:
    return [r["name"] for r in consulta("SELECT name FROM sqlite_master WHERE type='table'", path=path)]


def snapshot(tabs: list[str]) -> dict:
    """Contagem de linhas por tabela, para provar que 'nada mudou'."""
    return {t: contar(t) for t in tabs}


def colunas(tabela: str) -> list[str]:
    return [r["name"] for r in consulta(f"PRAGMA table_info({tabela})")]


def coluna(tabela: str, *candidatas: str) -> str:
    """Primeira coluna existente entre as candidatas (tolera diferencas de nome nao fixadas na SPEC)."""
    cols = colunas(tabela)
    for c in candidatas:
        if c in cols:
            return c
    raise ContratoAusente(f"Tabela {tabela!r} nao tem nenhuma das colunas {candidatas}. Colunas: {cols}")


def id_perfil(nome: str) -> int:
    col = coluna("perfis", "nome", "nome_perfil", "perfil")
    v = um(f"SELECT id FROM perfis WHERE {col} = ?", nome)
    if v is None:
        raise ContratoAusente(f"Perfil {nome!r} nao existe na tabela perfis (SPEC §2).")
    return v


def criar_usuario_db(login: str, senha: str, perfil: str = "Usuário Comum", *, ativo: int = 1,
                     nome: str | None = None, depto: str | None = "Produção") -> int:
    """Cria usuario direto no banco (sem passar pela UI) com hash real do Werkzeug."""
    from werkzeug.security import generate_password_hash

    con = conectar()
    try:
        id_depto = None
        if depto:
            r = con.execute("SELECT id FROM departamentos WHERE nome = ?", (depto,)).fetchone()
            id_depto = r[0] if r else None
        cur = con.execute(
            "INSERT INTO usuarios (nome, login, senha_hash, email, ativo, data_cadastro, id_departamento) "
            "VALUES (?,?,?,?,?,datetime('now'),?)",
            (nome or f"Usuario {login}", login, generate_password_hash(senha), f"{login}@teste.com", ativo, id_depto),
        )
        uid = cur.lastrowid
        con.execute("INSERT INTO usuarios_perfis (id_usuario, id_perfil) VALUES (?,?)", (uid, id_perfil(perfil)))
        con.commit()
        return uid
    except sqlite3.OperationalError as e:
        raise ContratoAusente(f"Nao consegui inserir usuario de teste ({e}); confira colunas de usuarios/usuarios_perfis (SPEC §3).") from e
    finally:
        con.close()


def id_usuario(login: str) -> int | None:
    return um("SELECT id FROM usuarios WHERE lower(login) = lower(?)", login)


# ---------------------------------------------------------------------------
# CNPJ
# ---------------------------------------------------------------------------

def _dv_cnpj(base: str) -> str:
    pesos1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    pesos2 = [6] + pesos1
    d1 = sum(int(a) * b for a, b in zip(base, pesos1)) % 11
    d1 = 0 if d1 < 2 else 11 - d1
    d2 = sum(int(a) * b for a, b in zip(base + str(d1), pesos2)) % 11
    d2 = 0 if d2 < 2 else 11 - d2
    return f"{d1}{d2}"


def cnpj_valido(cnpj: str) -> bool:
    n = re.sub(r"\D", "", cnpj or "")
    return len(n) == 14 and len(set(n)) > 1 and n[12:] == _dv_cnpj(n[:12])


_seq_cnpj = itertools.count(1000)


def gerar_cnpj(formatado: bool = True) -> str:
    """CNPJ matematicamente valido e unico dentro da execucao."""
    base = f"{(os.getpid() * 7919 + next(_seq_cnpj)) % 100000000:08d}0001"
    n = base + _dv_cnpj(base)
    return f"{n[:2]}.{n[2:5]}.{n[5:8]}/{n[8:12]}-{n[12:]}" if formatado else n


def cnpj_invalido(formatado: bool = True) -> str:
    """CNPJ com formato ok mas digito verificador errado."""
    n = gerar_cnpj(False)
    dv = n[12:]
    ruim = f"{(int(dv[0]) + 1) % 10}{dv[1]}"
    n = n[:12] + ruim
    return f"{n[:2]}.{n[2:5]}.{n[5:8]}/{n[8:12]}-{n[12:]}" if formatado else n


def so_digitos(s) -> str:
    return re.sub(r"\D", "", str(s or ""))


# ---------------------------------------------------------------------------
# Verificacoes reutilizaveis
# ---------------------------------------------------------------------------

STATUS_REDIRECT = (301, 302, 303, 307, 308)
STATUS_ERRO_FORM = (200, 400, 422)


def local(resp) -> str:
    return resp.headers.get("Location", "")


def e_redirect_login(resp) -> bool:
    return resp.status_code in STATUS_REDIRECT and urlparse(local(resp)).path.rstrip("/") == "/login"


def assert_sem_500(resp, contexto: str = ""):
    assert resp.status_code < 500, (
        f"Erro de servidor {resp.status_code} {contexto}. Trecho: {texto_visivel(html_de(resp))[:200]!r}"
    )


def assert_rejeitado(resp, contexto: str = ""):
    """O servidor rejeitou o formulario (re-render com erro ou 400/422) e NAO foi sucesso/redirect."""
    assert resp.status_code in STATUS_ERRO_FORM, (
        f"{contexto}: esperado re-render com erros (200/400/422) mas veio HTTP {resp.status_code} "
        f"(Location={local(resp)!r}). O dado invalido pode ter sido ACEITO."
    )


def assert_sucesso_post(resp, contexto: str = ""):
    """POST/Redirect/GET: sucesso = redirect (nao 200 com formulario de volta)."""
    assert resp.status_code in STATUS_REDIRECT, (
        f"{contexto}: esperado redirect (POST/Redirect/GET, SPEC §1) mas veio HTTP {resp.status_code}. "
        f"Trecho: {texto_visivel(html_de(resp))[:300]!r}"
    )


def assert_negado(resp, contexto: str = ""):
    """Acesso negado por permissao: 403 (SPEC §2). Redirect para login tambem vale se nao logado."""
    assert resp.status_code == 403, (
        f"{contexto}: esperado 403 (sem permissao, SPEC §2) mas veio HTTP {resp.status_code} "
        f"(Location={local(resp)!r})."
    )


def escapado(html: str, bruto: str) -> bool:
    """O texto `bruto` (com <, >, ', ") aparece escapado e NUNCA cru no HTML."""
    if bruto in html:
        return False
    return _html.escape(bruto) in html or _html.escape(bruto, quote=False) in html


def numero(txt) -> float:
    """'R$ 1.390,00' -> 1390.0 ; '15,50' -> 15.5 ; 12 -> 12.0"""
    if isinstance(txt, (int, float)):
        return float(txt)
    s = re.sub(r"[^\d,.\-]", "", str(txt))
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    return float(s) if s not in ("", "-") else 0.0


# Cargas de teste para injecao/XSS/SQL (usadas por varios modulos)
PAYLOADS_HOSTIS = [
    "<script>alert('xss')</script>",
    "\"><img src=x onerror=alert(1)>",
    "'; DROP TABLE usuarios; --",
    "Robert'); DROP TABLE pecas;--",
    "{{7*7}}",
    "${7*7}",
    "%s %d %(x)s",
    "<b>negrito</b>",
    "a' OR '1'='1",
]


def assert_exibido_com_seguranca(html: str, bruto: str, contexto: str = ""):
    """O texto hostil aparece como TEXTO (escapado) e nunca como marcacao executavel."""
    if any(ch in bruto for ch in "<>\"'&"):
        assert bruto not in html, f"{contexto}: '{bruto}' apareceu SEM escape no HTML (XSS)"
        e = _html.escape(bruto)
        variantes = {e, _html.escape(bruto, quote=False), e.replace("&#x27;", "&#39;"),
                     e.replace("&quot;", "&#34;"), e.replace("&quot;", "&#34;").replace("&#x27;", "&#39;"),
                     e.replace("&#x27;", "&#39;").replace("&quot;", '"')}  # Jinja usa &#34;/&#39;
        assert any(v in html for v in variantes), \
            f"{contexto}: '{bruto}' nem aparece escapado (dado perdido/truncado?)"
    else:
        assert bruto in html, f"{contexto}: '{bruto}' deveria ser exibido literalmente (nao interpretado)"


def lista_de(html: str) -> str:
    """So o miolo de dados da pagina (tabelas/cartoes de lista), sem faixa de alertas, flash, menu e cabecalho.
    Evita falso positivo quando '#1624' aparece num alerta ('Pedido #1624 de prioridade Alta...') ou no flash."""
    import re as _re
    limpo = _re.sub(r"<(aside|nav|header|dialog|script)\b.*?</\1>", "", html, flags=_re.S | _re.I)
    limpo = _re.sub(r"<[^>]+class=\"[^\"]*(?:aviso|alerta|flash|toast)[^\"]*\"[^>]*>.*?</(?:div|section|ul|p)>", "", limpo,
                    flags=_re.S | _re.I)
    tabelas = _re.findall(r"<table\b.*?</table>", limpo, flags=_re.S | _re.I)
    return "\n".join(tabelas) if tabelas else limpo
