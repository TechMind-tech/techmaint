# Referência: código do Sprint 2 (main em c547ad3)

Esta pasta guarda, sem alterações, o código que o time tinha na `main` antes do
merge com `feature/sistema-completo` (usuários, departamentos, máquinas, peças,
fornecedores, prestadores, visual do Figma, validadores, testes e docs).

Por que não está ativo na raiz: os dois lados implementaram os mesmos módulos com
estruturas incompatíveis (por exemplo `modulos/pecas.py` x pacote `modulos/pecas/`,
e dois `schema.sql` diferentes). Misturar quebraria o app. O sistema completo
(raiz do repositório) é a versão que roda e passa nos testes.

Aproveitados na raiz: `validadores.py` (+ `tests/test_validadores.py`) e a
documentação em `docs/sprint2/`.

Esta pasta não é carregada pelo app nem pelo pytest (`testpaths = tests`).
Pode ser removida depois que o time migrar o que quiser para a raiz.
