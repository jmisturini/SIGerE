# Guia de branches e releases

## Branches permanentes (protegidas — só recebem Pull Request)

| Branch | Papel |
|---|---|
| `main` | Código estável, fonte do deploy em produção. Cada release recebe tag `vX.Y.Z`. |
| `dev` | Branch de integração. Todo trabalho novo converge aqui. |

## Branches de trabalho (temporárias, criadas sempre a partir de `dev`)

| Prefixo | Quando usar | Destino |
|---|---|---|
| `feature/<nome>` | Nova função | PR → `dev` |
| `fix/<nome>` | Correção de bug | PR → `dev` |
| `hotfix/<nome>` | Urgência em produção | criada a partir de `main` → PR → `main`, depois merge de `main` → `dev` |

Depois do merge, apague a branch temporária.

## Fluxo do dia a dia

```bash
git switch dev && git pull
git switch -c feature/minha-funcao
# ... commits ...
git push -u origin feature/minha-funcao
# o push imprime o link para abrir o Pull Request para dev
```

A CI (workflow **Testes**) roda o `pytest` em todo PR e em todo push para `main`/`dev`.

## Release

1. Atualize `APP_VERSION` e o changelog em `app/version.py`;
2. PR `dev` → `main` e merge;
3. Crie a tag na `main` e envie:

```bash
git tag -a vX.Y.Z main -m "SIGerE vX.Y.Z"
git push origin vX.Y.Z
```

## Hotfix em produção

```bash
git switch main && git pull
git switch -c hotfix/correcao-urgente
# ... commits ...
git push -u origin hotfix/correcao-urgente
# PR para main; após o merge, integre a correção na dev
# (PR main → dev) para o fix não se perder na próxima release
```

## Estilo dos commits

Prefixo por área, em minúsculas: `pagamentos:`, `vt:`, `ui:`, `seguranca:`, `migrations:`, `testes:`, `docs:`, `ci:`, `release:`.
