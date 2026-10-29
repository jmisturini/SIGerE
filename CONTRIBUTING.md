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

A CI roda em todo PR e em todo push para `main`/`dev`: o workflow **Testes** executa o `pytest` em PRs e pushes para essas branches; o workflow **Qualidade** (ruff, bandit e pip-audit) roda apenas em PRs para elas.

## Release

1. Atualize `APP_VERSION` e o changelog em `app/version.py`;
2. PR `dev` → `main` e merge;
3. Crie a tag anotada no commit de merge (na `main`) e envie:

   ```bash
   git tag -a vX.Y.Z <sha-do-merge> -m "SIGerE vX.Y.Z"
   git push origin vX.Y.Z
   ```

4. Publique a **GitHub Release** a partir da tag, copiando título e grupos da
   entrada correspondente de `RELEASES` em `app/version.py`:

   ```bash
   gh release create vX.Y.Z --verify-tag --notes-file notas.md --title "SIGerE vX.Y.Z — <título da entrada>"
   ```

   O `--verify-tag` garante que a release usa a tag do passo 3 — sem ele, o
   `gh` criaria uma tag ausente apontando para o commit da branch padrão.

5. Nas máquinas sem `gh`, publique pela API: `POST /repos/jmisturini/SIGerE/releases`
   com `tag_name`, `name` e `body` — valide antes que a tag existe
   (`GET /repos/jmisturini/SIGerE/git/ref/tags/vX.Y.Z` → 200). Ver "Sem `gh`
   CLI" em [docs/guia-continuidade.md](docs/guia-continuidade.md).

6. PR `main` → `dev` para realinhar.

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
