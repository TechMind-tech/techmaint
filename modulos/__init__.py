"""
Pacote `modulos`: um Blueprint por area do sistema.

Blueprint = um "mini app" com as proprias rotas. O `registrar_blueprints()`
liga todos eles na aplicacao principal (veja `criar_app()` em app.py).
"""

from . import (auth, configuracoes, departamentos, equipamentos, estoque,
               fornecedores, ordens, painel, pecas, pedidos, prestadores,
               relatorios, usuarios)

TODOS = (auth, painel, usuarios, equipamentos, pecas, fornecedores, prestadores,
         departamentos, pedidos, ordens, estoque, relatorios, configuracoes)


def registrar_blueprints(app):
    for modulo in TODOS:
        app.register_blueprint(modulo.bp)
