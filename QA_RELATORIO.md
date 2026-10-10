# QA_RELATORIO — TechMaint

Relatório de qualidade para a **Entrega 3 (26/10/2026)**. Autor: QA Sênior · Data do último run completo: 10/10/2026 (rodada 2).
Documentos irmãos: `QA_PLANO.md` (estratégia e rastreabilidade) · `QA_BUGS.md` (defeitos, formato SPEC §9) ·
`tests/` (suíte) · `tests/screenshots/` (evidências visuais).

## 1. Recomendação

**GO** para a Entrega 3 (rodada 2, 10/10/2026).

* 0 bugs Críticos, 0 Altos, 0 Médios abertos. Todos os defeitos registrados como corrigidos foram **retestados e marcados
  Verificado**: FE-001, FE-002, FE-003, BUG-001 a BUG-010.
* Suíte completa verde: **1.740 passam, 0 falham, 0 pulados, 0 xfail** (ver §2).
* **Única pendência aberta:** BUG-011 (Baixo, Front): o texto de apoio de `/recuperar-senha` ainda diz que "o link aparece
  no aviso acima", o que deixou de ser verdade depois da correção do BUG-003. Não afeta função nem segurança.
* O BUG-003 era a ressalva da rodada 1. Agora o link de redefinição não aparece na tela, a resposta é idêntica para login
  existente e inexistente, e o link só existe no log do servidor (permitido pela SPEC) e no gancho de teste
  (`app.extensions`, só com `app.testing=True`).

## 2. Resultados do último run completo (rodada 2)

Comando: `python3 -m pytest -o addopts=""` (suíte inteira, 9 min 54 s).

| Total | Passaram | Falharam | XFAIL/XPASS | Pulados |
|---:|---:|---:|---:|---:|
| **1.740** | **1.740** | **0** | **0** | **0** |

* Sem navegador (integração, segurança, exploratório, concorrência): 1.625 casos.
* E2E Playwright (Chromium, 1440×900 e 390×844): 115 casos (rodada 1: 104 passavam e 9 falhavam por BUG-006/007).
* Comparação com a rodada 1 (1.725 casos, 9 falhas, 1 xfail): +15 casos líquidos (anti-enumeração sem link, BUG-008,
  BUG-009, CSP em 8 páginas, CSP em erro/exportação, CSP × templates, CSP E2E × 2 viewports; menos o xfail do BUG-003 removido).
* Os testes de contraste agora definem o tema explicitamente (claro ou escuro) antes de medir, então não dependem da ordem
  de execução (conferido rodando em ordem invertida).

### 2.1 Por módulo

| Módulo / arquivo | Casos | Resultado | Observações |
|---|---:|---|---|
| Contrato do repositório (`test_00_contrato`) | 14 | verde | blueprints, URLs, sem segredo fixo, SQL por AST, sem `\|safe` em dado, sem CDN, README/requirements |
| Seed (`test_seed`) | 39 | verde | 15 grupos, 149 subgrupos, 77 equipamentos do apoio, dados do Figma, idempotência |
| Autenticação (`test_auth`) | 55 | verde | login, bloqueio 5/5 min, `proximo` seguro, logout, recuperação de senha sem link na tela (BUG-003) |
| Permissões (`test_permissoes`) | 393 | verde | matriz 4 perfis × rotas GET/POST, IDOR, visão restrita do Usuário Comum |
| Usuários (`test_usuarios`) | 71 | verde | |
| Equipamentos (`test_equipamentos`) | 100 | verde | |
| Peças (`test_pecas`) | 47 | verde | |
| Departamentos (`test_departamentos`) | 31 | verde | |
| Fornecedores e Prestadores | 111 | verde | |
| Pedidos (`test_pedidos`) | 57 | verde | Baixado não oferecido nem aceito (BUG-009) |
| Ordens de Serviço (`test_os`) | 109 | verde | fechar OS vazia com aviso (BUG-008), reabrir, baixa/estorno |
| Estoque (`test_estoque`) | 39 | verde | |
| Fluxo ponta a ponta | 6 | verde | |
| Dashboard e Relatórios | 71 | verde | |
| Exportações | 58 | verde | |
| Segurança (`test_seguranca`) | 346 | verde | inclui CSP restritiva em 8 páginas e erro/exportação (BUG-010) |
| Configurações e Alertas | 48 | verde | |
| Exploratório (`test_exploratorio`) | 30 | verde | fuzz, extremos, concorrência |
| E2E navegador (`test_e2e_playwright`) | 115 | verde | sem violações de CSP, gráficos pintados, diálogo de confirmação, contraste AA nos 2 temas |

## 3. Cobertura do plano

* **Requisitos funcionais RF-01…RF-14:** todos cobertos (matriz em `QA_PLANO.md §3.1`). Exceção: **RF-06 Notas fiscais**
  só tem cobertura de schema/seed e do tipo "Nota Fiscal" na movimentação, porque a SPEC não prevê tela (risco R-07).
* **RNF:** segurança, usabilidade, offline, manutenibilidade e desempenho cobertos. Desempenho medido de forma exploratória
  com o seed completo: `/dashboard` 115 ms, `/relatorios` 55 ms, `/os` 60 ms, `/estoque` 33 ms, exportações PDF/XLSX 120–150 ms.
* **Manual de Interface:** todos os formulários exercitados com campos válidos, vazios, limites e hostis.
* **Regras de negócio SPEC §3.1–§3.7:** todas com teste positivo e negativo.
* **Permissões SPEC §2:** 393 casos (perfil × rota × método).
* **Telas × Figma (21 imagens):** comparação visual em 1440×900 e 390×844; sem divergência estrutural (ver `QA_BUGS.md`,
  quadro de divergências). O fundo escuro, o tema escuro e o menu off-canvas mobile foram conferidos por teste e imagem.

### Validação da própria suíte (mutação manual)
Para evitar testes "verdes por acaso", 11 defeitos foram injetados numa cópia do app e a suíte teve de detectá-los:
saldo de estoque negativo, CSRF desligado, Técnico gerenciando usuários, equipamento que nunca volta a "Ativo", limite de OS
atrasada 7→30 dias, OS concluída editável, excluir peça sem estorno, Técnico reabrindo OS, bloqueio de login 5→500, senha
mínima 8→3 e `|safe` na lista de usuários. **Os 11 foram detectados.** Um deles (Técnico reabrindo OS) só foi pego depois que acrescentei testes de "reabrir OS",
que não existiam; também acrescentei os casos de limite 6/7/8/9 dias para o alerta de OS atrasada. As mutações foram
feitas numa cópia em pasta temporária: o app original não foi alterado.

## 4. Bugs

| Severidade | Abertos | Corrigidos e verificados |
|---|---|---|
| Crítico | 0 | 0 |
| Alto | 0 | FE-001 |
| Médio | 0 | FE-002, BUG-001, BUG-002, BUG-003, BUG-004 |
| Baixo | BUG-011 | FE-003, BUG-005, BUG-006, BUG-007, BUG-008, BUG-009, BUG-010 |

Detalhes, passos e esperado × obtido em `QA_BUGS.md`.

## 5. Falhas na suíte

Nenhuma. O xfail do BUG-003 foi removido e os dois testes novos (resposta idêntica; sem link nem token na tela nem nos
cabeçalhos) passam.

## 6. Testes exploratórios realizados (resultado)

Todos sem 500 e sem perda de dado:

* **Redirecionamento aberto** (`proximo=//evil.com`, `https://…`, `/\evil.com`, `javascript:`): sempre vai para `/menu`.
* **IDOR:** Usuário Comum não abre pedido/OS de outra pessoa (403/404), não altera nada de outra pessoa.
* **Exclusões com vínculo** (peça com itens, equipamento com pedido, departamento, usuário técnico de OS, prestador,
  fornecedor, a si mesmo): bloqueio ou inativação com mensagem amigável; `PRAGMA foreign_key_check` vazio.
* **OS concluída** (editar, adicionar peça/serviço/apontamento, fechar de novo, excluir): nada muda.
* **Estorno:** excluir OS aberta com peça devolve o saldo (120 → 117 → 120) e o pedido volta a "Aberto".
* **Parâmetros lixo** (`pagina=-1`, `por_pagina=100000`, `ordem=...;DROP`, IDs gigantes, `periodo=zzz`): 200 sem erro.
* **Corpo de 3 MB:** 413. **HEAD/OPTIONS:** 200. **Barra final (`/usuarios/`):** 404 (consistente).
* **Concorrência (servidor real, 8 a 10 clientes simultâneos):** saídas no mesmo saldo, peças na mesma OS, aberturas da
  mesma OS e códigos de equipamento iguais: sem saldo negativo, sem OS duplicada, sem código repetido.
* **Cookie de sessão:** `HttpOnly; SameSite=Lax` (`Secure` só com `TECHMAINT_COOKIE_SEGURO=1`, correto para HTTP local).
* **Banco vazio** (só schema): `/login`, `/dashboard` e `/relatorios` sobem sem erro (FE-001 verificado).
* **Coerência do seed:** equipamento "Em manutenção" ⇔ OS em andamento, sem saldo negativo, 0 pedidos concluídos sem OS concluída.

### Reteste exploratório da rodada 2
* **Recuperar senha:** resposta idêntica para `admin` e login inexistente; nenhum token na tela nem nos cabeçalhos; o fluxo
  completo (token do gancho → nova senha → login → token de uso único) funciona.
* **Pedido com equipamento Baixado:** não aparece no select e o POST forçando o id é recusado sem criar pedido; equipamento
  "Em manutenção" continua aceito.
* **Fechar OS vazia:** fecha, conclui o pedido e mostra o aviso "OS fechada sem peças, serviços ou apontamentos"; com peça
  lançada o aviso não aparece.
* **CSP ativa:** presente em páginas, 404, exportação e API; sem `<script>` nem handler inline nos templates; em 10 telas ×
  2 viewports nenhum "Refused to…" no console, 4 gráficos com pixels no dashboard, diálogo de confirmação abre e Esc fecha
  sem fechar a OS.
* **Comparação visual final** (1440×900 e 390×844 contra `figma/*.jpg`): sem divergência estrutural. A tela Nova OS tem um
  campo extra "Equipamento (opcional)" para OS avulsa, que não está no Figma (aceito, previsto na SPEC).

## 7. Riscos residuais

| # | Risco | Prob. | Impacto | Observação |
|---|---|---|---|---|
| 1 | O link de redefinição vai para o log do servidor (SPEC): quem lê o log tem acesso às contas | B | Médio | Aceitável em demonstração; em produção trocar por envio de e-mail |
| 2 | Notas fiscais sem tela (RF-06): só schema/seed e tipo de documento no estoque | A | Baixo | Documentar no relatório do projeto que a SPEC previu apenas o modelo |
| 3 | `style-src 'unsafe-inline'` na CSP (estilos inline de gráficos/componentes) | B | Baixo | Aceitável; scripts continuam restritos a `'self'` |
| 4 | Suíte completa leva ~10 min (E2E ~3 min) e depende de Chromium em `/opt/pw-browsers` | B | Baixo | Rodar `python3 -m pytest -m "not e2e"` a cada commit e a suíte inteira antes de entregar |
| 5 | `tests/screenshots/` pesa ≈ 26 MB | A | Baixo | Sugestão: incluir no `.gitignore` (arquivos regeneráveis) |
| 6 | Sem teste em Firefox/Safari e sem leitor de tela real | M | Baixo | Só Chromium; acessibilidade por regras automatizadas |
| 7 | Mudanças de último dia sem reteste | M | Alto | Congelar código na véspera e rodar a suíte completa (≈ 10 min) |

## 8. O que não foi verificado

* Impressão/aparência do PDF em leitor externo (só abertura e conteúdo, por teste).
* Navegadores além de Chromium; telas fora de 1440×900 e 390×844; zoom 200%.
* Carga (mais de ≈ 10 usuários simultâneos), SQLite em disco lento, backup/restauração.
* HTTPS e cookie `Secure` (ambiente local é HTTP; a flag existe e depende de variável de ambiente).
* Idioma "en" em Configurações: a preferência é gravada, mas a SPEC não prevê tradução das telas.
* Notas fiscais e itens de NF pela interface (não existe tela).

## 9. Decisões de interpretação

As ambiguidades da SPEC e a decisão adotada em cada uma (D-01…D-17) estão em `QA_PLANO.md §5`. As que mudam o resultado
percebido pela equipe: **D-11** (campo vazio assume padrão: prioridade "Média", data de hoje), **D-12** (fechar OS vazia e
pedido para equipamento Baixado são aceitos e viraram BUG-008/009 como dúvida de contrato), **D-13** (faixa "pedido(s)
aguardando OS" ignora OS cancelada) e **D-14** (subgrupo é select dependente; o teste de integração resolve o id no banco
e o E2E exercita o JS real).

## 10. Como reproduzir

```
pip install pytest pytest-timeout playwright
python3 -m pytest -o addopts=""     # tudo
python3 -m pytest -m "not e2e"      # integração, segurança, exploratório, concorrência
python3 -m pytest -m e2e            # navegador (gera tests/screenshots/)
```
