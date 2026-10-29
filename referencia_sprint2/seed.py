"""
seed.py
-------
"Seed" (semente) = dados iniciais do banco.

Duas partes:

1. garantir_acesso_inicial()  -> SEMPRE roda quando o app sobe.
   Copia os perfis e permissoes do seguranca.py para o banco e, se ainda
   nao existir NENHUM usuario, cria o administrador inicial.

2. carregar_exemplos()        -> so quando voce roda `python seed.py`.
   Cadastra departamentos, maquinas, pecas, fornecedores, prestadores e
   um usuario de cada perfil, para demonstrar o sistema.

Tudo aqui pode rodar varias vezes seguidas sem duplicar nada:
`INSERT OR IGNORE` ignora a linha se ela bater num UNIQUE que ja existe.

Para rodar:
    python seed.py
"""

import os

from werkzeug.security import generate_password_hash

import database
from seguranca import MATRIZ, PERFIS, PERMISSOES

LOGIN_ADMIN = "admin"
# Troque a senha pela variavel de ambiente TECHMAINT_SENHA_ADMIN (ou pela
# tela de usuarios, depois do primeiro login).
SENHA_ADMIN = os.environ.get("TECHMAINT_SENHA_ADMIN", "admin123")
SENHA_EXEMPLOS = "senha123"


def garantir_acesso_inicial():
    conexao = database.conectar()
    with conexao:  # transacao: tudo ou nada
        for nome, descricao in PERFIS.items():
            conexao.execute(
                "INSERT OR IGNORE INTO perfis (nome, descricao) VALUES (?, ?)", (nome, descricao)
            )
        for codigo, descricao in PERMISSOES.items():
            conexao.execute(
                "INSERT OR IGNORE INTO permissoes (codigo, descricao) VALUES (?, ?)",
                (codigo, descricao),
            )

        # A matriz do seguranca.py e a fonte da verdade: apagamos os vinculos
        # e gravamos de novo. Assim, mudou a matriz, mudou o banco.
        conexao.execute("DELETE FROM perfis_permissoes")
        for perfil, codigos in MATRIZ.items():
            for codigo in codigos:
                conexao.execute(
                    """
                    INSERT INTO perfis_permissoes (id_perfil, id_permissao)
                    SELECT pf.id, pm.id FROM perfis pf, permissoes pm
                     WHERE pf.nome = ? AND pm.codigo = ?
                    """,
                    (perfil, codigo),
                )

        existe_alguem = conexao.execute("SELECT 1 FROM usuarios LIMIT 1").fetchone()
        if not existe_alguem:
            _criar_usuario(conexao, "Administrador", LOGIN_ADMIN, None, SENHA_ADMIN, ["ADMINISTRADOR"])
            print(f"\n  Administrador criado -> login: {LOGIN_ADMIN}  senha: {SENHA_ADMIN}")
            print("  Troque a senha depois do primeiro acesso.\n")
    conexao.close()


def _criar_usuario(conexao, nome, login, email, senha, perfis):
    conexao.execute(
        "INSERT OR IGNORE INTO usuarios (nome, login, email, senha_hash) VALUES (?, ?, ?, ?)",
        (nome, login, email, generate_password_hash(senha)),
    )
    for perfil in perfis:
        conexao.execute(
            """
            INSERT OR IGNORE INTO usuarios_perfis (id_usuario, id_perfil)
            SELECT u.id, p.id FROM usuarios u, perfis p WHERE u.login = ? AND p.nome = ?
            """,
            (login, perfil),
        )


def carregar_exemplos():
    conexao = database.conectar()
    with conexao:
        # --- Usuarios de demonstracao (um por perfil) ---------------------
        for nome, login, perfil in [
            ("Gabriela Gestora", "gestor", "GESTOR"),
            ("Tiago Tecnico", "tecnico", "TECNICO"),
            ("Carla Cliente", "cliente", "CLIENTE"),
        ]:
            _criar_usuario(conexao, nome, login, f"{login}@techmaint.local", SENHA_EXEMPLOS, [perfil])

        # --- Departamentos ------------------------------------------------
        for nome, responsavel in [
            ("Producao", "Marcos Lima"),
            ("Manutencao", "Rafael Souza"),
            ("Almoxarifado", "Beatriz Alves"),
            ("Administrativo", None),
        ]:
            conexao.execute(
                "INSERT OR IGNORE INTO departamentos (nome, responsavel) VALUES (?, ?)",
                (nome, responsavel),
            )

        # --- Maquinas (o departamento e achado pelo NOME) -------------------
        for nome, patrimonio, fabricante, modelo, departamento, status in [
            ("Torno CNC", "PAT-0001", "ROMI", "GL 240", "Producao", "OPERANDO"),
            ("Centro de usinagem", "PAT-0002", "ROMI", "D 800", "Producao", "EM_MANUTENCAO"),
            ("Compressor de ar", "PAT-0003", "Schulz", "SRP 3015", "Manutencao", "OPERANDO"),
            ("Empilhadeira eletrica", "PAT-0004", "Toyota", "8FBE20", "Almoxarifado", "PARADO"),
        ]:
            conexao.execute(
                """
                INSERT OR IGNORE INTO maquinas
                       (nome, patrimonio, fabricante, modelo, id_departamento, status)
                SELECT ?, ?, ?, ?, id, ? FROM departamentos WHERE nome = ?
                """,
                (nome, patrimonio, fabricante, modelo, status, departamento),
            )

        # --- Pecas + estoque ---------------------------------------------
        # (nome, codigo, ncm, valor em centavos, patrimonio da maquina,
        #  qtde atual, minima, maxima, local)
        for nome, codigo, ncm, valor, patrimonio, atual, minima, maxima, local in [
            ("Rolamento 6205 ZZ", "ROL-6205", "84821010", 3890, "PAT-0001", 12, 4, 20, "Almox. A-01"),
            ("Correia em V A-42", "COR-A42", "40103100", 5450, "PAT-0001", 2, 5, 15, "Almox. A-02"),
            ("Filtro de ar", "FIL-SRP", "84213990", 18900, "PAT-0003", 0, 2, 6, "Almox. B-01"),
            ("Oleo hidraulico 20L", "OLE-68", "27101932", 42500, "PAT-0002", 3, 2, 8, "Almox. C-03"),
            ("Bateria tracionaria", "BAT-48V", "85072090", 1250000, "PAT-0004", 1, 1, 2, "Almox. D-01"),
        ]:
            conexao.execute(
                """
                INSERT OR IGNORE INTO pecas (nome, codigo, ncm, valor_centavos, id_maquina)
                SELECT ?, ?, ?, ?, id FROM maquinas WHERE patrimonio = ?
                """,
                (nome, codigo, ncm, valor, patrimonio),
            )
            conexao.execute(
                """
                INSERT OR IGNORE INTO estoque_pecas (id_peca, qtde_atual, qtde_minima, qtde_maxima, local)
                SELECT id, ?, ?, ?, ? FROM pecas WHERE codigo = ?
                """,
                (atual, minima, maxima, local, codigo),
            )

        # --- Fornecedores e prestadores (CNPJs validos de exemplo) --------
        for razao, fantasia, cnpj, email, telefone, contato in [
            ("Rolamentos Paulista Ltda", "RolaSP", "11222333000181", "vendas@rolasp.exemplo",
             "(11) 4000-1000", "Joana"),
            ("Distribuidora Hidraulica Jundiai ME", "HidroJun", "44555666000181",
             "contato@hidrojun.exemplo", "(11) 4000-2000", "Paulo"),
        ]:
            conexao.execute(
                """
                INSERT OR IGNORE INTO fornecedores
                       (razao_social, nome_fantasia, cnpj, email, telefone, contato)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (razao, fantasia, cnpj, email, telefone, contato),
            )

        for razao, cnpj, especialidade, email, telefone, contato in [
            ("Eletrotec Servicos Industriais Ltda", "77888999000181", "Eletrica",
             "os@eletrotec.exemplo", "(11) 4000-3000", "Andre"),
            ("Frio Norte Refrigeracao EIRELI", "12312312000110", "Refrigeracao",
             "atendimento@frionorte.exemplo", "(11) 4000-4000", "Luciana"),
        ]:
            conexao.execute(
                """
                INSERT OR IGNORE INTO prestadores
                       (razao_social, cnpj, especialidade, email, telefone, contato)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (razao, cnpj, especialidade, email, telefone, contato),
            )
    conexao.close()


if __name__ == "__main__":
    database.criar_tabelas()
    garantir_acesso_inicial()
    carregar_exemplos()
    print("Banco pronto com dados de exemplo.")
    print(f"  admin / {SENHA_ADMIN}   (ADMINISTRADOR)")
    print(f"  gestor, tecnico, cliente / {SENHA_EXEMPLOS}")
