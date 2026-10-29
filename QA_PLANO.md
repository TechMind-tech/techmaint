# TechMaint — Plano de Testes (QA)

Versão 1.0 · Entrega 3 (26/10/2026) · Responsável: QA Sênior · Branch `feature/sistema-completo`

Este plano foi escrito **a partir dos requisitos** (`SPEC.md`, Projeto, Manual de Interface, Documentação de Apoio e protótipo
Figma), e não a partir do código. Cada caso de teste automatizado referencia o requisito que protege.

---

## 1. Objetivo e estratégia

Provar que o TechMaint cumpre o escopo da Entrega 3: **fluxo ponta a ponta Pedido → Ordem de Serviço → peças/serviços/apontamentos →
Fechamento → estoque → dashboard/relatórios**, com autenticação, autorização por perfil, validações, integridade e segurança básica.

Estratégia em camadas (pirâmide):

| Camada | Ferramenta | Onde | O que prova |
|---|---|---|---|
| Contrato estrutural | pytest + leitura de arquivos | `test_00_contrato.py` | Arquivos, rotas e endpoints da SPEC §4 existem; sem segredo fixo, sem `|safe`, sem CDN, SQL parametrizado (heurística) |
| Dados/seed | pytest + SQLite | `test_seed.py` | 15 grupos, 149 subgrupos, 77 equipamentos do apoio, dados do Figma, idempotência, integridade referencial |
| Integração HTTP (maioria) | pytest + Flask test client, banco temporário por teste | `test_*.py` | Rotas, permissões, CRUD, regras de negócio, validações, estoque, exportações, APIs |
| Segurança | idem | `test_seguranca.py`, módulos | CSRF, métodos, IDOR, injeção/XSS, arquivos expostos, erros sem stack |
| Exploratório automatizado | pytest (fuzz com semente fixa; threads contra servidor real) | `test_exploratorio.py` (`@lento`) | Nenhum 5xx com entrada aleatória, saldo nunca negativo sob concorrência, 1:1 pedido/OS sob corrida |
| E2E de navegador | Playwright + chromium (`/opt/pw-browsers`) | `test_e2e_playwright.py` (`@e2e`) | Jornada completa pela UI, responsividade 1440×900 e 390×844, off-canvas, foco/teclado, console limpo, sem rede externa, tema escuro, contraste AA, acessibilidade básica, screenshots |
| Comparação visual | inspeção das screenshots × `figma/*.jpg` | `tests/screenshots/` | Divergências de layout/cor/texto → `QA_BUGS.md` (Dono: Front) |

### Isolamento e determinismo
* `conftest.py` constrói **um banco modelo** (`init_db()` + `python seed.py` reais, em subprocesso) e **copia para cada teste** o
  arquivo apontado por `TECHMAINT_DB`, criando um app novo com `criar_app()`. Nada é gravado no repositório.
* E2E e concorrência sobem o app **real** (`app.run`) em **porta livre** com banco temporário próprio (um por módulo).
* Logins "descartáveis" únicos (`unico()`) evitam que o contador de bloqueio de força bruta contamine outros testes.
* Fuzz usa `random.Random(20261026)` (reprodutível).

### Tolerância ao contrato aberto
A SPEC não fixa os `name` dos campos de formulário nem o texto exato das mensagens. Por isso os helpers (`tests/helpers.py`) abrem a
página, **leem o `<form>` real** (defaults, selects, radios, checkboxes, CSRF) e preenchem por *aliases* (ex.: `qtde` →
`qtde_estoque|quantidade|…`). Quando um campo do contrato não existe, o teste falha dizendo **qual campo faltou e quais existem**.
`pytest.skip` só é usado quando a dependência externa (chromium/playwright) falta — nunca para esconder defeito.

---

## 2. Escopo

**Dentro:** todos os módulos da SPEC §4 (auth, painel/dashboard, usuários, equipamentos, peças, fornecedores, prestadores,
departamentos, pedidos, ordens de serviço, estoque, relatórios, configurações), APIs JSON, exportações PDF/XLSX/CSV, seed, alertas,
segurança básica, responsividade e acessibilidade básicas.

**Fora (documentado como risco/limitação):** carga/desempenho em escala; compatibilidade com Safari/Firefox (só chromium);
leitores de tela reais (só verificações programáticas de ARIA); expiração real dos 5 min de bloqueio (exigiria manipular relógio);
envio real de e-mail na recuperação de senha (simulado pela SPEC); backup automático e LGPD (RNF sem artefato testável nesta entrega);
integração externa/ERP (opcional no Projeto); Notas Fiscais e estoque de equipamentos têm tabelas, mas a SPEC não define telas.

---

## 3. Matriz de rastreabilidade

Legenda de arquivos: **AUTH** `test_auth.py` · **PERM** `test_permissoes.py` · **USU** `test_usuarios.py` · **EQP** `test_equipamentos.py` ·
**PEC** `test_pecas.py` · **FOR/PRE** `test_fornecedores_prestadores.py` · **DEP** `test_departamentos.py` · **PED** `test_pedidos.py` ·
**OS** `test_os.py` · **EST** `test_estoque.py` · **FLX** `test_fluxo_ponta_a_ponta.py` · **DASH** `test_dashboard_relatorios.py` ·
**EXP** `test_exportacoes.py` · **CFG** `test_configuracoes_alertas.py` · **SEG** `test_seguranca.py` · **SEED** `test_seed.py` ·
**CTR** `test_00_contrato.py` · **EXPL** `test_exploratorio.py` · **E2E** `test_e2e_playwright.py`.

### 3.1 Requisitos Funcionais (Projeto §15b / §8 / §9)

| Requisito | Casos de teste |
|---|---|
| RF-01 Cadastro de usuários, perfis, login seguro, recuperação de senha | AUTH (login ok/inválido/vazio/inativo/bloqueio/logout/proximo/recuperação), USU, PERM |
| RF-02 Cadastro de Departamentos | DEP (tela, criar, validar, editar, excluir com vínculo, auditoria) |
| RF-03 Cadastro de Máquinas/Equipamentos (com departamento, grupo/subgrupo) | EQP (CRUD, NCM, código único, subgrupo×grupo, `/api/subgrupos`, filtros) |
| RF-04 Cadastro de Peças por máquina, valor unitário, estoque | PEC (CRUD, select de equipamento, alerta Baixo, atualizar estoque) |
| RF-05 Fornecedores e Prestadores | FOR/PRE (CRUD, CNPJ, UF, e-mail, duplicidade, ativos/inativos, vínculos) |
| RF-06 Notas fiscais e itens | CTR/SEED (tabelas existem e íntegras); entrada de estoque por "Nota Fiscal" em EST. *Sem tela na SPEC → cobertura parcial (risco R-07)* |
| RF-07 Pedidos de manutenção: criação, aprovação, execução, encerramento | PED, OS, FLX |
| RF-08 Ordens de serviço (peças, serviços, apontamentos, fechamento) | OS, FLX, E2E jornada |
| RF-09 Controle de estoque: atualização automática, alerta de baixo estoque, histórico de consumo | EST, OS (baixa/estorno), CFG (alertas), PEC |
| RF-10 Dashboard: tempo médio, custo por máquina, peças mais usadas, status das ordens | DASH, FLX, E2E |
| RF-11 Relatórios financeiros/operacionais/manutenção com filtros; exportação PDF, Excel e CSV | DASH (APIs), EXP |
| RF-12 Histórico de alterações (miniecossistema §9) | `historico_alteracoes` verificado em USU, EQP, DEP, FOR/PRE, PED, OS, FLX |
| RF-13 Alertas automáticos (estoque baixo, OS atrasadas) | CFG (sino: estoque, OS > 7 dias, pedido Alta sem OS) |
| RF-14 Regras de negócio / políticas de acesso | PERM, SEG, OS, EST |

### 3.2 Requisitos Não Funcionais (Projeto §15c)

| RNF | Casos de teste |
|---|---|
| Desempenho (resposta rápida, interface de visualização) | EXPL rajada de leituras e leitura+escrita simultâneas; `pytest-timeout` 120 s por teste; E2E (gráficos atualizam sem recarregar) |
| Segurança (restrição de acesso, criptografia/hash, sessão) | PERM (matriz), SEG (CSRF, IDOR, cookies, cabeçalhos, hash nunca exposto), AUTH (bloqueio), USU (hash), CTR (sem segredo fixo) |
| Usabilidade (UI/UX, navegação, feedback claro) | E2E (jornada, foco, teclado, diálogo de exclusão, aria-live), mensagens de erro em pt-BR em todos os módulos, comparação Figma |
| Manutenção/Escalabilidade (modularidade, ambiente local, estrutura do banco) | CTR (blueprints, endpoints), SEED (schema/integridade/idempotência), EXPL (integridade após fuzz) |
| Funcionar offline (SPEC §1) | CTR (sem CDN em templates/CSS/JS), FOR/PRE (CEP offline), E2E (nenhuma requisição fora de localhost) |

### 3.3 Manual de Interface — cada formulário

| Formulário (Manual) | Campos/botões verificados | Casos |
|---|---|---|
| 1.1 Usuários e Perfis | Nome, Login, Senha, E-mail, Perfil (lista), Ativo; Novo/Salvar/Editar/Excluir/Pesquisar; filtro por perfil; 4 cards de contagem | USU `test_tela…`, `test_cards…`, `test_filtro_por_perfil`, `test_busca…` |
| 1.2 Equipamentos | Código, Descrição, Grupo, Subgrupo, Departamento, Vida útil, Valor residual, NCM, Status (rádios); listagem com status | EQP `test_formulario_tem_os_campos…`, validações |
| 1.3 Peças | Nome, Equipamento (select), Valor, Qtd, NCM; Salvar/Excluir/Atualizar estoque/Editar; filtro por equipamento | PEC `test_botoes…`, `test_formulario_usa_select…` |
| 1.4 Fornecedores/Prestadores | Razão, Fantasia, CNPJ, IE, Endereço (CEP…UF), Telefone, E-mail, Ativo; lista ativos/inativos | FOR/PRE (parametrizado nos dois módulos) |
| 1.5 Departamentos | Nome, Responsável (lista de usuários) | DEP |
| 2.1 Pedidos | Equipamento, Departamento, Data, Solicitante, Descrição, Prioridade; Abrir/Cancelar/Editar/Consultar/Visualizar OS | PED |
| 2.2 Ordens de Serviço | Pedido vinculado, Data, Técnico, Status, Obs.; subforms Peças e Serviços; Abrir/Fechar OS, Adicionar Peça/Serviço, Voltar, Editar, Excluir, Editar/Excluir Peça | OS, FLX |
| 2.3 Movimentação de Estoque | Tipo (rádios), Código, Descrição, Quantidade, Valor unit., Documento origem; Registrar/Cancelar/Editar/Excluir; histórico | EST |
| 3.1 Dashboard | 4 gráficos; filtros período/departamento/equipamento; Exportar PDF/Excel, Atualizar | DASH, EXP, E2E |
| 3.2 Relatórios detalhados | Estoque, fornecedores/prestadores, OS (status/técnico/depto), financeiro | DASH (`test_aba_*`), EXP |
| 4/5/6 Tela inicial, Menu Principal, Fluxo | Login → Menu (6 cards) → módulos | AUTH, PERM (`test_cards_do_menu…`), E2E |
| 6.2 Configurações | Perfil, Senha, Idioma, Tema; Sair | CFG |

### 3.4 Regras de negócio (SPEC §3)

| Regra | Casos |
|---|---|
| R1 Abrir OS → pedido *Em andamento*; fechar → OS *Concluída* + data + pedido *Concluído*; cancelar só se *Aberto* sem OS ativa | PED `test_abrir_os…`, `test_cancelar_*`; OS `test_fechar_os*`; FLX |
| R2 Peça na OS valida saldo, baixa estoque, cria Saída (doc "Ordem de Serviço", nº da OS); editar/excluir estorna; OS concluída somente leitura | OS `test_adicionar_peca…`, `test_saldo_insuficiente…`, `test_editar_quantidade_*`, `test_excluir_peca…`, `test_os_concluida_*`; E2E |
| R3 Movimentação manual: saída > saldo = erro e nada muda; entrada não altera valor da peça; excluir estorna se não negativar | EST (`test_saida_maior…`, `test_entrada_nao_altera_valor…`, `test_excluir_*`) |
| R4 Equipamento *Em manutenção* com OS *Em andamento*; volta *Ativo* ao concluir (exceto *Baixado*) | OS `test_equipamento_*`, `test_duas_os_ativas…`; FLX |
| R5 Alertas: estoque baixo, OS atrasada (> 7 dias), pedido Alta sem OS | CFG `test_alerta_*` |
| R6 Validações: obrigatórios, e-mail, login único 3–50 s/ espaço, senha ≥ 8, CNPJ DV, UF, quantidades > 0, valores ≥ 0, NCM 8 dígitos, código único | USU, EQP, PEC, FOR/PRE, OS, EST (tabelas `INVALIDOS` parametrizadas) |
| R7 Subgrupo depende do Grupo; Peça usa select de equipamentos | EQP (`subgrupo_de_outro_grupo`, API), PEC |
| Integridade: exclusão com vínculo → mensagem amigável, sem 500 | EQP, PEC, DEP, FOR/PRE, USU, SEED (`foreign_key_check`) |
| Auditoria `historico_alteracoes` | USU/EQP/DEP/FOR/PRE/PED/FLX |

### 3.5 Matriz de permissões (SPEC §2) — `test_permissoes.py`

Gerada a partir de duas tabelas declarativas (`MATRIZ_GET`, `MATRIZ_POST`) × 4 perfis → **391 casos**:
* **Não logado:** toda rota protegida → 302 `/login?proximo=…` (APIs aceitam 401).
* **GET:** perfil × rota com 200/403 (tuplas onde a SPEC é ambígua).
* **POST (estrito):** negado → **403 e banco inalterado**; permitido → ≠ 403 e < 500 (dados vazios; destrutivos testados com id inexistente).
* **Menu:** itens sem permissão **não aparecem** (por perfil) e todo link visível leva a 200.
* **Escopo do Usuário Comum:** só pedidos/OS próprios (lista, detalhe, busca), só aba *Ordens*; Técnico sem financeiro (HTML e API).
* **Escalada:** perfil forjado em `/configuracoes` não vira Administrador.

| Área | Admin | Gestor | Técnico | Comum |
|---|---|---|---|---|
| Dashboard / API | 200 | 200 | 200 (sem financeiro) | 200 ou 403 *(ambíguo)* |
| Exportar dashboard/relatórios | 200 | 200 | 403 | 403 |
| Relatórios (aba financeiro) | 200 | 200 | 302/403 | 302/403 |
| Usuários e Perfis | 200 | 403 | 403 | 403 |
| Equipamentos / Peças (CRUD) | 200 | ver | 200 | 403 |
| Fornecedores/Prestadores/Departamentos | CRUD | ver | ver | 403 |
| Pedidos | tudo | tudo + aprovar | abrir/editar/consultar | abrir + próprios |
| OS | tudo | ver + fechar | tudo | próprias (status) |
| Estoque | tudo | ver | tudo | 403 |
| Configurações | 200 | 200 | 200 | 200 |

### 3.6 Segurança (SPEC §1/§6)
CSRF: **35 rotas POST × (sem token, token falso)** + token de outra sessão · exclusão/ações só por POST (405 em GET) · PUT/DELETE/PATCH
rejeitados · ids inválidos/gigantes → 404 (nunca 500) · stack trace ausente em 404/405/500 · arquivos sensíveis e *path traversal* ·
15 parâmetros de URL × 12 payloads (XSS refletido, SQLi, UNION) · hash nunca exposto · cookie HttpOnly/SameSite · cabeçalhos
(`nosniff`, `X-Frame-Options`) · CSV/XLSX *formula injection* · open redirect no `proximo` · header injection.

---

## 4. Critérios de aceite (Entrega 3)

**Go** se, no último run completo:
1. **0 bugs Críticos e 0 Altos abertos.**
2. Fluxo ponta a ponta (FLX + E2E jornada) **100% verde**.
3. Matriz de permissões (PERM) **100% verde** (nenhum 200 indevido em escrita; nenhum 403 para perfil permitido).
4. CSRF (SEG) e regras de estoque (OS/EST/EXPL concorrência) **100% verdes**.
5. Exportações PDF/XLSX/CSV abrem e têm conteúdo; APIs JSON respeitam o shape da SPEC §4.
6. E2E: sem scroll horizontal, sem erros de console e sem requisições externas nas telas principais, em 1440×900 e 390×844.
7. Seed idempotente e com as contagens do apoio (15/149/77).
8. Bugs Médios abertos ≤ 5, todos com contorno documentado; Baixos/dúvidas de contrato não bloqueiam.

**No-go** se houver qualquer Crítico/Alto aberto, perda de integridade de estoque, exposição de dado entre perfis, ou jornada principal quebrada.

Severidades: **Crítico** (perda/corrupção de dados, falha de segurança explorável, sistema não sobe, fluxo principal bloqueado) ·
**Alto** (regra de negócio/permissão incorreta, tela principal inutilizável) · **Médio** (validação ausente, divergência funcional
com contorno, UX/acessibilidade relevante) · **Baixo** (texto, estética, detalhe, *dúvida de contrato*).

---

## 5. Decisões de interpretação (contrato ambíguo → decisão conservadora)

| # | Ambiguidade | Decisão adotada nos testes |
|---|---|---|
| D-01 | Usuário Comum e `/dashboard` | Aceita 200 **ou** 403, mas *login nunca pode terminar em 403* e Comum só vê aba Ordens |
| D-02 | Gestor/Técnico "ver" nos cadastros: GET de `/novo` e `/editar` | GET aceita (200, 403); **POST negado é estrito (403)** |
| D-03 | Status inicial da OS (Aberta × Em andamento) | Aceita os dois; regra 4 só é exigida quando a OS está *Em andamento* |
| D-04 | Excluir OS com peças | Aceita "bloqueia" **ou** "exclui e estorna estoque"; nunca perder estoque nem deixar pedido *Em andamento* sem OS |
| D-05 | E-mail vazio no usuário (opcional no Projeto × "válido" na SPEC) | Só exige não quebrar; formato inválido é sempre rejeitado |
| D-06 | Peça criada com saldo inicial gera Entrada? | Aceita nenhuma ou uma Entrada igual ao saldo |
| D-07 | Nome dos parâmetros de filtro na URL | Testes tentam as variantes plausíveis (`grupo`, `filtro_grupo`, `grupo_id`…) e relatam as tentadas |
| D-08 | Excluir movimento gerado por OS | Aceita bloquear **ou** manter coerência item×saldo×histórico |
| D-09 | `periodo` padrão e KPIs "do mês" | KPI "Pedidos abertos"/"OS em andamento" comparados com contagem global do banco (sem filtro) |
| D-10 | Cards do estoque (R$ 1.390,00 / R$ 54,00) | Comparados ao banco (mês corrente) **e** ao Figma (SPEC §3) |
| D-11 | Campo opcional com padrão: prioridade vazia no pedido, data vazia no apontamento | Não é erro: o app assume "Média" / hoje (o formulário já vem preenchido). Teste confirma o padrão gravado |
| D-12 | Fechar OS sem nenhum item; pedido para equipamento Baixado | Aceitos (sem 500); registrados como dúvidas de contrato BUG-008/BUG-009 |
| D-13 | Faixa de pedidos aguardando OS | Conta pedidos `Aberto` sem OS **não cancelada** (OS cancelada libera o pedido) |
| D-14 | Subgrupo é select dependente (opções só do grupo padrão no HTML; JS recarrega via `/api/subgrupos`) | O helper resolve o id do subgrupo no banco quando a opção não está no HTML (emula o navegador); o E2E cobre o JS de verdade |
| D-15 | Textos que se repetem fora da lista (alertas do sino, flash "Pedido #1627 aberto", placeholder "Ex: Rolamento 6204") | Asserções de "aparece/não aparece" olham só a tabela (`lista_de`) ou só o painel do sino (`_alertas`), nunca a página inteira |
| D-16 | `<input type=number>` e `<input type=date>` | Testes enviam como o navegador: número com ponto, data só em AAAA-MM-DD (valor fora do formato vira vazio) |
| D-17 | Fundo em gradiente/imagem no cálculo de contraste | Elemento ignorado (indeterminado); sidebar azul escuro não gera falso positivo |

---

## 6. Riscos

| ID | Risco | Prob. | Impacto | Mitigação |
|---|---|---|---|---|
| R-01 | Corrida em saldo de estoque (SQLite sem transação explícita) → saldo negativo | M | Alto | EXPL concorrência (10 threads) contra servidor real |
| R-02 | CSRF ausente em algum POST (rotas novas) | M | Alto | SEG itera 35 rotas; teste que todo `<form method=post>` renderizado tem `csrf_token` |
| R-03 | Divergência de nomes de campos entre Dev/Front quebra os formulários | A | Médio | Helpers leem o formulário real; falha lista os campos existentes |
| R-04 | Front depende de rede (Chart.js/fontes via CDN) | M | Alto | CTR (varredura), E2E (toda requisição precisa ser localhost) |
| R-05 | Regressão visual vs. Figma sem teste automático | A | Médio | Screenshots em 2 viewports + inspeção manual, registrada em `QA_BUGS.md` |
| R-06 | Bloqueio por força bruta em memória não resetar entre testes | B | Médio | Logins descartáveis únicos |
| R-07 | Notas Fiscais/estoque de equipamentos sem tela | M | Baixo | Cobertos só no schema/seed; registrar como dívida |
| R-08 | Exportações com acentos/markup quebrando reportlab | M | Médio | EXP com unicode/HTML hostil e 300+ linhas |
| R-09 | Contraste insuficiente (badges coloridos, tema escuro) | A | Médio | E2E calcula razão WCAG para ~200 elementos por tela/tema |
| R-10 | Prazo apertado: correções de última hora sem reteste | M | Alto | Suíte completa roda em minutos; reteste obrigatório antes de marcar *Verificado* |

---

## 7. Execução

```
pip install pytest pytest-timeout playwright        # chromium em /opt/pw-browsers (não rode `playwright install`)
pytest                                              # tudo (~1.700 casos)
pytest -m "not e2e and not lento"                   # rápido (integração)
pytest -m e2e                                       # navegador
pytest -m lento                                     # fuzz + concorrência
pytest tests/test_permissoes.py -k "tecnico"        # fatias
```
Screenshots: `tests/screenshots/<viewport>_<tela>.png` (≈ 26 MB, regenerados a cada `pytest -m e2e`; recomenda-se ignorá-los no `.gitignore`).
Relatório de resultados: `QA_RELATORIO.md` · defeitos: `QA_BUGS.md` (formato SPEC §9).
