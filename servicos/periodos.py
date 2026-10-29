"""
periodos.py
-----------
Os periodos dos filtros (Dashboard, Relatorios, Estoque):
    7d = ultimos 7 dias | 30d = ultimos 30 dias | 6m = ultimos 6 meses | 12m = ultimo ano
"""

from datetime import timedelta

from servicos.formatacao import hoje, soma_meses

PERIODOS = [
    {"valor": "7d", "rotulo": "Últimos 7 dias"},
    {"valor": "30d", "rotulo": "Últimos 30 dias"},
    {"valor": "6m", "rotulo": "Últimos 6 meses"},
    {"valor": "12m", "rotulo": "Último ano"},
]
ROTULOS = {p["valor"]: p["rotulo"] for p in PERIODOS}


def periodo_valido(texto, padrao="30d"):
    t = (texto or "").strip().lower()
    return t if t in ROTULOS else padrao


def inicio_do_periodo(periodo, referencia=None):
    """Primeiro dia (inclusive) do periodo, contando ate `referencia` (hoje)."""
    ref = referencia or hoje()
    if periodo == "7d":
        return ref - timedelta(days=6)
    if periodo == "30d":
        return ref - timedelta(days=29)
    if periodo == "6m":
        return soma_meses(ref.replace(day=1), -5)
    return soma_meses(ref.replace(day=1), -11)      # 12m
