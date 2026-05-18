# CLAUDE.md

Guidance for Claude Code when working in this repository.

## What this project is

**Maldinis** is a Django 5.1 web app for a FIFA World Cup 2026 predictions game, built for a Spanish/Argentine friend group.

Users join private tournaments (via invite codes), make predictions, and earn points. Matches are global/shared across the app; predictions and rankings are scoped per tournament, so different friend groups can run separate pools.

**Production:** https://maldinis.app (also https://maldinis.onrender.com). Auto-deploys from `main` on push.

## Communication style

- **Spanish** for all user-facing UI text and copy. Code, comments, commit messages, and internal docs in English is fine.
- **Concise**: skip lengthy explanations. Brief justification when making design calls, then move on.
- **Complete files, not snippets**: when delivering code changes, show full file contents or use proper edits — never partial fragments with "..." that the user has to merge.
- **Ask before structural changes**: renaming folders, moving modules, changing URL routes in production, altering deploy config. Warn explicitly about consequences (Docker port conflicts, volume data loss, breaking external links, etc.).
- **Delegate technical calls when invited**: phrases like "lo mejor" or "lo que sea mejor" mean "you decide, give me a one-line justification."

## Workflow: phased development

The project is built in numbered phases, each with a clear scope, often spread across separate sessions. Some phases have sub-phases (e.g. 13a, 13b, 14a-g).

**Commit and branch conventions:**
- Commit messages and branch names in **Spanish**.
- One commit per phase (or sub-phase) combining all related changes.
- Conventional Commits format with Spanish descriptions: `feat:`, `fix:`, `chore:`, `style:`, `refactor:`, `docs:`.
  - Examples: `feat: pivot modelos a predicciones por grupo`, `fix: corregir filtro de fase de grupos en fixture`, `docs: contexto completo para Claude Code`.
- Branch names in Spanish, kebab-case: `fase-14a-modelos-prediccion`, `fix-bracket-render`, etc.
- Run `git add .` from repo root.
- Never leave `main` in a broken state between phases. If a phase removes a model or function, clean up all references in the same commit.

## Current state (Phase 14 in progress)

**Major pivot from Phase 13 era.** The original scoring model (predict score per match) is being replaced.

**New prediction model:**
1. **Group predictions** — pick 1st, 2nd, 3rd for each of the 12 groups (A–L).
2. **Third-place ranking** — order the 8 best third-place teams.
3. **Bracket predictions** — pick the winner (no score) of each knockout match.

**Special predictions** (Golden Ball / Golden Boot) unchanged.

**Scoring (Phase 14f):**
- Groups: 5/3/2 pts for correct 1st/2nd/3rd (max 120 pts)
- Thirds: 2 pts per team qualifying + 1 pt for exact position (max 24 pts)
- Bracket: 2/4/8/16/32 pts by round (R32/R16/QF/SF/F) — max 160 pts
- Total ~300 pts before specials.

**The old `Prediction` model (score-per-match) is being deleted.** New models being added in Phase 14a: `GroupPrediction`, `ThirdPlaceRanking` + `ThirdPlaceRankingEntry` (intermediate table), `BracketPrediction`. Per-user brackets are resolved on-the-fly by combining `Match.home_source`/`away_source` codes with the user's group + bracket predictions.

**Phase 14 sub-phases:**
- 14a — models + migrations (delete `Prediction`, clean ALL references in views/templates/admin/signals/services in one commit)
- 14b — pure function `resolve_user_bracket` + tests
- 14c — UI for group predictions
- 14d — UI for third-place ranking
- 14e — UI for interactive bracket
- 14f — scoring + ranking
- 14g — final cleanup

**Dependency chain:** changing a group prediction invalidates that user's third-place ranking and bracket. Enforce strict validation with user confirmation before cascade.

## Development setup

The project runs entirely via Docker Compose. The `app/` directory is volume-mounted, so code changes hot-reload without rebuilding.

```bash
docker-compose up              # Start web + postgres + pgadmin
docker-compose exec web python manage.py migrate
docker-compose exec web python manage.py createsuperuser
```

All `manage.py` commands run inside the `web` container:

```bash
docker-compose exec web python manage.py <command>
```

pgAdmin: `http://localhost:5050`.

### Key management commands

```bash
python manage.py sync_world_cup           # Pulls matches/scores from Football-Data.org
python manage.py sync_world_cup --dry-run
python manage.py crear_superusuario       # Bootstrap superuser from DJANGO_SUPERUSER_* env vars (Render)
```

### Tests

```bash
docker-compose exec web python manage.py test
docker-compose exec web python manage.py test predictions
```

## Architecture

Three Django apps under `app/`:

- **`predictions`** — core domain. Owns `Team`, `Match`, prediction models, special predictions. URL namespace for all tournament-scoped views at `/torneo/<id>/...` (fixture, bracket, ranking, etc.).
- **`tournaments`** — multi-tenant layer: `Tournament` + `TournamentMember`. Users create or join via an 8-character invite code. Admin actions (delete) require `Role.ADMIN`.
- **`accounts`** — auth: registration, login/logout via Django's built-in views, `UserSettings`.

### Data flow

1. `Team` and `Match` rows are seeded from JSON fixtures in `predictions/fixtures/` and updated via `sync_world_cup`.
2. `Match.stage` ∈ {`GROUP`, `R32`, `R16`, `QF`, `SF`, `3P`, `F`}.
3. `Match.home_source` / `away_source` encode bracket origin: `"1A"` = winner group A, `"2B"` = runner-up B, `"W73"` = winner of match 73, `"L101"` = loser of match 101. Empty for group stage. These were populated via data migration (not a management command) so they reproduce on a fresh DB.
4. Real teams populate `home_team`/`away_team` later via Football-Data.org sync; `home_source`/`away_source` remain as permanent metadata.
5. `SpecialPrediction` stores free-text "Golden Ball" / "Golden Boot" guesses, gated by `settings.SPECIAL_PREDICTIONS_DEADLINE`.

### Tournament membership guard

Every view in `predictions/views.py` and `tournaments/views.py` checks:

```python
TournamentMember.objects.filter(tournament=..., user=request.user).exists()
```

before serving the page. This is the authorization boundary — there is no object-level permission framework.

### Templates

- Global base: `app/templates/base.html`
- Per-app templates: `app/<appname>/templates/<appname>/<template>.html`
- Pure CSS with custom properties, Google Fonts (Barlow Condensed). No Bootstrap.
- Inline CSS/JS in templates via `{% block extra_css %}` / `{% block extra_js %}`.
- Flag rendering uses a `flag_url` template tag (`flagcdn.com` PNGs) with FIFA-to-ISO2 code mapping. Native emoji flags don't render on Windows/Chrome.

## Code conventions

- **Logic in views, not templates.** Conditional logic, state calculation, data grouping all belong in the view layer. Templates display only.
- **Data migrations for fixed regulation-defined data** (e.g. the 32 knockout slots are fixed by FIFA 2026 rules). Don't use management commands when the data must reproduce on a fresh DB setup.
- **YAGNI.** Don't model speculative scenarios. Example: FIFA 2026 R32 has ~495 possible third-place combinations — use generic "Tercer puesto" placeholder text instead.
- **Render free tier limitations are acceptable pre-tournament.** Data loss on DB recreation is fine until launch.

## Environment variables (`.env`)

| Variable | Purpose |
|---|---|
| `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` | Local Docker DB |
| `DATABASE_URL` | Production (Render injects automatically) |
| `SECRET_KEY` | Django secret |
| `DEBUG` | `"True"` locally, `"False"` on Render |
| `FOOTBALL_DATA_API_KEY` | Required for `sync_world_cup` |

## Deployment

- **Render free tier** (`render.yaml`). Cold start ~30–60s.
- Build command runs: migrations → `collectstatic` → `loaddata` (both fixture files) → `crear_superusuario`.
- Static files served by WhiteNoise.
- Custom domain via Namecheap (`maldinis.app`).
- Production admin credentials live in Render env vars.
- **Watch out:** Render's free PostgreSQL DB expires ~90 days after creation. Must be renewed before the World Cup.

## Security & destructive actions

Always ask before:
- Dropping tables, deleting data, running `migrate --fake` or `flush`.
- Renaming Django apps or top-level project folders (causes Docker port conflicts, volume rebinding, container naming collisions).
- Modifying `render.yaml` build/start commands.
- Force-pushing or rewriting git history on `main`.
- Touching production credentials or `.env` in commits.