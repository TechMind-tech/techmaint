"""
prestadores.py
--------------
Cadastro de Prestadores de Servico (mesma logica de Fornecedores, mais `especialidade`).

    /prestadores               prestadores.listar     prestadores.html
    /prestadores/novo          prestadores.novo       prestador_form.html
    /prestadores/<id>/editar   prestadores.editar     prestador_form.html
    /prestadores/<id>/excluir  prestadores.excluir    (POST)
"""

from modulos._pj import criar_blueprint

bp = criar_blueprint(
    nome="prestadores", tabela="prestadores_servico", rotulo="prestador", prefixo_codigo="PST",
    template_lista="prestadores.html", template_form="prestador_form.html", tem_especialidade=True,
    consulta_vinculos="SELECT COUNT(*) FROM servicos_os WHERE id_prestador = ?", rotulo_vinculos="serviços em OS")
