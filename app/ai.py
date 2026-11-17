import json
import re

import httpx

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

SYSTEM_PROMPT = """Tu es un assistant de gestion de projets. Tu aides l'utilisateur à gérer
le planning, le budget et le kanban de ses projets, en tenant compte de l'argent libre
disponible (revenus mensuels moins abonnements Wallos moins dépenses engagées).

Règles :
- Réponds toujours en français, de façon claire et concise.
- Si l'utilisateur te demande de modifier quelque chose (ajouter une tâche, déplacer une
  tâche, enregistrer une dépense/revenu, modifier le budget, mettre à jour ta mémoire),
  tu DOIS émettre un ou plusieurs blocs d'actions.
- Un bloc d'actions est un bloc de code json délimité par ```actions ... ```
  contenant une liste "actions" :

```actions
{"actions": [
  {"type": "add_task", "title": "...", "status": "todo|doing|done", "due_date": "YYYY-MM-DD", "cost": 0},
  {"type": "move_task", "task_id": 1, "status": "todo|doing|done"},
  {"type": "update_task", "task_id": 1, "title": "...", "due_date": "YYYY-MM-DD", "cost": 0, "description": "..."},
  {"type": "delete_task", "task_id": 1},
  {"type": "add_transaction", "kind": "income|expense", "label": "...", "amount": 10, "date": "YYYY-MM-DD", "category": "..."},
  {"type": "delete_transaction", "transaction_id": 1},
  {"type": "update_project", "name": "...", "description": "...", "total_budget": 0, "start_date": "YYYY-MM-DD", "end_date": "YYYY-MM-DD"},
  {"type": "update_memory", "content": "contenu complet du fichier mémoire"},
  {"type": "append_memory", "content": "texte à ajouter à la mémoire"}
]}
```

- Utilise update_memory pour réécrire entièrement ta mémoire (fiche projet, décisions,
  état d'avancement) et append_memory pour ajouter une note.
- Avant de planifier des dépenses, vérifie l'argent libre mensuel dans le contexte :
  ne propose jamais un budget qui dépasse l'argent libre sans le signaler clairement.
- Après un bloc d'actions, explique brièvement ce que tu as fait et pourquoi."""


ACTION_TYPES = {
    "add_task",
    "move_task",
    "update_task",
    "delete_task",
    "add_transaction",
    "delete_transaction",
    "update_project",
    "update_memory",
    "append_memory",
}


def extract_actions(text: str) -> list[dict]:
    actions: list[dict] = []
    blocks = re.findall(r"```actions\s*(.*?)```", text, flags=re.DOTALL)
    for block in blocks:
        try:
            data = json.loads(block)
            for action in data.get("actions", []):
                if isinstance(action, dict) and action.get("type") in ACTION_TYPES:
                    actions.append(action)
        except json.JSONDecodeError:
            continue
    return actions


async def chat(api_key: str, model: str, messages: list[dict]) -> str:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {"model": model, "messages": messages}
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(OPENROUTER_URL, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]
