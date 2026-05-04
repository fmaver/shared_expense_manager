# Contributing to shared_expense_manager

## Branch model

| Branch | Purpose | Deploys to |
|---|---|---|
| `main` | Integration trunk — always deployable | Staging (auto on merge) |
| `prod_render` | Production pointer — only moves via release workflow | Production (auto on push) |
| `feature/*`, `fix/*`, `chore/*` | Short-lived work branches | — |

## Day-to-day workflow

```
# 1. Branch from main
git checkout main && git pull
git checkout -b feature/my-thing

# 2. Work and push
git push -u origin feature/my-thing

# 3. Open a PR to main
#    → CI runs: lint → unit → docker-build
#    → Merging is blocked until all checks are green

# 4. Merge to main
#    → Render auto-deploys to staging
#    → Verify the change on the staging URL
```

## Cutting a production release

When staging looks good and you're ready to promote to prod:

1. Go to **Actions → Release → Run workflow**.
2. Enter the version (e.g. `v1.2.0`). Follow SemVer:
   - `PATCH` — bug fixes, no new features.
   - `MINOR` — new backwards-compatible features.
   - `MAJOR` — breaking changes.
3. Click **Run workflow**.

The workflow will:
- Tag `main` HEAD as `vX.Y.Z`.
- Fast-forward `prod_render` to that tag (triggers Render prod deploy).
- Create a GitHub Release with auto-generated notes.

## Rules

- Never push directly to `main` or `prod_render` — always go through a PR or the release workflow.
- `prod_render` only ever moves via the release workflow (fast-forward from a tag).
- PRs need green CI before merge.
- Commit messages should be descriptive; using Conventional Commits (`feat:`, `fix:`, `chore:`, `refactor:`) keeps auto-generated release notes clean.
