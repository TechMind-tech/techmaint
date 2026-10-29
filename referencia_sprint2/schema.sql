-- ===========================================================================
-- schema.sql  -  estrutura do banco do TechMaint (SQLite)
-- ===========================================================================
--
-- Este arquivo e a MODELAGEM do banco em forma de codigo (DDL).
-- O database.py le este arquivo e executa tudo quando o app sobe.
--
-- Convencoes usadas em TODAS as tabelas:
--   * chave primaria se chama `id`
--   * chave estrangeira se chama `id_<tabela no singular>`  (ex.: id_departamento)
--   * nomes em portugues, minusculo, com underline (snake_case)
--   * dinheiro em CENTAVOS, num INTEGER. Nunca REAL/float para dinheiro:
--     0.1 + 0.2 em float da 0.30000000000000004
--   * booleano vira INTEGER 0/1 (SQLite nao tem tipo booleano)
--   * datas em TEXT no formato ISO (AAAA-MM-DD HH:MM:SS)
--
-- `IF NOT EXISTS` faz o script poder rodar toda vez sem apagar nada.
--
-- Atencao: no SQLite a checagem de chave estrangeira vem DESLIGADA.
-- O database.py liga com `PRAGMA foreign_keys = ON` em toda conexao.
-- ===========================================================================


-- ---------------------------------------------------------------------------
-- BLOCO 1 - ACESSO  (SB-102 / US-01)
--
--   usuarios  N:N  perfis      (tabela de juncao usuarios_perfis)
--   perfis    N:N  permissoes  (tabela de juncao perfis_permissoes)
--
-- Isso e RBAC (Role-Based Access Control): a permissao nao e dada direto
-- para a pessoa, e dada para o PERFIL. A pessoa recebe perfis.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS perfis (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    nome        TEXT    NOT NULL UNIQUE,          -- ADMINISTRADOR, GESTOR...
    descricao   TEXT
);

CREATE TABLE IF NOT EXISTS permissoes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo      TEXT    NOT NULL UNIQUE,          -- ex.: 'maquinas:editar'
    descricao   TEXT
);

CREATE TABLE IF NOT EXISTS perfis_permissoes (
    id_perfil     INTEGER NOT NULL REFERENCES perfis(id)     ON DELETE CASCADE,
    id_permissao  INTEGER NOT NULL REFERENCES permissoes(id) ON DELETE CASCADE,
    PRIMARY KEY (id_perfil, id_permissao)         -- impede o par repetido
);

CREATE TABLE IF NOT EXISTS usuarios (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    nome           TEXT    NOT NULL,
    login          TEXT    NOT NULL UNIQUE COLLATE NOCASE,  -- 'Ana' = 'ana'
    email          TEXT    UNIQUE COLLATE NOCASE,
    senha_hash     TEXT    NOT NULL,              -- NUNCA a senha em texto puro
    ativo          INTEGER NOT NULL DEFAULT 1 CHECK (ativo IN (0, 1)),
    data_cadastro  TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS usuarios_perfis (
    id_usuario  INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    id_perfil   INTEGER NOT NULL REFERENCES perfis(id)   ON DELETE CASCADE,
    PRIMARY KEY (id_usuario, id_perfil)
);


-- ---------------------------------------------------------------------------
-- BLOCO 2 - MAQUINAS E DEPARTAMENTOS  (SB-103 / US-02)
--
--   departamentos  1:N  maquinas
--   (um departamento tem varias maquinas; cada maquina fica em UM departamento)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS departamentos (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    nome         TEXT    NOT NULL UNIQUE COLLATE NOCASE,
    responsavel  TEXT
);

CREATE TABLE IF NOT EXISTS maquinas (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    nome             TEXT    NOT NULL,
    patrimonio       TEXT    UNIQUE COLLATE NOCASE,   -- numero da plaqueta
    fabricante       TEXT,
    modelo           TEXT,
    -- ON DELETE RESTRICT: o banco NAO deixa apagar um departamento
    -- que ainda tem maquina. Protege contra maquina "orfa".
    id_departamento  INTEGER NOT NULL
                     REFERENCES departamentos(id) ON DELETE RESTRICT,
    status           TEXT    NOT NULL DEFAULT 'OPERANDO'
                     CHECK (status IN ('OPERANDO', 'EM_MANUTENCAO', 'PARADO'))
);

CREATE INDEX IF NOT EXISTS idx_maquinas_departamento ON maquinas(id_departamento);


-- ---------------------------------------------------------------------------
-- BLOCO 3 - PECAS E ESTOQUE  (SB-105 / US-03)
--
--   maquinas  1:N  pecas
--   pecas     1:1  estoque_pecas   (garantido pelo UNIQUE em id_peca)
--
-- Por que o estoque fica em outra tabela? Porque "o que a peca e" (nome,
-- NCM, preco) muda pouco, e "quanto tem dela" muda o tempo todo. Separar
-- deixa cada tabela com um assunto so.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS pecas (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    nome             TEXT    NOT NULL,
    codigo           TEXT    UNIQUE COLLATE NOCASE,   -- codigo interno/fabricante
    ncm              TEXT    CHECK (ncm IS NULL OR length(ncm) = 8),
    valor_centavos   INTEGER NOT NULL DEFAULT 0 CHECK (valor_centavos >= 0),
    id_maquina       INTEGER NOT NULL
                     REFERENCES maquinas(id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_pecas_maquina ON pecas(id_maquina);

CREATE TABLE IF NOT EXISTS estoque_pecas (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    id_peca      INTEGER NOT NULL UNIQUE
                 REFERENCES pecas(id) ON DELETE CASCADE,
    qtde_atual   INTEGER NOT NULL DEFAULT 0 CHECK (qtde_atual  >= 0),
    qtde_minima  INTEGER NOT NULL DEFAULT 0 CHECK (qtde_minima >= 0),
    qtde_maxima  INTEGER NOT NULL DEFAULT 0,
    local        TEXT,                                -- ex.: "Almoxarifado A - prateleira 3"
    CHECK (qtde_maxima >= qtde_minima)
);


-- ---------------------------------------------------------------------------
-- BLOCO 4 - FORNECEDORES  (SB-107 / US-04)
--
-- CNPJ guardado SO com numeros (14 caracteres). A mascara 00.000.000/0000-00
-- e colocada so na hora de mostrar.
-- Fornecedor nunca e apagado: e desativado (ativo = 0), para nao perder o
-- historico de notas fiscais que vao apontar para ele.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS fornecedores (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    razao_social   TEXT    NOT NULL,
    nome_fantasia  TEXT,
    cnpj           TEXT    NOT NULL UNIQUE CHECK (length(cnpj) = 14),
    email          TEXT,
    telefone       TEXT,
    contato        TEXT,                              -- nome da pessoa de contato
    endereco       TEXT,
    ativo          INTEGER NOT NULL DEFAULT 1 CHECK (ativo IN (0, 1)),
    data_cadastro  TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);


-- ---------------------------------------------------------------------------
-- BLOCO 5 - PRESTADORES DE SERVICO  (SB-109 / US-05)
--
-- Quase igual a fornecedores, mas quem PRESTA SERVICO (executa manutencao),
-- nao quem vende peca. Mesma regra de exclusao logica.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS prestadores (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    razao_social   TEXT    NOT NULL,
    cnpj           TEXT    NOT NULL UNIQUE CHECK (length(cnpj) = 14),
    especialidade  TEXT,                              -- ex.: "Eletrica", "Hidraulica"
    email          TEXT,
    telefone       TEXT,
    contato        TEXT,
    ativo          INTEGER NOT NULL DEFAULT 1 CHECK (ativo IN (0, 1)),
    data_cadastro  TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);
