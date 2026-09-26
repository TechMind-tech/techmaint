# TechMaint

Sistema de manutenção predial e de máquinas em Flask, feito em etapas.
Continua **propositalmente simples**: só Flask, SQLite (`sqlite3` puro, sem ORM),
Jinja e CSS. Tudo comentado em português.

A Sprint 2 trouxe login com perfis de acesso e os cadastros de Departamentos,
Máquinas, Peças com estoque, Fornecedores e Prestadores de serviço, cada um
com **telas** e **API JSON**.

---

## 1. Como rodar

No terminal, dentro da pasta do projeto:

```bash
python -m venv .venv
.venv\Scripts\Activate.ps1          # Windows (PowerShell)
pip install -r requirements.txt
python seed.py                       # opcional: carrega dados de exemplo
python app.py
```

Abra <http://127.0.0.1:5000>. O arquivo `techmaint.db` é criado sozinho.

| Login | Senha | Perfil |
|---|---|---|
| `admin` | `admin123` | ADMINISTRADOR (criado sozinho no primeiro `python app.py`) |
| `gestor` | `senha123` | GESTOR (só com `python seed.py`) |
| `tecnico` | `senha123` | TÉCNICO (só com `python seed.py`) |
| `cliente` | `senha123` | CLIENTE (só com `python seed.py`) |

Entre com cada um e repare como o menu e os botões mudam. Troque a senha do
`admin` pela tela de Usuários.

> Se você já tinha um `techmaint.db` da versão com Equipamentos, apague o
> arquivo antes de rodar: o banco novo tem outras tabelas.

> **Ambiente virtual (`venv`)** é uma pasta com um Python só para este projeto.
> Você sabe que está ativo quando aparece `(.venv)` no começo da linha.

---

## 2. Os arquivos

```
techmaint/
├── app.py              cria o app, registra os módulos, erros e filtros
├── database.py         conexão com o banco + atalhos consultar/executar
├── schema.sql          a MODELAGEM: CREATE TABLE de todas as tabelas
├── seguranca.py        login obrigatório, perfis, permissões (RBAC), CSRF
├── validadores.py      regras de validação (CNPJ, dinheiro, e-mail...)
├── api.py              ajudantes das respostas JSON
├── seed.py             perfis, admin inicial e dados de exemplo
├── modulos/
│   ├── departamentos/  ← MÓDULO DE REFERÊNCIA: leia este primeiro
│   │   ├── dados.py        o SQL do módulo
│   │   └── rotas.py        telas + API do módulo
│   ├── maquinas/
│   ├── pecas/          peças + estoque mínimo/máximo
│   ├── fornecedores/
│   ├── prestadores/
│   └── usuarios/       login, logout e CRUD de usuários
├── templates/
│   ├── base.html       molde: menu por perfil, avisos, rodapé
│   ├── _macros.html    campo de formulário reutilizável + token CSRF
│   ├── inicio.html     página inicial com um cartão por módulo
│   ├── erros/          página amigável de erro (403, 404...)
│   └── <módulo>/       listar.html e form.html de cada módulo
├── static/css/style.css
├── tests/              testes automáticos (pytest)
└── docs/
    ├── usuarios-diretos-e-indiretos.md   (SB-111)
    ├── modelo-de-dados.md                diagrama ER e regras
    └── api.md                            todos os endpoints JSON
```

A regra de ouro continua: **`rotas.py` não escreve SQL** e **`dados.py` não
conhece HTML**.

---

## 3. Como os dados percorrem o sistema

```
navegador → seguranca.py (logado? tem permissão? token CSRF ok?)
          → modulos/x/rotas.py (valida com validadores.py)
          → modulos/x/dados.py (SQL) → banco (SQLite)
          → templates/x/*.html  → HTML pronto → navegador
                         ou JSON (rotas /api/...)
```

Cada módulo tem as mesmas rotas. Exemplo com departamentos:

| Endereço | Método | Função | Operação |
|---|---|---|---|
| `/departamentos/` | GET | `listar` | READ (tela) |
| `/departamentos/novo` | GET / POST | `novo` | formulário / CREATE |
| `/departamentos/editar/<id>` | GET / POST | `editar` | formulário / UPDATE |
| `/departamentos/apagar/<id>` | POST | `apagar` | DELETE |
| `/api/departamentos` | GET / POST | `api_listar` / `api_criar` | READ / CREATE (JSON) |
| `/api/departamentos/<id>` | GET / PUT / DELETE | `api_buscar` / `api_atualizar` / `api_apagar` | JSON |

Fornecedores, prestadores e usuários trocam o `apagar` por `desativar` e
`reativar` (exclusão lógica). A lista completa da API está em [docs/api.md](docs/api.md).

---

## 4. Ideias que se repetem em qualquer CRUD

**Um formulário serve para criar e editar.** A variável `item` decide: vazia
mostra campos em branco, preenchida mostra os valores atuais.

**Post/Redirect/Get.** Depois de gravar, a rota faz `redirect`. Sem isso, o F5
cadastraria o mesmo registro duas vezes.

**Query parametrizada.** Todo SQL usa `?` no lugar dos valores. Nunca monte SQL
com f-string: é assim que nasce SQL Injection.

**Valide no Python, não só no HTML.** O `required` do navegador ajuda, mas pode
ser burlado. A validação que vale é a do servidor, e ela é a mesma para a tela
e para a API (`validar()` no `rotas.py` de cada módulo).

**Regra importante fica em dois lugares.** Na rota, para dar uma mensagem clara
("Já existe um fornecedor com este CNPJ"); no banco (`UNIQUE`, `CHECK`,
`FOREIGN KEY`), para garantir mesmo se o código falhar.

**Permissão na rota, não só no menu.** Esconder o botão é conforto. Segurança é
o `@requer_permissao("maquinas:editar")` em cima da rota.

**Gravou em duas tabelas? Use transação.** Peça e estoque (e usuário e perfis)
são gravados com `with conexao:`: ou grava tudo, ou não grava nada.

---

## 5. Criar um módulo novo (ex.: Grupos)

1. `schema.sql`: escreva o `CREATE TABLE IF NOT EXISTS grupos (...)`.
2. `modulos/grupos/`: copie a pasta de `departamentos` (com o `__init__.py`
   vazio) e troque nomes, colunas e SQL em `dados.py` e `rotas.py`.
3. `templates/grupos/`: copie `listar.html` e `form.html` de departamentos e
   ajuste colunas e campos.
4. `seguranca.py`: adicione `"grupos": "Grupos"` em `MODULOS` e as permissões
   `grupos:ver` e `grupos:editar` nos perfis da `MATRIZ`.
5. `app.py`: importe o `bp` e registre com `app.register_blueprint(...)`.
6. `base.html` e `inicio.html`: adicione o link, dentro de `{% if pode('grupos:ver') %}`.
7. `tests/`: escreva pelo menos criar, validar e o 403 de quem não pode.

Rode `python app.py` de novo: as tabelas novas e as permissões novas entram sozinhas.

---

## 6. Segurança, em uma página

| O quê | Onde | Como |
|---|---|---|
| Senha | `modulos/usuarios/rotas.py` | Só o hash vai para o banco (`generate_password_hash`) |
| Login obrigatório | `seguranca.py` | `@requer_permissao` manda para `/login?next=...` |
| Perfis e permissões (RBAC) | `seguranca.py` → `MATRIZ` | usuário → perfis → permissões; 403 se não pode |
| CSRF nas telas | `seguranca.py` + `_macros.html` | Todo `<form method="POST">` leva `{{ csrf() }}` |
| CSRF na API | `seguranca.py` | POST/PUT só aceitam `Content-Type: application/json` |
| Redirecionamento aberto | `seguranca.destino_seguro` | O `?next=` só aceita endereços do próprio site |
| Erros | `app.py` | Página amigável; nunca o stack trace para o usuário |

**Esqueceu o `{{ csrf() }}` no formulário?** O POST volta com erro 400
"Formulario expirado". É a proteção funcionando.

---

## 7. Testes

```bash
pip install -r requirements.txt
python -m pytest
```

Cada teste roda num banco novo e descartável: o seu `techmaint.db` não é tocado.

| Arquivo | O que confere |
|---|---|
| `tests/test_validadores.py` | CNPJ, dinheiro, e-mail |
| `tests/test_autenticacao.py` | login, logout, hash da senha, CSRF, `?next=` |
| `tests/test_permissoes.py` | os 4 perfis, 403 no servidor, menu por perfil |
| `tests/test_usuarios.py` | CRUD de usuários, regras do último administrador |
| `tests/test_cadastros.py` | os cinco cadastros, estoque, API e as regras do banco |

---

## 8. Entregas da Sprint 2

| Tarefa | História | Entrega | Onde |
|---|---|---|---|
| SB-102 | US-01 Usuários | API CRUD de usuários com RBAC | `modulos/usuarios/`, `seguranca.py` |
| SB-103 | US-02 Máquinas | Modelagem: máquinas e departamentos | `schema.sql` (bloco 2), `docs/modelo-de-dados.md` |
| SB-104 | US-02 Máquinas | API CRUD de máquinas (e departamentos) | `modulos/maquinas/`, `modulos/departamentos/` |
| SB-105 | US-03 Peças | Modelagem: peças e estoque | `schema.sql` (bloco 3) |
| SB-106 | US-03 Peças | API CRUD de peças + estoque mínimo/máximo | `modulos/pecas/` |
| SB-107 | US-04 Fornecedores | Modelagem: fornecedores | `schema.sql` (bloco 4) |
| SB-108 | US-04 Fornecedores | API CRUD de fornecedores | `modulos/fornecedores/`, `validadores.py` |
| SB-109 | US-05 Prestadores | Modelagem: prestadores de serviço | `schema.sql` (bloco 5) |
| SB-110 | US-05 Prestadores | API CRUD de prestadores | `modulos/prestadores/` |
| SB-111 | US-15 Produto | Usuários diretos e indiretos | `docs/usuarios-diretos-e-indiretos.md` |

"API CRUD" aqui significa **as duas coisas**: as telas HTML (que o PWA usa) e
as rotas JSON em `/api/...`, ambas chamando o mesmo `dados.py`.

---

## 9. Próximos passos (Sprint 3)

- Movimentação de estoque (entrada e saída) e entrada de nota fiscal atualizando o saldo.
- Pedidos de manutenção e ordens de serviço, com as permissões de aprovar (GESTOR).
- Tela de detalhe da máquina com as peças e o histórico de manutenção.

---

## 10. Trabalhando com Git no VS Code

As entregas da Sprint 2 estão na branch **`feat/sprint2-cadastros`**. A `main`
continua com o CRUD base de Equipamentos até o merge.

### Abrir o projeto

`Arquivo → Abrir Pasta` e escolha `techmaint`. O painel do Git é o terceiro
ícone da barra lateral esquerda (três bolinhas ligadas por linhas), atalho
`Ctrl+Shift+G`.

### Ver em qual branch você está

Canto **inferior esquerdo** da janela. Aparece o nome da branch atual.
Clicando nele, o VS Code lista as branches e você troca de uma para outra.

> Trocar de branch com alterações não salvas no Git pode dar conflito.
> Faça commit antes de trocar.

### O ciclo do dia a dia

1. **Edite** os arquivos normalmente.
2. Abra o painel Git. Os arquivos alterados aparecem em *Changes*.
3. Clique no nome de um arquivo para ver o que mudou: vermelho é o que saiu,
   verde é o que entrou.
4. Passe o mouse no arquivo e clique no **`+`** (*Stage Changes*). Isso
   escolhe o que entra no commit. Para tudo de uma vez, use o `+` do
   cabeçalho *Changes*.
5. Escreva a mensagem na caixa de texto do topo. Frase curta, no presente:
   `adiciona busca por setor`.
6. Clique em **Commit**. O commit ficou salvo no seu computador.
7. Clique em **Sync Changes** (ou `...` → *Push*) para enviar ao GitHub.

Faça um commit por assunto. Vários commits pequenos são muito mais fáceis de
entender depois do que um commit gigante.

### Fazer o merge de `feat/sprint2-cadastros` na `main`

Quando estiver funcionando e comitado:

1. Canto inferior esquerdo → troque para **`main`**.
2. `...` (menu do painel Git) → **Pull** — traz o que houver de novo do
   GitHub.
3. `...` → **Branch** → **Merge...** → escolha **`feat/sprint2-cadastros`**.
4. **Sync Changes** para enviar a `main` atualizada.

Em resumo: você fica **na branch que vai receber** e manda trazer a outra.

### Se der conflito

O VS Code marca o arquivo e mostra os botões *Accept Current Change*,
*Accept Incoming Change* e *Accept Both Changes*. Escolha, salve o arquivo,
dê *Stage* e faça o commit do merge.

*Current* é a branch em que você está (`main`). *Incoming* é a que está
chegando (`feat/sprint2-cadastros`).

### Depois do merge

A branch `feat/sprint2-cadastros` pode ser apagada: painel Git → `...` → *Branch* →
*Delete Branch*. O histórico dos commits continua na `main`.

### Os mesmos comandos pelo terminal

Se quiser entender o que o VS Code faz por baixo:

```bash
git status
git add .
git commit -m "adiciona busca por setor"
git push
git checkout main
git merge feat/sprint2-cadastros
git push
```
