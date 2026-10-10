"""
formularios.py
--------------
Leitura tolerante de formularios e montagem de `erros` / `valores`.

Os nomes "canonicos" dos campos sao os nomes das colunas do banco (ex.: `id_perfil`).
Para o backend e o front-end nao dependerem de combinar cada nome ao pixel, aceitamos
variacoes comuns (`perfil_id`, `perfil`...) e devolvemos `erros` e `valores` tambem sob
essas variacoes. Veja DEV_NOTAS_CONTRATO.md.
"""

CAMPOS_SECRETOS = {"senha", "nova_senha", "confirmar_senha", "senha_atual", "csrf_token",
                   "senha_nova", "confirmar", "confirmacao", "confirma_senha"}

# canonico -> variacoes aceitas (alem das regras automaticas id_x -> x_id, x)
ALIASES = {
    "id_perfil": ["perfil_id", "perfil"],
    "id_departamento": ["departamento_id", "departamento", "id_depto", "depto"],
    "id_grupo": ["grupo_id", "grupo"],
    "id_subgrupo": ["subgrupo_id", "subgrupo", "id_sub_grupo"],
    "id_equipamento": ["equipamento_id", "equipamento", "equipamento_vinculado"],
    "id_peca": ["peca_id", "peca", "descricao_peca", "descricao"],
    "id_pedido": ["pedido_id", "pedido", "pedido_vinculado"],
    "id_tecnico": ["tecnico_id", "tecnico", "tecnico_responsavel"],
    "id_prestador": ["prestador_id", "prestador"],
    "responsavel_id": ["id_responsavel", "responsavel_usuario"],
    "responsavel_nome": ["responsavel"],
    "valor_unitario": ["valor", "valor_unit", "preco", "preco_unitario"],
    "qtde_estoque": ["quantidade_estoque", "qtd_estoque", "estoque", "quantidade_em_estoque", "qtde"],
    "valor_servico": ["valor", "valor_do_servico"],
    "descricao_servico": ["descricao", "servico"],
    "horas_trabalhadas": ["horas", "horas_trab"],
    "valor_residual_padrao": ["valor_residual", "residual"],
    "vida_util_meses": ["vida_util", "vida_util_em_meses"],
    "descricao_problema": ["descricao", "problema", "descricao_do_problema"],
    "documento_origem": ["tipo_documento", "tipo_de_documento", "documento"],
    "numero_documento": ["n_documento", "numero_do_documento", "num_documento", "nr_documento"],
    "codigo_item": ["codigo_do_item", "codigo"],
    "razao_social": ["razao"],
    "inscricao_estadual": ["ie"],
    "nova_quantidade": ["qtde_estoque", "quantidade_nova", "saldo"],
    "nova_senha": ["senha_nova", "nova", "senha"],
    "confirmar_senha": ["confirmacao", "confirma_senha", "confirmar", "repetir_senha", "nova_senha2",
                        "confirmar_nova_senha"],
    "tipo": ["tipo_movimento", "tipo_de_movimento"],
    "ativo": ["status", "usuario_ativo"],
    "nome": ["nome_completo"],
    "data": ["data_apontamento"],
}


def variacoes(nome):
    """Todos os nomes sob os quais o campo canonico `nome` pode chegar."""
    lista = [nome] + ALIASES.get(nome, [])
    if nome.startswith("id_"):
        base = nome[3:]
        lista += [f"{base}_id", base]
    vistos = []
    for v in lista:
        if v not in vistos:
            vistos.append(v)
    return vistos


class Form:
    """Envelope em volta de `request.form` com leitura por nome canonico."""

    def __init__(self, dados):
        self.dados = dados

    def tem(self, nome):
        return any(v in self.dados for v in variacoes(nome))

    def get(self, nome, padrao="", strip=True):
        """Valor (texto sem espacos nas pontas) do primeiro nome que existir.
        Para senhas use strip=False: espacos fazem parte da senha."""
        for v in variacoes(nome):
            if v in self.dados:
                valor = self.dados.get(v)
                valor = valor if valor is not None else ""
                return valor.strip() if strip else valor
        return padrao

    def lista(self, nome):
        for v in variacoes(nome):
            if v in self.dados:
                return self.dados.getlist(v) if hasattr(self.dados, "getlist") else [self.dados[v]]
        return []

    def booleano(self, nome, padrao=None):
        """Checkbox: `padrao` quando o campo nao veio (None = quem chama decide)."""
        valores = self.lista(nome)
        if not valores:
            return padrao
        return any(str(v).strip().lower() in ("1", "on", "true", "sim", "ativo", "s", "yes") for v in valores)


def montar_valores(dados, canonicos):
    """`valores` para re-renderizar o formulario: o que o usuario digitou (sem senhas)
    + os nomes canonicos preenchidos a partir de qualquer variacao usada."""
    valores = {k: v for k, v in dados.items() if k not in CAMPOS_SECRETOS}
    form = Form(dados)
    for c in canonicos:
        if c in CAMPOS_SECRETOS:
            continue
        if c not in valores and form.tem(c):
            valores[c] = form.get(c)
    return valores


def expandir_erros(erros):
    """Repete cada erro sob as variacoes do nome do campo (o template pode usar qualquer uma)."""
    saida = dict(erros)
    for campo, msg in erros.items():
        for v in variacoes(campo):
            saida.setdefault(v, msg)
    return saida
