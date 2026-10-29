# TechMaint — notas do Dev para o Front-end e o QA (complemento da SPEC §4)

Esta nota fecha o que a SPEC deixou em aberto. Se algo aqui divergir do que o backend faz, o backend é a verdade
(e eu corrijo esta nota). Atualizado conforme o backend evolui.

## 0. Regras gerais que valem para TODOS os templates
- Linhas vêm como **dicts** (não `sqlite3.Row`). Datas: `*_fmt` (`dd/mm/aaaa`) e `*_iso` (`aaaa-mm-dd`). Dinheiro: `*_fmt` = `R$ 1.390,00`.
- Formulário com erro → mesma página, HTTP 200, `erros` (campo→msg) e `valores` (**o que o usuário enviou, com os mesmos `name=` que ele usou**).
  Em edição o preenchimento vem de `item` (chaves = colunas do banco + `id_*`). Convenção do `_macros.html` (`f = valores or item`) funciona.
- **Nomes de campos aceitos** (canônicos = nomes das colunas da SPEC §3). O backend também aceita variações comuns
  (`perfil_id`, `departamento_id`, `grupo_id`, `valor`, `quantidade`…), mas use os canônicos:
  - usuários: `nome, login, senha, email, id_perfil, id_departamento, ativo, data_cadastro`
  - equipamentos: `codigo, descricao, id_grupo, id_subgrupo, id_departamento, status, vida_util_meses, valor_residual_padrao, ncm, controla_depreciacao, patrimoniado`
  - peças: `nome, id_equipamento, valor_unitario, qtde_estoque, ncm, estoque_minimo` (opcional); ajuste rápido `POST /pecas/<id>/estoque`: `tipo` (`Entrada`|`Saída`) + `quantidade` (+ `observacao`) **ou** `nova_quantidade` (saldo absoluto)
  - fornecedores/prestadores: `razao_social, fantasia, cnpj, inscricao_estadual, telefone, email, cep, logradouro, numero, complemento, bairro, municipio, uf, ativo` (+ `especialidade` no prestador)
  - departamentos: `nome` + `responsavel_id` (select de usuários) **ou** `responsavel_nome` (texto livre)
  - pedidos: `id_equipamento, id_departamento, descricao_problema, prioridade` (data e solicitante são do servidor)
  - OS (nova/editar): `id_pedido` (opcional), `id_tecnico`, `observacao`, `status` (só na edição), `id_equipamento` (opcional, só vale sem pedido)
  - OS peça `POST /os/<id>/pecas`: `id_peca, quantidade` · editar peça: `quantidade` · serviço: `descricao_servico, valor_servico, id_prestador` (opcional) · apontamento: `data, tecnico, horas_trabalhadas, tipo, observacao`
  - estoque `POST /estoque`: `tipo` (`Entrada`|`Saída`), `id_peca` (select "Descrição"), `codigo_item` (opcional; resolve a peça pelo código se `id_peca` vier vazio), `quantidade, valor_unitario, documento_origem` (= "Tipo de documento"; também aceito `tipo_documento`), `numero_documento, observacao`
  - configurações `POST /configuracoes`: `acao` = `perfil` (`nome, email`) | `senha` (`senha_atual, nova_senha, confirmar_senha`) | `preferencias` (`tema, idioma`). Sem `acao`, trata o que vier preenchido.
  - login: `usuario, senha, lembrar, proximo` · recuperar: `usuario` · redefinir: `senha, confirmar_senha`
- **Checkbox "ativo"**: idioma recomendado `<input type="hidden" name="ativo" value="0">` seguido do `<input type="checkbox" name="ativo" value="1">`.
  **Semântica HTML**: se o campo não vier no POST, o checkbox está desmarcado (ativo = 0), na criação e na edição.
  (O `marcador` do Front não envia hidden "0"; está certo assim.)
- Quantidade/valores aceitam `1234.56` e `1.234,56`. `R$` é ignorado.
- Listas aceitam `?pagina=N&por_pagina=M` (padrão 200). Todo template de lista recebe `pagina`, `total_paginas`, `por_pagina`, `total` (macro `paginacao` do Front funciona).
- Globals Jinja extras: `pode('chave')` (permissão do usuário logado, ex.: `pode('equipamentos.editar')`), `moeda(v)`, `data_br(iso)`.
- Menu: cada item tem `chave, rotulo, endpoint, icone, url, ativo` (bool) além do contrato.

## 1. Chaves de permissão (`pode(...)`)
`dashboard.ver, dashboard.exportar, relatorios.exportar, usuarios.gerir, equipamentos.ver, equipamentos.editar, pecas.ver, pecas.editar,
fornecedores.ver, fornecedores.editar, prestadores.ver, prestadores.editar, departamentos.ver, departamentos.editar,
pedidos.criar, pedidos.editar, pedidos.cancelar, pedidos.aprovar, pedidos.abrir_os, os.gerir, os.fechar, os.reabrir, estoque.ver, estoque.editar, financeiro.ver`

## 2. Shapes que a SPEC não detalhou
- `dashboard.kpis` (a API `/api/dashboard` devolve números simples; a **página** `/dashboard` recebe, além disso, as 4 chaves
  `pedidos_abertos`, `os_andamento`, `os_concluidas`, `custo_total` como dicts `{valor, valor_fmt, detalhe, cor}`; `custo_total` só existe se `financeiro.ver`): `{pedidos_abertos, pedidos_abertos_semana, os_andamento, os_atrasadas, os_concluidas_mes, meta_os_mes, custo_total_mes (None p/ Técnico), custo_total_mes_fmt, orcamento_mes, orcamento_mes_fmt, financeiro_visivel, cards:[{chave,titulo,valor,valor_fmt,detalhe,cor}]}`
  (`cor`: marinho|laranja|verde|ciano). `cards` já vem pronto para iterar (4 itens; o de custo some para quem não vê financeiro).
- `dashboard.filtros`: `{periodo:'6m', departamento_id:int|None, equipamento_id:int|None}`; `periodos`: `[{valor,rotulo}]`; `departamentos`: `[{id,nome}]`; `equipamentos`: `[{id,codigo,descricao}]`.
- `/api/dashboard` → `{tempo_medio:[{rotulo,valor}], custo_por_maquina:[…], pecas_mais_usadas:[…], status_ordens:[…], kpis:{…}, titulo_periodo}`. Sem valor → `0` (nunca `null`).
- Relatórios: `tabela = {titulo, colunas:[str], linhas:[[str]], rodape:[str]|[], alinhamentos:['esq'|'dir']}` (células já formatadas, texto puro);
  `graficos = [{id, titulo, tipo:'bar'|'line'|'pie'|'doughnut', rotulos:[], valores:[], unidade:'R$'|''}]`. Abas: `os|estoque|financeiro|fornecedores`.
  Perfil sem financeiro não recebe colunas/gráficos de custo.
- `usuarios.contagem_perfis`: lista `[{nome,total}]` na ordem Administrador, Técnico, Gestor, Usuário Comum (também aceita `contagem_perfis['Técnico']` e `.items()`).
- `pedidos.contadores = {aberto, andamento, concluido, cancelado}`; `os.resumo = {aberta, andamento, concluida, cancelada}`.
- Pedido (item): `id, numero('#1623'), equipamento_id, equipamento, equipamento_codigo, departamento_id, departamento, solicitante, prioridade, status, data_solicitacao_fmt/_iso (e data_fmt), descricao_problema, aprovado_por, aprovado(bool)`.
  `pedido_detalhe` também recebe `pode_editar, pode_cancelar, pode_aprovar, pode_abrir_os` (bool) e `os` (dict|None).
- OS (item/detalhe): `id, numero('OS-10234'), status, id_pedido, pedido_numero, equipamento, departamento, prioridade, id_tecnico, tecnico, data_abertura_fmt/_iso, data_fechamento_fmt, observacao, atrasada(bool), dias_aberta`.
  `itens_os`: `id, id_peca, peca, peca_codigo, quantidade, quantidade_fmt, valor_unitario_fmt, valor_total_fmt`; `servicos_os`: `id, descricao_servico, valor_servico_fmt, id_prestador, prestador`; `apontamentos`: `id, data_fmt, data_iso, tecnico, horas_trabalhadas, tipo, observacao`.
  `os_detalhe` também recebe `pode_editar, pode_fechar, pode_reabrir` (bool), `status_opcoes` (edição).
  `os_form` recebe também `equipamentos` (para OS sem pedido) e `status_opcoes`.
- Peça (item): `id, codigo, nome, id_equipamento, equipamento, equipamento_codigo, ncm, valor_unitario, valor_unitario_fmt, qtde_estoque, qtde_fmt, estoque_minimo, baixo(bool)`.
- Movimento (estoque.itens): `id, peca_id, peca, codigo, tipo, quantidade, quantidade_fmt, valor_unitario_fmt, valor_total_fmt, data_fmt, documento_origem, numero_documento, usuario, observacao, pode_excluir`.
  `estoque.pecas` (selects): `id, codigo, nome, qtde_estoque, qtde_fmt, valor_unitario`.
- Equipamento (item): `id, codigo, descricao, ncm, id_grupo, grupo, id_subgrupo, subgrupo, id_departamento, departamento, status, controla_depreciacao, patrimoniado, vida_util_meses, valor_residual_padrao, valor_residual_fmt`. `grupos/subgrupos/departamentos` = `[{id,nome}]` (subgrupos também `id_grupo`). `status_opcoes` = lista de strings.
- Usuário (item): `id, nome, login, email, id_perfil, perfil, id_departamento, departamento, ativo(bool), status('Ativo'|'Inativo'), data_cadastro_fmt/_iso, iniciais`. `perfis` = `[{id,nome,descricao}]`.
- Fornecedor/prestador (item): colunas + `cnpj_fmt`, `cnpj` (só dígitos), `ativo(bool)`, `status`, `codigo` (`PST-001` para prestador), `endereco_fmt`; `ufs` = lista de siglas.
- `403.html/404.html/500.html` recebem `codigo`, `titulo`, `mensagem`. Falha de CSRF = HTTP 400 renderizando `403.html` com `codigo=400`.
- `redefinir_senha.html`: `token_invalido` (bool), `erros`, `erro`. Token inválido responde HTTP 400.
- `login.html`: `erro`, `proximo`, `valores.usuario`, `bloqueado` (bool).
- Depois do login o destino padrão é `/menu` (Manual §6.1), ou `proximo` se for caminho local seguro.

## 3. Variáveis de ambiente
`TECHMAINT_DB`, `TECHMAINT_SECRET_KEY`, `TECHMAINT_HOJE=AAAA-MM-DD` (congela a "data de hoje" — útil em testes). O link de redefinição de senha NUNCA aparece na tela (BUG-003): vai só para o log; com `app.testing=True` fica em `app.extensions["techmaint_ultimo_link_reset"]` (último link) e `app.extensions["techmaint_links_reset"]` (`{login: link}`). A resposta de `/recuperar-senha` é idêntica para login existente ou não.

## 4. Ajustes posteriores (leia se já tinha lido as seções acima)
- `equipamentos.listar` / `editar`: `subgrupos` traz **todos** os subgrupos (`id, nome, id_grupo`), para o select funcionar sem JS; com JS o select é refeito por `/api/subgrupos?grupo_id=`.
- Sub-formulários da OS (`/os/<id>/pecas`, `/servicos`, `/apontamentos`, edição de peça): se recusados, voltam a página `os_detalhe.html` com HTTP 200, `erros` (campo -> mensagem; campos `id_peca, quantidade, descricao_servico, valor_servico, horas_trabalhadas`; ou `geral`) e `valores`; a mensagem também vai como flash `erro`. `pecas_disponiveis` inclui peças sem saldo (o servidor recusa com "Estoque insuficiente...").
- `prestadores` no `os_detalhe`: dicts com `id, razao_social, nome, especialidade`.
- `POST /pedidos/<id>/abrir-os`: abre a OS direto com `id_tecnico` (ou, sem ele, com o próprio usuário se for Técnico; senão redireciona ao formulário `/os/nova?pedido_id=`). `GET` só redireciona ao formulário (não altera nada).
- Pedido: `prioridade` é obrigatória (a tela já vem com "Média" selecionada). Equipamentos "Baixado" aparecem no select com o sufixo " (baixado)" e são recusados no servidor.
- Apontamento: `data` é obrigatória. Item de usuário: `data_cadastro` já vem como `AAAA-MM-DD` (e `data_cadastro_iso` igual).
- Busca de fornecedores/prestadores aceita CNPJ com ou sem pontuação; CNPJ com letras é recusado.
- O token CSRF é mantido ao fazer login (formulários abertos antes do login continuam válidos).
- IDs na URL maiores que 2^63 -> 404; `//` na URL não é redirecionado (404).


## Rodada 2 (Dev)
- BUG-009: `/pedidos/novo` (e o filtro) NÃO oferece equipamento Baixado (substitui a nota antiga "(baixado)"); no POST, recusa com "Equipamento baixado não pode receber pedidos de manutenção." Na edição, o equipamento atual do pedido continua visível.
- BUG-008: fechar OS sem peças/serviços/apontamentos é permitido; flash `sucesso` + flash `aviso` "OS fechada sem peças, serviços ou apontamentos."
- BUG-010: `Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'`. O front usa atributos `style=` (por isso o unsafe-inline só em style-src), nenhum script/handler inline executável (o único `<script>` é `type="application/json"`).
