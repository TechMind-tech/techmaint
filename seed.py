"""
seed.py
-------
Popula o banco com dados de DEMONSTRACAO (tudo ficticio, so para desenvolvimento).

    python seed.py            # cria o banco (se preciso) e popula
    python seed.py --limpar   # APAGA o banco e recria do zero (so use em desenvolvimento!)

Pode rodar varias vezes (idempotente):
- os dados de referencia (departamentos, usuarios demo, 15 grupos, 149 subgrupos e os
  77 equipamentos reais do documento de apoio) usam "INSERT OR IGNORE": nunca duplicam
  e nunca sobrescrevem o que voce alterou;
- os dados de demonstracao (pecas, notas fiscais, pedidos, OS, historico de ~12 meses)
  entram uma unica vez; o marcador `seed_demo` na tabela `parametros` evita repeticao.

O historico e gerado com `random.Random(2026)` (sempre o mesmo resultado) e datas
relativas a "hoje" — os graficos nunca ficam vazios. Os dados do Figma (pedidos #1621 e
#1623 a #1626, OS-10232 a OS-10234, pecas, fornecedores e prestadores) tem datas e numeros fixos.

Usuarios de demonstracao (documentados no README):
    admin / admin123 · tecnico / tecnico123 · gestor / gestor123 · solicitante / solicitante123 · plima / plima123
"""

import argparse
import json
import os
import random
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import database
from database import transacao
from servicos import manutencao
from servicos.formatacao import hoje, soma_meses
from servicos.seguranca import gerar_hash

RAIZ = Path(__file__).resolve().parent
DADOS = RAIZ / "dados"

# ---------------------------------------------------------------------------
# Dados fixos
# ---------------------------------------------------------------------------
USUARIOS = [   # login, senha, nome, e-mail, perfil, departamento
    ("admin", "admin123", "João Administrador", "admin@techmaint.com", "Administrador", "TI"),
    ("tecnico", "tecnico123", "Maria Técnica", "tecnico@techmaint.com", "Técnico", "Manutenção"),
    ("gestor", "gestor123", "Carlos Gestor", "gestor@techmaint.com", "Gestor", "Produção"),
    ("solicitante", "solicitante123", "Ana Solicitante", "ana@techmaint.com", "Usuário Comum", "Produção"),
    ("plima", "plima123", "Pedro Lima", "plima@techmaint.com", "Técnico", "Manutenção"),
]

DEPARTAMENTOS = [   # nome, responsavel (texto) — TI e Infraestrutura apontam para usuarios reais
    ("Produção", "Roberto Alves"), ("Manutenção", "João Silva"), ("Logística", "Fernanda Costa"),
    ("Utilidades", "Paulo Menezes"), ("Administração", "Carla Mendes"), ("TI", None), ("Infraestrutura", None),
]
RESPONSAVEL_USUARIO = {"TI": "admin", "Infraestrutura": "gestor"}

FORNECEDORES = [   # razao, fantasia, cnpj, IE, telefone, e-mail, cep, logradouro, numero, bairro, municipio, uf
    ("TecManutenções LTDA", "TecManutenções", "12345678000190", "110.042.490.114", "(11) 3456-7890",
     "contato@tecmanutencoes.com.br", "01310100", "Avenida Paulista", "1000", "Bela Vista", "São Paulo", "SP"),
    ("Construservice S.A.", "Construservice", "98765432000110", "110.042.490.115", "(11) 9988-7766",
     "vendas@construservice.com.br", "04538132", "Avenida Brigadeiro Faria Lima", "3477", "Itaim Bibi", "São Paulo", "SP"),
    ("Elétrica Forte ME", "Elétrica Forte", "11222333000144", "110.042.490.116", "(11) 88755-4321",
     "contato@eletricaforte.com.br", "03004000", "Rua do Gasômetro", "250", "Brás", "São Paulo", "SP"),
]

PRESTADORES = [   # razao, fantasia, cnpj, telefone, e-mail, cep, logradouro, numero, bairro, municipio, uf, especialidade, ativo
    ("TecServiços Ltda", "TecServiços", "11222333000144", "(11) 4002-1001", "contato@tecservicos.com.br",
     "09710000", "Rua das Indústrias", "120", "Centro", "São Bernardo do Campo", "SP", "Mecânica Geral", 1),
    ("Elétrica Forte ME", "Elétrica Forte", "22333444000155", "(11) 4002-2002", "contato@eletricaforte.com.br",
     "03004000", "Rua do Gasômetro", "250", "Brás", "São Paulo", "SP", "Elétrica Industrial", 1),
    ("Hidro Masters ME", "Hidro Masters", "33444555000166", "(11) 4002-3003", "contato@hidromasters.com.br",
     "09910000", "Avenida Industrial", "800", "Jardim Pinheiros", "Diadema", "SP", "Hidráulica", 0),
]

# codigo, nome, equipamento (descricao exata), valor, minimo, saldo_final_desejado (None = calculado), NCM
PECAS = [
    ("ROL-6204", "Rolamento 6204", "INJETORA 01 - YIZUMI", 15.00, 20, 120, "84821010"),
    ("SEN-IND", "Sensor Indutivo", "INJETORA 02 - YIZUMI", 25.50, 10, 50, "90318099"),
    ("COR-V", "Correia V", "BANBURY 1 - CILINDRO ABERTO", 8.00, 30, 200, "40103900"),
    ("FIL-AR", "Filtro de Ar", "COMPRESSOR METALPLAN", 32.00, 40, 30, "84213990"),
    ("OLE-HID20", "Óleo Hidráulico 20L", "INJETORA 03 - YIZUMI", 189.90, 4, None, "27101932"),
    ("SEL-MEC", "Selo Mecânico", "BOMBA 1 (RESFRIADOR)", 145.00, 3, None, "84842000"),
    ("ROT-BMB", "Rotor de Bomba", "BOMBA 2 (RESFRIADOR)", 320.00, 2, None, "84919000"),
    ("ROL-6205", "Rolamento 6205", "PRENSA 1", 18.50, 15, None, "84821010"),
    ("CTT-25A", "Contator 25A", "SISTEMA DE EXAUSTAO", 62.40, 6, None, "85364900"),
    ("PNE-EMP", "Pneu de Empilhadeira", "EMPILHADEIRA HYSTER 2014", 480.00, 2, None, "40118000"),
    ("COR-ELV", "Corrente de Elevação", "EMPILHADEIRA HYSTER 2014", 260.00, 2, None, "73158200"),
    ("MNG-HID", "Mangueira Hidráulica", "PRENSA 2", 54.90, 8, None, "40093100"),
    ("RES-220", "Resistência Elétrica 220V", "INJETORA 01 - YIZUMI", 78.00, 6, None, "85168000"),
    ("TRM-J", "Termopar Tipo J", "INJETORA 03 - YIZUMI", 36.50, 8, None, "90259000"),
    ("OLE-CMP5", "Óleo de Compressor 5L", "COMPRESSOR METALPLAN", 98.00, 3, None, "27101932"),
    ("VEN-TRR", "Ventilador de Torre", "TORRE DE RESFRIAMENTO", 410.00, 2, None, "84145990"),
    ("BAT-12V", "Bateria 12V 7Ah", "NOBREAK 03 - SMS 1500 VA (SERVIDOR)", 135.00, 4, None, "85072010"),
]

EQUIPAMENTOS_BAIXADOS = ["COMPUTADOR 04 - PC WORK PENTIUM (PRODUCAO)", "IMPRESSORA 01 - HP PHOTOSMART C4400",
                         "ESTABILIZADOR 01 - BMI 1000 VA (IMPR. ELO)"]
# maquinas "principais": recebem a maior parte das OS
EQUIP_PRINCIPAIS = ["INJETORA 01 - YIZUMI", "INJETORA 02 - YIZUMI", "INJETORA 03 - YIZUMI", "BANBURY 1 - CILINDRO ABERTO",
                    "BANBURY 2 - CILINDRO ABERTO", "PRENSA 1", "PRENSA 2", "PRENSA 3", "COMPRESSOR METALPLAN",
                    "BOMBA 2 (RESFRIADOR)", "EMPILHADEIRA HYSTER 2014", "TORRE DE RESFRIAMENTO", "SISTEMA DE EXAUSTAO",
                    "TALHA ELETRICA 4000 KG", "HOMOGEINIZADOR 01", "CILINDRO 1"]

PROBLEMAS = [
    "Ruído anormal durante a operação.", "Vazamento de óleo identificado na base.", "Parada inesperada durante o turno.",
    "Superaquecimento acima do normal.", "Manutenção preventiva programada.", "Falha intermitente no painel de comando.",
    "Vibração excessiva em funcionamento.", "Perda de pressão no sistema.", "Desgaste visível em peça de reposição.",
    "Troca de lubrificante conforme plano.", "Falha de leitura no sensor.", "Equipamento não parte após parada.",
]
SERVICOS = [
    "Retífica e balanceamento", "Rebobinamento de motor", "Revisão do sistema hidráulico", "Calibração e ajuste fino",
    "Soldagem especializada", "Manutenção corretiva terceirizada", "Inspeção técnica e laudo",
]
OBS_APONTAMENTO = ["Diagnóstico realizado.", "Peça substituída e testada.", "Limpeza e lubrificação concluídas.",
                   "Ajuste fino após teste de carga.", "Aguardando liberação da produção.", "Serviço concluído e validado."]


# ---------------------------------------------------------------------------
# Utilitarios
# ---------------------------------------------------------------------------
def _dt(dia, hora=None, rng=None):
    """date -> 'AAAA-MM-DD HH:MM:SS' (hora fixa ou sorteada entre 07h e 17h)."""
    if hora is None:
        hora = (rng.randint(7, 17), rng.choice((0, 15, 30, 45)), 0) if rng else (8, 0, 0)
    return datetime(dia.year, dia.month, dia.day, *hora).strftime("%Y-%m-%d %H:%M:%S")


def _iso(dia):
    return dia.isoformat()


def _limitar(dia, minimo, maximo):
    return max(minimo, min(dia, maximo))


# ---------------------------------------------------------------------------
# 1. Dados de referencia (sempre idempotentes)
# ---------------------------------------------------------------------------
def semear_referencia(db):
    novos = {"departamentos": 0, "usuarios": 0}
    # departamentos
    for nome, resp in DEPARTAMENTOS:
        cur = db.execute("INSERT OR IGNORE INTO departamentos (nome, responsavel_nome) VALUES (?, ?)", (nome, resp))
        novos["departamentos"] += cur.rowcount
    # usuarios de demonstracao
    perfis = {r["nome"]: r["id"] for r in db.execute("SELECT id, nome FROM perfis")}
    deptos = {r["nome"]: r["id"] for r in db.execute("SELECT id, nome FROM departamentos")}
    ids_usuario = {}
    for login, senha, nome, email, perfil, depto in USUARIOS:
        u = db.execute("SELECT id FROM usuarios WHERE login = ?", (login,)).fetchone()
        if u is None:
            cur = db.execute(
                "INSERT INTO usuarios (nome, login, senha_hash, email, ativo, data_cadastro, id_departamento) "
                "VALUES (?, ?, ?, ?, 1, ?, ?)",
                (nome, login, gerar_hash(senha), email, _dt(hoje() - timedelta(days=400)), deptos[depto]))
            db.execute("INSERT INTO usuarios_perfis (id_usuario, id_perfil) VALUES (?, ?)", (cur.lastrowid, perfis[perfil]))
            novos["usuarios"] += 1
            ids_usuario[login] = cur.lastrowid
        else:
            ids_usuario[login] = u["id"]
    # responsaveis "reais" dos departamentos TI e Infraestrutura (so se ainda nao tem responsavel)
    for depto, login in RESPONSAVEL_USUARIO.items():
        nome = next(u[2] for u in USUARIOS if u[0] == login)
        db.execute("UPDATE departamentos SET responsavel_id = ?, responsavel_nome = ? WHERE nome = ? "
                   "AND responsavel_id IS NULL AND responsavel_nome IS NULL", (ids_usuario[login], nome, depto))

    # grupos, subgrupos e equipamentos do documento de apoio
    grupos = json.loads((DADOS / "grupos.json").read_text(encoding="utf-8"))
    subgrupos = json.loads((DADOS / "subgrupos.json").read_text(encoding="utf-8"))
    equipamentos = json.loads((DADOS / "equipamentos.json").read_text(encoding="utf-8"))
    for g in grupos:
        db.execute("INSERT OR IGNORE INTO grupos (id, nome) VALUES (?, ?)", (g["id"], g["nome"]))
    for s in subgrupos:
        db.execute("INSERT OR IGNORE INTO subgrupos (id, nome, id_grupo) VALUES (?, ?, ?)",
                   (s["id"], s["nome"], s["id_grupo"]))
    deptos = {r["nome"]: r["id"] for r in db.execute("SELECT id, nome FROM departamentos")}
    vida_util = {"TI": 60, "Logística": 96}
    for e in equipamentos:
        cur = db.execute(
            "INSERT OR IGNORE INTO equipamentos (codigo, descricao, id_grupo, id_subgrupo, id_departamento, status, "
            "controla_depreciacao, patrimoniado, vida_util_meses) VALUES (?, ?, ?, ?, ?, 'Ativo', 1, 1, ?)",
            (e["codigo"], e["descricao"], e["id_grupo"], e["id_subgrupo"], deptos[e["departamento"]],
             vida_util.get(e["departamento"], 120)))
        novos["equipamentos"] = novos.get("equipamentos", 0) + cur.rowcount
    return ids_usuario, novos


# ---------------------------------------------------------------------------
# 2. Dados de demonstracao (uma unica vez)
# ---------------------------------------------------------------------------
class Demo:
    def __init__(self, db, ids_usuario):
        self.db = db
        self.rng = random.Random(2026)
        self.hoje = hoje()
        self.mes_ini = self.hoje.replace(day=1)
        self.u = ids_usuario
        self.nomes = {login: nome for login, _s, nome, *_ in USUARIOS}
        self.eq = {r["descricao"]: dict(r) for r in db.execute("SELECT * FROM equipamentos")}
        self.deptos = {r["nome"]: r["id"] for r in db.execute("SELECT id, nome FROM departamentos")}
        self.pecas = {}               # codigo -> dict (id, valor, ...)
        self.movs = {}                # id_peca -> saldo liquido dos movimentos (ex.: sem a entrada inicial)
        self.prest = []
        self.forn = []
        self.os_dados = []

    # ---- auxiliares -------------------------------------------------------
    def hist(self, entidade, id_entidade, acao, usuario, data, detalhe):
        self.db.execute("INSERT INTO historico_alteracoes (entidade, id_entidade, acao, usuario, data, detalhe) "
                        "VALUES (?, ?, ?, ?, ?, ?)", (entidade, id_entidade, acao, usuario, data, detalhe))

    def mov(self, codigo, tipo, qtd, valor, data, doc, numero, obs, login, id_nf=None, id_os=None):
        p = self.pecas[codigo]
        self.db.execute(
            "INSERT INTO movimentacao_estoque_pecas (id_peca, tipo, quantidade, valor_unitario, data, documento_origem, "
            "numero_documento, observacao, id_usuario, id_nota_fiscal, id_os) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (p["id"], tipo, qtd, round(valor, 2), data, doc, numero, obs, self.u[login] if login else None, id_nf, id_os))
        self.movs[p["id"]] = self.movs.get(p["id"], 0) + (qtd if tipo == "Entrada" else -qtd)

    # ---- fornecedores, prestadores e pecas ------------------------------------
    def parceiros(self):
        db = self.db
        for f in FORNECEDORES:
            cur = db.execute(
                "INSERT OR IGNORE INTO fornecedores (razao_social, fantasia, cnpj, inscricao_estadual, telefone, email, cep, "
                "logradouro, numero, bairro, municipio, uf, ativo) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)", f)
            self.forn.append(db.execute("SELECT id FROM fornecedores WHERE cnpj = ?", (f[2],)).fetchone()["id"])
        for p in PRESTADORES:
            db.execute(
                "INSERT OR IGNORE INTO prestadores_servico (razao_social, fantasia, cnpj, telefone, email, cep, logradouro, "
                "numero, bairro, municipio, uf, especialidade, ativo) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", p)
            self.prest.append(db.execute("SELECT id FROM prestadores_servico WHERE cnpj = ?", (p[2],)).fetchone()["id"])

    def criar_pecas(self):
        for codigo, nome, equip, valor, minimo, _alvo, ncm in PECAS:
            cur = self.db.execute(
                "INSERT INTO pecas (codigo, id_equipamento, nome, ncm, valor_unitario, qtde_estoque, estoque_minimo) "
                "VALUES (?, ?, ?, ?, ?, 0, ?)", (codigo, self.eq[equip]["id"], nome, ncm, valor, minimo))
            self.pecas[codigo] = {"id": cur.lastrowid, "valor": valor, "minimo": minimo, "equip": equip, "nome": nome}

    # ---- notas fiscais ---------------------------------------------------------
    def nota_fiscal(self, forn_idx, dia, itens, numero):
        """itens = [(codigo, qtd, valor_unit)]; cria NF + itens + movimentos de Entrada."""
        total = round(sum(q * v for _c, q, v in itens), 2)
        chave = "".join(str(self.rng.randint(0, 9)) for _ in range(44))
        cur = self.db.execute(
            "INSERT INTO notas_fiscais (id_fornecedor, numero_nf, chave_acesso, serie_nf, data_emissao, data_entrada, cfop, "
            "valor_total_nf, valor_frete, valor_ipi, valor_icms, observacao) VALUES (?, ?, ?, '1', ?, ?, '1102', ?, 0, 0, 0, ?)",
            (self.forn[forn_idx], numero, chave, _iso(dia - timedelta(days=1)), _iso(dia), total, "Compra de reposição (demonstração)"))
        id_nf = cur.lastrowid
        for codigo, qtd, valor in itens:
            p = self.pecas[codigo]
            self.db.execute(
                "INSERT INTO itens_nota_fiscal (id_nota_fiscal, id_peca, descricao_item, ncm, cfop, qtde, valor_unitario, valor_total) "
                "VALUES (?, ?, ?, ?, '1102', ?, ?, ?)",
                (id_nf, p["id"], p["nome"], self.db.execute("SELECT ncm FROM pecas WHERE id = ?", (p["id"],)).fetchone()[0],
                 qtd, valor, round(qtd * valor, 2)))
            self.mov(codigo, "Entrada", qtd, valor, _dt(dia, (9, 30, 0)), "Nota Fiscal", f"NF-{numero:06d}",
                     "Entrada por nota fiscal", "tecnico", id_nf=id_nf)
        self.hist("nota_fiscal", id_nf, "criar", self.nomes["tecnico"], _dt(dia, (9, 30, 0)), f"NF {numero} lançada")
        return id_nf

    # ---- pedidos e OS ----------------------------------------------------------
    def pedido(self, pid, equip, dia, solicitante, prioridade, status, descricao=None, aprovado=None):
        e = self.eq[equip]
        login = solicitante
        ap_por = self.nomes["gestor"] if aprovado else None
        self.db.execute(
            "INSERT INTO pedidos_manutencao (id, id_equipamento, id_departamento, data_solicitacao, solicitante, "
            "id_usuario_solicitante, descricao_problema, prioridade, status, aprovado_por, data_aprovacao) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (pid, e["id"], e["id_departamento"], _iso(dia), self.nomes[login], self.u[login],
             descricao or self.rng.choice(PROBLEMAS), prioridade, status, ap_por,
             _iso(min(dia + timedelta(days=1), self.hoje)) if aprovado else None))
        self.hist("pedido", pid, "criar", self.nomes[login], _dt(dia, rng=self.rng), f"Pedido #{pid} aberto")
        if aprovado:
            self.hist("pedido", pid, "aprovar", self.nomes["gestor"], _dt(dia, (16, 0, 0)), "Pedido aprovado")

    def ordem(self, oid, pid, equip, abertura, fechamento, tecnico, status, pecas=(), servicos=(), apontamentos=1,
              observacao=None):
        """Cria a OS e seus itens/servicos/apontamentos. `pecas` = [(codigo, qtd)]; `servicos` = [(desc, valor, idx_prestador)]."""
        db, rng = self.db, self.rng
        e = self.eq[equip]
        db.execute(
            "INSERT INTO ordens_servico (id, id_pedido, id_equipamento, data_abertura, data_fechamento, id_tecnico, "
            "responsavel, status, observacao) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (oid, pid, e["id"], abertura, fechamento, self.u[tecnico], self.nomes[tecnico], status, observacao))
        self.hist("os", oid, "criar", self.nomes[tecnico], abertura, f"OS-{oid} aberta para {self.nomes[tecnico]}")
        dia_ab = date.fromisoformat(abertura[:10])
        for codigo, qtd in pecas:
            p = self.pecas[codigo]
            db.execute("INSERT INTO itens_os (id_os, id_peca, quantidade, valor_unitario, valor_total) VALUES (?, ?, ?, ?, ?)",
                       (oid, p["id"], qtd, p["valor"], round(qtd * p["valor"], 2)))
            self.mov(codigo, "Saída", qtd, p["valor"], abertura, "Ordem de Serviço", f"OS-{oid}",
                     f"Peça lançada na OS-{oid}", tecnico, id_os=oid)
        for desc, valor, idx in servicos:
            db.execute("INSERT INTO servicos_os (id_os, descricao_servico, valor_servico, id_prestador) VALUES (?, ?, ?, ?)",
                       (oid, desc, valor, self.prest[idx] if idx is not None else None))
        limite = date.fromisoformat(fechamento[:10]) if fechamento else self.hoje
        for i in range(apontamentos):
            dia = _limitar(dia_ab + timedelta(days=rng.randint(0, max(0, (limite - dia_ab).days))), dia_ab, limite)
            db.execute("INSERT INTO apontamentos_os (id_os, data, tecnico, horas_trabalhadas, tipo, observacao) "
                       "VALUES (?, ?, ?, ?, ?, ?)",
                       (oid, _iso(dia), self.nomes[tecnico], rng.choice((0.5, 1, 1.5, 2, 3, 4, 6, 8)),
                        rng.choice(manutencao.TIPOS_APONTAMENTO), rng.choice(OBS_APONTAMENTO)))
        if status == "Concluída":
            self.hist("os", oid, "fechar", self.nomes[tecnico], fechamento, f"OS-{oid} concluída")
        elif status == "Cancelada":
            self.hist("os", oid, "status", self.nomes[tecnico], abertura, "Aberta → Cancelada")

    def itens_sorteados(self, equip, dia):
        """0 a 3 pecas (ate o mes anterior ao atual: o mes corrente so tem as 4 movimentacoes do Figma)."""
        if dia >= self.mes_ini:
            return []
        rng = self.rng
        proprias = [c for c, p in self.pecas.items() if p["equip"] == equip]
        candidatas = [c for c in self.pecas if c not in ("ROL-6204", "COR-V", "FIL-AR") or rng.random() < 0.6]
        n = rng.choices((0, 1, 2, 3), weights=(25, 40, 25, 10))[0]
        escolhidas = []
        for _ in range(n):
            c = rng.choice(proprias) if proprias and rng.random() < 0.6 else rng.choice(candidatas)
            if c not in escolhidas:
                escolhidas.append(c)
        saida = []
        for c in escolhidas:
            v = self.pecas[c]["valor"]
            saida.append((c, rng.randint(1, 4 if v < 100 else 2)))
        return saida

    def servicos_sorteados(self, id_os_ref=None):
        rng = self.rng
        if rng.random() < 0.55:
            return [(rng.choice(SERVICOS), round(rng.randint(35, 520) * 10 + rng.choice((0, 0, 50)), 2),
                     rng.choice((0, 0, 1, 1, 2)))]
        return []

    # ---- fluxo principal ---------------------------------------------------------
    def gerar(self):
        rng, D, M = self.rng, self.hoje, self.mes_ini
        self.parceiros()
        self.criar_pecas()

        # --- pedidos/OS do Figma (datas fixas) -------------------------------------------
        self.pedido(1621, "INJETORA 01 - YIZUMI", date(2026, 9, 7), "plima", "Média", "Em andamento",
                    "Troca de resistência e verificação do termopar.")
        self.pedido(1623, "BOMBA 1 (RESFRIADOR)", date(2026, 9, 11), "solicitante", "Alta", "Em andamento",
                    "Vazamento no selo da bomba do resfriador.")
        self.pedido(1624, "INJETORA 02 - YIZUMI", _limitar(D - timedelta(days=2), date(2020, 1, 1), D), "solicitante", "Média",
                    "Aberto", "Injetora parando durante o ciclo de injeção.")
        self.pedido(1625, "EMPILHADEIRA HYSTER 2014", date(2026, 9, 9), "gestor", "Baixa", "Concluído",
                    "Troca de pneu dianteiro.")
        self.pedido(1626, "COMPRESSOR METALPLAN", _limitar(D - timedelta(days=4), date(2020, 1, 1), D), "solicitante", "Média",
                    "Aberto", "Queda de pressão e filtro saturado.")
        # OS-10232 (Aberta), OS-10233 (Concluida), OS-10234 (Em andamento)
        self.ordem(10232, 1621, "INJETORA 01 - YIZUMI", "2026-09-08 08:00:00", None, "tecnico", "Aberta", apontamentos=0,
                   observacao="Aguardando chegada da resistência.")
        self.ordem(10233, 1625, "EMPILHADEIRA HYSTER 2014", "2026-09-10 08:30:00", "2026-09-11 15:45:00", "tecnico",
                   "Concluída", pecas=[("PNE-EMP", 1)], servicos=[("Montagem e balanceamento de pneu", 180.00, 0)],
                   apontamentos=2, observacao="Pneu dianteiro trocado.")
        self.ordem(10234, 1623, "BOMBA 1 (RESFRIADOR)", "2026-09-12 09:15:00", None, "tecnico", "Em andamento",
                   pecas=[("SEL-MEC", 1)], apontamentos=1, observacao="Selo substituído; aguardando teste de vazamento.")
        em_manutencao = {"BOMBA 1 (RESFRIADOR)": "2026-09-12 09:15:00"}

        # --- historico: 100 pedidos (ids 1521-1620) ----------------------------------------
        baixados = set(EQUIPAMENTOS_BAIXADOS)
        ativos = [d for d, e in self.eq.items() if d not in baixados]
        pesos = [8 if d in EQUIP_PRINCIPAIS else 1 for d in ativos]

        def sorteia_equip(excluir=()):
            while True:
                d = rng.choices(ativos, weights=pesos)[0]
                if d not in excluir and d not in em_manutencao:
                    return d

        def aleat(ini, fim):
            if fim < ini:
                return ini
            return ini + timedelta(days=rng.randint(0, (fim - ini).days))

        def prioridade():
            return rng.choices(("Baixa", "Média", "Alta"), weights=(30, 45, 25))[0]

        solicitantes = ["solicitante", "solicitante", "gestor", "tecnico", "plima", "admin"]
        tecnicos = ["tecnico", "plima", "tecnico"]
        itens = []     # registros a criar, depois ordenados por data
        for k in range(63):    # concluidos antes do mes atual (distribuidos pelos ultimos 11 meses)
            ini_mes = soma_meses(M, -(11 - k % 11))
            fim_mes = min(soma_meses(ini_mes, 1) - timedelta(days=1), M - timedelta(days=12))
            itens.append({"tipo": "concluido", "ab": aleat(max(ini_mes, D - timedelta(days=360)), fim_mes)})
        for _ in range(18):    # concluidos neste mes
            ab = aleat(M - timedelta(days=9), max(M - timedelta(days=9), D - timedelta(days=1)))
            itens.append({"tipo": "concluido_mes", "ab": ab})
        for i in range(5):     # cancelados (2 deles tiveram uma OS aberta e cancelada antes do pedido ser cancelado)
            itens.append({"tipo": "cancelado", "ab": aleat(D - timedelta(days=300), D - timedelta(days=20)),
                          "os_cancelada": i < 2})
        for _ in range(4):     # em andamento
            itens.append({"tipo": "andamento", "ab": aleat(D - timedelta(days=14), D - timedelta(days=3))})
        recentes = [D - timedelta(days=i) for i in (0, 1, 3, 5, 6, 9, 12, 15, 18, 22)]
        for i, dia in enumerate(recentes):     # abertos (sem OS; o de indice 3 e prioridade Alta, para o alerta)
            itens.append({"tipo": "aberto", "ab": dia, "alta": i == 3})
        itens.sort(key=lambda x: x["ab"])

        pid, oid = 1521, 10132
        usados_em_manutencao = set(em_manutencao)
        for it in itens:
            tipo, ab = it["tipo"], it["ab"]
            ab = _limitar(ab, D - timedelta(days=365), D)
            excl = usados_em_manutencao if tipo == "andamento" else ()
            equip = sorteia_equip(excl)
            solic = rng.choice(solicitantes)
            prio = "Alta" if it.get("alta") else prioridade()
            if tipo == "andamento":
                usados_em_manutencao.add(equip)
                em_manutencao[equip] = None
            status_ped = {"concluido": "Concluído", "concluido_mes": "Concluído", "cancelado": "Cancelado",
                          "andamento": "Em andamento", "aberto": "Aberto"}[tipo]
            self.pedido(pid, equip, ab, solic, prio, status_ped, aprovado=tipo in ("concluido", "concluido_mes", "andamento")
                        and rng.random() < 0.7)
            if tipo == "cancelado":
                if it.get("os_cancelada"):
                    tec = rng.choice(tecnicos)
                    abertura = _dt(_limitar(ab + timedelta(days=1), ab, D), rng=rng)
                    self.ordem(oid, pid, equip, abertura, None, tec, "Cancelada", apontamentos=0,
                               observacao="OS cancelada: equipamento liberado pela produção.")
                    oid += 1
                self.hist("pedido", pid, "cancelar", self.nomes["gestor"], _dt(ab + timedelta(days=2) if ab + timedelta(days=2) <= D else ab, (17, 0, 0)),
                          "Pedido cancelado")
            elif tipo in ("concluido", "concluido_mes", "andamento"):
                tec = rng.choice(tecnicos)
                dia_ab = _limitar(ab + timedelta(days=rng.choice((0, 1, 1, 2))), ab, D)
                abertura = _dt(dia_ab, rng=rng)
                if tipo == "concluido_mes":
                    fim_dia = _limitar(dia_ab + timedelta(days=rng.randint(0, 3)), M, D)
                    fim_dia = max(fim_dia, dia_ab)
                    horas = rng.randint(2, 40)
                    ab_dt = datetime.strptime(abertura, "%Y-%m-%d %H:%M:%S")
                    fim = max(ab_dt + timedelta(hours=horas), datetime(fim_dia.year, fim_dia.month, fim_dia.day, 8, 0, 0))
                    fim = min(fim, datetime(D.year, D.month, D.day, 23, 59, 0))
                    if fim < ab_dt:
                        fim = ab_dt + timedelta(hours=1)
                    fechamento = fim.strftime("%Y-%m-%d %H:%M:%S")
                    status_os = "Concluída"
                elif tipo == "concluido":
                    ab_dt = datetime.strptime(abertura, "%Y-%m-%d %H:%M:%S")
                    horas = rng.choice((4, 6, 8, 12, 18, 24, 30, 36, 48, 60, 72, 96))
                    fim = ab_dt + timedelta(hours=horas + rng.randint(0, 5))
                    fechamento, status_os = fim.strftime("%Y-%m-%d %H:%M:%S"), "Concluída"
                else:
                    fechamento, status_os = None, "Em andamento"
                    em_manutencao[equip] = abertura
                pecas = self.itens_sorteados(equip, dia_ab)
                servicos = self.servicos_sorteados()
                self.ordem(oid, pid, equip, abertura, fechamento, tec, status_os, pecas=pecas, servicos=servicos,
                           apontamentos=rng.randint(1, 3) if status_os == "Concluída" else 1,
                           observacao="Manutenção executada conforme solicitação." if status_os == "Concluída" else None)
                oid += 1
            pid += 1
        assert pid == 1621, f"historico deveria ocupar os ids 1521-1620 (parou em {pid})"
        return em_manutencao

    # ---- estoque ----------------------------------------------------------------------
    def estoque(self):
        rng, D, M = self.rng, self.hoje, self.mes_ini
        # NFs historicas de reposicao (so pecas "livres" e meses anteriores ao atual)
        livres = [p[0] for p in PECAS if p[5] is None]
        numero = 4100
        for i in range(10):
            dia = _limitar(D - timedelta(days=rng.randint(40, 330)), D - timedelta(days=400), M - timedelta(days=5))
            lote = []
            for c in rng.sample(livres, rng.randint(1, 3)):
                v = self.pecas[c]["valor"]
                lote.append((c, rng.randint(2, 12) if v >= 100 else rng.randint(6, 30), round(v * rng.choice((0.95, 1.0, 1.0)), 2)))
            self.nota_fiscal(i % 3, dia, lote, numero + i * 37)

        # Movimentacoes do mes atual (Figma: 4 movimentos, R$ 1.390,00 de entradas e R$ 54,00 de saidas)
        def no_mes(dias):
            return _limitar(D - timedelta(days=dias), M, D)
        self.nota_fiscal(0, no_mes(8), [("ROL-6204", 50, 15.00)], 5821)
        self.nota_fiscal(1, no_mes(6), [("COR-V", 80, 8.00)], 3310)
        self.mov("ROL-6204", "Saída", 2, 15.00, _dt(no_mes(4), (10, 20, 0)), "Pedido Interno", "PI-000041",
                 "Retirada para manutenção preventiva", "tecnico")
        self.mov("COR-V", "Saída", 3, 8.00, _dt(no_mes(2), (14, 10, 0)), "Pedido Interno", "PI-000042",
                 "Reposição de correias na prensa", "plima")

        # Entrada inicial (balanco) e saldos finais
        abertura_estoque = _dt(D - timedelta(days=390), (8, 0, 0))
        for codigo, nome, equip, valor, minimo, alvo, _ncm in PECAS:
            p = self.pecas[codigo]
            liquido = self.movs.get(p["id"], 0)
            if alvo is not None:
                inicial = alvo - liquido
                assert inicial > 0, f"saldo inicial de {nome} ficaria <= 0 ({inicial})"
            else:
                desejado = minimo + (rng.randint(3, 25) if valor < 100 else rng.randint(2, 6))
                inicial = max(desejado - liquido, minimo + 2)
            self.mov(codigo, "Entrada", inicial, valor, abertura_estoque, "Pedido Interno", "ESTOQUE-INICIAL",
                     "Saldo inicial (implantação do sistema)", "admin")
        # saldo oficial = soma dos movimentos; tabela estoque_pecas em sincronia
        for codigo, nome, equip, valor, minimo, alvo, _ncm in PECAS:
            p = self.pecas[codigo]
            saldo = round(self.movs[p["id"]], 3)
            if alvo is not None:
                assert saldo == alvo, f"saldo final de {nome}: {saldo} != {alvo}"
            self.db.execute("UPDATE pecas SET qtde_estoque = ? WHERE id = ?", (saldo, p["id"]))
            self.db.execute(
                "INSERT INTO estoque_pecas (id_peca, qtde_atual, localizacao, estoque_minimo, ultima_atualizacao) "
                "VALUES (?, ?, 'Almoxarifado', ?, ?)", (p["id"], saldo, minimo, _dt(D, (8, 0, 0))))

    # ---- equipamentos ---------------------------------------------------------------------
    def equipamentos(self, em_manutencao):
        db = self.db
        for desc in EQUIPAMENTOS_BAIXADOS:
            e = self.eq[desc]
            db.execute("UPDATE equipamentos SET status = 'Baixado' WHERE id = ?", (e["id"],))
            db.execute("INSERT INTO movimentacao_equipamentos (id_equipamento, id_departamento, tipo_movimento, data, "
                       "responsavel, observacao) VALUES (?, ?, 'Baixa', ?, ?, 'Equipamento obsoleto (demonstração)')",
                       (e["id"], e["id_departamento"], _dt(self.hoje - timedelta(days=200), (9, 0, 0)), self.nomes["admin"]))
        for desc, abertura in em_manutencao.items():
            e = self.eq[desc]
            db.execute("UPDATE equipamentos SET status = 'Em manutenção' WHERE id = ?", (e["id"],))
            db.execute("INSERT INTO movimentacao_equipamentos (id_equipamento, id_departamento, tipo_movimento, data, "
                       "responsavel, observacao) VALUES (?, ?, 'Saída para manutenção', ?, ?, 'Status: Ativo → Em manutenção')",
                       (e["id"], e["id_departamento"], abertura, None))
        for r in db.execute("SELECT id FROM equipamentos").fetchall():
            manutencao.garantir_estoque_equipamento(db, r["id"])


# ---------------------------------------------------------------------------
# Execucao
# ---------------------------------------------------------------------------
def popular(caminho=None, verbose=True):
    """Cria o que falta. Devolve um dicionario com o que foi inserido nesta execucao."""
    database.init_db(caminho)
    db = database.conectar(caminho)
    resumo = {}
    try:
        with transacao(db):
            ids_usuario, novos = semear_referencia(db)
            resumo.update(novos)
            if db.execute("SELECT 1 FROM parametros WHERE chave = 'seed_demo'").fetchone() is None:
                demo = Demo(db, ids_usuario)
                em_manutencao = demo.gerar()
                demo.estoque()
                demo.equipamentos(em_manutencao)
                db.execute("INSERT INTO parametros (chave, valor) VALUES ('seed_demo', '1')")
                resumo["demonstracao"] = "criada"
            else:
                resumo["demonstracao"] = "já existia (nada foi repetido)"
        if verbose:
            _imprimir_resumo(db, resumo)
    finally:
        db.close()
    return resumo


def _imprimir_resumo(db, resumo):
    def n(sql):
        return db.execute(sql).fetchone()[0]
    print("TechMaint - dados de demonstração")
    print(f"  banco: {database.caminho_banco()}")
    print(f"  demonstração: {resumo['demonstracao']}")
    for rotulo, tabela in (("usuários", "usuarios"), ("departamentos", "departamentos"), ("grupos", "grupos"),
                           ("subgrupos", "subgrupos"), ("equipamentos", "equipamentos"), ("peças", "pecas"),
                           ("fornecedores", "fornecedores"), ("prestadores", "prestadores_servico"),
                           ("pedidos", "pedidos_manutencao"), ("ordens de serviço", "ordens_servico"),
                           ("movimentos de estoque", "movimentacao_estoque_pecas")):
        print(f"  {rotulo:<24}{n(f'SELECT COUNT(*) FROM {tabela}')}")
    print("  logins: admin/admin123 · tecnico/tecnico123 · gestor/gestor123 · solicitante/solicitante123 · plima/plima123")


# nomes alternativos (quem importar o seed por outro nome)
seed = main_seed = executar = popular


def main(argv=None):
    ap = argparse.ArgumentParser(description="Popula o banco do TechMaint com dados de demonstração.")
    ap.add_argument("--limpar", action="store_true", help="APAGA o banco atual e recria do zero (só desenvolvimento).")
    args = ap.parse_args(argv)
    if args.limpar:
        caminho = database.caminho_banco()
        for sufixo in ("", "-wal", "-shm", "-journal"):
            try:
                os.remove(caminho + sufixo)
            except FileNotFoundError:
                pass
        print(f"Banco {caminho} apagado.")
    popular()
    return 0


if __name__ == "__main__":
    sys.exit(main())
