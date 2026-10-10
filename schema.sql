-- schema.sql
-- ----------
-- Estrutura do banco (SQLite) do TechMaint. Adaptacao do modelo SQL Server da
-- documentacao do projeto (secao 6): nomes em snake_case, sem acento.
--
-- Pode ser executado quantas vezes quiser (`IF NOT EXISTS`): o `init_db()` do
-- database.py faz isso toda vez que o app sobe.
--
-- Convencoes:
--   * datas "so dia"      -> texto ISO  'AAAA-MM-DD'
--   * data e hora          -> texto ISO  'AAAA-MM-DD HH:MM:SS'
--   * dinheiro / quantidade -> REAL (arredondado a 2 casas no codigo)
--   * booleano             -> INTEGER 0/1

-- ===========================================================================
-- a. Cadastros basicos: usuarios, perfis e permissoes
-- ===========================================================================

CREATE TABLE IF NOT EXISTS perfis (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    nome      TEXT NOT NULL UNIQUE,
    descricao TEXT
);

CREATE TABLE IF NOT EXISTS permissoes (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    nome      TEXT NOT NULL UNIQUE,
    descricao TEXT
);

CREATE TABLE IF NOT EXISTS departamentos (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    nome             TEXT NOT NULL UNIQUE COLLATE NOCASE,
    responsavel_id   INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
    responsavel_nome TEXT
);

CREATE TABLE IF NOT EXISTS usuarios (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    nome            TEXT NOT NULL,
    login           TEXT NOT NULL UNIQUE COLLATE NOCASE,
    senha_hash      TEXT NOT NULL,
    email           TEXT,
    ativo           INTEGER NOT NULL DEFAULT 1 CHECK (ativo IN (0, 1)),
    data_cadastro   TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    id_departamento INTEGER REFERENCES departamentos(id),
    idioma          TEXT NOT NULL DEFAULT 'pt-BR',
    tema            TEXT NOT NULL DEFAULT 'claro' CHECK (tema IN ('claro', 'escuro'))
);

-- N:N usuario <-> perfil (na tela, cada usuario tem 1 perfil principal)
CREATE TABLE IF NOT EXISTS usuarios_perfis (
    id_usuario INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    id_perfil  INTEGER NOT NULL REFERENCES perfis(id),
    PRIMARY KEY (id_usuario, id_perfil)
);

CREATE TABLE IF NOT EXISTS perfis_permissoes (
    id_perfil    INTEGER NOT NULL REFERENCES perfis(id) ON DELETE CASCADE,
    id_permissao INTEGER NOT NULL REFERENCES permissoes(id) ON DELETE CASCADE,
    PRIMARY KEY (id_perfil, id_permissao)
);

-- Fornecedores e prestadores de servico (mesmos campos; o prestador tem especialidade)
CREATE TABLE IF NOT EXISTS fornecedores (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    razao_social      TEXT NOT NULL,
    fantasia          TEXT,
    cnpj              TEXT NOT NULL UNIQUE,          -- 14 digitos, sem pontuacao
    inscricao_estadual TEXT,
    telefone          TEXT,
    email             TEXT,
    cep               TEXT,
    logradouro        TEXT,
    numero            TEXT,
    complemento       TEXT,
    bairro            TEXT,
    municipio         TEXT,
    uf                TEXT,
    ativo             INTEGER NOT NULL DEFAULT 1 CHECK (ativo IN (0, 1))
);

CREATE TABLE IF NOT EXISTS prestadores_servico (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    razao_social      TEXT NOT NULL,
    fantasia          TEXT,
    cnpj              TEXT NOT NULL UNIQUE,
    inscricao_estadual TEXT,
    telefone          TEXT,
    email             TEXT,
    cep               TEXT,
    logradouro        TEXT,
    numero            TEXT,
    complemento       TEXT,
    bairro            TEXT,
    municipio         TEXT,
    uf                TEXT,
    especialidade     TEXT,
    ativo             INTEGER NOT NULL DEFAULT 1 CHECK (ativo IN (0, 1))
);

-- ===========================================================================
-- b. Estruturas de classificacao: grupos, subgrupos, equipamentos, pecas
-- ===========================================================================

CREATE TABLE IF NOT EXISTS grupos (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    nome TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS subgrupos (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    nome     TEXT NOT NULL,
    id_grupo INTEGER NOT NULL REFERENCES grupos(id),
    UNIQUE (nome, id_grupo)
);

CREATE TABLE IF NOT EXISTS equipamentos (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo                TEXT NOT NULL UNIQUE COLLATE NOCASE,
    descricao             TEXT NOT NULL,
    ncm                   TEXT,
    id_grupo              INTEGER NOT NULL REFERENCES grupos(id),
    id_subgrupo           INTEGER NOT NULL REFERENCES subgrupos(id),
    id_departamento       INTEGER REFERENCES departamentos(id),
    status                TEXT NOT NULL DEFAULT 'Ativo'
                          CHECK (status IN ('Ativo', 'Em manutenção', 'Baixado')),
    controla_depreciacao  INTEGER NOT NULL DEFAULT 0 CHECK (controla_depreciacao IN (0, 1)),
    patrimoniado          INTEGER NOT NULL DEFAULT 0 CHECK (patrimoniado IN (0, 1)),
    vida_util_meses       INTEGER,
    valor_residual_padrao REAL
);

CREATE TABLE IF NOT EXISTS pecas (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo         TEXT UNIQUE COLLATE NOCASE,          -- ex.: ROL-6204 (gerado se vazio)
    id_equipamento INTEGER NOT NULL REFERENCES equipamentos(id),
    nome           TEXT NOT NULL,
    ncm            TEXT,
    valor_unitario REAL NOT NULL DEFAULT 0 CHECK (valor_unitario >= 0),
    qtde_estoque   REAL NOT NULL DEFAULT 0 CHECK (qtde_estoque >= 0),
    estoque_minimo REAL NOT NULL DEFAULT 5 CHECK (estoque_minimo >= 0)
);

-- ===========================================================================
-- c. Notas fiscais
-- ===========================================================================

CREATE TABLE IF NOT EXISTS notas_fiscais (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    id_fornecedor  INTEGER NOT NULL REFERENCES fornecedores(id),
    numero_nf      INTEGER NOT NULL,
    chave_acesso   TEXT,
    serie_nf       TEXT,
    data_emissao   TEXT,
    data_entrada   TEXT,
    cfop           TEXT,
    valor_total_nf REAL,
    valor_frete    REAL DEFAULT 0,
    valor_ipi      REAL DEFAULT 0,
    valor_icms     REAL DEFAULT 0,
    observacao     TEXT
);

CREATE TABLE IF NOT EXISTS itens_nota_fiscal (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    id_nota_fiscal INTEGER NOT NULL REFERENCES notas_fiscais(id) ON DELETE CASCADE,
    id_peca        INTEGER NOT NULL REFERENCES pecas(id),
    descricao_item TEXT,
    ncm            TEXT,
    cfop           TEXT,
    qtde           REAL NOT NULL,
    valor_unitario REAL NOT NULL,
    valor_total    REAL NOT NULL
);

-- ===========================================================================
-- d. Estoque e movimentacoes
-- ===========================================================================

-- Saldo por peca. O saldo "oficial" fica em pecas.qtde_estoque; esta tabela e
-- mantida em sincronia por servicos/estoque.py (ajustar_estoque).
CREATE TABLE IF NOT EXISTS estoque_pecas (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    id_peca            INTEGER NOT NULL UNIQUE REFERENCES pecas(id) ON DELETE CASCADE,
    qtde_atual         REAL NOT NULL DEFAULT 0,
    localizacao        TEXT,
    estoque_minimo     REAL,
    estoque_maximo     REAL,
    ultima_atualizacao TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS movimentacao_estoque_pecas (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    id_peca          INTEGER NOT NULL REFERENCES pecas(id),
    tipo             TEXT NOT NULL CHECK (tipo IN ('Entrada', 'Saída')),
    quantidade       REAL NOT NULL CHECK (quantidade > 0),
    valor_unitario   REAL,
    data             TEXT NOT NULL,
    documento_origem TEXT CHECK (documento_origem IN ('Nota Fiscal', 'Ordem de Serviço', 'Pedido Interno')),
    numero_documento TEXT,
    observacao       TEXT,
    id_usuario       INTEGER REFERENCES usuarios(id),
    id_nota_fiscal   INTEGER REFERENCES notas_fiscais(id) ON DELETE SET NULL,
    id_os            INTEGER REFERENCES ordens_servico(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS estoque_equipamentos (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    id_equipamento     INTEGER NOT NULL UNIQUE REFERENCES equipamentos(id) ON DELETE CASCADE,
    id_departamento    INTEGER REFERENCES departamentos(id),
    qtde_atual         REAL NOT NULL DEFAULT 1,
    localizacao        TEXT,
    status             TEXT,
    ultima_atualizacao TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS movimentacao_equipamentos (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    id_equipamento  INTEGER NOT NULL REFERENCES equipamentos(id) ON DELETE CASCADE,
    id_departamento INTEGER REFERENCES departamentos(id),
    tipo_movimento  TEXT NOT NULL,
    data            TEXT NOT NULL,
    responsavel     TEXT,
    observacao      TEXT
);

-- ===========================================================================
-- e. Manutencao e servicos
-- ===========================================================================

CREATE TABLE IF NOT EXISTS pedidos_manutencao (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    id_equipamento         INTEGER NOT NULL REFERENCES equipamentos(id),
    id_departamento        INTEGER NOT NULL REFERENCES departamentos(id),
    data_solicitacao       TEXT NOT NULL,
    solicitante            TEXT NOT NULL,
    id_usuario_solicitante INTEGER REFERENCES usuarios(id),
    descricao_problema     TEXT,
    prioridade             TEXT NOT NULL DEFAULT 'Média' CHECK (prioridade IN ('Baixa', 'Média', 'Alta')),
    status                 TEXT NOT NULL DEFAULT 'Aberto'
                           CHECK (status IN ('Aberto', 'Em andamento', 'Concluído', 'Cancelado')),
    aprovado_por           TEXT,
    data_aprovacao         TEXT
);

CREATE TABLE IF NOT EXISTS ordens_servico (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    id_pedido       INTEGER REFERENCES pedidos_manutencao(id),
    id_equipamento  INTEGER REFERENCES equipamentos(id),   -- vem do pedido; opcional se nao ha pedido
    data_abertura   TEXT NOT NULL,
    data_fechamento TEXT,
    id_tecnico      INTEGER REFERENCES usuarios(id),
    responsavel     TEXT,
    status          TEXT NOT NULL DEFAULT 'Aberta'
                    CHECK (status IN ('Aberta', 'Em andamento', 'Concluída', 'Cancelada')),
    observacao      TEXT
);

-- Regra pedido 1:1 OS: no maximo uma OS "viva" por pedido (OS cancelada libera o pedido).
CREATE UNIQUE INDEX IF NOT EXISTS ux_os_pedido_ativa
    ON ordens_servico (id_pedido) WHERE id_pedido IS NOT NULL AND status <> 'Cancelada';

CREATE TABLE IF NOT EXISTS itens_os (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    id_os          INTEGER NOT NULL REFERENCES ordens_servico(id) ON DELETE CASCADE,
    id_peca        INTEGER NOT NULL REFERENCES pecas(id),
    quantidade     REAL NOT NULL CHECK (quantidade > 0),
    valor_unitario REAL NOT NULL DEFAULT 0,
    valor_total    REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS servicos_os (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    id_os             INTEGER NOT NULL REFERENCES ordens_servico(id) ON DELETE CASCADE,
    descricao_servico TEXT NOT NULL,
    valor_servico     REAL NOT NULL DEFAULT 0 CHECK (valor_servico >= 0),
    id_prestador      INTEGER REFERENCES prestadores_servico(id)
);

CREATE TABLE IF NOT EXISTS apontamentos_os (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    id_os             INTEGER NOT NULL REFERENCES ordens_servico(id) ON DELETE CASCADE,
    data              TEXT NOT NULL,
    tecnico           TEXT NOT NULL,
    horas_trabalhadas REAL,
    tipo              TEXT,
    observacao        TEXT
);

-- ===========================================================================
-- Apoio: auditoria, parametros, seguranca
-- ===========================================================================

-- Log de auditoria: quem fez o que, em qual registro e quando.
CREATE TABLE IF NOT EXISTS historico_alteracoes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    entidade    TEXT NOT NULL,
    id_entidade INTEGER,
    acao        TEXT NOT NULL,
    usuario     TEXT,
    data        TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    detalhe     TEXT
);

CREATE TABLE IF NOT EXISTS parametros (
    chave TEXT PRIMARY KEY,
    valor TEXT
);

-- Controle de forca bruta no login: 5 falhas seguidas bloqueiam por 5 minutos.
CREATE TABLE IF NOT EXISTS tentativas_login (
    login         TEXT PRIMARY KEY COLLATE NOCASE,
    falhas        INTEGER NOT NULL DEFAULT 0,
    bloqueado_ate TEXT
);

-- Recuperacao de senha (simulada): guardamos so o hash do token.
CREATE TABLE IF NOT EXISTS tokens_recuperacao (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    token_hash TEXT NOT NULL UNIQUE,
    id_usuario INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    expira_em  TEXT NOT NULL,
    usado      INTEGER NOT NULL DEFAULT 0
);

-- ===========================================================================
-- Indices (consultas de listas, dashboard e relatorios)
-- ===========================================================================
CREATE INDEX IF NOT EXISTS ix_equip_grupo     ON equipamentos (id_grupo);
CREATE INDEX IF NOT EXISTS ix_equip_subgrupo  ON equipamentos (id_subgrupo);
CREATE INDEX IF NOT EXISTS ix_equip_depto     ON equipamentos (id_departamento);
CREATE INDEX IF NOT EXISTS ix_pecas_equip     ON pecas (id_equipamento);
CREATE INDEX IF NOT EXISTS ix_pedidos_status  ON pedidos_manutencao (status);
CREATE INDEX IF NOT EXISTS ix_pedidos_data    ON pedidos_manutencao (data_solicitacao);
CREATE INDEX IF NOT EXISTS ix_pedidos_equip   ON pedidos_manutencao (id_equipamento);
CREATE INDEX IF NOT EXISTS ix_os_status       ON ordens_servico (status);
CREATE INDEX IF NOT EXISTS ix_os_abertura     ON ordens_servico (data_abertura);
CREATE INDEX IF NOT EXISTS ix_os_pedido       ON ordens_servico (id_pedido);
CREATE INDEX IF NOT EXISTS ix_os_tecnico      ON ordens_servico (id_tecnico);
CREATE INDEX IF NOT EXISTS ix_itens_os_os     ON itens_os (id_os);
CREATE INDEX IF NOT EXISTS ix_itens_os_peca   ON itens_os (id_peca);
CREATE INDEX IF NOT EXISTS ix_serv_os_os      ON servicos_os (id_os);
CREATE INDEX IF NOT EXISTS ix_apont_os_os     ON apontamentos_os (id_os);
CREATE INDEX IF NOT EXISTS ix_mov_peca_data   ON movimentacao_estoque_pecas (id_peca, data);
CREATE INDEX IF NOT EXISTS ix_mov_data        ON movimentacao_estoque_pecas (data);
CREATE INDEX IF NOT EXISTS ix_hist_entidade   ON historico_alteracoes (entidade, id_entidade);
CREATE INDEX IF NOT EXISTS ix_nf_fornecedor   ON notas_fiscais (id_fornecedor);
