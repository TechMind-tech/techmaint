# Usuários diretos e indiretos do TechMaint

**Tarefa:** SB-111 · **História:** US-15 Produto · **Versão:** 1.0 (Sprint 2)

## 1. Para que serve este documento

Define **quem usa** o TechMaint e **quem é afetado** por ele, sem usar. Essa
separação orienta três decisões do projeto:

- quais **perfis de acesso** o sistema precisa ter (e o que cada um pode fazer);
- quais **telas e relatórios** entram no escopo;
- quais **dados** precisam ser guardados, mesmo sem ninguém "de fora" entrar no sistema.

## 2. Definições

| Tipo | Definição | Tem login? |
|---|---|---|
| **Usuário direto** | Opera o sistema: cadastra, consulta, aprova, executa. As telas são desenhadas para ele. | Sim |
| **Usuário indireto** | Não opera o sistema, mas **fornece informação** para ele, **recebe algo** que sai dele (relatório, pedido, serviço) ou **é afetado** pelo resultado da manutenção. | Não |

Regra prática: se a pessoa precisa de **usuário e senha** para fazer o trabalho
dela, é usuário direto. Se ela aparece no sistema só como **cadastro** (um
fornecedor, um prestador) ou só **recebe o resultado**, é indireta.

## 3. Usuários diretos

Cada usuário direto corresponde a um **perfil** do sistema. Uma pessoa pode ter
mais de um perfil (por exemplo, GESTOR e TÉCNICO), e as permissões se somam.

| Perfil | Quem é na empresa | O que faz no TechMaint | Onde e quando usa |
|---|---|---|---|
| **ADMINISTRADOR** | Responsável de TI ou coordenador do sistema | Cadastra usuários, define perfis, reativa acessos; tem acesso a todos os cadastros | Computador, eventualmente |
| **GESTOR** | Gestor ou supervisor de manutenção | Mantém os cadastros (máquinas, departamentos, peças, fornecedores, prestadores), acompanha o estoque e os alertas de reposição, aprova ou rejeita pedidos de manutenção, acompanha indicadores | Computador, todos os dias |
| **TÉCNICO** | Técnico de manutenção interno (mecânico, eletricista) | Consulta máquinas, peças e estoque; executa as ordens de serviço, lança peças usadas e horas trabalhadas | **Celular (PWA)**, no chão de fábrica, várias vezes ao dia |
| **CLIENTE** | Quem precisa da manutenção: líder de setor, operador de máquina, área administrativa | Consulta as máquinas do seu departamento e abre pedidos de manutenção; acompanha o andamento do pedido | Celular ou computador, quando há um problema |

> Pedidos de manutenção e ordens de serviço entram na Sprint 3. Os perfis que
> vão usá-los já existem desde a Sprint 2.

### O que cada perfil precisa do sistema

- **ADMINISTRADOR:** controle de acesso seguro (senha com hash, desativar sem apagar), garantia de que o sistema nunca fica sem administrador.
- **GESTOR:** cadastros confiáveis (CNPJ validado, sem duplicidade), visão rápida do que está **abaixo do estoque mínimo**, histórico preservado para auditoria e custos.
- **TÉCNICO:** telas simples e legíveis no celular, poucos toques, busca rápida de máquina e peça, saber onde a peça está (local no almoxarifado).
- **CLIENTE:** abrir um pedido em poucos passos e saber se ele foi aprovado, sem acesso a custos, fornecedores ou estoque.

## 4. Usuários indiretos

| Quem | Como se relaciona com o TechMaint | O que o sistema guarda ou entrega para ele |
|---|---|---|
| **Diretoria / gerência geral** | Não opera; recebe os resultados | Indicadores e relatórios: custo de manutenção por máquina, tempo médio de atendimento, máquinas paradas |
| **Fornecedores de peças** | Vendem as peças; não acessam o sistema | Cadastro com CNPJ validado e contato; notas fiscais de compra vinculadas a eles; nunca são apagados (exclusão lógica) para não perder o histórico |
| **Prestadores de serviço terceirizados** | Executam serviços nas ordens de serviço; não acessam o sistema nesta versão | Cadastro com CNPJ e especialidade; registro dos serviços prestados em cada OS |
| **Compras** | Recebe a necessidade de reposição | Lista de peças abaixo do mínimo, com a **quantidade sugerida de compra** (máximo − atual) |
| **Financeiro e contabilidade** | Paga as notas e apura custos | Valores em centavos (sem erro de arredondamento), NCM das peças, notas fiscais por fornecedor, custo acumulado por máquina |
| **Operadores de máquina e ocupantes do prédio** | São afetados pela disponibilidade das máquinas e das instalações | Status da máquina (operando, em manutenção, parada) e prazo de atendimento dos pedidos |
| **Segurança do trabalho** | Precisa saber de equipamentos parados ou em risco | Status e histórico de manutenção de cada máquina |
| **Auditoria (interna ou externa)** | Confere o que foi feito, por quem e quando | Histórico preservado: usuários, fornecedores e prestadores são **desativados, nunca apagados** |

## 5. Como isso virou regra no sistema

| Decisão do sistema | Por causa de quem |
|---|---|
| Quatro perfis com permissões diferentes (RBAC) | Os quatro usuários diretos têm necessidades e responsabilidades diferentes |
| TÉCNICO e CLIENTE só **consultam** cadastros | Evita alteração de preço, estoque ou fornecedor por quem não é responsável por isso |
| Menu e botões mudam conforme o perfil, **e** a rota confere a permissão no servidor | Esconder o botão melhora a experiência; a checagem no servidor garante a segurança |
| Exclusão lógica de usuários, fornecedores e prestadores | Auditoria, financeiro e contabilidade precisam do histórico |
| Alerta de estoque mínimo com sugestão de compra | Gestor e Compras |
| Dinheiro em centavos; CNPJ só com números e validado | Financeiro, contabilidade e a qualidade do cadastro de fornecedores |
| Layout responsivo e PWA instalável | Técnico e Cliente usam o celular |
| API JSON além das telas | Permite o app no celular e integrações futuras (por exemplo, compras) |

## 6. Matriz de permissões (Sprint 2)

`ver` = listar e consultar · `editar` = cadastrar, alterar e remover ou desativar.

| Módulo | ADMINISTRADOR | GESTOR | TÉCNICO | CLIENTE |
|---|---|---|---|---|
| Usuários | ver, editar | ver | — | — |
| Departamentos | ver, editar | ver, editar | ver | ver |
| Máquinas | ver, editar | ver, editar | ver | ver |
| Peças e estoque | ver, editar | ver, editar | ver | — |
| Fornecedores | ver, editar | ver, editar | ver | — |
| Prestadores de serviço | ver, editar | ver, editar | ver | — |

A fonte da verdade desta tabela é o dicionário `MATRIZ` em `seguranca.py`. O
`seed.py` copia a matriz para o banco (tabelas `perfis`, `permissoes` e
`perfis_permissoes`). As permissões de pedidos e ordens de serviço entram na
Sprint 3, junto com esses módulos.

## 7. Premissas e pontos a confirmar

1. **CLIENTE é interno.** Nesta versão, "cliente" é o colaborador de outro setor
   que pede a manutenção. Se o sistema for usado por uma empresa de manutenção
   predial que atende clientes externos (condomínios, por exemplo), o CLIENTE
   passa a precisar ver **só os pedidos da própria unidade**, e isso exige um
   vínculo usuário → departamento ou unidade.
2. **Prestador sem login.** Prestadores terceirizados não acessam o sistema. Se
   no futuro eles forem fechar as próprias OS pelo celular, viram usuários
   diretos com um quinto perfil (PRESTADOR).
3. **Compras fora do sistema.** O TechMaint indica o que repor, mas o pedido de
   compra é feito fora dele. A entrada da nota fiscal (Sprint 3) é que atualiza
   o estoque.
