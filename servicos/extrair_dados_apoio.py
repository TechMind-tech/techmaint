"""
extrair_dados_apoio.py
----------------------
Script de uso unico (ja executado): le o texto de `docs/documentacao-de-apoio.txt`
e grava `dados/grupos.json`, `dados/subgrupos.json` e `dados/equipamentos.json`.

Uso:
    python servicos/extrair_dados_apoio.py caminho/para/documentacao-de-apoio.txt

O `seed.py` le apenas os JSON; este script fica no repositorio so para mostrar
de onde vieram os dados (e para regera-los se o documento mudar).
"""

import json
import re
import sys
from pathlib import Path

PASTA_DADOS = Path(__file__).resolve().parent.parent / "dados"

# Departamento "dono" de cada grupo (nao vem no documento: e uma decisao do projeto).
DEPARTAMENTO_POR_GRUPO = {
    "Predial": "Administração",
    "Infraestrutura": "Utilidades",
    "Produção": "Produção",
    "Ferramentaria": "Manutenção",
    "Logística": "Logística",
    "Frota": "Logística",
    "TI": "TI",
    "Móveis e Utensílios": "Administração",
    "Laboratório / Qualidade": "Produção",
    "Serviços e Benfeitorias": "Manutenção",
    "Segurança Patrimonial": "Administração",
    "Meio Ambiente": "Utilidades",
    "Utilidades Industriais": "Utilidades",
    "Metrologia": "Produção",
    "Automação Industrial": "Manutenção",
}
# Excecoes por subgrupo (o compressor e da Infraestrutura, como no Figma).
DEPARTAMENTO_POR_SUBGRUPO = {"Compressores": "Infraestrutura"}


def ler_secao(linhas, inicio, fim):
    """Devolve as linhas entre dois titulos de secao."""
    i = next(n for n, l in enumerate(linhas) if re.match(inicio, l.strip()))
    j = next(n for n, l in enumerate(linhas) if n > i and re.match(fim, l.strip()))
    return linhas[i + 1:j]


def extrair(caminho_txt):
    linhas = Path(caminho_txt).read_text(encoding="utf-8").splitlines()

    # ---- 1. Grupos: "1   Predial"
    grupos = []
    for l in ler_secao(linhas, r"^1\.\s+Grupos\s*$", r"^2\.\s+SubGrupos\s*$"):
        m = re.match(r"^(\d+)\s+(.+?)\s*$", l.strip())
        if m:
            grupos.append({"id": int(m.group(1)), "nome": m.group(2)})
    nome_do_grupo = {g["id"]: g["nome"] for g in grupos}

    # ---- 2. Subgrupos: "37  CLPs   15   Automacao Industrial"
    subgrupos = []
    for l in ler_secao(linhas, r"^2\.\s+SubGrupos\s*$", r"^3\.\s+Equipamentos\s*$"):
        m = re.match(r"^(\d+)\s+(.+?)\s{2,}(\d+)\s+(.+?)\s*$", l.strip())
        if m:
            subgrupos.append({"id": int(m.group(1)), "nome": m.group(2), "id_grupo": int(m.group(3))})

    # ---- 3. Equipamentos
    # Quase todas as linhas sao "codigo  descricao  grupo  subgrupo" (colunas separadas por
    # 2+ espacos). Quatro registros quebram em varias linhas no PDF; para eles
    # usamos as correcoes abaixo (conferidas a olho no documento).
    correcoes = {
        "07.000.0062": ("BALANCA 09 (BORRACHA) 60KG X 10G - TOLEDO SERIE 12789325", "Produção", "Balanças de Processo"),
        "07.000.0007": ("HOMOGEINIZADOR 01", "Produção", "Misturadores e Homogeneizadores"),
        "07.000.0012": ("HOMOGEINIZADOR 02", "Produção", "Misturadores e Homogeneizadores"),
        "07.000.0038": ("PAQUIMETRO 02", "Laboratório / Qualidade", "Metrologia"),
    }
    bruto = ler_secao(linhas, r"^3\.\s+Equipamentos\s*$", r"^4\.\s+Listas Suspensas")
    id_do_grupo = {g["nome"]: g["id"] for g in grupos}
    equipamentos = []
    for l in bruto:
        m = re.match(r"^\s*(\d\d\.\d{3}\.\d{4})\s*(.*)$", l)
        if not m:
            continue  # cabecalho, rodape ou linha de continuacao
        codigo, resto = m.group(1), m.group(2).strip()
        if codigo in correcoes:
            desc, grupo, sub = correcoes[codigo]
        else:
            partes = re.split(r"\s{2,}", resto)
            if len(partes) != 3:
                raise ValueError(f"Linha inesperada para {codigo}: {partes}")
            desc, grupo, sub = partes
        id_grupo = id_do_grupo[grupo]
        # o subgrupo precisa pertencer ao grupo (existem dois "Metrologia")
        cand = [s for s in subgrupos if s["nome"] == sub and s["id_grupo"] == id_grupo]
        if not cand:
            raise ValueError(f"Subgrupo {sub!r} nao existe no grupo {grupo!r} ({codigo})")
        depto = DEPARTAMENTO_POR_SUBGRUPO.get(sub) or DEPARTAMENTO_POR_GRUPO[grupo]
        equipamentos.append({
            "codigo": codigo, "descricao": desc,
            "id_grupo": id_grupo, "grupo": grupo,
            "id_subgrupo": cand[0]["id"], "subgrupo": sub,
            "departamento": depto,
        })
    return grupos, subgrupos, equipamentos


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)
    grupos, subgrupos, equipamentos = extrair(sys.argv[1])
    PASTA_DADOS.mkdir(exist_ok=True)
    for nome, dados in (("grupos", grupos), ("subgrupos", subgrupos), ("equipamentos", equipamentos)):
        (PASTA_DADOS / f"{nome}.json").write_text(
            json.dumps(dados, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{len(grupos)} grupos, {len(subgrupos)} subgrupos, {len(equipamentos)} equipamentos")


if __name__ == "__main__":
    main()
