import json
import re
import shutil
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import ai, db, wallos

app = FastAPI(title="Planning & Budget IA")

static_dir = Path(__file__).parent / "static"


# ---------- helpers ----------

def project_or_404(project_id: int) -> dict:
    conn = db.get_conn()
    row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "Projet introuvable")
    return dict(row)


def docs_dir(project_id: int) -> Path:
    d = db.DOCS_DIR / f"project_{project_id}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def memory_path(project_id: int) -> Path:
    db.MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    return db.MEMORY_DIR / f"project_{project_id}_memory.md"


def safe_name(name: str) -> str:
    name = Path(name).name
    if not re.fullmatch(r"[\w\-. ]+\.md", name, flags=re.IGNORECASE):
        raise HTTPException(400, "Nom de fichier invalide (fichier .md attendu)")
    return name


# ---------- schemas ----------

class ProjectIn(BaseModel):
    name: str
    description: str = ""
    start_date: str = ""
    end_date: str = ""
    total_budget: float = 0


class TaskIn(BaseModel):
    title: str
    description: str = ""
    status: str = "todo"
    due_date: str = ""
    cost: float = 0


class TaskPatch(BaseModel):
    title: str | None = None
    description: str | None = None
    status: str | None = None
    due_date: str | None = None
    cost: float | None = None
    position: int | None = None


class TransactionIn(BaseModel):
    kind: str
    label: str
    amount: float
    date: str
    category: str = ""


class SettingsIn(BaseModel):
    wallos_url: str | None = None
    wallos_api_key: str | None = None
    openrouter_api_key: str | None = None
    openrouter_model: str | None = None
    monthly_income: float | None = None


class ChatIn(BaseModel):
    message: str


class MemoryIn(BaseModel):
    content: str


# ---------- settings ----------

@app.get("/api/settings")
def read_settings():
    keys = ["wallos_url", "wallos_api_key", "openrouter_api_key", "openrouter_model", "monthly_income"]
    out = {k: db.get_setting(k) for k in keys}
    if out["openrouter_api_key"]:
        out["openrouter_api_key"] = "••••" + out["openrouter_api_key"][-4:]
    if out["wallos_api_key"]:
        out["wallos_api_key"] = "••••" + out["wallos_api_key"][-4:]
    return out


@app.put("/api/settings")
def update_settings(payload: SettingsIn):
    for key, value in payload.model_dump().items():
        if value is None:
            continue
        if isinstance(value, str) and value.startswith("••••"):
            continue
        db.set_setting(key, str(value))
    return {"ok": True}


# ---------- projects ----------

@app.get("/api/projects")
def list_projects():
    conn = db.get_conn()
    rows = [dict(r) for r in conn.execute("SELECT * FROM projects ORDER BY id")]
    conn.close()
    return rows


@app.post("/api/projects")
def create_project(payload: ProjectIn):
    conn = db.get_conn()
    cur = conn.execute(
        "INSERT INTO projects (name, description, start_date, end_date, total_budget, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (payload.name, payload.description, payload.start_date, payload.end_date, payload.total_budget, db.now()),
    )
    project_id = cur.lastrowid
    conn.commit()
    conn.close()
    memory_path(project_id).write_text(
        f"# Mémoire — {payload.name}\n\nCréé le {db.now()}.\n", encoding="utf-8"
    )
    return project_or_404(project_id)


@app.put("/api/projects/{project_id}")
def update_project(project_id: int, payload: ProjectIn):
    project_or_404(project_id)
    conn = db.get_conn()
    conn.execute(
        "UPDATE projects SET name = ?, description = ?, start_date = ?, end_date = ?, total_budget = ? WHERE id = ?",
        (payload.name, payload.description, payload.start_date, payload.end_date, payload.total_budget, project_id),
    )
    conn.commit()
    conn.close()
    return project_or_404(project_id)


@app.delete("/api/projects/{project_id}")
def delete_project(project_id: int):
    project_or_404(project_id)
    conn = db.get_conn()
    conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
    conn.commit()
    conn.close()
    shutil.rmtree(docs_dir(project_id), ignore_errors=True)
    memory_path(project_id).unlink(missing_ok=True)
    return {"ok": True}


# ---------- tasks ----------

@app.get("/api/projects/{project_id}/tasks")
def list_tasks(project_id: int):
    project_or_404(project_id)
    conn = db.get_conn()
    rows = [dict(r) for r in conn.execute(
        "SELECT * FROM tasks WHERE project_id = ? ORDER BY position, id", (project_id,)
    )]
    conn.close()
    return rows


@app.post("/api/projects/{project_id}/tasks")
def create_task(project_id: int, payload: TaskIn):
    project_or_404(project_id)
    if payload.status not in ("todo", "doing", "done"):
        raise HTTPException(400, "Statut invalide")
    conn = db.get_conn()
    cur = conn.execute(
        "INSERT INTO tasks (project_id, title, description, status, due_date, cost, position, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (project_id, payload.title, payload.description, payload.status,
         payload.due_date, payload.cost, 0, db.now()),
    )
    conn.commit()
    task = dict(conn.execute("SELECT * FROM tasks WHERE id = ?", (cur.lastrowid,)).fetchone())
    conn.close()
    return task


@app.put("/api/tasks/{task_id}")
def update_task(task_id: int, payload: TaskPatch):
    conn = db.get_conn()
    row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "Tâche introuvable")
    if payload.status and payload.status not in ("todo", "doing", "done"):
        conn.close()
        raise HTTPException(400, "Statut invalide")
    fields = {k: v for k, v in payload.model_dump().items() if v is not None}
    sets = ", ".join(f"{k} = ?" for k in fields)
    conn.execute(f"UPDATE tasks SET {sets} WHERE id = ?", (*fields.values(), task_id))
    conn.commit()
    task = dict(conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone())
    conn.close()
    return task


@app.delete("/api/tasks/{task_id}")
def delete_task(task_id: int):
    conn = db.get_conn()
    conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
    conn.commit()
    conn.close()
    return {"ok": True}


# ---------- transactions ----------

@app.get("/api/projects/{project_id}/transactions")
def list_transactions(project_id: int):
    project_or_404(project_id)
    conn = db.get_conn()
    rows = [dict(r) for r in conn.execute(
        "SELECT * FROM transactions WHERE project_id = ? ORDER BY date DESC, id DESC", (project_id,)
    )]
    conn.close()
    return rows


@app.post("/api/projects/{project_id}/transactions")
def create_transaction(project_id: int, payload: TransactionIn):
    project_or_404(project_id)
    if payload.kind not in ("income", "expense"):
        raise HTTPException(400, "Type invalide (income ou expense)")
    conn = db.get_conn()
    cur = conn.execute(
        "INSERT INTO transactions (project_id, kind, label, amount, date, category, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (project_id, payload.kind, payload.label, payload.amount, payload.date, payload.category, db.now()),
    )
    conn.commit()
    tx = dict(conn.execute("SELECT * FROM transactions WHERE id = ?", (cur.lastrowid,)).fetchone())
    conn.close()
    return tx


@app.delete("/api/transactions/{transaction_id}")
def delete_transaction(transaction_id: int):
    conn = db.get_conn()
    conn.execute("DELETE FROM transactions WHERE id = ?", (transaction_id,))
    conn.commit()
    conn.close()
    return {"ok": True}


# ---------- overview ----------

@app.get("/api/projects/{project_id}/overview")
def project_overview(project_id: int):
    project = project_or_404(project_id)
    conn = db.get_conn()
    tasks = [dict(r) for r in conn.execute(
        "SELECT * FROM tasks WHERE project_id = ? ORDER BY position, id", (project_id,)
    )]
    txs = [dict(r) for r in conn.execute(
        "SELECT * FROM transactions WHERE project_id = ? ORDER BY date, id", (project_id,)
    )]
    conn.close()

    income = sum(t["amount"] for t in txs if t["kind"] == "income")
    expenses = sum(t["amount"] for t in txs if t["kind"] == "expense")
    planned_cost = sum(t["cost"] for t in tasks if t["status"] != "done")

    wallos_cache = db.get_setting("wallos_summary")
    wallos_total = 0.0
    if wallos_cache:
        try:
            wallos_total = json.loads(wallos_cache).get("monthly_total", 0.0)
        except json.JSONDecodeError:
            pass
    monthly_income = float(db.get_setting("monthly_income", "0") or 0)
    free_money = round(monthly_income - wallos_total, 2)

    today = db.now()[:10]
    return {
        "project": project,
        "income": round(income, 2),
        "expenses": round(expenses, 2),
        "balance": round(income - expenses, 2),
        "total_budget": project["total_budget"],
        "budget_used_pct": round(expenses / project["total_budget"] * 100, 1) if project["total_budget"] else 0,
        "planned_cost": round(planned_cost, 2),
        "tasks_total": len(tasks),
        "tasks_done": sum(1 for t in tasks if t["status"] == "done"),
        "tasks_late": sum(1 for t in tasks if t["status"] != "done" and t["due_date"] and t["due_date"] < today),
        "monthly_income": monthly_income,
        "wallos_monthly_total": round(wallos_total, 2),
        "free_money_monthly": free_money,
    }


# ---------- wallos ----------

@app.post("/api/wallos/sync")
async def wallos_sync():
    url = db.get_setting("wallos_url")
    key = db.get_setting("wallos_api_key")
    if not url or not key:
        raise HTTPException(400, "Configurez l'URL Wallos et la clé API dans les paramètres")
    try:
        payload = await wallos.fetch_subscriptions(url, key)
    except Exception as exc:
        raise HTTPException(502, f"Erreur Wallos : {exc}") from exc
    if not payload.get("success"):
        raise HTTPException(502, f"Wallos a refusé la requête : {payload.get('title', '?')}")
    summary = wallos.build_summary(payload)
    db.set_setting("wallos_summary", json.dumps(summary))
    db.set_setting("wallos_last_sync", db.now())
    return summary


@app.get("/api/wallos/summary")
def wallos_summary():
    cache = db.get_setting("wallos_summary")
    if not cache:
        return {"synced": False}
    data = json.loads(cache)
    data["synced"] = True
    data["last_sync"] = db.get_setting("wallos_last_sync")
    return data


# ---------- documents .md ----------

@app.post("/api/projects/{project_id}/docs")
async def upload_doc(project_id: int, file: UploadFile = File(...)):
    project_or_404(project_id)
    name = safe_name(file.filename or "doc.md")
    content = (await file.read()).decode("utf-8", errors="replace")
    (docs_dir(project_id) / name).write_text(content, encoding="utf-8")
    return {"ok": True, "name": name}


@app.get("/api/projects/{project_id}/docs")
def list_docs(project_id: int):
    project_or_404(project_id)
    files = sorted(p.name for p in docs_dir(project_id).glob("*.md"))
    return files


@app.get("/api/projects/{project_id}/docs/{name}")
def read_doc(project_id: int, name: str):
    project_or_404(project_id)
    path = docs_dir(project_id) / safe_name(name)
    if not path.exists():
        raise HTTPException(404, "Document introuvable")
    return {"name": name, "content": path.read_text(encoding="utf-8")}


@app.delete("/api/projects/{project_id}/docs/{name}")
def delete_doc(project_id: int, name: str):
    project_or_404(project_id)
    path = docs_dir(project_id) / safe_name(name)
    path.unlink(missing_ok=True)
    return {"ok": True}


# ---------- mémoire IA ----------

@app.get("/api/projects/{project_id}/memory")
def read_memory(project_id: int):
    project_or_404(project_id)
    path = memory_path(project_id)
    return {"content": path.read_text(encoding="utf-8") if path.exists() else ""}


@app.put("/api/projects/{project_id}/memory")
def write_memory(project_id: int, payload: MemoryIn):
    project_or_404(project_id)
    memory_path(project_id).write_text(payload.content, encoding="utf-8")
    return {"ok": True}


# ---------- chat IA ----------

def build_context(project_id: int) -> str:
    project = project_or_404(project_id)
    conn = db.get_conn()
    tasks = [dict(r) for r in conn.execute(
        "SELECT * FROM tasks WHERE project_id = ? ORDER BY position, id", (project_id,)
    )]
    txs = [dict(r) for r in conn.execute(
        "SELECT * FROM transactions WHERE project_id = ? ORDER BY date DESC LIMIT 30", (project_id,)
    )]
    conn.close()

    overview = project_overview(project_id)
    memory = ""
    path = memory_path(project_id)
    if path.exists():
        memory = path.read_text(encoding="utf-8")

    docs = []
    for name in sorted(p.name for p in docs_dir(project_id).glob("*.md")):
        content = (docs_dir(project_id) / name).read_text(encoding="utf-8")
        docs.append(f"### {name}\n{content[:4000]}")

    lines = [
        "## Contexte actuel",
        f"### Projet : {project['name']}",
        f"Description : {project['description'] or '—'}",
        f"Période : {project['start_date'] or '?'} → {project['end_date'] or '?'}",
        f"Budget total : {project['total_budget']} € | Dépenses : {overview['expenses']} € | "
        f"Revenus : {overview['income']} € | Coût planifié restant : {overview['planned_cost']} €",
        f"Revenu mensuel déclaré : {overview['monthly_income']} € | "
        f"Abonnements Wallos/mois : {overview['wallos_monthly_total']} € | "
        f"Argent libre/mois : {overview['free_money_monthly']} €",
        f"Tâches : {overview['tasks_done']}/{overview['tasks_total']} terminées, {overview['tasks_late']} en retard",
        "",
        "### Tâches (id | statut | échéance | coût | titre)",
    ]
    for t in tasks:
        lines.append(f"- #{t['id']} | {t['status']} | {t['due_date'] or '—'} | {t['cost']} € | {t['title']}")
    lines.append("")
    lines.append("### Dernières transactions")
    for t in txs:
        signe = "+" if t["kind"] == "income" else "-"
        lines.append(f"- #{t['id']} {t['date']} {signe}{t['amount']} € {t['label']} ({t['category'] or '—'})")

    lines.append("")
    lines.append("### Mémoire IA (memory.md)")
    lines.append(memory or "(vide)")
    if docs:
        lines.append("")
        lines.append("### Documents projet fournis (.md)")
        lines.extend(docs)
    return "\n".join(lines)


def apply_actions(project_id: int, actions: list[dict]) -> list[str]:
    log = []
    for action in actions:
        kind = action.get("type")
        try:
            if kind == "add_task":
                create_task(project_id, TaskIn(
                    title=str(action.get("title", "Sans titre")),
                    description=str(action.get("description", "")),
                    status=action.get("status", "todo"),
                    due_date=str(action.get("due_date", "")),
                    cost=float(action.get("cost", 0) or 0),
                ))
                log.append(f"Tâche ajoutée : {action.get('title')}")
            elif kind == "move_task":
                update_task(int(action["task_id"]), TaskPatch(status=action.get("status")))
                log.append(f"Tâche #{action['task_id']} déplacée vers {action.get('status')}")
            elif kind == "update_task":
                fields = {k: action[k] for k in ("title", "description", "due_date", "cost", "status") if k in action}
                update_task(int(action["task_id"]), TaskPatch(**fields))
                log.append(f"Tâche #{action['task_id']} mise à jour")
            elif kind == "delete_task":
                delete_task(int(action["task_id"]))
                log.append(f"Tâche #{action['task_id']} supprimée")
            elif kind == "add_transaction":
                create_transaction(project_id, TransactionIn(
                    kind=action.get("kind", "expense"),
                    label=str(action.get("label", "Sans nom")),
                    amount=float(action.get("amount", 0) or 0),
                    date=str(action.get("date") or db.now()[:10]),
                    category=str(action.get("category", "")),
                ))
                log.append(f"Transaction ajoutée : {action.get('label')} ({action.get('amount')} €)")
            elif kind == "delete_transaction":
                delete_transaction(int(action["transaction_id"]))
                log.append(f"Transaction #{action['transaction_id']} supprimée")
            elif kind == "update_project":
                p = project_or_404(project_id)
                update_project(project_id, ProjectIn(
                    name=action.get("name", p["name"]),
                    description=action.get("description", p["description"]),
                    start_date=action.get("start_date", p["start_date"]),
                    end_date=action.get("end_date", p["end_date"]),
                    total_budget=float(action.get("total_budget", p["total_budget"]) or 0),
                ))
                log.append("Projet mis à jour")
            elif kind == "update_memory":
                write_memory(project_id, MemoryIn(content=str(action.get("content", ""))))
                log.append("Mémoire mise à jour")
            elif kind == "append_memory":
                path = memory_path(project_id)
                current = path.read_text(encoding="utf-8") if path.exists() else ""
                write_memory(project_id, MemoryIn(content=current + "\n" + str(action.get("content", ""))))
                log.append("Note ajoutée à la mémoire")
        except Exception as exc:
            log.append(f"Échec action {kind} : {exc}")
    return log


@app.post("/api/projects/{project_id}/chat")
async def chat(project_id: int, payload: ChatIn):
    project_or_404(project_id)
    api_key = db.get_setting("openrouter_api_key")
    model = db.get_setting("openrouter_model", "openai/gpt-4o-mini")
    if not api_key:
        raise HTTPException(400, "Configurez votre clé OpenRouter dans les paramètres")

    conn = db.get_conn()
    history = [dict(r) for r in conn.execute(
        "SELECT role, content FROM chat_messages WHERE project_id = ? ORDER BY id DESC LIMIT 20", (project_id,)
    )]
    conn.close()
    history.reverse()

    messages = [{"role": "system", "content": ai.SYSTEM_PROMPT}]
    messages.append({"role": "system", "content": build_context(project_id)})
    messages.extend({"role": m["role"], "content": m["content"]} for m in history)
    messages.append({"role": "user", "content": payload.message})

    try:
        reply = await ai.chat(api_key, model, messages)
    except Exception as exc:
        raise HTTPException(502, f"Erreur OpenRouter : {exc}") from exc

    actions = ai.extract_actions(reply)
    log = apply_actions(project_id, actions)

    conn = db.get_conn()
    conn.execute(
        "INSERT INTO chat_messages (project_id, role, content, actions, created_at) VALUES (?, ?, ?, ?, ?)",
        (project_id, "user", payload.message, "", db.now()),
    )
    conn.execute(
        "INSERT INTO chat_messages (project_id, role, content, actions, created_at) VALUES (?, ?, ?, ?, ?)",
        (project_id, "assistant", reply, json.dumps(log, ensure_ascii=False), db.now()),
    )
    conn.commit()
    conn.close()
    return {"reply": reply, "applied": log}


@app.get("/api/projects/{project_id}/chat")
def chat_history(project_id: int):
    project_or_404(project_id)
    conn = db.get_conn()
    rows = [dict(r) for r in conn.execute(
        "SELECT * FROM chat_messages WHERE project_id = ? ORDER BY id", (project_id,)
    )]
    conn.close()
    return rows


@app.delete("/api/projects/{project_id}/chat")
def clear_chat(project_id: int):
    project_or_404(project_id)
    conn = db.get_conn()
    conn.execute("DELETE FROM chat_messages WHERE project_id = ?", (project_id,))
    conn.commit()
    conn.close()
    return {"ok": True}


# ---------- frontend ----------

@app.get("/")
def index():
    return FileResponse(static_dir / "index.html")


app.mount("/", StaticFiles(directory=static_dir), name="static")
