# API JSON do TechMaint

Tudo o que as telas fazem, a API também faz, usando **as mesmas funções de
banco e a mesma validação**. A API existe para o app no celular (PWA), para os
testes automáticos e para integrações futuras.

## Autenticação

A API usa a **mesma sessão** das telas (cookie). Faça login uma vez e mande o
cookie nas próximas chamadas.

```bash
# 1. Login (guarda o cookie no arquivo cookies.txt)
curl -c cookies.txt -H "Content-Type: application/json" \
     -d '{"login": "admin", "senha": "admin123"}' \
     http://127.0.0.1:5000/api/login

# 2. Chamadas seguintes usam o cookie
curl -b cookies.txt http://127.0.0.1:5000/api/eu
curl -b cookies.txt "http://127.0.0.1:5000/api/pecas?alerta=1"
```

No Postman ou no Insomnia, o cookie é guardado sozinho depois do `POST /api/login`.

**Toda requisição que envia dados (POST e PUT) precisa de `Content-Type: application/json`.**
É a proteção contra CSRF da API: um site de fora não consegue mandar JSON para
cá sem o navegador pedir licença antes (CORS), e o TechMaint não dá essa licença.

## Códigos de resposta

| Código | Quando |
|---|---|
| 200 | Deu certo |
| 201 | Registro criado (a resposta traz o registro, com o `id`) |
| 204 | Apagado (sem corpo) |
| 400 | O corpo não é um objeto JSON |
| 401 | Não está logado |
| 403 | Logado, mas o perfil não tem permissão |
| 404 | O `id` não existe |
| 409 | Conflito: apagar departamento com máquinas, desativar o próprio usuário... |
| 415 | Faltou `Content-Type: application/json` |
| 422 | Dados inválidos. A resposta diz o que está errado em cada campo |

Exemplo de 422:

```json
{
  "erro": "Dados invalidos.",
  "campos": {
    "cnpj": "CNPJ invalido. Confira os numeros digitados.",
    "razao_social": "Preencha a razao social."
  }
}
```

## Endpoints

Permissão necessária entre colchetes. "Desativa" = exclusão lógica: o registro
continua no banco com `ativo: false`.

### Sessão e usuários (SB-102)

| Método | Endereço | O que faz |
|---|---|---|
| POST | `/api/login` | `{"login", "senha"}` → usuário logado |
| POST | `/api/logout` | Encerra a sessão |
| GET | `/api/eu` | Usuário logado, perfis e lista de permissões [login] |
| GET | `/api/usuarios?busca=&inativos=1` | Lista [usuarios:ver] |
| GET | `/api/usuarios/<id>` | Um usuário [usuarios:ver] |
| POST | `/api/usuarios` | Cria [usuarios:editar] |
| PUT | `/api/usuarios/<id>` | Altera; `senha` vazia mantém a atual [usuarios:editar] |
| DELETE | `/api/usuarios/<id>` | Desativa [usuarios:editar] |

```json
{ "nome": "Ana Souza", "login": "ana", "email": "ana@empresa.com",
  "senha": "senhaforte", "perfis": ["TECNICO"] }
```

A resposta **nunca** traz a senha nem o hash.

### Departamentos (SB-104)

| Método | Endereço | O que faz |
|---|---|---|
| GET | `/api/departamentos?busca=` | Lista, com `total_maquinas` [departamentos:ver] |
| GET | `/api/departamentos/<id>` | Um departamento [departamentos:ver] |
| POST | `/api/departamentos` | `{"nome", "responsavel"}` [departamentos:editar] |
| PUT | `/api/departamentos/<id>` | Altera [departamentos:editar] |
| DELETE | `/api/departamentos/<id>` | Apaga (409 se tiver máquinas) [departamentos:editar] |

### Máquinas (SB-104)

| Método | Endereço | O que faz |
|---|---|---|
| GET | `/api/maquinas?busca=&departamento=ID&status=PARADO` | Lista com filtros [maquinas:ver] |
| GET | `/api/maquinas/<id>` | Uma máquina [maquinas:ver] |
| POST | `/api/maquinas` | Cria [maquinas:editar] |
| PUT | `/api/maquinas/<id>` | Altera [maquinas:editar] |
| DELETE | `/api/maquinas/<id>` | Apaga (409 se tiver peças) [maquinas:editar] |

```json
{ "nome": "Torno CNC", "patrimonio": "PAT-0001", "fabricante": "ROMI",
  "modelo": "GL 240", "id_departamento": 1, "status": "OPERANDO" }
```

`status`: `OPERANDO`, `EM_MANUTENCAO` ou `PARADO`.

### Peças e estoque (SB-106)

| Método | Endereço | O que faz |
|---|---|---|
| GET | `/api/pecas?busca=&maquina=ID&alerta=1` | Lista; mais críticos primeiro [pecas:ver] |
| GET | `/api/pecas/<id>` | Uma peça com o estoque [pecas:ver] |
| POST | `/api/pecas` | Cria peça + estoque [pecas:editar] |
| PUT | `/api/pecas/<id>` | Altera cadastro e limites (não altera o saldo) [pecas:editar] |
| DELETE | `/api/pecas/<id>` | Apaga a peça e o estoque dela [pecas:editar] |

```json
{ "nome": "Rolamento 6205 ZZ", "codigo": "ROL-6205", "ncm": "84821010",
  "valor_centavos": 3890, "id_maquina": 1,
  "estoque": { "atual": 12, "minimo": 4, "maximo": 20, "local": "Almox. A-01" } }
```

Na API o dinheiro vai em **centavos, número inteiro** (3890 = R$ 38,90). Na
resposta, `estoque.situacao` vem como `REPOR`, `EXCESSO` ou `OK`, e
`estoque.sugestao_compra` traz quanto comprar para voltar ao máximo.

### Fornecedores (SB-108) e prestadores de serviço (SB-110)

| Método | Endereço | O que faz |
|---|---|---|
| GET | `/api/fornecedores?busca=&inativos=1` | Lista (só ativos, por padrão) [fornecedores:ver] |
| GET | `/api/fornecedores/<id>` | Um fornecedor [fornecedores:ver] |
| POST | `/api/fornecedores` | Cria [fornecedores:editar] |
| PUT | `/api/fornecedores/<id>` | Altera [fornecedores:editar] |
| DELETE | `/api/fornecedores/<id>` | Desativa [fornecedores:editar] |

Os prestadores seguem o mesmo padrão, em `/api/prestadores`.

```json
{ "razao_social": "Rolamentos Paulista Ltda", "nome_fantasia": "RolaSP",
  "cnpj": "11.222.333/0001-81", "email": "vendas@rolasp.com",
  "telefone": "(11) 4000-1000", "contato": "Joana", "endereco": "Rua X, 100" }
```

Prestador: `razao_social`, `cnpj`, `especialidade`, `email`, `telefone`, `contato`.

O CNPJ pode ir com ou sem máscara. A resposta traz `cnpj` (só números) e
`cnpj_formatado` (com máscara).
