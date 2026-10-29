"""Testes das funcoes de validadores.py (nao precisam de banco nem de app)."""

import pytest

from validadores import (Validacao, centavos_para_texto, cnpj_valido, email_valido,
                         formatar_cnpj, reais_para_centavos, somente_digitos)


@pytest.mark.parametrize("cnpj", [
    "11222333000181",        # sem mascara
    "11.222.333/0001-81",    # com mascara
    " 44.555.666/0001-81 ",  # com espacos
])
def test_cnpj_valido_passa(cnpj):
    assert cnpj_valido(cnpj)


@pytest.mark.parametrize("cnpj", [
    "11222333000182",   # ultimo digito errado
    "11222333000191",   # penultimo digito errado
    "11111111111111",   # sequencia repetida: passa na conta, mas nao existe
    "00000000000000",
    "1122233300018",    # 13 digitos
    "112223330001810",  # 15 digitos
    "",
    None,
    "abc",
])
def test_cnpj_invalido_nao_passa(cnpj):
    assert not cnpj_valido(cnpj)


def test_formatar_cnpj_coloca_mascara():
    assert formatar_cnpj("11222333000181") == "11.222.333/0001-81"


def test_somente_digitos():
    assert somente_digitos("11.222.333/0001-81") == "11222333000181"


@pytest.mark.parametrize("texto, centavos", [
    ("1234,56", 123456),
    ("1.234,56", 123456),
    ("1234.56", 123456),
    ("R$ 38,9", 3890),
    ("10", 1000),
    ("0,05", 5),
    ("-2,50", -250),
])
def test_reais_para_centavos(texto, centavos):
    assert reais_para_centavos(texto) == centavos


@pytest.mark.parametrize("texto", ["", "abc", "1,234,5", "12,345"])
def test_reais_para_centavos_invalido(texto):
    assert reais_para_centavos(texto) is None


def test_centavos_para_texto():
    assert centavos_para_texto(3890) == "38,90"
    assert centavos_para_texto(5) == "0,05"
    assert centavos_para_texto(123456) == "1234,56"


def test_email_valido():
    assert email_valido("ana@empresa.com.br")
    assert not email_valido("ana@empresa")
    assert not email_valido("ana empresa.com")


def test_validacao_junta_todos_os_erros_de_uma_vez():
    v = Validacao({"nome": "", "qtde": "-1", "cnpj": "123"})
    v.texto("nome", obrigatorio=True)
    v.inteiro("qtde", minimo=0)
    v.cnpj("cnpj")
    assert set(v.erros) == {"nome", "qtde", "cnpj"}


def test_validacao_texto_vazio_vira_none():
    v = Validacao({"apelido": "   "})
    v.texto("apelido")
    assert v.dados["apelido"] is None
