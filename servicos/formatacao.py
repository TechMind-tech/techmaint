"""
formatacao.py
-------------
Datas, dinheiro e numeros no padrao brasileiro, mais o relogio do sistema.

O banco guarda datas em ISO (AAAA-MM-DD); a tela mostra dd/mm/aaaa.
"""

import os
import re
import unicodedata
from datetime import date, datetime

MESES_CURTOS = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"]
MESES = ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho", "Agosto",
         "Setembro", "Outubro", "Novembro", "Dezembro"]


# ---------------------------------------------------------------------------
# Relogio
# ---------------------------------------------------------------------------
def hoje():
    """Data de hoje. `TECHMAINT_HOJE=AAAA-MM-DD` congela o dia (util em testes)."""
    fixo = os.environ.get("TECHMAINT_HOJE", "").strip()
    if fixo:
        try:
            return date.fromisoformat(fixo)
        except ValueError:
            pass
    return date.today()


def agora():
    """Data e hora atuais (usa o dia congelado, se houver, e a hora real)."""
    real = datetime.now()
    d = hoje()
    return datetime(d.year, d.month, d.day, real.hour, real.minute, real.second)


def agora_iso():
    return agora().strftime("%Y-%m-%d %H:%M:%S")


def hoje_iso():
    return hoje().isoformat()


# ---------------------------------------------------------------------------
# Datas
# ---------------------------------------------------------------------------
def data_iso(valor):
    """'2026-09-12 08:30:00' -> '2026-09-12' (so o dia). Vazio -> ''."""
    return str(valor)[:10] if valor else ""


def data_br(valor):
    """'2026-09-12' (ou com hora) -> '12/09/2026'. Vazio -> ''."""
    iso = data_iso(valor)
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", iso)
    return f"{m.group(3)}/{m.group(2)}/{m.group(1)}" if m else ""


def data_hora_br(valor):
    """'2026-09-12 08:30:00' -> '12/09/2026 08:30'."""
    if not valor:
        return ""
    texto = str(valor)
    hora = texto[11:16] if len(texto) >= 16 else ""
    return (data_br(texto) + (" " + hora if hora else "")).strip()


def parse_data(texto):
    """Aceita 'AAAA-MM-DD' ou 'dd/mm/aaaa'. Devolve date ou None."""
    s = (texto or "").strip()
    if not s:
        return None
    try:
        if re.match(r"^\d{4}-\d{2}-\d{2}$", s):
            return date.fromisoformat(s)
        m = re.match(r"^(\d{2})/(\d{2})/(\d{4})$", s)
        if m:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    except ValueError:
        return None
    return None


def soma_meses(d, meses):
    """Soma `meses` a uma data (sempre cai no dia 1 do mes resultante)."""
    total = d.year * 12 + (d.month - 1) + meses
    return date(total // 12, total % 12 + 1, 1)


# ---------------------------------------------------------------------------
# Numeros e dinheiro
# ---------------------------------------------------------------------------
def numero_br(valor, casas=2):
    """1234.5 -> '1.234,50'."""
    if valor is None:
        return ""
    texto = f"{float(valor):,.{casas}f}"
    return texto.replace(",", "#").replace(".", ",").replace("#", ".")


def moeda(valor):
    """1390 -> 'R$ 1.390,00'. None -> 'R$ 0,00'."""
    v = float(valor or 0)
    sinal = "-" if v < 0 else ""
    return f"{sinal}R$ {numero_br(abs(v), 2)}"


def qtd_br(valor):
    """Quantidade sem zeros a toa: 120.0 -> '120'; 2.5 -> '2,5'."""
    if valor is None:
        return ""
    v = round(float(valor), 3)
    if v == int(v):
        return str(int(v))
    return numero_br(v, 3).rstrip("0").rstrip(",")


def inteiro_br(valor):
    return numero_br(valor, 0)


# ---------------------------------------------------------------------------
# Texto
# ---------------------------------------------------------------------------
def normalizar(texto):
    """Minusculo e sem acento: 'Balança' -> 'balanca'. Usado nas buscas."""
    if texto is None:
        return ""
    s = unicodedata.normalize("NFKD", str(texto))
    return "".join(c for c in s if not unicodedata.combining(c)).lower()


def iniciais(nome):
    """'João Administrador' -> 'JA'."""
    partes = [p for p in re.split(r"\s+", (nome or "").strip()) if p]
    if not partes:
        return "?"
    if len(partes) == 1:
        return partes[0][:2].upper()
    return (partes[0][0] + partes[-1][0]).upper()


def cnpj_fmt(digitos):
    d = re.sub(r"\D", "", digitos or "")
    if len(d) != 14:
        return digitos or ""
    return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}"


def cep_fmt(digitos):
    d = re.sub(r"\D", "", digitos or "")
    return f"{d[:5]}-{d[5:]}" if len(d) == 8 else (digitos or "")
