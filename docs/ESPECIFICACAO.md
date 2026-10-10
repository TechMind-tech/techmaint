# TechMaint — Especificação de desenvolvimento (contrato entre Dev, Front-end e QA)

Projeto acadêmico (UniAnchieta 2026/2): sistema de gestão de manutenção predial e de máquinas, em Python.
Repositório: `/home/claude/repo/techmaint` (branch `feature/sistema-completo`, já criada). Hoje o repo é só um
CRUD didático de Equipamentos em Flask + SQLite; vamos evoluí-lo para o sistema completo descrito abaixo.
Entrega 3 (versão funcional de ponta a ponta): 26/10/2026. Líder técnico: Ronaldo.

## 0. Material de referência (leia o que é da sua função)

Tudo em `/home/claude/work/`:

- `docs/manual-de-interface.txt` + `docs/manual-pag-01..10.png` — Manual de interface (formulários, botões, fluxo de navegação).
  As imagens das páginas 2, 7 e 8 mostram login, menu, cadastro de usuários, fluxo. (Use `Read` nas PNG para ver.)
- `docs/projeto-documentacao.txt` — documentação do projeto: escopo, modelo de dados completo, cardinalidades,
  requisitos funcionais/não funcionais, casos de uso, bibliotecas recomendadas, calendário.
- `docs/documentacao-de-apoio.txt` — grupos, subgrupos, equipamentos reais (≈70) e listas suspensas por formulário.
- `figma/*.jpg` — prints das telas do protótipo (Figma Make). **É a referência visual** (cores, layout, componentes).
  O Manual é a referência de campos/fluxo. Se divergirem: layout/estética = Figma; campos/regras = Manual + Projeto.
  Os prints foram tirados num painel estreito (~737px, layout "mobile/tablet"), então a versão desktop deve
  reorganizar a grade (sidebar fixa + conteúdo largo) mantendo a mesma identidade visual.

## 1. Stack e convenções

- Python 3.13, Flask 3, SQLite (módulo `sqlite3`, **sem ORM**), Jinja2, CSS/JS puros (sem framework CSS).
  Bibliotecas extras permitidas: `openpyxl` (Excel), `reportlab` (PDF), Werkzeug (hash de senha). Gráficos: Chart.js
  **empacotado localmente** em `static/vendor/` (sem CDN em runtime — o sistema precisa funcionar offline).
  Fontes: Poppins (títulos) e Inter (texto), também locais (`static/vendor/fonts/`), com fallback `system-ui`.
  Se não der para obter localmente, usar fallback e seguir.
- Interface 100% pt-BR. Identificadores e comentários em português, sem acento nos identificadores (padrão do repo atual).
  Comentários didáticos e curtos, como no código atual.
- Organização do código (Dev é dono): `app.py` (fábrica `criar_app()` + `app = criar_app()`), `database.py`
  (conexão, `init_db()`), `schema.sql`, `seed.py`, pacote `modulos/` com um Blueprint por módulo
  (`auth.py, painel.py, usuarios.py, equipamentos.py, pecas.py, fornecedores.py, prestadores.py, departamentos.py,
  pedidos.py, ordens.py, estoque.py, relatorios.py, configuracoes.py`), `servicos/` (regras de negócio, exportação PDF/Excel),
  `dados/` (JSON de grupos/subgrupos/equipamentos extraídos de `docs/documentacao-de-apoio.txt`).
- Banco: arquivo definido por `TECHMAINT_DB` (variável de ambiente; default `techmaint.db`). Testes usam banco temporário.
  `init_db()` cria tabelas se não existirem; `python seed.py` popula dados de demonstração (idempotente).
  `python app.py` sobe em `127.0.0.1:5000`. `flask --app app run` também deve funcionar.
- Sem segredos no código: `SECRET_KEY` vem de `TECHMAINT_SECRET_KEY` (default de desenvolvimento só se `FLASK_DEBUG`/testes).
- Segurança básica obrigatória: SQL sempre parametrizado; senha com `generate_password_hash`; sessão assinada;
  CSRF em todo POST (token na sessão, campo `csrf_token`); escaping padrão do Jinja (nunca `|safe` em dado do usuário);
  validação no servidor (não só `required`); POST/Redirect/GET; exclusão só por POST.
- Arquivos por dono (para não haver conflito de edição em paralelo):
  - **Dev**: `app.py, database.py, schema.sql, seed.py, modulos/**, servicos/**, dados/**, requirements.txt, README.md`
  - **Front-end**: `templates/**, static/**` (inclui `static/vendor/**`)
  - **QA**: `tests/**, QA_PLANO.md, QA_RELATORIO.md, QA_BUGS.md, pytest.ini`
  Ninguém edita arquivo de outro dono. Problema em arquivo alheio → registrar em `QA_BUGS.md` (qualquer um pode acrescentar
  uma linha, formato na seção 9) ou avisar no relatório final.
- Nada de `git commit`/`push` pelos agentes. O líder (Claude principal) consolida e comita.

## 2. Perfis e permissões

Perfis (tabela `perfis`): `Administrador`, `Técnico`, `Gestor`, `Usuário Comum`.

| Área | Administrador | Gestor | Técnico | Usuário Comum |
|---|---|---|---|---|
| Dashboard / Relatórios | total + exportar | total + exportar | ver (sem financeiro) | só "relatórios de atendimento" (aba Ordens) |
| Usuários e Perfis | CRUD | — | — | — |
| Equipamentos, Peças | CRUD | ver | CRUD | — |
| Fornecedores, Prestadores, Departamentos | CRUD | ver | ver | — |
| Pedidos de Manutenção | tudo | tudo + aprovar | abrir/editar/consultar | abrir/consultar os próprios |
| Ordens de Serviço | tudo | ver + fechar | tudo | consultar status das próprias |
| Movimentação de Estoque | tudo | ver | tudo | — |
| Configurações (perfil/senha/idioma/tema) | sim | sim | sim | sim |

Sem permissão → HTTP 403 com `403.html`. Não logado → redirect 302 para `/login?proximo=<url>`.
Itens de menu que o perfil não pode abrir **não aparecem** no menu. Usuário inativo não loga.
Mensagem de login inválido genérica: "Usuário ou senha inválidos." (não revelar qual). Campos vazios: "Preencha todos os campos."
Bloqueio simples contra força bruta: após 5 falhas seguidas do mesmo login, bloqueia 5 min (mensagem clara).

Usuários de demonstração criados pelo `seed.py` (apenas dados fictícios de desenvolvimento, documentar no README):
`admin / admin123` (Administrador, "João Administrador", depto TI), `tecnico / tecnico123` ("Maria Técnica", Manutenção),
`gestor / gestor123` ("Carlos Gestor", Produção), `solicitante / solicitante123` ("Ana Solicitante", Produção, Usuário Comum),
`plima / plima123` ("Pedro Lima", Técnico, Manutenção).

## 3. Modelo de dados (SQLite) — adaptação do modelo SQL Server do Projeto

Seguir `docs/projeto-documentacao.txt` §6 (nomes de tabelas/colunas em snake_case sem acento), com estas decisões:

- `usuarios(id, nome, login UNIQUE, senha_hash, email, ativo, data_cadastro, id_departamento NULL, idioma DEFAULT 'pt-BR', tema DEFAULT 'claro')`,
  `perfis`, `permissoes`, `usuarios_perfis`, `perfis_permissoes` (N:N como no documento; na UI um usuário tem 1 perfil principal).
- `departamentos(id, nome UNIQUE, responsavel_id NULL→usuarios.id, responsavel_nome)` — "Responsável" é lista de usuários cadastrados (apoio §4).
- `fornecedores` e `prestadores_servico` (campos do documento: razão social, fantasia, CNPJ único com validação de dígitos,
  IE, telefone, e-mail, CEP, logradouro, número, complemento, bairro, município, UF, ativo; prestador ganha `especialidade`).
- `grupos`, `subgrupos`, `equipamentos(codigo UNIQUE, descricao, ncm, id_grupo, id_subgrupo, id_departamento, status('Ativo'|'Em manutenção'|'Baixado'),
  controla_depreciacao, patrimoniado, vida_util_meses, valor_residual_padrao)`.
- `pecas(id, id_equipamento, nome, ncm, valor_unitario, qtde_estoque, estoque_minimo DEFAULT 5)` — regra do alerta "Baixo": `qtde_estoque < estoque_minimo`.
  No seed use `estoque_minimo` coerente (ex.: Filtro de Ar com 30 em estoque e mínimo 40 → "Baixo", como no Figma; as demais acima do mínimo).
- `notas_fiscais`, `itens_nota_fiscal` (como no documento; entrada de estoque pode referenciar NF).
- `estoque_pecas` (saldo/local/mín/máx — pode ser derivado de `pecas`; manter coerência) e `movimentacao_estoque_pecas`
  (tipo Entrada/Saída, quantidade, valor_unitario, data, documento_origem ∈ {Nota Fiscal, Ordem de Serviço, Pedido Interno}, numero_documento, observacao, id_usuario).
  `estoque_equipamentos` + `movimentacao_equipamentos` conforme o documento (tela de Movimentação cobre peças; equipamentos pode ter aba/seleção "Tipo de item").
- `pedidos_manutencao(id, id_equipamento, id_departamento, data_solicitacao, solicitante, id_usuario_solicitante, descricao_problema, prioridade('Baixa'|'Média'|'Alta'),
  status('Aberto'|'Em andamento'|'Concluído'|'Cancelado'), aprovado_por NULL)`; numeração exibida como `#1623` (ids de seed começam em 1621 para casar com o Figma).
- `ordens_servico(id, id_pedido NULL, data_abertura, data_fechamento, id_tecnico, responsavel, status('Aberta'|'Em andamento'|'Concluída'|'Cancelada'), observacao)`;
  número exibido `OS-10234` (ids de seed começam em 10232).
  Regra do documento: pedido 1:1 OS (a UI do Figma permite "sem pedido vinculado" — manter opcional; se vinculado, no máximo 1 OS por pedido).
- `itens_os(id_os, id_peca, quantidade, valor_unitario, valor_total)`, `servicos_os(id_os, descricao_servico, valor_servico, id_prestador NULL)`,
  `apontamentos_os(id_os, data, tecnico, horas_trabalhadas, tipo, observacao)` com `tipo` ∈ lista de apoio §4 "ApontamentosOS"
  (AJUSTE, CALIBRACAO, INSPECAO, LIMPEZA, LUBRIFICACAO, OUTROS, PEÇA, PEÇA + SERVIÇOS, REGULAGEM, SOLDA, TERCEIRIZADO).
- `historico_alteracoes(entidade, id_entidade, acao, usuario, data, detalhe)` — log de auditoria (item "miniecossistema" do Projeto): gravar em criar/editar/excluir/fechar OS/mudar status.
- Integridade: `PRAGMA foreign_keys=ON`; exclusão de registro referenciado → mensagem amigável ("Não é possível excluir: há X vínculos") em vez de erro 500;
  para usuários/fornecedores/prestadores prefira inativar quando houver vínculos.

### Regras de negócio
1. Abrir OS a partir de pedido: pedido passa a `Em andamento`; fechar OS → OS `Concluída` + `data_fechamento` + pedido `Concluído`. Cancelar pedido só se `Aberto` (sem OS ativa).
2. Adicionar peça à OS: valida saldo; baixa estoque; cria movimentação Saída (doc origem "Ordem de Serviço", nº = número da OS). Editar quantidade/excluir peça ajusta o estoque (estorno).
   OS Concluída/Cancelada é somente leitura (exceto reabrir por Administrador, opcional).
3. Movimentação manual: Saída maior que o saldo → erro e nada muda. Entrada com valor unitário atualiza `valor_unitario` da peça? **Não** (só registra). Excluir movimento estorna o saldo (se não deixar saldo negativo).
4. Equipamento `Em manutenção` automaticamente quando há OS `Em andamento` para ele; volta a `Ativo` ao concluir (a menos que `Baixado`).
5. Alertas (sino do cabeçalho, contador + lista): peças com estoque baixo, OS atrasadas (aberta há mais de 7 dias sem fechar — constante configurável), pedidos `Aberto` de prioridade Alta sem OS.
6. Validações: obrigatórios; e-mail válido; login único (case-insensitive) 3–50 chars sem espaços; senha ≥ 8 chars na criação **de usuário comum do cadastro**
   (os usuários seed usam senhas de demonstração mais curtas — a regra vale para formulários, não para o seed); CNPJ com dígito verificador; UF na lista; quantidades > 0; valores ≥ 0; NCM 8 dígitos; código de equipamento único.
7. Equipamento: Subgrupo depende do Grupo (select dependente via `/api/subgrupos`). Peça: "Equipamento vinculado" é select de equipamentos cadastrados (Figma mostra texto livre; o Manual/apoio diz lista — **siga o Manual: select**).

### Dados de demonstração (`seed.py`)
- Grupos (15), subgrupos (149) e **todos** os equipamentos listados em `docs/documentacao-de-apoio.txt` (≈70, com grupo/subgrupo/departamento coerente; status Ativo; alguns "Em manutenção"/"Baixado").
  O Figma mostra "24 equipamentos cadastrados" — não é requisito reproduzir a contagem; use os reais do apoio.
- Departamentos (Figma): Produção/Roberto Alves, Manutenção/João Silva, Logística/Fernanda Costa, Utilidades/Paulo Menezes, Administração/Carla Mendes; mais TI. (Responsáveis podem ser nomes livres no seed; o select usa usuários quando houver.)
- Peças (Figma): Rolamento 6204 (R$ 15,00, 120), Sensor Indutivo (25,50, 50), Correia V (8,00, 200), Filtro de Ar (32,00, 30 → "Baixo"); vincule a equipamentos reais coerentes; adicione outras.
- Fornecedores (Figma): TecManutenções LTDA 12.345.678/0001-90, Construservice S.A. 98.765.432/0001-10, Elétrica Forte ME 11.222.333/0001-44 (CNPJs podem não ter dígito válido — no seed grave sem validar, ou use CNPJs válidos equivalentes; documente a escolha).
- Prestadores (Figma): PST-001 TecServiços Ltda (Mecânica Geral), PST-002 Elétrica Forte ME (Elétrica Industrial), PST-003 Hidro Masters ME (Hidráulica); 3 prestadores, 2 ativos.
- Pedidos (Figma, 4): #1623 BOMBA 1 (RESFRIADOR)/Utilidades/Ana Solicitante, #1624 INJETORA 02 - YIZUMI/Produção/Ana, #1625 EMPILHADEIRA HYSTER 2014/Logística/Carlos Gestor, #1626 COMPRESSOR METALPLAN/Infraestrutura/Ana
  (status: 2 Aberto, 1 Em andamento, 1 Concluído, 0 Cancelado, como o cabeçalho de contadores do Figma).
- OS (Figma, 3): OS-10234 (#1623, Em Andamento, Maria Técnica, 12/09/2026, Alta), OS-10233 (#1625, Concluída, 10/09/2026, Baixa), OS-10232 (#1621 pedido extra, Aberta, 08/09/2026).
- Movimentações (4): total entradas do mês R$ 1.390,00, saídas R$ 54,00 (como no Figma).
- Dashboard (Figma): KPIs 12 pedidos abertos (+3 esta semana), 5 OS em andamento (2 com prazo hoje), 18 OS concluídas/mês (meta 20), custo total R$ 32.500 (orçamento R$ 40k). No sistema real os KPIs são **calculados do banco**;
  o seed deve gerar volume suficiente (≈ 12 meses de histórico: dezenas de pedidos/OS com custos e peças) para os gráficos não ficarem vazios. Metas/orçamento ficam em tabela `parametros` (`meta_os_mes=20`, `orcamento_mes=40000`).
- Usuários seed: ver §2.

## 4. Rotas e contrato de templates (Dev ↔ Front-end)

Convenções: todo endpoint é `<blueprint>.<funcao>`; templates recebem o contexto listado (nomes exatos). Todo template estende `base.html`
(exceto `login.html`/`recuperar_senha.html` que estendem `base_auth.html`, e `403.html`/`404.html`/`500.html` que estendem `base.html` ou `base_auth.html`).
Dev injeta em **todos** os templates via `context_processor`: `usuario_atual` (dict: id, nome, login, perfil, depto, iniciais), `menu` (lista de seções→itens já filtrada por permissão:
`[{"secao":"Principal","itens":[{"chave":"dashboard","rotulo":"Dashboard","endpoint":"painel.dashboard","icone":"layout-dashboard"}]}, ...]`),
`endpoint_atual`, `alertas` (`{"total":int,"itens":[{"tipo","texto","url"}]}`), `csrf_token()` (função), `tema` (`claro|escuro`), `agora`.
Flash: categorias `sucesso`, `erro`, `aviso`, `info` (use `get_flashed_messages(with_categories=true)` em `base.html`).
Todo `<form method="post">` leva `<input type="hidden" name="csrf_token" value="{{ csrf_token() }}">`.
Datas: o backend entrega strings já formatadas para exibição (`dd/mm/aaaa`) em `*_fmt` e ISO em `*_iso` para inputs `type=date`. Valores monetários: `*_fmt` = `"R$ 1.390,00"`.
Formulários com erro: re-renderizar a mesma página com `erros` (dict campo→mensagem) e `valores` (dict com o que o usuário digitou); nunca perder o que foi digitado.

| URL | Endpoint | Métodos | Template | Contexto principal |
|---|---|---|---|---|
| `/login` | `auth.login` | GET, POST | `login.html` | `erro`, `proximo`, `valores.usuario` |
| `/logout` | `auth.logout` | POST | — | redirect `/login` |
| `/recuperar-senha` | `auth.recuperar_senha` | GET, POST | `recuperar_senha.html` | `enviado` (bool) — sem e-mail real: gera token local exibido em log/flash "simulado" e permite redefinir em `/redefinir-senha/<token>` (`redefinir_senha.html`) |
| `/` | `painel.inicio` | GET | — | redirect `/dashboard` |
| `/menu` | `painel.menu_principal` | GET | `menu_principal.html` | `cards` (6 cards do Manual §5: Cadastros, Ordens de Serviço, Estoque, Pedidos de Manutenção, Relatórios, Dashboard — filtrados por perfil) |
| `/dashboard` | `painel.dashboard` | GET | `dashboard.html` | `kpis`, `filtros`, `periodos`, `departamentos`, `equipamentos`, `titulo_periodo` |
| `/api/dashboard` | `painel.api_dashboard` | GET | JSON | query `periodo`(`7d|30d|6m|12m`), `departamento_id`, `equipamento_id` → `{"tempo_medio":[{"rotulo","valor"}],"custo_por_maquina":[...],"pecas_mais_usadas":[...],"status_ordens":[...],"kpis":{...}}` |
| `/dashboard/exportar.pdf` `/dashboard/exportar.xlsx` | `painel.exportar_pdf` / `exportar_xlsx` | GET | arquivo | mesmos filtros da query |
| `/usuarios` | `usuarios.listar` | GET, POST(criar) | `usuarios.html` | `itens`, `item`, `perfis`, `departamentos`, `contagem_perfis` (4 cards: Administrador/Técnico/Gestor/Usuário Comum), `filtro_perfil`, `busca`, `erros`, `valores` |
| `/usuarios/<id>/editar` | `usuarios.editar` | GET, POST | `usuarios.html` | idem com `item` preenchido (senha opcional na edição) |
| `/usuarios/<id>/excluir` | `usuarios.excluir` | POST | — | redirect |
| `/equipamentos` (+`/<id>/editar`, `/<id>/excluir`) | `equipamentos.*` | idem | `equipamentos.html` | `itens`, `item`, `grupos`, `subgrupos` (do grupo do item/ou do primeiro), `departamentos`, `status_opcoes`, `total`, `filtro_grupo`, `filtro_status`, `busca` |
| `/api/subgrupos?grupo_id=` | `equipamentos.api_subgrupos` | GET | JSON | `[{"id","nome"}]` |
| `/pecas` (+`/<id>/editar`, `/<id>/excluir`, `POST /<id>/estoque`) | `pecas.*` | idem | `pecas.html` | `itens` (cada um com `baixo` bool), `item`, `equipamentos`, `filtro_equipamento`, `busca` — botão "Atualizar estoque" abre ajuste rápido (gera movimentação) |
| `/fornecedores` (+`/novo`, `/<id>/editar`, `/<id>/excluir`) | `fornecedores.*` | idem | `fornecedores.html` (lista) e `fornecedor_form.html` | `itens`, `busca`, `filtro_ativo` (`todos|ativos|inativos`), `ufs`; form: `item`, `erros`, `valores`, `ufs` |
| `/prestadores` (idem) | `prestadores.*` | idem | `prestadores.html`, `prestador_form.html` | idem + `especialidades` |
| `/departamentos` (+`/<id>/editar`, `/<id>/excluir`) | `departamentos.*` | idem | `departamentos.html` | `itens`, `item`, `usuarios` (responsáveis) |
| `/pedidos` | `pedidos.listar` | GET | `pedidos.html` | `itens`, `contadores` (`aberto, andamento, concluido, cancelado`), filtros `busca,status,prioridade,departamento_id`, listas de apoio |
| `/pedidos/novo` | `pedidos.novo` | GET, POST | `pedido_form.html` | `equipamentos`, `departamentos`, `prioridades`, `valores`, `erros`; data da solicitação = hoje (readonly) e solicitante = usuário logado |
| `/pedidos/<id>` | `pedidos.detalhe` | GET | `pedido_detalhe.html` | `pedido`, `os` (ou None), `historico` — botões: Editar, Cancelar Pedido, Visualizar Ordem de Serviço / Abrir OS, Aprovar (Gestor) |
| `/pedidos/<id>/editar` · `/cancelar` · `/aprovar` · `/abrir-os` | `pedidos.*` | GET/POST | `pedido_form.html` / redirect | — |
| `/os` | `ordens.listar` | GET | `os_lista.html` | `itens`, `resumo` (`aberta, andamento, concluida, cancelada`), `pedidos_sem_os` (int), filtros `status,tecnico_id,busca` |
| `/os/nova` | `ordens.nova` | GET, POST | `os_form.html` | `pedidos_disponiveis`, `tecnicos`, `valores`, `erros`, `pedido_id` (pré-seleção) |
| `/os/<id>` | `ordens.detalhe` | GET | `os_detalhe.html` | `os`, `itens_os`, `servicos_os`, `apontamentos`, `pecas_disponiveis`, `prestadores`, `tipos_apontamento`, `totais` (`pecas, servicos, geral` + `_fmt`), `somente_leitura` |
| `/os/<id>/editar` | `ordens.editar` | GET, POST | `os_form.html` | idem com `os` |
| `/os/<id>/pecas` · `/pecas/<item>/editar` · `/pecas/<item>/excluir` | `ordens.adicionar_peca` etc. | POST | redirect | — |
| `/os/<id>/servicos` · `/servicos/<sid>/excluir` · `/apontamentos` | `ordens.*` | POST | redirect | — |
| `/os/<id>/fechar` · `/os/<id>/excluir` | `ordens.fechar` / `excluir` | POST | redirect | — |
| `/estoque` | `estoque.listar` | GET, POST(registrar) | `estoque.html` | `resumo` (`total_entradas_fmt, total_saidas_fmt, qtd_movimentos`), `itens` (histórico), `pecas`, `tipos_documento` (`Nota Fiscal, Ordem de Serviço, Pedido Interno`), `valores`, `erros`, filtros `tipo, busca, periodo` |
| `/estoque/<id>/excluir` | `estoque.excluir` | POST | redirect | — |
| `/relatorios` | `relatorios.pagina` | GET | `relatorios.html` | `aba` (`os|estoque|financeiro|fornecedores`), `filtros` (`periodo, departamento_id, tecnico_id`), `departamentos`, `tecnicos`, `tabela` (`colunas`, `linhas`, `rodape`), `graficos` (lista de `{"id","titulo","tipo","rotulos","valores"}`) |
| `/api/relatorios/<aba>` | `relatorios.api` | GET | JSON | mesmo conteúdo de `tabela` e `graficos` (para o botão Atualizar sem recarregar) |
| `/relatorios/<aba>/exportar.pdf` · `.xlsx` · `.csv` | `relatorios.exportar` | GET | arquivo | PDF (reportlab) e Excel (openpyxl) com cabeçalho TechMaint, filtros aplicados e data |
| `/configuracoes` | `configuracoes.pagina` | GET, POST | `configuracoes.html` | `perfil` (nome, e-mail), troca de senha (senha atual + nova), `idiomas` (`pt-BR` apenas funcional, `en` e `es` desabilitados "em breve"), `temas` (`claro|escuro`) |
| erros | — | — | `403.html`, `404.html`, `500.html` | — |

Ícones: SVG inline (sprite em `static/img/icones.svg` ou macros Jinja em `templates/_icones.html`) — Front-end é dono; nomes lucide-like (`layout-dashboard, users, cpu, wrench, building, briefcase-user, clipboard-list, settings-2, boxes, bar-chart, bell, menu, search, plus, pencil, trash, download, refresh, log-out, ...`).
O Dev passa só o nome do ícone nos itens de menu; o Front-end resolve (macro `icone(nome)`).

## 5. Telas — o que o Front-end entrega (referência: `figma/*.jpg` + Manual)

Identidade (do Figma): sidebar azul-marinho em degradê (≈ `#0b1f4b → #13306b`), item ativo com barra lateral ciano e fundo translúcido, logo "TechMaint" com ícone, selo "Admin" vermelho no topo da sidebar;
cabeçalho branco com botão hambúrguer, sino com bolinha vermelha, avatar com iniciais (círculo vermelho/coral), nome + perfil (perfil em vermelho p/ Administrador).
Fundo de conteúdo cinza-azulado claro (`#eef2f8`), cards brancos com raio ~14px e sombra suave, botão primário azul-marinho (`#1b3a6b`), secundário branco com borda, ação ciano (`#0ea5e9`), verde para Excel/sucesso (`#10b981`), vermelho suave para excluir.
Títulos em Poppins semibold, texto em Inter. Badges coloridos (perfil, status). Tabelas com cabeçalho em caixa-alta cinza, linhas compactas, código/mono em campos técnicos (login, código de equipamento, NCM, CNPJ).
Login: fundo degradê azul com card branco central (Figma `01-login.jpg`), ícone engrenagem + "TechMaint", subtítulo "Faça login para continuar", campos com ícone, "Lembrar-me", link "Esqueceu a senha?", botão ENTRAR em degradê azul→ciano, rodapé "Desenvolvido em Python · TechMaint v1.0", erro em faixa vermelha clara "Preencha todos os campos.".
(O Manual mostra uma versão alternativa com ilustração do técnico à esquerda no desktop — opcional: ilustração em CSS/SVG simples à esquerda em telas largas.)

Telas: Login · Recuperar/Redefinir senha · Menu principal (cards) · Dashboard (4 KPIs coloridos com ponto de cor + 4 gráficos: Tempo médio de atendimento [linha], Custo por máquina [barra horizontal], Peças mais utilizadas [barra], Status das ordens [pizza/rosca]; botões Exportar PDF, Exportar Excel, Atualizar; filtros período/departamento/equipamento) ·
Usuários e Perfis (4 cards de contagem por perfil + formulário "Novo Usuário" + lista com busca e filtro por perfil, badges de perfil, status Ativo/Inativo) · Equipamentos (form com Código, Descrição, Grupo, Subgrupo, Departamento, Status em rádios com bolinha colorida + vida útil, valor residual, NCM, controla depreciação, patrimoniado; lista com filtros de grupo/status, busca por código/descrição, colunas Código/Descrição/Grupo-Subgrupo/Depto/Status/Ações) ·
Peças (form Nome, Equipamento vinculado, Valor unitário, Qtd. em estoque, NCM; botões Cadastrar, Excluir, Atualizar estoque, Editar; lista com filtro por equipamento e aviso "⚠ Baixo" em laranja) · Fornecedores e Prestadores (lista + "+ Novo" → formulário completo com busca de CEP **opcional/offline** — sem chamar API externa) · Departamentos (form + tabela com Editar/Excluir) ·
Pedidos de Manutenção (4 contadores coloridos, filtros, tabela #número/Equipamento/Departamento/Solicitante/Prioridade/Status/Data/Ações, "+ Novo Pedido") · Ordens de Serviço (lista em cartões com número, status em pílula, pedido vinculado, técnico·data, prioridade; faixa amarela "⚠ N pedido(s) aguardando abertura de OS"; "+ Nova OS") ·
Nova OS (Pedido vinculado opcional, Técnico responsável, Observações iniciais, botões "Abrir OS"/"Cancelar") · Detalhe da OS (cabeçalho com status, dados do pedido, subformulários Peças usadas e Serviços executados com tabelas, Apontamentos, totais, botões Adicionar Peça, Adicionar Serviço, Editar Peça, Excluir Peça, Editar, Excluir, Voltar, Fechar OS) ·
Movimentação de Estoque (3 cards: total entradas, total saídas, nº movimentações + formulário Registrar Movimento [Entrada/Saída em rádios, Código do item, Descrição (select), Quantidade, Valor unit., Tipo de documento, Nº documento; Registrar Movimento / Limpar] + histórico) ·
Relatórios (filtros Período/Departamento/Técnico + Atualizar; botões Exportar PDF e Exportar Excel; abas Ordens de Serviço / Estoque / Financeiro / Fornecedores; gráficos "OS por Técnico", "Custo por Técnico (R$)"; tabela "Relatório Detalhado de OS": Status/Técnico/Qtd. OS/Custo total) · Configurações (perfil, senha, idioma, tema; botão Sair) · 403/404/500.

Requisitos de front: responsivo (sidebar vira off-canvas abaixo de ~900px, tabelas com rolagem horizontal contida, formulários em 1 coluna no celular, alvos de toque ≥ 40px);
acessível (labels ligados aos inputs, foco visível, contraste AA, `aria-current` no menu, `aria-live` nos avisos, teclado funciona em menu/abas/modais, `prefers-reduced-motion`);
tema claro/escuro (`data-theme` no `<html>` a partir de `tema`, tokens em `:root`); estados vazios amigáveis ("Nenhum pedido encontrado"); confirmação antes de excluir (diálogo `<dialog>` acessível, com fallback de `confirm` desnecessário);
sem dependência de rede; JS progressivo (as telas funcionam sem JS exceto gráficos e select dependente). Gráficos: Chart.js local lendo `/api/dashboard` e `/api/relatorios/<aba>`; botão Atualizar refaz o fetch; com `prefers-reduced-motion` sem animação.
Cada gráfico também tem uma versão tabular acessível (`<table class="sr-only">` ou `<details>`).

## 6. Qualidade e testes

- Dev: cobrir regras de negócio com código claro; mensagens de erro em pt-BR; logs (`logging`) em auditoria/erros; 500 → página amigável sem stack trace (stack só em debug).
- QA (pytest + Flask test client + Playwright quando útil): ver §8. Cobertura mínima: autenticação/autorização por perfil (matriz da §2, incluindo 302/403), CRUD de cada módulo
  (criar, listar, editar, excluir, validações, duplicidade, vínculos), fluxo ponta a ponta Pedido → OS → peças/serviços/apontamentos → Fechar OS → estoque atualizado → dashboard/relatórios refletem,
  regras de estoque (saldo insuficiente, estorno), CSRF (POST sem token = 400/403), exportação PDF/XLSX (abre, tem conteúdo, content-type), APIs JSON (shape), injeção (aspas/`<script>` em campos não quebram nem executam), paginação/busca/filtros,
  seed idempotente, banco temporário isolado por teste, e responsividade/acessibilidade básica via Playwright (viewport 1440×900 e 390×844: sem scroll horizontal da página, menu off-canvas funciona, foco visível, sem erros de console, contraste dos tokens).
- Comparação visual: QA tira screenshots das telas principais (Playwright, chromium em `/opt/pw-browsers`) em `tests/screenshots/` e compara com `figma/*.jpg` por inspeção (Read na imagem) registrando divergências em `QA_BUGS.md`.

## 7. Divisão de trabalho (resumo)

| Agente | Dono de | Entrega |
|---|---|---|
| **Dev Sênior Master** | backend inteiro (§1 "Dev") | app Flask funcionando com todos os módulos/rotas/contexto da §4, schema, seed, regras da §3, exportações, README atualizado, `requirements.txt` |
| **Front-end Master** | `templates/**`, `static/**` | todas as telas da §5 consumindo exatamente o contrato da §4, CSS/JS, gráficos, responsivo, acessível, tema claro/escuro |
| **QA** | `tests/**`, `QA_*.md` | plano de testes, suíte pytest, testes E2E Playwright, relatório e lista de bugs com severidade; reexecuta após correções |

Rodadas: (1) Dev e Front-end constroem em paralelo contra o contrato; QA estuda tudo, escreve plano + testes a partir do contrato e do Manual/Projeto/Figma (sem depender do código pronto).
(2) Quando o app subir, QA roda tudo e registra bugs em `QA_BUGS.md`; Dev e Front-end corrigem os que são seus; QA reexecuta até zerar críticos/altos.
Se o contrato estiver ambíguo, **decida de forma conservadora, siga o que está escrito aqui e anote a decisão** na seção "Decisões" do seu relatório final.

## 8. Como rodar (alvo)

```
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\Activate.ps1
pip install -r requirements.txt                    # Flask, openpyxl, reportlab (+ pytest, playwright em requirements-dev.txt)
python seed.py                                     # dados de demonstração
python app.py                                      # http://127.0.0.1:5000  (admin / admin123)
pytest -q                                          # suíte completa
```
Neste sandbox já existem Flask, openpyxl, reportlab, playwright (+ chromium). `pytest` pode precisar de `pip install pytest --break-system-packages`.
Servidor de teste manual: `TECHMAINT_DB=/tmp/tm_demo.db python seed.py && TECHMAINT_DB=/tmp/tm_demo.db python app.py` (porta 5000; para o Playwright use uma porta livre via `--port`/env `PORT`).

## 9. Formato de `QA_BUGS.md`

Tabela Markdown: `| ID | Sev (Crítico/Alto/Médio/Baixo) | Dono (Dev/Front) | Onde (URL/arquivo) | Passos p/ reproduzir | Esperado x Obtido | Status (Aberto/Corrigido/Verificado) |`.
Quem corrige muda para `Corrigido` e descreve em 1 linha; QA muda para `Verificado` após reteste.
