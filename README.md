# Planning & Budget IA

Application web auto-hébergée pour gérer le **planning**, le **budget** et le suivi de vos
projets, avec :

- 📊 **Tableau de bord** : argent libre, solde, avancement, échéances
- 🗂️ **Kanban** : À faire / En cours / Terminé avec glisser-déposer
- 📅 **Planning** : chronologie des tâches avec retards signalés
- 💰 **Budget** : revenus, dépenses, coût planifié
- 🤖 **Assistant IA** (OpenRouter) : discutez avec lui, il crée/déplace des tâches,
  enregistre des dépenses, ajuste le budget et tient une **mémoire** persistante
- 📄 **Documents .md** : importez vos résumés de projets, l'IA les lit pour vous suivre
- 🔗 **Intégration Wallos** : récupère vos abonnements via l'API Wallos et calcule
  l'**argent libre mensuel** (revenu mensuel − abonnements)

## Démarrage rapide (Docker)

```bash
docker compose up -d --build
```

Ouvrez http://localhost:8000

## Démarrage sans Docker

```bash
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## Configuration

Tout se configure dans l'onglet **⚙️ Paramètres** de l'application :

| Paramètre | Description |
|---|---|
| URL Wallos | Ex. `http://wallos:8282` (même hôte Docker) ou `http://IP:8282` |
| Clé API Wallos | Dans Wallos : Paramètres → API |
| Clé API OpenRouter | Sur [openrouter.ai](https://openrouter.ai) → Keys |
| Modèle | Ex. `openai/gpt-4o-mini`, `anthropic/claude-3.5-sonnet`, `mistralai/mistral-small`… |
| Revenu mensuel | Vos revenus mensuels, pour calculer l'argent libre |

**Argent libre / mois = revenu mensuel − total des abonnements Wallos.**
L'IA reçoit ce chiffre dans son contexte et adapte ses propositions de planning et de
budget en conséquence (elle ne proposera pas un budget supérieur à l'argent libre sans
vous prévenir).

## Mémoire de l'IA

La mémoire est stockée dans `data/memory/project_<id>_memory.md`. L'IA peut la relire et
la réécrire à chaque conversation (`update_memory` / `append_memory`), et vous pouvez
l'éditer à la main dans l'onglet Documents.

Les résumés de projets importés (.md) sont stockés dans `data/projects_md/project_<id>/`.

## API

Documentation interactive : http://localhost:8000/docs

Principales routes :

- `GET/POST /api/projects`, `PUT/DELETE /api/projects/{id}`
- `GET/POST /api/projects/{id}/tasks`, `PUT/DELETE /api/tasks/{id}`
- `GET/POST /api/projects/{id}/transactions`, `DELETE /api/transactions/{id}`
- `GET /api/projects/{id}/overview` — synthèse budget + planning
- `POST /api/wallos/sync` — synchronise les abonnements Wallos
- `POST /api/projects/{id}/chat` — parle à l'IA (elle agit sur le projet)
- `GET/PUT /api/projects/{id}/memory` — mémoire IA (.md)
- `POST /api/projects/{id}/docs` — import d'un .md

## Actions que l'IA peut exécuter

`add_task`, `move_task`, `update_task`, `delete_task`, `add_transaction`,
`delete_transaction`, `update_project`, `update_memory`, `append_memory`

## Stack

Python / FastAPI / SQLite (fichier `data/planner.db`) / frontend vanilla JS sans build.
