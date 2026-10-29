"""
api.py
------
Pequenos ajudantes usados pelas rotas da API JSON de todos os modulos.

Tela HTML x API JSON:
    - a TELA devolve uma pagina pronta para a pessoa ler
    - a API devolve so os DADOS (JSON), para outro programa usar
      (o app no celular, um teste automatico, o Postman...)

Os dois usam as MESMAS funcoes de dados.py e a MESMA validacao.

Codigos HTTP que a nossa API usa:
    200 OK            deu certo
    201 Created       criou um registro novo
    400 Bad Request   o corpo nao e um JSON valido
    401 Unauthorized  nao esta logado
    403 Forbidden     esta logado, mas o perfil nao pode
    404 Not Found     o id nao existe
    409 Conflict      conflito com o que ja existe (ex.: CNPJ repetido)
    415               nao mandou Content-Type: application/json
    422               JSON valido, mas com dados errados (validacao)
"""

from flask import abort, jsonify, request


def ler_json():
    """Le o corpo da requisicao como dicionario. Qualquer outra coisa -> 400."""
    dados = request.get_json(silent=True)
    if not isinstance(dados, dict):
        abort(400, description="O corpo precisa ser um objeto JSON, ex.: {\"nome\": \"...\"}.")
    return dados


def erro_validacao(erros):
    return jsonify(erro="Dados invalidos.", campos=erros), 422


def conflito(mensagem):
    return jsonify(erro=mensagem), 409


def nao_encontrado(mensagem="Registro nao encontrado."):
    return jsonify(erro=mensagem), 404
