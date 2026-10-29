"""Erros de regra de negocio: viram mensagem amigavel na tela (nunca um 500)."""


class ErroNegocio(Exception):
    """Uma regra de negocio foi violada. `campo` (opcional) indica qual campo do formulario."""

    def __init__(self, mensagem, campo=None):
        super().__init__(mensagem)
        self.mensagem = mensagem
        self.campo = campo


class EstoqueInsuficiente(ErroNegocio):
    pass
