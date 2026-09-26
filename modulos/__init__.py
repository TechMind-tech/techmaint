"""
modulos/
--------
Cada pasta aqui dentro e um MODULO do sistema (um assunto): usuarios,
departamentos, maquinas, pecas, fornecedores, prestadores.

Todo modulo tem os mesmos dois arquivos:

    dados.py   -> o SQL daquele assunto (conversa com o banco)
    rotas.py   -> as telas HTML e a API JSON (conversa com o navegador)

A regra de ouro continua valendo: rotas.py nao escreve SQL e dados.py nao
conhece HTML.

Para o Flask enxergar um modulo, ele precisa ser registrado no app.py
(procure por `register_blueprint`).
"""
