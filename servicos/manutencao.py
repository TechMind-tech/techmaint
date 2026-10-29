"""
manutencao.py (servicos)
------------------------
O "coracao" das regras: Pedido -> Ordem de Servico -> Pecas/Servicos -> Fechar.

Resumo das regras (SPEC secao 3):
  1. Abrir OS a partir de um pedido: pedido vira "Em andamento". Fechar a OS: OS "Concluída",
     data de fechamento e pedido "Concluído". Cancelar pedido so se estiver "Aberto".
  2. Adicionar peca na OS valida o saldo e baixa o estoque (movimento de Saida). Editar a
     quantidade ou excluir a peca estorna a diferenca. OS concluida/cancelada e so leitura.
  4. O equipamento fica "Em manutenção" enquanto houver OS "Em andamento" para ele.

Todas as funcoes esperam estar dentro de `with transacao():`.
"""

from servicos import auditoria
from servicos import estoque as srv_estoque
from servicos.erros import ErroNegocio
from servicos.formatacao import agora_iso, hoje_iso

STATUS_OS = ("Aberta", "Em andamento", "Concluída", "Cancelada")
STATUS_PEDIDO = ("Aberto", "Em andamento", "Concluído", "Cancelado")
PRIORIDADES = ("Baixa", "Média", "Alta")
STATUS_EQUIPAMENTO = ("Ativo", "Em manutenção", "Baixado")
TIPOS_APONTAMENTO = ["AJUSTE", "CALIBRACAO", "INSPECAO", "LIMPEZA", "LUBRIFICACAO", "OUTROS", "PEÇA",
                     "PEÇA + SERVIÇOS", "REGULAGEM", "SOLDA", "TERCEIRIZADO"]
OS_ABERTAS = ("Aberta", "Em andamento")      # status em que a OS ainda aceita alteracoes


def numero_pedido(id_pedido):
    return f"#{id_pedido}"


def numero_os(id_os):
    return f"OS-{id_os}"


def buscar_os(db, id_os):
    return db.execute("SELECT * FROM ordens_servico WHERE id = ?", (id_os,)).fetchone()


def buscar_pedido(db, id_pedido):
    return db.execute("SELECT * FROM pedidos_manutencao WHERE id = ?", (id_pedido,)).fetchone()


# ---------------------------------------------------------------------------
# Equipamento: status automatico (regra 4)
# ---------------------------------------------------------------------------
def garantir_estoque_equipamento(db, id_equipamento):
    """Mantem a linha de estoque_equipamentos (1 unidade, no departamento do equipamento)."""
    e = db.execute("SELECT id_departamento, status FROM equipamentos WHERE id = ?", (id_equipamento,)).fetchone()
    if e is None:
        return
    db.execute("INSERT OR IGNORE INTO estoque_equipamentos (id_equipamento, id_departamento, qtde_atual, "
               "localizacao, status) VALUES (?, ?, 1, 'Instalado', ?)",
               (id_equipamento, e["id_departamento"], e["status"]))
    db.execute("UPDATE estoque_equipamentos SET id_departamento = ?, status = ?, ultima_atualizacao = ? "
               "WHERE id_equipamento = ?", (e["id_departamento"], e["status"], agora_iso(), id_equipamento))


def sincronizar_equipamento(db, id_equipamento):
    """Equipamento "Em manutenção" se ha OS "Em andamento"; volta a "Ativo" quando nao ha mais."""
    if not id_equipamento:
        return
    e = db.execute("SELECT id, status, id_departamento FROM equipamentos WHERE id = ?", (id_equipamento,)).fetchone()
    if e is None or e["status"] == "Baixado":
        return
    ha_os = db.execute("SELECT 1 FROM ordens_servico WHERE id_equipamento = ? AND status = 'Em andamento' LIMIT 1",
                       (id_equipamento,)).fetchone()
    if ha_os:
        novo = "Em manutenção"
    else:
        novo = "Ativo" if e["status"] == "Em manutenção" else e["status"]
    if novo != e["status"]:
        db.execute("UPDATE equipamentos SET status = ? WHERE id = ?", (novo, id_equipamento))
        tipo = "Saída para manutenção" if novo == "Em manutenção" else "Retorno da manutenção"
        db.execute("INSERT INTO movimentacao_equipamentos (id_equipamento, id_departamento, tipo_movimento, data, "
                   "responsavel, observacao) VALUES (?, ?, ?, ?, ?, ?)",
                   (id_equipamento, e["id_departamento"], tipo, agora_iso(), None, f"Status: {e['status']} → {novo}"))
        auditoria.registrar(db, "equipamento", id_equipamento, "status", f"{e['status']} → {novo} (automático)")
    garantir_estoque_equipamento(db, id_equipamento)


# ---------------------------------------------------------------------------
# Totais
# ---------------------------------------------------------------------------
def totais_os(db, id_os):
    pecas = db.execute("SELECT COALESCE(SUM(valor_total), 0) FROM itens_os WHERE id_os = ?", (id_os,)).fetchone()[0]
    servicos = db.execute("SELECT COALESCE(SUM(valor_servico), 0) FROM servicos_os WHERE id_os = ?",
                          (id_os,)).fetchone()[0]
    pecas, servicos = round(pecas, 2), round(servicos, 2)
    return {"pecas": pecas, "servicos": servicos, "geral": round(pecas + servicos, 2)}


# ---------------------------------------------------------------------------
# Pedido
# ---------------------------------------------------------------------------
def cancelar_pedido(db, id_pedido):
    p = buscar_pedido(db, id_pedido)
    if p is None:
        raise ErroNegocio("Pedido não encontrado.")
    if p["status"] != "Aberto":
        raise ErroNegocio("Só é possível cancelar pedidos com status “Aberto”.")
    ativa = db.execute("SELECT 1 FROM ordens_servico WHERE id_pedido = ? AND status <> 'Cancelada'",
                       (id_pedido,)).fetchone()
    if ativa:
        raise ErroNegocio("Este pedido já tem uma Ordem de Serviço ativa e não pode ser cancelado.")
    db.execute("UPDATE pedidos_manutencao SET status = 'Cancelado' WHERE id = ?", (id_pedido,))
    auditoria.registrar(db, "pedido", id_pedido, "cancelar", "Pedido cancelado")


def aprovar_pedido(db, id_pedido, nome_aprovador):
    p = buscar_pedido(db, id_pedido)
    if p is None:
        raise ErroNegocio("Pedido não encontrado.")
    if p["status"] in ("Cancelado", "Concluído"):
        raise ErroNegocio("Pedidos concluídos ou cancelados não podem ser aprovados.")
    if p["aprovado_por"]:
        raise ErroNegocio(f"Este pedido já foi aprovado por {p['aprovado_por']}.")
    db.execute("UPDATE pedidos_manutencao SET aprovado_por = ?, data_aprovacao = ? WHERE id = ?",
               (nome_aprovador, hoje_iso(), id_pedido))
    auditoria.registrar(db, "pedido", id_pedido, "aprovar", f"Aprovado por {nome_aprovador}")


# ---------------------------------------------------------------------------
# Ordem de servico: abrir, alterar, fechar, cancelar, excluir
# ---------------------------------------------------------------------------
def validar_tecnico(db, id_tecnico):
    t = db.execute(
        "SELECT u.id, u.nome FROM usuarios u JOIN usuarios_perfis up ON up.id_usuario = u.id "
        "JOIN perfis p ON p.id = up.id_perfil WHERE u.id = ? AND u.ativo = 1 AND p.nome = 'Técnico'",
        (id_tecnico,)).fetchone()
    if t is None:
        raise ErroNegocio("Selecione um técnico responsável válido (usuário ativo com perfil Técnico).",
                          campo="id_tecnico")
    return t


def abrir_os(db, id_tecnico, observacao, id_pedido=None, id_equipamento=None):
    """Abre uma OS. Com pedido: o pedido precisa estar "Aberto" e vira "Em andamento"."""
    tecnico = validar_tecnico(db, id_tecnico)
    if id_pedido:
        p = buscar_pedido(db, id_pedido)
        if p is None:
            raise ErroNegocio("Pedido não encontrado.", campo="id_pedido")
        if p["status"] != "Aberto":
            raise ErroNegocio("Só é possível abrir OS para pedidos com status “Aberto”.", campo="id_pedido")
        ja = db.execute("SELECT id FROM ordens_servico WHERE id_pedido = ? AND status <> 'Cancelada'",
                        (id_pedido,)).fetchone()
        if ja:
            raise ErroNegocio(f"O pedido já possui a {numero_os(ja['id'])} (cada pedido gera uma única OS).",
                              campo="id_pedido")
        id_equipamento = p["id_equipamento"]
    cur = db.execute(
        "INSERT INTO ordens_servico (id_pedido, id_equipamento, data_abertura, id_tecnico, responsavel, status, "
        "observacao) VALUES (?, ?, ?, ?, ?, 'Aberta', ?)",
        (id_pedido, id_equipamento, agora_iso(), tecnico["id"], tecnico["nome"], observacao or None))
    id_os = cur.lastrowid
    if id_pedido:
        db.execute("UPDATE pedidos_manutencao SET status = 'Em andamento' WHERE id = ?", (id_pedido,))
        auditoria.registrar(db, "pedido", id_pedido, "status", f"Aberto → Em andamento ({numero_os(id_os)})")
    auditoria.registrar(db, "os", id_os, "criar", f"OS aberta para {tecnico['nome']}")
    return id_os


def _exigir_os_aberta(os_):
    if os_ is None:
        raise ErroNegocio("Ordem de serviço não encontrada.")
    if os_["status"] not in OS_ABERTAS:
        raise ErroNegocio(f"A OS está {os_['status'].lower()} e é somente leitura.")


def _iniciar_se_aberta(db, os_):
    """A primeira peca/servico/apontamento coloca uma OS "Aberta" em andamento."""
    if os_["status"] == "Aberta":
        db.execute("UPDATE ordens_servico SET status = 'Em andamento' WHERE id = ?", (os_["id"],))
        auditoria.registrar(db, "os", os_["id"], "status", "Aberta → Em andamento (primeiro lançamento)")
        sincronizar_equipamento(db, os_["id_equipamento"])


def estornar_itens(db, os_, motivo):
    """Devolve ao estoque todas as pecas da OS (usado ao cancelar/excluir a OS)."""
    for it in db.execute("SELECT * FROM itens_os WHERE id_os = ?", (os_["id"],)).fetchall():
        srv_estoque.registrar_movimento(
            db, it["id_peca"], "Entrada", it["quantidade"], it["valor_unitario"], "Ordem de Serviço",
            numero_os(os_["id"]), f"Estorno: {motivo}", id_os=os_["id"])


def alterar_os(db, id_os, id_tecnico, observacao, status, id_equipamento=None):
    """Edita dados da OS. `status` pode ser Aberta, Em andamento ou Cancelada (Concluída so via fechar)."""
    os_ = buscar_os(db, id_os)
    _exigir_os_aberta(os_)
    if status not in ("Aberta", "Em andamento", "Cancelada"):
        raise ErroNegocio("Para concluir a OS use o botão “Fechar OS”.", campo="status")
    tecnico = validar_tecnico(db, id_tecnico)
    equip = os_["id_equipamento"]
    if os_["id_pedido"] is None and id_equipamento:
        equip = id_equipamento
    antigo = os_["status"]
    db.execute("UPDATE ordens_servico SET id_tecnico = ?, responsavel = ?, observacao = ?, status = ?, "
               "id_equipamento = ? WHERE id = ?",
               (tecnico["id"], tecnico["nome"], observacao or None, status, equip, id_os))
    detalhe = f"OS editada (técnico {tecnico['nome']})"
    if status != antigo:
        detalhe += f"; status {antigo} → {status}"
    auditoria.registrar(db, "os", id_os, "editar", detalhe)
    if status == "Cancelada":
        estornar_itens(db, os_, f"OS {numero_os(id_os)} cancelada")
        if os_["id_pedido"]:
            db.execute("UPDATE pedidos_manutencao SET status = 'Aberto' WHERE id = ? AND status = 'Em andamento'",
                       (os_["id_pedido"],))
            auditoria.registrar(db, "pedido", os_["id_pedido"], "status", "Em andamento → Aberto (OS cancelada)")
    sincronizar_equipamento(db, os_["id_equipamento"])
    if equip != os_["id_equipamento"]:
        sincronizar_equipamento(db, equip)


def fechar_os(db, id_os):
    os_ = buscar_os(db, id_os)
    if os_ is None:
        raise ErroNegocio("Ordem de serviço não encontrada.")
    if os_["status"] not in OS_ABERTAS:
        raise ErroNegocio(f"A OS já está {os_['status'].lower()}.")
    os_sem_lancamentos = _os_vazia(db, id_os)
    db.execute("UPDATE ordens_servico SET status = 'Concluída', data_fechamento = ? WHERE id = ?",
               (agora_iso(), id_os))
    if os_["id_pedido"]:
        db.execute("UPDATE pedidos_manutencao SET status = 'Concluído' WHERE id = ? AND status <> 'Cancelado'",
                   (os_["id_pedido"],))
        auditoria.registrar(db, "pedido", os_["id_pedido"], "status", f"→ Concluído ({numero_os(id_os)} fechada)")
    auditoria.registrar(db, "os", id_os, "fechar", f"OS fechada (era {os_['status']})")
    sincronizar_equipamento(db, os_["id_equipamento"])
    return os_sem_lancamentos     # True: OS fechada sem peças, serviços nem apontamentos (a rota avisa)


def _os_vazia(db, id_os):
    return not any(db.execute(f"SELECT 1 FROM {t} WHERE id_os = ? LIMIT 1", (id_os,)).fetchone()
                   for t in ("itens_os", "servicos_os", "apontamentos_os"))


def reabrir_os(db, id_os):
    os_ = buscar_os(db, id_os)
    if os_ is None:
        raise ErroNegocio("Ordem de serviço não encontrada.")
    if os_["status"] != "Concluída":
        raise ErroNegocio("Só é possível reabrir uma OS concluída.")
    db.execute("UPDATE ordens_servico SET status = 'Em andamento', data_fechamento = NULL WHERE id = ?", (id_os,))
    if os_["id_pedido"]:
        db.execute("UPDATE pedidos_manutencao SET status = 'Em andamento' WHERE id = ? AND status = 'Concluído'",
                   (os_["id_pedido"],))
    auditoria.registrar(db, "os", id_os, "reabrir", "OS reaberta pelo administrador")
    sincronizar_equipamento(db, os_["id_equipamento"])


def excluir_os(db, id_os):
    """Exclui a OS (so se nao concluida), devolvendo as pecas ao estoque."""
    os_ = buscar_os(db, id_os)
    if os_ is None:
        raise ErroNegocio("Ordem de serviço não encontrada.")
    if os_["status"] == "Concluída":
        raise ErroNegocio("Não é possível excluir uma OS concluída (ela faz parte do histórico).")
    estornar_itens(db, os_, f"OS {numero_os(id_os)} excluída")
    db.execute("DELETE FROM ordens_servico WHERE id = ?", (id_os,))     # itens, servicos e apontamentos: CASCADE
    if os_["id_pedido"]:
        db.execute("UPDATE pedidos_manutencao SET status = 'Aberto' WHERE id = ? AND status = 'Em andamento'",
                   (os_["id_pedido"],))
        auditoria.registrar(db, "pedido", os_["id_pedido"], "status", "Em andamento → Aberto (OS excluída)")
    auditoria.registrar(db, "os", id_os, "excluir", f"OS excluída (status {os_['status']})")
    sincronizar_equipamento(db, os_["id_equipamento"])


# ---------------------------------------------------------------------------
# Pecas da OS (regra 2)
# ---------------------------------------------------------------------------
def adicionar_peca(db, id_os, id_peca, quantidade, id_usuario=None):
    os_ = buscar_os(db, id_os)
    _exigir_os_aberta(os_)
    quantidade = srv_estoque.arredondar(quantidade)
    if quantidade <= 0:
        raise ErroNegocio("A quantidade deve ser maior que zero.", campo="quantidade")
    peca = srv_estoque.buscar_peca(db, id_peca)
    if peca is None:
        raise ErroNegocio("Selecione uma peça válida.", campo="id_peca")
    # baixa o estoque primeiro: se faltar saldo, levanta erro e nada e gravado
    srv_estoque.registrar_movimento(
        db, id_peca, "Saída", quantidade, peca["valor_unitario"], "Ordem de Serviço", numero_os(id_os),
        f"Peça lançada na {numero_os(id_os)}", id_usuario=id_usuario, id_os=id_os)
    existente = db.execute("SELECT * FROM itens_os WHERE id_os = ? AND id_peca = ?", (id_os, id_peca)).fetchone()
    if existente:        # mesma peca de novo: soma na linha existente
        nova = srv_estoque.arredondar(existente["quantidade"] + quantidade)
        db.execute("UPDATE itens_os SET quantidade = ?, valor_total = ? WHERE id = ?",
                   (nova, round(nova * existente["valor_unitario"], 2), existente["id"]))
        id_item = existente["id"]
    else:
        cur = db.execute("INSERT INTO itens_os (id_os, id_peca, quantidade, valor_unitario, valor_total) "
                         "VALUES (?, ?, ?, ?, ?)",
                         (id_os, id_peca, quantidade, peca["valor_unitario"],
                          round(quantidade * peca["valor_unitario"], 2)))
        id_item = cur.lastrowid
    auditoria.registrar(db, "os", id_os, "peça", f"+{srv_estoque.qtd_br(quantidade)} × {peca['nome']}")
    _iniciar_se_aberta(db, os_)
    return id_item


def editar_peca(db, id_os, id_item, nova_quantidade, id_usuario=None):
    os_ = buscar_os(db, id_os)
    _exigir_os_aberta(os_)
    item = db.execute("SELECT * FROM itens_os WHERE id = ? AND id_os = ?", (id_item, id_os)).fetchone()
    if item is None:
        raise ErroNegocio("Peça não encontrada nesta OS.")
    nova = srv_estoque.arredondar(nova_quantidade)
    if nova <= 0:
        raise ErroNegocio("A quantidade deve ser maior que zero (para remover use Excluir Peça).", campo="quantidade")
    diferenca = srv_estoque.arredondar(nova - item["quantidade"])
    if diferenca != 0:
        tipo = "Saída" if diferenca > 0 else "Entrada"
        obs = "Ajuste de quantidade na OS" if diferenca > 0 else "Estorno: quantidade reduzida na OS"
        srv_estoque.registrar_movimento(db, item["id_peca"], tipo, abs(diferenca), item["valor_unitario"],
                                        "Ordem de Serviço", numero_os(id_os), obs, id_usuario=id_usuario, id_os=id_os)
    db.execute("UPDATE itens_os SET quantidade = ?, valor_total = ? WHERE id = ?",
               (nova, round(nova * item["valor_unitario"], 2), id_item))
    auditoria.registrar(db, "os", id_os, "peça", f"quantidade {srv_estoque.qtd_br(item['quantidade'])} → "
                                                 f"{srv_estoque.qtd_br(nova)}")


def excluir_peca(db, id_os, id_item, id_usuario=None):
    os_ = buscar_os(db, id_os)
    _exigir_os_aberta(os_)
    item = db.execute("SELECT i.*, p.nome AS peca_nome FROM itens_os i JOIN pecas p ON p.id = i.id_peca "
                      "WHERE i.id = ? AND i.id_os = ?", (id_item, id_os)).fetchone()
    if item is None:
        raise ErroNegocio("Peça não encontrada nesta OS.")
    srv_estoque.registrar_movimento(db, item["id_peca"], "Entrada", item["quantidade"], item["valor_unitario"],
                                    "Ordem de Serviço", numero_os(id_os), "Estorno: peça removida da OS",
                                    id_usuario=id_usuario, id_os=id_os)
    db.execute("DELETE FROM itens_os WHERE id = ?", (id_item,))
    auditoria.registrar(db, "os", id_os, "peça", f"removida: {item['peca_nome']}")


# ---------------------------------------------------------------------------
# Servicos e apontamentos
# ---------------------------------------------------------------------------
def adicionar_servico(db, id_os, descricao, valor, id_prestador=None):
    os_ = buscar_os(db, id_os)
    _exigir_os_aberta(os_)
    if id_prestador:
        pr = db.execute("SELECT id, ativo FROM prestadores_servico WHERE id = ?", (id_prestador,)).fetchone()
        if pr is None:
            raise ErroNegocio("Prestador não encontrado.", campo="id_prestador")
        if not pr["ativo"]:
            raise ErroNegocio("O prestador selecionado está inativo.", campo="id_prestador")
    cur = db.execute("INSERT INTO servicos_os (id_os, descricao_servico, valor_servico, id_prestador) "
                     "VALUES (?, ?, ?, ?)", (id_os, descricao, round(valor, 2), id_prestador or None))
    auditoria.registrar(db, "os", id_os, "serviço", f"{descricao[:80]} (R$ {valor:.2f})")
    _iniciar_se_aberta(db, os_)
    return cur.lastrowid


def excluir_servico(db, id_os, id_servico):
    os_ = buscar_os(db, id_os)
    _exigir_os_aberta(os_)
    s = db.execute("SELECT * FROM servicos_os WHERE id = ? AND id_os = ?", (id_servico, id_os)).fetchone()
    if s is None:
        raise ErroNegocio("Serviço não encontrado nesta OS.")
    db.execute("DELETE FROM servicos_os WHERE id = ?", (id_servico,))
    auditoria.registrar(db, "os", id_os, "serviço", f"removido: {s['descricao_servico'][:80]}")


def adicionar_apontamento(db, id_os, data_iso, tecnico, horas, tipo, observacao):
    os_ = buscar_os(db, id_os)
    _exigir_os_aberta(os_)
    cur = db.execute("INSERT INTO apontamentos_os (id_os, data, tecnico, horas_trabalhadas, tipo, observacao) "
                     "VALUES (?, ?, ?, ?, ?, ?)", (id_os, data_iso, tecnico, horas, tipo, observacao or None))
    auditoria.registrar(db, "os", id_os, "apontamento", f"{tipo or 'sem tipo'}: {horas or 0} h por {tecnico}")
    _iniciar_se_aberta(db, os_)
    return cur.lastrowid


def excluir_apontamento(db, id_os, id_apontamento):
    os_ = buscar_os(db, id_os)
    _exigir_os_aberta(os_)
    a = db.execute("SELECT * FROM apontamentos_os WHERE id = ? AND id_os = ?", (id_apontamento, id_os)).fetchone()
    if a is None:
        raise ErroNegocio("Apontamento não encontrado nesta OS.")
    db.execute("DELETE FROM apontamentos_os WHERE id = ?", (id_apontamento,))
    auditoria.registrar(db, "os", id_os, "apontamento", "apontamento removido")
