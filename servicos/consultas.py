"""
consultas.py
------------
Ajudas para montar consultas SQL com seguranca:

- busca sem acento/maiuscula (`filtro_busca`)
- ORDER BY por lista de permitidos ("whitelist"): nome de coluna NUNCA vem direto do usuario
- paginacao
- contagem de vinculos (para exclusao amigavel)

Regra de ouro: valor digitado pelo usuario entra SEMPRE como parametro `?`.
"""

import math
import re

from servicos.formatacao import normalizar

POR_PAGINA_PADRAO = 200
POR_PAGINA_MAXIMO = 500


class ListaDict(list):
    """Lista de dicts que tambem responde como dicionario (`lista['Tecnico']`, `.items()`).

    Usada em `contagem_perfis`: o template pode percorrer os cards (lista) ou
    consultar um perfil pelo nome.
    """
    def __init__(self, itens, chave="nome", valor="total"):
        super().__init__(itens)
        self._chave, self._valor = chave, valor

    def __getitem__(self, indice):
        if isinstance(indice, str):
            for item in self:
                if item[self._chave] == indice:
                    return item[self._valor]
            raise KeyError(indice)
        return super().__getitem__(indice)

    def items(self):
        return [(i[self._chave], i[self._valor]) for i in self]

    def keys(self):
        return [i[self._chave] for i in self]

    def values(self):
        return [i[self._valor] for i in self]

    def get(self, indice, padrao=None):
        try:
            return self[indice]
        except (KeyError, IndexError):
            return padrao


def como_dicts(linhas):
    return [dict(l) for l in linhas]


def escapar_like(termo):
    """Neutraliza % _ \\ para que o usuario nao mude o sentido do LIKE."""
    return termo.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def filtro_busca(termo, colunas):
    """Devolve (trecho_sql, parametros) para buscar `termo` em varias colunas.

    As colunas vem do CODIGO (nunca do usuario). Ex.:
        sql, params = filtro_busca("balanca", ["e.codigo", "e.descricao"])
        -> "(norm(e.codigo) LIKE ? ESCAPE '\\' OR norm(e.descricao) LIKE ? ESCAPE '\\')"
    """
    t = normalizar((termo or "").strip())[:100]
    if not t:
        return "", []
    padrao = f"%{escapar_like(t)}%"
    partes = [f"norm({c}) LIKE ? ESCAPE '\\'" for c in colunas]
    return "(" + " OR ".join(partes) + ")", [padrao] * len(colunas)


def ordenacao(args, permitidas, padrao):
    """Monta o ORDER BY a partir de ?ordem=coluna&dir=asc|desc.

    `permitidas` mapeia nome-na-URL -> expressao SQL escrita por nos. Se o usuario pedir
    qualquer outra coisa, usamos `padrao`. Assim nada digitado vira SQL.
    """
    chave = (args.get("ordem") or "").strip()
    expressao = permitidas.get(chave)
    if not expressao:
        return padrao
    direcao = "DESC" if (args.get("dir") or "").lower() == "desc" else "ASC"
    return f"{expressao} {direcao}"


def paginacao(args, total):
    """Le ?pagina e ?por_pagina e devolve o dicionario usado pelas telas (+ limit/offset)."""
    try:
        por_pagina = int(args.get("por_pagina") or POR_PAGINA_PADRAO)
    except (TypeError, ValueError):
        por_pagina = POR_PAGINA_PADRAO
    por_pagina = max(1, min(por_pagina, POR_PAGINA_MAXIMO))
    total_paginas = max(1, math.ceil(total / por_pagina))
    try:
        pagina = int(args.get("pagina") or 1)
    except (TypeError, ValueError):
        pagina = 1
    pagina = max(1, min(pagina, total_paginas))
    return {
        "pagina": pagina, "por_pagina": por_pagina, "total": total, "total_paginas": total_paginas,
        "tem_anterior": pagina > 1, "tem_proxima": pagina < total_paginas,
        "limite": por_pagina, "deslocamento": (pagina - 1) * por_pagina,
    }


def inteiro_ou_none(texto):
    """'12' -> 12; '' / 'abc' / None -> None."""
    t = str(texto if texto is not None else "").strip()
    return int(t) if re.fullmatch(r"\d{1,12}", t) else None


def contar_vinculos(db, consultas):
    """Conta registros que ainda usam algo que o usuario quer excluir.

    `consultas` = lista de (rotulo, sql_com_um_?, valor). Devolve (total, texto), ex.:
        (7, "peças: 3, pedidos: 4")
    Os SQL sao escritos no codigo (constantes) e o id entra como parametro.
    """
    total, partes = 0, []
    for rotulo, sql, valor in consultas:
        n = db.execute(sql, (valor,)).fetchone()[0]
        if n:
            total += n
            partes.append(f"{rotulo}: {n}")
    return total, ", ".join(partes)


def mensagem_vinculos(total, detalhe):
    return f"Não é possível excluir: há {total} vínculo(s) ({detalhe})."
