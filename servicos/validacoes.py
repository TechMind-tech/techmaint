"""
validacoes.py
-------------
Funcoes pequenas que dizem se um dado e valido. Todas devolvem a mensagem de
erro (texto em pt-BR) ou `None` quando esta tudo certo.
"""

import re
from decimal import Decimal, InvalidOperation

UFS = ["AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS", "MG", "PA", "PB",
       "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO"]

REGEX_EMAIL = re.compile(r"^[^@\s<>\"']+@[^@\s<>\"']+\.[^@\s<>\"']{2,}$")
REGEX_LOGIN = re.compile(r"^\S{3,50}$")


def so_digitos(texto):
    return re.sub(r"\D", "", str(texto or ""))


# ---------------------------------------------------------------------------
# Numeros digitados pelo usuario
# ---------------------------------------------------------------------------
def para_decimal(texto):
    """'1.234,56' | '1234.56' | 'R$ 15,00' -> Decimal. Texto invalido -> None."""
    s = str(texto if texto is not None else "").strip().replace("R$", "").replace(" ", "")
    if not s:
        return None
    if "," in s:
        s = s.replace(".", "").replace(",", ".")   # formato brasileiro
    if not re.match(r"^-?\d+(\.\d+)?$", s) or len(s) > 30:
        return None          # rejeita 'abc', 'nan', '1e400'...
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def para_float(texto):
    d = para_decimal(texto)
    return None if d is None else float(d)


def validar_decimal(texto, rotulo, obrigatorio=True, minimo=0, maximo=1_000_000_000, estrito=False):
    """Devolve (valor_float, erro). `estrito=True` exige > minimo (senao >= minimo)."""
    if texto is None or str(texto).strip() == "":
        return (None, f"Informe {rotulo}." if obrigatorio else None)
    valor = para_float(texto)
    if valor is None:
        return (None, f"{rotulo[0].upper() + rotulo[1:]} inválido(a).")
    if estrito and valor <= minimo:
        return (None, f"{rotulo[0].upper() + rotulo[1:]} deve ser maior que {minimo:g}.")
    if not estrito and valor < minimo:
        return (None, f"{rotulo[0].upper() + rotulo[1:]} não pode ser negativo(a)." if minimo == 0
                else f"{rotulo[0].upper() + rotulo[1:]} deve ser no mínimo {minimo:g}.")
    if valor > maximo:
        return (None, f"{rotulo[0].upper() + rotulo[1:]} muito grande.")
    return (valor, None)


def validar_inteiro(texto, rotulo, obrigatorio=False, minimo=0, maximo=100000):
    if texto is None or str(texto).strip() == "":
        return (None, f"Informe {rotulo}." if obrigatorio else None)
    s = str(texto).strip()
    if not re.match(r"^-?\d+$", s):
        return (None, f"{rotulo[0].upper() + rotulo[1:]} deve ser um número inteiro.")
    valor = int(s)
    if valor < minimo or valor > maximo:
        return (None, f"{rotulo[0].upper() + rotulo[1:]} deve estar entre {minimo} e {maximo}.")
    return (valor, None)


# ---------------------------------------------------------------------------
# Documentos e contatos
# ---------------------------------------------------------------------------
def cnpj_valido(cnpj):
    """Confere o tamanho e os dois digitos verificadores do CNPJ."""
    n = so_digitos(cnpj)
    if len(n) != 14 or len(set(n)) == 1:
        return False

    def digito(base, pesos):
        soma = sum(int(a) * b for a, b in zip(base, pesos))
        resto = soma % 11
        return 0 if resto < 2 else 11 - resto

    pesos1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    pesos2 = [6] + pesos1
    d1 = digito(n[:12], pesos1)
    d2 = digito(n[:12] + str(d1), pesos2)
    return n[12:] == f"{d1}{d2}"


def erro_email(email, obrigatorio=False):
    e = (email or "").strip()
    if not e:
        return "Informe o e-mail." if obrigatorio else None
    if len(e) > 150 or not REGEX_EMAIL.match(e):
        return "E-mail inválido."
    return None


def erro_login(login):
    l = (login or "").strip()
    if not l:
        return "Informe o login."
    if not REGEX_LOGIN.match(l):
        return "O login deve ter de 3 a 50 caracteres, sem espaços."
    return None


def erro_ncm(ncm):
    """NCM e opcional; se vier, precisa ter 8 digitos (pontos sao ignorados)."""
    n = (ncm or "").strip()
    if not n:
        return None
    if not re.match(r"^[\d.\-\s]+$", n) or len(so_digitos(n)) != 8:
        return "O NCM deve ter 8 dígitos."
    return None


def erro_senha_nova(senha):
    if not senha:
        return "Informe a senha."
    if len(senha) < 8:
        return "A senha deve ter pelo menos 8 caracteres."
    if len(senha) > 128:
        return "A senha é muito longa."
    return None


def erro_cep(cep):
    c = (cep or "").strip()
    if not c:
        return None
    if len(so_digitos(c)) != 8 or not re.match(r"^[\d.\-\s]+$", c):
        return "CEP inválido (use 8 dígitos)."
    return None


def erro_telefone(tel):
    t = (tel or "").strip()
    if not t:
        return None
    if not re.match(r"^[\d\s()+\-.]+$", t) or not (8 <= len(so_digitos(t)) <= 13):
        return "Telefone inválido."
    return None


def erro_tamanho(texto, rotulo, maximo, obrigatorio=False):
    t = (texto or "").strip()
    if not t:
        return f"Informe {rotulo}." if obrigatorio else None
    if len(t) > maximo:
        return f"{rotulo[0].upper() + rotulo[1:]} deve ter no máximo {maximo} caracteres."
    return None
