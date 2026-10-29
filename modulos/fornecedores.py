"""
fornecedores.py
---------------
Cadastro de Fornecedores. Administrador edita; Gestor e Tecnico consultam.
Toda a logica fica em _pj.py (compartilhada com Prestadores de Servico).

    /fornecedores               fornecedores.listar     fornecedores.html
    /fornecedores/novo          fornecedores.novo       fornecedor_form.html
    /fornecedores/<id>/editar   fornecedores.editar     fornecedor_form.html
    /fornecedores/<id>/excluir  fornecedores.excluir    (POST)
"""

from modulos._pj import criar_blueprint

bp = criar_blueprint(
    nome="fornecedores", tabela="fornecedores", rotulo="fornecedor", prefixo_codigo="FOR",
    template_lista="fornecedores.html", template_form="fornecedor_form.html", tem_especialidade=False,
    consulta_vinculos="SELECT COUNT(*) FROM notas_fiscais WHERE id_fornecedor = ?", rotulo_vinculos="notas fiscais")
