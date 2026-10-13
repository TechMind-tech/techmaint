"""
validadores.py
--------------
Regras de validacao usadas por TODOS os modulos.

A ideia: a tela (formulario HTML) e a API (JSON) mandam dados para o mesmo
lugar e passam pela MESMA validacao. A regra mora num lugar so.

Lembrete: o `required` do HTML ajuda, mas pode ser burlado. A validacao
que vale e a do servidor, que e esta aqui.

Uso tipico, dentro do rotas.py de um modulo:

    v = Validacao(request.form)          # ou o dicionario do JSON
    v.texto("nome", obrigatorio=True)
    v.inteiro("qtde_minima", minimo=0)
    if v.erros:
        ...mostra os erros...
    else:
        ...grava v.dados no banco...
"""

import re


# ---------------------------------------------------------------------------
# Funcoes soltas (da para importar e usar em qualquer lugar)
# ---------------------------------------------------------------------------


def somente_digitos(texto):
    """'12.345.678/0001-95' -> '12345678000195'"""
    return "".join(c for c in str(texto or "") if c.isdigit())


def cnpj_valido(cnpj):
    """Confere os dois digitos verificadores do CNPJ.

    Aceita com ou sem mascara. Recusa sequencias repetidas como
    '11111111111111', que passariam na conta mas nao existem.
    """
    numeros = somente_digitos(cnpj)
    if len(numeros) != 14 or numeros == numeros[0] * 14:
        return False

    def digito(base, pesos):
        soma = sum(int(d) * p for d, p in zip(base, pesos))
        resto = soma % 11
        return "0" if resto < 2 else str(11 - resto)

    pesos1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    pesos2 = [6] + pesos1
    d1 = digito(numeros[:12], pesos1)
    d2 = digito(numeros[:12] + d1, pesos2)
    return numeros[12:] == d1 + d2


def formatar_cnpj(cnpj):
    """'12345678000195' -> '12.345.678/0001-95' (so para mostrar na tela)."""
    n = somente_digitos(cnpj)
    if len(n) != 14:
        return cnpj or ""
    return f"{n[:2]}.{n[2:5]}.{n[5:8]}/{n[8:12]}-{n[12:]}"


# Nao e a validacao "perfeita" de e-mail (essa e enorme), mas pega os
# erros de digitacao comuns: falta de @, falta de ponto no dominio, espaco.
_PADRAO_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def email_valido(email):
    return bool(_PADRAO_EMAIL.match(email or ""))


def reais_para_centavos(texto):
    """Converte o que a pessoa digitou em centavos (int).

    Aceita '1234,56', '1.234,56', '1234.56' e '1234'.
    Devolve None se nao for um numero.

    Por que centavos? Porque dinheiro NUNCA deve ser float.
    Em float, 0.1 + 0.2 da 0.30000000000000004.
    """
    texto = str(texto).strip().replace("R$", "").replace(" ", "")
    if not texto:
        return None
    if "," in texto:
        # formato brasileiro: ponto separa milhar, virgula separa centavos
        texto = texto.replace(".", "").replace(",", ".")
    if not re.fullmatch(r"-?\d+(\.\d{1,2})?", texto):
        return None
    inteiro, _, fracao = texto.partition(".")
    negativo = inteiro.startswith("-")
    centavos = abs(int(inteiro)) * 100 + int((fracao + "00")[:2])
    return -centavos if negativo else centavos


def centavos_para_texto(centavos):
    """3890 -> '38,90'  (para colocar dentro de um input de formulario)."""
    negativo = centavos < 0
    texto = f"{abs(centavos) // 100},{abs(centavos) % 100:02d}"
    return "-" + texto if negativo else texto


# ---------------------------------------------------------------------------
# Classe Validacao: junta os erros de um formulario inteiro
# ---------------------------------------------------------------------------


class Validacao:
    """Valida um formulario campo a campo e junta tudo em dois dicionarios:

    - self.dados  -> os valores ja limpos, prontos para gravar
    - self.erros  -> {campo: mensagem} de tudo que deu errado

    Validamos TODOS os campos antes de responder, para a pessoa ver todos
    os problemas de uma vez (e nao um por vez, que irrita).
    """

    def __init__(self, entrada):
        # `entrada` pode ser o request.form (tela) ou um dict (API JSON).
        self.entrada = entrada or {}
        self.dados = {}
        self.erros = {}

    def _bruto(self, campo):
        valor = self.entrada.get(campo)
        return "" if valor is None else str(valor).strip()

    def texto(self, campo, obrigatorio=False, maximo=200, rotulo=None):
        valor = self._bruto(campo)
        rotulo = rotulo or campo
        if obrigatorio and not valor:
            self.erros[campo] = f"Preencha {rotulo}."
        elif len(valor) > maximo:
            self.erros[campo] = f"{rotulo.capitalize()} pode ter no maximo {maximo} caracteres."
        # Texto vazio vira None (NULL no banco), nao string vazia.
        self.dados[campo] = valor or None
        return self.dados[campo]

    def inteiro(self, campo, minimo=None, obrigatorio=True, rotulo=None, padrao=None):
        valor = self._bruto(campo)
        rotulo = rotulo or campo
        if not valor:
            if obrigatorio and padrao is None:
                self.erros[campo] = f"Preencha {rotulo}."
            self.dados[campo] = padrao
            return padrao
        try:
            numero = int(valor)
        except ValueError:
            self.erros[campo] = f"{rotulo.capitalize()} precisa ser um numero inteiro."
            self.dados[campo] = None
            return None
        if minimo is not None and numero < minimo:
            self.erros[campo] = f"{rotulo.capitalize()} nao pode ser menor que {minimo}."
        self.dados[campo] = numero
        return numero

    def dinheiro(self, campo, obrigatorio=True, rotulo=None):
        """Le um valor em reais e guarda em CENTAVOS em self.dados."""
        valor = self._bruto(campo)
        rotulo = rotulo or campo
        if not valor:
            if obrigatorio:
                self.erros[campo] = f"Preencha {rotulo}."
            self.dados[campo] = 0
            return 0
        centavos = reais_para_centavos(valor)
        if centavos is None:
            self.erros[campo] = f"{rotulo.capitalize()} invalido. Use o formato 1234,56."
        elif centavos < 0:
            self.erros[campo] = f"{rotulo.capitalize()} nao pode ser negativo."
        self.dados[campo] = centavos
        return centavos

    def escolha(self, campo, opcoes, rotulo=None, padrao=None):
        """O valor precisa estar na lista de opcoes (ex.: status)."""
        valor = self._bruto(campo) or padrao
        if valor not in opcoes:
            self.erros[campo] = f"Escolha um {rotulo or campo} valido."
        self.dados[campo] = valor
        return valor

    def cnpj(self, campo="cnpj"):
        """CNPJ obrigatorio e valido. Guarda SO os numeros."""
        valor = self._bruto(campo)
        if not valor:
            self.erros[campo] = "Preencha o CNPJ."
        elif not cnpj_valido(valor):
            self.erros[campo] = "CNPJ invalido. Confira os numeros digitados."
        self.dados[campo] = somente_digitos(valor)
        return self.dados[campo]

    def email(self, campo="email", obrigatorio=False):
        valor = self._bruto(campo).lower()
        if not valor:
            if obrigatorio:
                self.erros[campo] = "Preencha o e-mail."
            self.dados[campo] = None
            return None
        if not email_valido(valor):
            self.erros[campo] = "E-mail invalido."
        self.dados[campo] = valor
        return valor

    def erro(self, campo, mensagem):
        """Para regras que so o modulo conhece (ex.: minimo <= maximo)."""
        self.erros[campo] = mensagem
