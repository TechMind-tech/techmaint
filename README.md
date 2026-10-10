# TechMaint — Sistema de Gestão de Manutenção

Sistema web para registrar equipamentos, peças, pedidos de manutenção e ordens de
serviço (OS), controlar o estoque de peças e acompanhar indicadores e relatórios.

Feito de propósito com poucas peças, para ser lido e aprendido: **Flask 3** (Python),
**SQLite** (módulo `sqlite3`, sem ORM), **Jinja** (templates) e CSS/JS próprios.
Tudo em português do Brasil e comentado.

---

## 1. Como rodar

Dentro da pasta do projeto:

```bash
python -m venv .venv
.venv\Scripts\Activate.ps1          # Windows (PowerShell)
source .venv/bin/activate           # Linux / macOS

pip install -r requirements.txt     # Flask, openpyxl (Excel) e reportlab (PDF)
python seed.py                      # cria o banco e os dados de demonstração
python app.py                       # http://127.0.0.1:5000
```

- O arquivo do banco (`techmaint.db`) é criado sozinho. Para usar outro caminho:
  `TECHMAINT_DB=/caminho/meu.db`.
- `python seed.py` pode ser repetido à vontade: não duplica nada e não desfaz o que
  você alterou. `python seed.py --limpar` **apaga** o banco e recria (só em desenvolvimento).
- Sem o `seed.py` o sistema sobe com o banco vazio e **sem nenhum usuário** para entrar.

> **Ambiente virtual (`venv`)** é uma pasta com um Python só para este projeto, para
> as bibliotecas de um projeto não conflitarem com as de outro.

### Usuários de demonstração (dados fictícios, só para desenvolvimento)

| Usuário | Senha | Nome | Perfil | Departamento |
|---|---|---|---|---|
| `admin` | `admin123` | João Administrador | Administrador | TI |
| `tecnico` | `tecnico123` | Maria Técnica | Técnico | Manutenção |
| `gestor` | `gestor123` | Carlos Gestor | Gestor | Produção |
| `solicitante` | `solicitante123` | Ana Solicitante | Usuário Comum | Produção |
| `plima` | `plima123` | Pedro Lima | Técnico | Manutenção |

**Troque essas senhas (ou apague os usuários) antes de usar fora do seu computador.**
As senhas curtas valem só para o seed: o cadastro de usuários exige 8 caracteres ou mais.

### Variáveis de ambiente

| Variável | Para quê |
|---|---|
| `TECHMAINT_DB` | caminho do arquivo SQLite (padrão: `techmaint.db` na pasta do projeto) |
| `TECHMAINT_SECRET_KEY` | chave que assina a sessão. **Defina em produção.** Sem ela, o app usa uma chave aleatória (as sessões caem a cada reinício) |
| `FLASK_DEBUG=1` | modo de desenvolvimento (recarrega sozinho e mostra erros) |
| `TECHMAINT_HOJE=AAAA-MM-DD` | congela a data "de hoje" (útil em testes e demonstrações) |
| `TECHMAINT_COOKIE_SEGURO=1` | marca o cookie de sessão como `Secure` (ligue ao usar HTTPS) |
| `PORT` | porta do `python app.py` (padrão 5000) |

---

## 2. Estrutura do projeto

```
techmaint/
├── app.py                 fábrica do app (criar_app): login, CSRF, permissões, erros 403/404/500
├── database.py            conexão SQLite, transações, init_db() e parâmetros
├── schema.sql             todas as tabelas (CREATE TABLE IF NOT EXISTS)
├── seed.py                dados de demonstração (idempotente)
├── dados/                 grupos, subgrupos e equipamentos reais (JSON gerado do documento de apoio)
├── modulos/               as rotas, um arquivo por área (Blueprints)
│   ├── auth.py            login, sair, recuperar e redefinir senha
│   ├── painel.py          menu principal e dashboard
│   ├── usuarios.py · departamentos.py · equipamentos.py · pecas.py
│   ├── fornecedores.py · prestadores.py (+ _pj.py, a parte em comum das duas)
│   ├── pedidos.py · ordens.py · estoque.py
│   ├── relatorios.py      relatórios e exportações
│   └── configuracoes.py   perfil, senha, tema e idioma
├── servicos/              regras de negócio (sem HTML)
│   ├── manutencao.py      pedido → OS → peças → fechar
│   ├── estoque.py         único lugar que mexe no saldo de peças
│   ├── permissoes.py      quem pode o quê (matriz) e o menu
│   ├── seguranca.py       senhas, CSRF, bloqueio de login, tokens
│   ├── indicadores.py     números do dashboard e dos relatórios
│   ├── exportacao.py      PDF, Excel e CSV
│   ├── alertas.py         sino do cabeçalho
│   └── validacoes.py · formularios.py · formatacao.py · consultas.py · auditoria.py ...
├── templates/             páginas (Jinja)
├── static/                CSS, JS e Chart.js (tudo local, sem CDN)
└── tests/                 testes automatizados (pytest e Playwright)
```

Regra de ouro: **rota (`modulos/`) recebe e responde; regra de negócio (`servicos/`)
decide; template só mostra.** Assim cada arquivo tem um trabalho só.

### Caminho de uma página

```
navegador → before_request (logado? CSRF confere?) → rota (modulos/*.py)
          → regra (servicos/*.py) → banco (SQLite) → template (templates/*.html) → navegador
```

---

## 3. Perfis e permissões

| Área | Administrador | Gestor | Técnico | Usuário Comum |
|---|---|---|---|---|
| Dashboard e relatórios | ver e exportar | ver e exportar | ver (sem valores em R$) | só relatório de OS (as próprias) |
| Usuários e perfis | tudo | — | — | — |
| Equipamentos, peças | tudo | ver | tudo | — |
| Fornecedores, prestadores, departamentos | tudo | ver | ver | — |
| Pedidos de manutenção | tudo | tudo e aprova | abrir, editar e consultar | abrir e ver os próprios |
| Ordens de serviço | tudo (reabre OS) | ver e fechar | tudo | ver o status das próprias |
| Movimentação de estoque | tudo | ver | tudo | — |
| Configurações | sim | sim | sim | sim |

- Sem login → redireciona (302) para `/login?proximo=...`. Sem permissão → página **403**.
- Itens de menu que o perfil não pode abrir não aparecem.
- A matriz fica em `servicos/permissoes.py` (fonte da verdade) e é copiada para as tabelas
  `permissoes` e `perfis_permissoes`. Na rota, basta `@permissao("equipamentos.editar")`.

---

## 4. Rotas principais

| Endereço | Para quê |
|---|---|
| `/login` · `/logout` · `/recuperar-senha` · `/redefinir-senha/<token>` | acesso |
| `/` · `/menu` · `/dashboard` | início, cards do menu e indicadores |
| `/usuarios` · `/departamentos` · `/equipamentos` · `/pecas` | cadastros (lista + formulário na mesma tela; `/<id>/editar`, `/<id>/excluir`) |
| `/fornecedores` · `/prestadores` | idem, com `/novo` |
| `/pedidos` · `/pedidos/novo` · `/pedidos/<id>` | pedidos (`/editar`, `/cancelar`, `/aprovar`, `/abrir-os`) |
| `/os` · `/os/nova` · `/os/<id>` | ordens de serviço (`/pecas`, `/servicos`, `/apontamentos`, `/fechar`, `/reabrir`) |
| `/estoque` | movimentação de estoque (registrar e histórico) |
| `/relatorios?aba=os\|estoque\|financeiro\|fornecedores` | relatórios |
| `/configuracoes` | perfil, senha, tema e idioma |
| `/api/dashboard` · `/api/relatorios/<aba>` · `/api/subgrupos?grupo_id=` | JSON (gráficos e select dependente) |
| `/dashboard/exportar.pdf` · `.xlsx` · `/relatorios/<aba>/exportar.pdf` · `.xlsx` · `.csv` | exportações (Administrador e Gestor) |

**GET** = quero ver uma página. **POST** = estou enviando dados. Ações que alteram dados
(excluir, aprovar, fechar...) só aceitam POST, sempre com o token CSRF.

---

## 5. Regras de negócio

1. **Pedido → OS.** Abrir uma OS a partir de um pedido "Aberto" o muda para "Em andamento".
   Cada pedido tem no máximo uma OS ativa. Cancelar pedido só se estiver "Aberto" e sem OS ativa.
2. **Peças na OS.** Adicionar peça confere o saldo, baixa o estoque e cria uma movimentação de
   *Saída*. Alterar a quantidade ou remover a peça estorna a diferença. A mesma peça lançada duas
   vezes soma na mesma linha. OS concluída ou cancelada é somente leitura (o Administrador pode reabrir).
3. **Fechar OS.** A OS vira "Concluída" (com data de fechamento) e o pedido vira "Concluído".
4. **Equipamento "Em manutenção"** automaticamente quando há OS "Em andamento" para ele; volta a
   "Ativo" ao concluir (equipamento "Baixado" não muda sozinho e não recebe pedidos).
5. **Estoque.** *Saída* maior que o saldo é recusada e nada muda. *Entrada* não altera o valor da
   peça. Excluir um movimento manual estorna o saldo (movimentos criados por uma OS só se desfazem
   pela própria OS). O saldo da peça é sempre igual à soma das suas movimentações.
6. **Alertas** (sino): peça abaixo do mínimo, OS aberta há mais de 7 dias (parâmetro
   `dias_os_atrasada`) e pedido de prioridade Alta sem OS.
7. **Exclusão com vínculos** não dá erro 500: usuários, fornecedores e prestadores com histórico
   são **inativados**; equipamentos, peças e departamentos em uso mostram "Não é possível excluir: há N vínculos".
8. **Auditoria.** Criar, editar, excluir, fechar e mudar status gravam em `historico_alteracoes`
   (quem, o quê, quando).
9. **Validações** (sempre no servidor): obrigatórios, e-mail, login único (3 a 50 caracteres, sem
   espaços), CNPJ com dígito verificador, UF válida, NCM com 8 dígitos, quantidade maior que zero,
   valores a partir de zero, código de equipamento único.
10. **Metas e orçamento** ficam na tabela `parametros` (`meta_os_mes`, `orcamento_mes`, `dias_os_atrasada`).

---

## 6. Segurança (o que já vem pronto)

- **SQL parametrizado** (`?`) em todo lugar; a ordenação de listas usa lista de colunas permitidas.
- **Senhas** com hash (Werkzeug); nunca em texto puro.
- **Login:** mensagem genérica ("Usuário ou senha inválidos."); 5 falhas seguidas bloqueiam o
  login por 5 minutos; usuário inativo não entra; sessão nova a cada login.
- **CSRF:** todo POST exige o token do formulário (campo `csrf_token`).
- **Recuperação de senha (simulada):** a tela responde sempre a mesma mensagem genérica, exista o login ou não, e
  **nunca mostra o link**. O link (válido por 30 minutos, de uso único; só o hash do token é guardado) vai
  apenas para o **log do servidor** (nível INFO, linha "[SIMULADO] Link de redefinição..."). Nos testes
  (`app.testing = True`) o último link fica em `app.extensions["techmaint_ultimo_link_reset"]` e todos em
  `app.extensions["techmaint_links_reset"]` (`{login: link}`); fora do modo de teste esses ganchos não existem.
- **Cabeçalhos** de segurança (inclui `Content-Security-Policy` só com recursos do próprio servidor, sem script inline; `style-src` aceita `unsafe-inline` porque as telas usam atributos `style`), páginas internas sem cache e erros sem *stack trace* na tela.
- **Exportações** neutralizam fórmulas (`=`, `+`, `-`, `@`) em Excel e CSV.
- Nenhum segredo no código: a chave da sessão vem do ambiente.

---

## 7. Como testar

```bash
pip install -r requirements-dev.txt
pytest -m "not e2e"          # testes de backend (usa o Flask test client)
playwright install chromium  # uma vez
pytest -m e2e                # testes de navegador
```

Os testes criam um banco temporário próprio (a partir do `seed.py`); o seu `techmaint.db` não é tocado.
Roteiro manual rápido: entre como `admin`, abra **Pedidos → #1624 → Abrir OS**, lance uma peça, feche
a OS e veja o estoque, o dashboard e os relatórios mudarem.

---

## 8. Limites conhecidos

- **Idioma:** só português (pt-BR) está disponível; as outras opções aparecem desabilitadas.
- **E-mail:** não há envio real; a recuperação de senha grava o link apenas no log do servidor (nunca na tela).
- **SQLite** atende bem uma equipe pequena. Muitos acessos simultâneos de escrita pedem outro banco.
- Para publicar, use um servidor de verdade (por exemplo `gunicorn app:app`) atrás de HTTPS,
  com `TECHMAINT_SECRET_KEY` e `TECHMAINT_COOKIE_SEGURO=1`.

---

## 9. Trabalhando com Git

O trabalho está na branch **`feature/sistema-completo`**. Ciclo do dia a dia: editar, `git status`,
`git add <arquivos>`, `git commit -m "adiciona busca por setor"` (frase curta, no presente) e `git push`.
Um commit por assunto fica muito mais fácil de entender depois. O arquivo `techmaint.db` **não** vai para
o Git (está no `.gitignore`): cada pessoa tem o seu.
