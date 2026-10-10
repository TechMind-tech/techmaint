"""
_pj.py
------
Fornecedores e Prestadores de Servico tem os MESMOS campos (o prestador so ganha
`especialidade`), entao as duas telas compartilham este codigo. Cada arquivo
(fornecedores.py / prestadores.py) chama `criar_blueprint(...)` com as diferencas.

Rotas geradas (substitua <x> por fornecedores ou prestadores):
    /<x>                  GET   lista (+ busca e filtro ativo/inativo)
    /<x>/novo             GET, POST   formulario de cadastro
    /<x>/<id>/editar      GET, POST   formulario de edicao
    /<x>/<id>/excluir     POST        exclui (ou inativa, se houver vinculos)
"""

import re
import sqlite3

from flask import Blueprint, flash, redirect, render_template, request, url_for

import database
from database import transacao
from modulos._comum import ou_404, selecionado
from servicos import auditoria
from servicos.consultas import contar_vinculos, filtro_busca, ordenacao, paginacao
from servicos.formatacao import cep_fmt, cnpj_fmt
from servicos.formularios import Form, expandir_erros, montar_valores
from servicos.permissoes import permissao
from servicos.validacoes import (UFS, cnpj_valido, erro_cep, erro_email, erro_telefone, erro_tamanho,
                                 so_digitos)

CAMPOS_BASE = ["razao_social", "fantasia", "cnpj", "inscricao_estadual", "telefone", "email", "cep", "logradouro",
               "numero", "complemento", "bairro", "municipio", "uf", "ativo"]

ESPECIALIDADES = ["Mecânica Geral", "Elétrica Industrial", "Hidráulica", "Pneumática", "Refrigeração",
                  "Automação", "Civil / Predial", "Informática", "Soldagem", "Usinagem"]


def criar_blueprint(nome, tabela, rotulo, prefixo_codigo, template_lista, template_form, tem_especialidade,
                    consulta_vinculos, rotulo_vinculos):
    """Monta o Blueprint. `tabela` e fixo no codigo (nunca vem do usuario)."""
    bp = Blueprint(nome, __name__)
    campos = CAMPOS_BASE + (["especialidade"] if tem_especialidade else [])
    perm_ver, perm_editar = f"{nome}.ver", f"{nome}.editar"
    rotulo_art = "o" if rotulo == "fornecedor" else "o"      # "o fornecedor" / "o prestador"

    def preparar(linha):
        r = dict(linha)
        r["ativo"] = bool(r["ativo"])
        r["status"] = "Ativo" if r["ativo"] else "Inativo"
        r["codigo"] = f"{prefixo_codigo}-{r['id']:03d}"
        r["cnpj_fmt"] = cnpj_fmt(r["cnpj"])
        r["cep_fmt"] = cep_fmt(r["cep"])
        partes = [r.get("logradouro"), r.get("numero"), r.get("bairro"),
                  " - ".join(x for x in [r.get("municipio"), r.get("uf")] if x)]
        r["endereco_fmt"] = ", ".join(p for p in partes if p)
        return r

    def contexto_lista():
        db = database.get_db()
        busca = request.args.get("busca", "").strip()
        filtro = selecionado(request.args, "ativo", "filtro_ativo", "status").lower()
        filtro = {"ativos": "ativos", "ativo": "ativos", "1": "ativos", "inativos": "inativos",
                  "inativo": "inativos", "0": "inativos"}.get(filtro, "todos")
        onde, params = [], []
        trecho, ps = filtro_busca(busca, ["razao_social", "fantasia", "cnpj", "email", "municipio"
                                          ] + (["especialidade"] if tem_especialidade else []))
        if trecho:
            if re.fullmatch(r"[\d.\-/\s]+", busca) and so_digitos(busca):      # CNPJ digitado com ou sem pontuacao
                trecho = f"({trecho} OR cnpj LIKE ? ESCAPE '\\')"
                ps = ps + [f"%{so_digitos(busca)}%"]
            onde.append(trecho)
            params += ps
        if filtro != "todos":
            onde.append("ativo = ?")
            params.append(1 if filtro == "ativos" else 0)
        where = (" WHERE " + " AND ".join(onde)) if onde else ""
        total_geral = db.execute(f"SELECT COUNT(*) FROM {tabela}").fetchone()[0]
        total = db.execute(f"SELECT COUNT(*) FROM {tabela}{where}", params).fetchone()[0]
        ativos = db.execute(f"SELECT COUNT(*) FROM {tabela} WHERE ativo = 1").fetchone()[0]
        pag = paginacao(request.args, total)
        ordem = ordenacao(request.args, {"razao_social": "razao_social", "cnpj": "cnpj", "id": "id",
                                         "municipio": "municipio"}, "razao_social COLLATE NOCASE")
        linhas = db.execute(f"SELECT * FROM {tabela}{where} ORDER BY {ordem} LIMIT ? OFFSET ?",
                            params + [pag["limite"], pag["deslocamento"]]).fetchall()
        ctx = {"itens": [preparar(l) for l in linhas], "busca": busca, "filtro_ativo": filtro, "ufs": UFS,
               "total": total, "total_geral": total_geral, "total_ativos": ativos,
               "total_inativos": total_geral - ativos, "paginacao": pag}
        ctx.update({k: pag[k] for k in ("pagina", "por_pagina", "total_paginas")})
        if tem_especialidade:
            ctx["especialidades"] = ESPECIALIDADES
        return ctx

    def contexto_form(item=None, erros=None, valores=None):
        ctx = {"item": item, "erros": expandir_erros(erros or {}), "valores": valores, "ufs": UFS}
        if tem_especialidade:
            ctx["especialidades"] = ESPECIALIDADES
        return ctx

    def validar(db, f, id_atual=None, cnpj_atual=None):
        erros = {}
        razao = f.get("razao_social")
        msg = erro_tamanho(razao, "a razão social", 150, obrigatorio=True)
        if msg:
            erros["razao_social"] = msg
        for campo, rot, maximo in (("fantasia", "o nome fantasia", 100), ("inscricao_estadual", "a inscrição estadual", 20),
                                   ("logradouro", "o logradouro", 200), ("numero", "o número", 20),
                                   ("complemento", "o complemento", 100), ("bairro", "o bairro", 100),
                                   ("municipio", "o município", 100)):
            msg = erro_tamanho(f.get(campo), rot, maximo)
            if msg:
                erros[campo] = msg

        digitos = so_digitos(f.get("cnpj"))
        if not f.get("cnpj"):
            erros["cnpj"] = "Informe o CNPJ."
        elif re.search(r"[A-Za-z]", f.get("cnpj")):
            erros["cnpj"] = "CNPJ inválido (use apenas números)."
        elif digitos != (cnpj_atual or "") and not cnpj_valido(digitos):
            # (um CNPJ ja gravado e mantido como esta: dados de demonstracao podem nao ter digito valido)
            erros["cnpj"] = "CNPJ inválido (confira os dígitos)."
        elif db.execute(f"SELECT 1 FROM {tabela} WHERE cnpj = ? AND id <> ?", (digitos, id_atual or -1)).fetchone():
            erros["cnpj"] = f"Já existe {rotulo} com este CNPJ."

        for campo, funcao in (("email", erro_email), ("telefone", erro_telefone), ("cep", erro_cep)):
            msg = funcao(f.get(campo))
            if msg:
                erros[campo] = msg
        uf = f.get("uf").upper()
        if uf and uf not in UFS:
            erros["uf"] = "UF inválida."
        if tem_especialidade:
            msg = erro_tamanho(f.get("especialidade"), "a especialidade", 100)
            if msg:
                erros["especialidade"] = msg

        dados = {c: (f.get(c) or None) for c in campos if c not in ("ativo",)}
        dados.update(cnpj=digitos, uf=uf or None, cep=so_digitos(f.get("cep")) or None)
        return dados, erros

    @bp.route(f"/{nome}")
    @permissao(perm_ver)
    def listar():
        return render_template(template_lista, **contexto_lista())

    @bp.route(f"/{nome}/novo", methods=["GET", "POST"])
    @permissao(perm_editar)
    def novo():
        if request.method == "GET":
            return render_template(template_form, **contexto_form())
        db = database.get_db()
        f = Form(request.form)
        dados, erros = validar(db, f)
        if erros:
            return render_template(template_form, **contexto_form(erros=erros,
                                                                  valores=montar_valores(request.form, campos)))
        dados["ativo"] = 1 if f.booleano("ativo", False) else 0
        cols = list(dados)
        try:
            with transacao(db):
                cur = db.execute(f"INSERT INTO {tabela} ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})",
                                 [dados[c] for c in cols])
                auditoria.registrar(db, rotulo, cur.lastrowid, "criar", f"{rotulo.capitalize()} {dados['razao_social']} criado")
        except sqlite3.IntegrityError:
            return render_template(template_form, **contexto_form(
                erros={"cnpj": f"Já existe {rotulo} com este CNPJ."}, valores=montar_valores(request.form, campos)))
        flash(f"{rotulo.capitalize()} cadastrado com sucesso.", "sucesso")
        return redirect(url_for(f"{nome}.listar"))

    @bp.route(f"/{nome}/<int:id>/editar", methods=["GET", "POST"])
    @permissao(perm_editar)
    def editar(id):
        db = database.get_db()
        atual = preparar(ou_404(db.execute(f"SELECT * FROM {tabela} WHERE id = ?", (id,)).fetchone()))
        if request.method == "GET":
            return render_template(template_form, **contexto_form(item=atual))
        f = Form(request.form)
        dados, erros = validar(db, f, id_atual=id, cnpj_atual=atual["cnpj"])
        if erros:
            return render_template(template_form, **contexto_form(item=atual, erros=erros,
                                                                  valores=montar_valores(request.form, campos)))
        dados["ativo"] = 1 if f.booleano("ativo", False) else 0
        cols = list(dados)
        try:
            with transacao(db):
                db.execute(f"UPDATE {tabela} SET {', '.join(c + ' = ?' for c in cols)} WHERE id = ?",
                           [dados[c] for c in cols] + [id])
                auditoria.registrar(db, rotulo, id, "editar", f"{rotulo.capitalize()} {dados['razao_social']} editado")
        except sqlite3.IntegrityError:
            return render_template(template_form, **contexto_form(
                item=atual, erros={"cnpj": f"Já existe {rotulo} com este CNPJ."},
                valores=montar_valores(request.form, campos)))
        flash(f"{rotulo.capitalize()} atualizado com sucesso.", "sucesso")
        return redirect(url_for(f"{nome}.listar"))

    @bp.route(f"/{nome}/<int:id>/excluir", methods=["POST"])
    @permissao(perm_editar)
    def excluir(id):
        db = database.get_db()
        r = ou_404(db.execute(f"SELECT id, razao_social, ativo FROM {tabela} WHERE id = ?", (id,)).fetchone())
        total, detalhe = contar_vinculos(db, [(rotulo_vinculos, consulta_vinculos, id)])
        try:
            with transacao(db):
                if total:
                    db.execute(f"UPDATE {tabela} SET ativo = 0 WHERE id = ?", (id,))
                    auditoria.registrar(db, rotulo, id, "inativar", f"Inativado (vínculos: {detalhe})")
                    flash(f"{rotulo.capitalize()} possui vínculos ({detalhe}) e não pode ser excluído; foi inativado.",
                          "aviso")
                else:
                    db.execute(f"DELETE FROM {tabela} WHERE id = ?", (id,))
                    auditoria.registrar(db, rotulo, id, "excluir", f"{rotulo.capitalize()} {r['razao_social']} excluído")
                    flash(f"{rotulo.capitalize()} excluído com sucesso.", "sucesso")
        except sqlite3.IntegrityError:
            flash("Não é possível excluir: o registro está em uso.", "erro")
        return redirect(url_for(f"{nome}.listar"))

    return bp
