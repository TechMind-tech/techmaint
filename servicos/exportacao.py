"""
exportacao.py (servicos)
------------------------
Gera os arquivos de exportacao do Dashboard e dos Relatorios:

    PDF  (reportlab)   -> `gerar_pdf(documento)`
    XLSX (openpyxl)    -> `gerar_xlsx(documento)`
    CSV  (modulo csv)  -> `gerar_csv(tabela)`

Todos recebem o mesmo "documento" (um dict simples), montado por `doc_dashboard` ou `doc_relatorio`:

    {"titulo": "...", "filtros": [("Período", "Último ano"), ...],
     "secoes": [{"titulo", "colunas", "linhas", "rodape", "alinhamentos"}, ...]}

Cabecalho de todo arquivo: "TechMaint", titulo, filtros aplicados e data/hora da emissao.

Seguranca: texto vindo do banco nunca vira formula (Excel/CSV: "CSV injection") nem
markup (PDF: o texto e escapado antes de ir para o reportlab).
"""

import csv
import io
import re
from xml.sax.saxutils import escape

from servicos.formatacao import agora, moeda

NOME_SISTEMA = "TechMaint - Sistema de Gestão de Manutenção"
MIME_PDF = "application/pdf"
MIME_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
MIME_CSV = "text/csv; charset=utf-8"

PERIGOSOS = ("=", "+", "-", "@", "\t", "\r")          # inicios que o Excel interpreta como formula

RE_MOEDA = re.compile(r"^R\$\s?(-?\d{1,3}(?:\.\d{3})*,\d{2}|-?\d+,\d{2})$")
RE_NUMERO = re.compile(r"^-?(?:[1-9]\d{0,2}(?:\.\d{3})+|[1-9]\d*|0)(?:,\d+)?$")


# ---------------------------------------------------------------------------
# Montagem do "documento"
# ---------------------------------------------------------------------------
def _secao(titulo, colunas, linhas, rodape=None, alinhamentos=None):
    return {"titulo": titulo, "colunas": list(colunas), "linhas": [list(l) for l in linhas],
            "rodape": list(rodape or []), "alinhamentos": alinhamentos or ["esq"] * len(colunas)}


def _secao_do_grafico(g):
    unidade = g.get("unidade") or ""
    cab = "Valor (R$)" if unidade == "R$" else "Valor"
    linhas = [[str(r), moeda(v) if unidade == "R$" else _num_txt(v)] for r, v in zip(g["rotulos"], g["valores"])]
    return _secao(g["titulo"], ["Item", cab], linhas, alinhamentos=["esq", "dir"])


def _num_txt(v):
    if isinstance(v, float) and not v.is_integer():
        return f"{v:.2f}".replace(".", ",")
    return str(int(v))


def doc_relatorio(titulo_aba, rel, filtros):
    """`rel` = resultado de indicadores.relatorio(); `filtros` = lista de (rotulo, valor)."""
    t = rel["tabela"]
    secoes = [_secao(t["titulo"], t["colunas"], t["linhas"], t.get("rodape"), t.get("alinhamentos"))]
    secoes += [_secao_do_grafico(g) for g in rel["graficos"] if g["rotulos"]]
    return {"titulo": f"Relatório - {titulo_aba}", "filtros": filtros, "secoes": secoes,
            "graficos": rel["graficos"]}


def doc_dashboard(dados, filtros):
    """`dados` = resultado de indicadores.dashboard()."""
    k = dados["kpis"]
    linhas = [[c["titulo"], c["valor_fmt"], c["detalhe"]] for c in k["cards"]]
    secoes = [_secao("Indicadores principais", ["Indicador", "Valor", "Detalhe"], linhas)]
    secoes.append(_secao("Tempo médio de atendimento (horas)", ["Período", "Horas"],
                         [[x["rotulo"], _num_txt(x["valor"])] for x in dados["tempo_medio"]], alinhamentos=["esq", "dir"]))
    if k["financeiro_visivel"]:
        secoes.append(_secao("Custo por máquina (R$)", ["Máquina", "Custo"],
                             [[x["rotulo"], moeda(x["valor"])] for x in dados["custo_por_maquina"]],
                             alinhamentos=["esq", "dir"]))
    secoes.append(_secao("Peças mais utilizadas", ["Peça", "Quantidade"],
                         [[x["rotulo"], _num_txt(x["valor"])] for x in dados["pecas_mais_usadas"]],
                         alinhamentos=["esq", "dir"]))
    secoes.append(_secao("Status das ordens", ["Status", "Ordens"],
                         [[x["rotulo"], _num_txt(x["valor"])] for x in dados["status_ordens"]],
                         alinhamentos=["esq", "dir"]))
    return {"titulo": "Dashboard de Indicadores", "filtros": filtros, "secoes": secoes}


def _emissao():
    return agora().strftime("%d/%m/%Y %H:%M")


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------
def _csv_seguro(celula):
    texto = "" if celula is None else str(celula)
    return "'" + texto if texto.startswith(PERIGOSOS) else texto


def gerar_csv(secao):
    """CSV em UTF-8 com BOM (o Excel brasileiro abre com acentos) e ';' como separador."""
    saida = io.StringIO()
    w = csv.writer(saida, delimiter=";", lineterminator="\r\n")
    w.writerow([_csv_seguro(c) for c in secao["colunas"]])
    for linha in secao["linhas"]:
        w.writerow([_csv_seguro(c) for c in linha])
    if secao["rodape"]:
        w.writerow([_csv_seguro(c) for c in secao["rodape"]])
    return ("﻿" + saida.getvalue()).encode("utf-8")


# ---------------------------------------------------------------------------
# XLSX
# ---------------------------------------------------------------------------
def _converter_celula(texto):
    """'R$ 1.234,50' -> (1234.5, formato moeda); '1.250' -> (1250, '#,##0'); resto = texto."""
    if not isinstance(texto, str):
        return texto, None
    t = texto.strip()
    if RE_MOEDA.match(t):
        return float(t.replace("R$", "").strip().replace(".", "").replace(",", ".")), '"R$" #,##0.00'
    if RE_NUMERO.match(t) and len(re.sub(r"\D", "", t)) <= 9:       # telefones/CNPJ puros ficam como texto
        valor = float(t.replace(".", "").replace(",", "."))
        if "," in t:
            return valor, "#,##0.00"
        return int(valor), "#,##0"
    return texto, None


def _escrever(ws, linha, coluna, valor, **estilo):
    c = ws.cell(row=linha, column=coluna)
    novo, formato = _converter_celula(valor)
    c.value = novo
    if isinstance(novo, str):
        c.data_type = "s"                 # texto puro: nunca formula, mesmo comecando com "="
    if formato:
        c.number_format = formato
    for nome, v in estilo.items():
        setattr(c, nome, v)
    return c


def gerar_xlsx(doc):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = "Relatório"[:31]
    azul = PatternFill("solid", fgColor="0B2A4A")
    cinza = PatternFill("solid", fgColor="EEF2F6")
    borda = Border(bottom=Side(style="thin", color="C9D3DE"))

    r = 1
    _escrever(ws, r, 1, NOME_SISTEMA, font=Font(bold=True, size=14, color="0B2A4A"))
    r += 1
    _escrever(ws, r, 1, doc["titulo"], font=Font(bold=True, size=12))
    r += 1
    _escrever(ws, r, 1, f"Emitido em {_emissao()}")
    for rot, val in doc["filtros"]:
        r += 1
        _escrever(ws, r, 1, f"{rot}: {val}")
    r += 2

    larguras = {}

    def _largura(col, texto):
        larguras[col] = max(larguras.get(col, 10), min(len(str(texto)) + 2, 60))

    for i, sec in enumerate(doc["secoes"]):
        alvo = ws
        if i > 0 and len(doc["secoes"]) > 1 and "graficos" in doc:
            # relatorios: tabela principal na 1a aba, dados dos graficos numa aba a parte
            if i == 1:
                ws2 = wb.create_sheet("Gráficos")
                r2 = 1
            alvo, r_atual = ws2, r2
        else:
            r_atual = r
        _escrever(alvo, r_atual, 1, sec["titulo"], font=Font(bold=True, size=12, color="0B2A4A"))
        r_atual += 1
        for j, c in enumerate(sec["colunas"], start=1):
            _escrever(alvo, r_atual, j, c, font=Font(bold=True, color="FFFFFF"), fill=azul,
                      alignment=Alignment(horizontal="right" if sec["alinhamentos"][j - 1] == "dir" else "left"))
            _largura(j, c)
        r_atual += 1
        for linha in sec["linhas"]:
            for j, c in enumerate(linha, start=1):
                _escrever(alvo, r_atual, j, c, border=borda,
                          alignment=Alignment(horizontal="right" if sec["alinhamentos"][j - 1] == "dir" else "left"))
                _largura(j, c)
            r_atual += 1
        if sec["rodape"]:
            for j, c in enumerate(sec["rodape"], start=1):
                _escrever(alvo, r_atual, j, c, font=Font(bold=True), fill=cinza,
                          alignment=Alignment(horizontal="right" if sec["alinhamentos"][j - 1] == "dir" else "left"))
            r_atual += 1
        r_atual += 1
        if alvo is ws:
            r = r_atual
        else:
            r2 = r_atual

    for col, w in larguras.items():
        ws.column_dimensions[get_column_letter(col)].width = w
    if "Gráficos" in wb.sheetnames:
        wb["Gráficos"].column_dimensions["A"].width = 40
        wb["Gráficos"].column_dimensions["B"].width = 18
    saida = io.BytesIO()
    wb.save(saida)
    return saida.getvalue()


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------
def gerar_pdf(doc):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    marinho = colors.HexColor("#0B2A4A")
    cinza = colors.HexColor("#EEF2F6")
    largo = any(len(s["colunas"]) > 6 for s in doc["secoes"])
    pagina = landscape(A4) if largo else A4
    saida = io.BytesIO()
    emissao = _emissao()

    def cabecalho_rodape(canvas, d):
        canvas.saveState()
        w, h = pagina
        canvas.setFillColor(marinho)
        canvas.rect(0, h - 14 * mm, w, 14 * mm, stroke=0, fill=1)
        canvas.setFillColor(colors.white)
        canvas.setFont("Helvetica-Bold", 13)
        canvas.drawString(15 * mm, h - 9 * mm, "TechMaint")
        canvas.setFont("Helvetica", 9)
        canvas.drawRightString(w - 15 * mm, h - 9 * mm, "Sistema de Gestão de Manutenção")
        canvas.setFillColor(colors.HexColor("#555555"))
        canvas.setFont("Helvetica", 8)
        canvas.drawString(15 * mm, 8 * mm, f"TechMaint - emitido em {emissao}")
        canvas.drawRightString(w - 15 * mm, 8 * mm, f"Página {d.page}")
        canvas.restoreState()

    estilos = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=estilos["Heading1"], fontName="Helvetica-Bold", fontSize=16, textColor=marinho,
                        spaceAfter=4)
    h2 = ParagraphStyle("h2", parent=estilos["Heading2"], fontName="Helvetica-Bold", fontSize=12, textColor=marinho,
                        spaceBefore=12, spaceAfter=4)
    normal = ParagraphStyle("n", parent=estilos["Normal"], fontName="Helvetica", fontSize=9, leading=11)
    celula = ParagraphStyle("c", parent=normal, fontSize=8, leading=10)
    celula_dir = ParagraphStyle("cd", parent=celula, alignment=2)
    celula_neg = ParagraphStyle("cn", parent=celula, fontName="Helvetica-Bold")
    celula_neg_dir = ParagraphStyle("cnd", parent=celula_neg, alignment=2)
    cab_est = ParagraphStyle("cab", parent=celula, fontName="Helvetica-Bold", textColor=colors.white)
    cab_dir = ParagraphStyle("cabd", parent=cab_est, alignment=2)

    def p(txt, est):
        return Paragraph(escape(str(txt if txt is not None else "")), est)

    historia = [Paragraph(escape(doc["titulo"]), h1)]
    for rot, val in doc["filtros"]:
        historia.append(Paragraph(f"<b>{escape(str(rot))}:</b> {escape(str(val))}", normal))
    historia.append(Paragraph(f"<b>Emitido em:</b> {emissao}", normal))
    largura_util = pagina[0] - 30 * mm

    for sec in doc["secoes"]:
        historia.append(Paragraph(escape(sec["titulo"]), h2))
        n = len(sec["colunas"])
        alin = sec["alinhamentos"]
        dados = [[p(c, cab_dir if alin[j] == "dir" else cab_est) for j, c in enumerate(sec["colunas"])]]
        for linha in sec["linhas"]:
            dados.append([p(c, celula_dir if alin[j] == "dir" else celula) for j, c in enumerate(linha)])
        if not sec["linhas"]:
            vazio = [p("Sem dados para os filtros escolhidos.", celula)] + [p("", celula)] * (n - 1)
            dados.append(vazio)
        if sec["rodape"]:
            dados.append([p(c, celula_neg_dir if alin[j] == "dir" else celula_neg) for j, c in enumerate(sec["rodape"])])
        tabela = Table(dados, colWidths=[largura_util / n] * n, repeatRows=1)
        estilo = [
            ("BACKGROUND", (0, 0), (-1, 0), marinho),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LINEBELOW", (0, 1), (-1, -1), 0.25, colors.HexColor("#C9D3DE")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F7F9FB")]),
            ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]
        if sec["rodape"]:
            estilo.append(("BACKGROUND", (0, -1), (-1, -1), cinza))
        tabela.setStyle(TableStyle(estilo))
        historia.append(tabela)
        historia.append(Spacer(1, 4))

    pdf = SimpleDocTemplate(saida, pagesize=pagina, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=20 * mm,
                            bottomMargin=16 * mm, title=f"TechMaint - {doc['titulo']}", author="TechMaint")
    pdf.build(historia, onFirstPage=cabecalho_rodape, onLaterPages=cabecalho_rodape)
    return saida.getvalue()


def nome_arquivo(base, extensao):
    return f"techmaint_{base}_{agora().strftime('%Y-%m-%d')}.{extensao}"
