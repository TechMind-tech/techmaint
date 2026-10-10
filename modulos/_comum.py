"""
_comum.py
---------
Pequenas ajudas compartilhadas pelos modulos (nao e um Blueprint).
"""

from flask import abort, flash, g, request

from servicos.erros import ErroNegocio


def ou_404(linha):
    """Devolve a linha ou responde 404 se nao existir."""
    if linha is None:
        abort(404)
    return linha


def flash_erro(e):
    """Mostra uma regra de negocio violada como aviso vermelho."""
    flash(e.mensagem if isinstance(e, ErroNegocio) else str(e), "erro")


def quer_json():
    return request.path.startswith("/api/") or request.accept_mimetypes.best == "application/json"


def usuario_id():
    return g.usuario["id"] if getattr(g, "usuario", None) else None


def usuario_nome():
    return g.usuario["nome"] if getattr(g, "usuario", None) else "sistema"


def selecionado(args, *nomes):
    """Primeiro parametro de URL preenchido entre `nomes` (ou '')."""
    for n in nomes:
        v = (args.get(n) or "").strip()
        if v:
            return v
    return ""
