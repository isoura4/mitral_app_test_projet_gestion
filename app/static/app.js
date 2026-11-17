const $ = (sel) => document.querySelector(sel);

let projects = [];
let currentProject = null;
let tasks = [];
let transactions = [];

function toast(msg) {
  const el = $("#toast");
  el.textContent = msg;
  el.classList.add("show");
  clearTimeout(el._t);
  el._t = setTimeout(() => el.classList.remove("show"), 2600);
}

async function api(path, options = {}) {
  if (options.json) {
    options.body = JSON.stringify(options.json);
    options.headers = { "Content-Type": "application/json" };
    delete options.json;
  }
  const res = await fetch(path, options);
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch {}
    throw new Error(detail);
  }
  return res.json();
}

function fmt(amount) {
  return Number(amount || 0).toLocaleString("fr-FR", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + " €";
}

// ---------- projects ----------

async function loadProjects() {
  projects = await api("/api/projects");
  const sel = $("#projectSelect");
  sel.innerHTML = "";
  for (const p of projects) {
    const opt = document.createElement("option");
    opt.value = p.id;
    opt.textContent = p.name;
    sel.appendChild(opt);
  }
  if (projects.length) {
    const saved = localStorage.getItem("projectId");
    currentProject = projects.find((p) => p.id == saved) || projects[0];
    sel.value = currentProject.id;
    await loadAll();
  } else {
    currentProject = null;
    openProjectDialog();
  }
}

function openProjectDialog() {
  $("#projectDialogTitle").textContent = currentProject ? "Modifier le projet" : "Nouveau projet";
  $("#pName").value = currentProject?.name || "";
  $("#pDesc").value = currentProject?.description || "";
  $("#pStart").value = currentProject?.start_date || "";
  $("#pEnd").value = currentProject?.end_date || "";
  $("#pBudget").value = currentProject?.total_budget || "";
  $("#projectDialog").showModal();
}

$("#newProjectBtn").addEventListener("click", () => {
  currentProject = null;
  openProjectDialog();
});
$("#projectSelect").addEventListener("change", async (e) => {
  currentProject = projects.find((p) => p.id == e.target.value);
  localStorage.setItem("projectId", currentProject.id);
  await loadAll();
});
$("#projectSaveBtn").addEventListener("click", async (e) => {
  e.preventDefault();
  const payload = {
    name: $("#pName").value.trim(),
    description: $("#pDesc").value,
    start_date: $("#pStart").value,
    end_date: $("#pEnd").value,
    total_budget: parseFloat($("#pBudget").value) || 0,
  };
  if (!payload.name) return toast("Le nom est requis");
  try {
    if (currentProject) {
      await api(`/api/projects/${currentProject.id}`, { method: "PUT", json: payload });
    } else {
      const p = await api("/api/projects", { method: "POST", json: payload });
      currentProject = p;
      localStorage.setItem("projectId", p.id);
    }
    $("#projectDialog").close();
    await loadProjects();
    toast("Projet enregistré");
  } catch (err) { toast(err.message); }
});

async function loadAll() {
  if (!currentProject) return;
  [tasks, transactions] = await Promise.all([
    api(`/api/projects/${currentProject.id}/tasks`),
    api(`/api/projects/${currentProject.id}/transactions`),
  ]);
  await Promise.all([renderDashboard(), renderKanban(), renderPlanning(), renderBudget(), renderDocs(), renderChat()]);
}

// ---------- dashboard ----------

async function renderDashboard() {
  const o = await api(`/api/projects/${currentProject.id}/overview`);
  const donePct = o.tasks_total ? Math.round(o.tasks_done / o.tasks_total * 100) : 0;
  $("#dashCards").innerHTML = `
    <div class="card"><div class="label">Argent libre / mois</div><div class="value ${o.free_money_monthly < 0 ? "bad" : "ok"}">${fmt(o.free_money_monthly)}</div></div>
    <div class="card"><div class="label">Abonnements Wallos / mois</div><div class="value">${fmt(o.wallos_monthly_total)}</div></div>
    <div class="card"><div class="label">Solde du projet</div><div class="value ${o.balance < 0 ? "bad" : "ok"}">${fmt(o.balance)}</div></div>
    <div class="card"><div class="label">Budget utilisé</div><div class="value ${o.budget_used_pct > 100 ? "bad" : ""}">${o.budget_used_pct}%</div></div>
    <div class="card"><div class="label">Avancement</div><div class="value">${donePct}%</div><div class="label">${o.tasks_done}/${o.tasks_total} tâches · ${o.tasks_late} en retard</div></div>`;

  const today = new Date().toISOString().slice(0, 10);
  const upcoming = tasks
    .filter((t) => t.status !== "done" && t.due_date)
    .sort((a, b) => a.due_date.localeCompare(b.due_date))
    .slice(0, 8);
  $("#dashUpcoming").innerHTML = upcoming.map((t) => `
    <li><span class="${t.due_date < today ? "late" : ""}">${t.due_date} — ${t.title}</span><span>${fmt(t.cost)}</span></li>
  `).join("") || "<li><span class='muted'>Aucune échéance à venir</span></li>";

  $("#dashTx").innerHTML = transactions.slice(0, 8).map((t) => `
    <li><span>${t.date} — ${t.label}</span><span class="${t.kind === "income" ? "amount-income" : "amount-expense"}">${t.kind === "income" ? "+" : "−"}${fmt(t.amount)}</span></li>
  `).join("") || "<li><span class='muted'>Aucune transaction</span></li>";
}

// ---------- kanban ----------

function taskCard(t) {
  const today = new Date().toISOString().slice(0, 10);
  const late = t.status !== "done" && t.due_date && t.due_date < today;
  const div = document.createElement("div");
  div.className = "task";
  div.draggable = true;
  div.dataset.id = t.id;
  div.innerHTML = `
    <div class="title">${escapeHtml(t.title)}</div>
    <div class="meta">
      ${t.due_date ? `<span class="${late ? "late" : ""}">📅 ${t.due_date}${late ? " (retard)" : ""}</span>` : ""}
      ${t.cost ? `<span>💸 ${fmt(t.cost)}</span>` : ""}
    </div>
    <div class="actions">
      <button data-act="edit">✏️ modifier</button>
      <button data-act="del">🗑️ suppr.</button>
    </div>`;
  div.addEventListener("dragstart", (e) => {
    e.dataTransfer.setData("text/plain", t.id);
    div.classList.add("dragging");
  });
  div.addEventListener("dragend", () => div.classList.remove("dragging"));
  div.querySelector('[data-act="del"]').addEventListener("click", async () => {
    await api(`/api/tasks/${t.id}`, { method: "DELETE" });
    await loadAll();
  });
  div.querySelector('[data-act="edit"]').addEventListener("click", () => editTask(t));
  return div;
}

function editTask(t) {
  const title = prompt("Titre :", t.title);
  if (title === null) return;
  const due = prompt("Échéance (YYYY-MM-DD, vide = aucune) :", t.due_date);
  if (due === null) return;
  const cost = prompt("Coût (€) :", t.cost);
  if (cost === null) return;
  api(`/api/tasks/${t.id}`, {
    method: "PUT",
    json: { title, due_date: due, cost: parseFloat(cost) || 0 },
  }).then(loadAll).catch((e) => toast(e.message));
}

async function renderKanban() {
  for (const status of ["todo", "doing", "done"]) {
    const col = $(`#col-${status}`);
    col.innerHTML = "";
    tasks.filter((t) => t.status === status).forEach((t) => col.appendChild(taskCard(t)));
  }
}

document.querySelectorAll(".kanban-col").forEach((col) => {
  col.addEventListener("dragover", (e) => { e.preventDefault(); col.classList.add("dragover"); });
  col.addEventListener("dragleave", () => col.classList.remove("dragover"));
  col.addEventListener("drop", async (e) => {
    e.preventDefault();
    col.classList.remove("dragover");
    const id = e.dataTransfer.getData("text/plain");
    const status = col.dataset.status;
    await api(`/api/tasks/${id}`, { method: "PUT", json: { status } });
    await loadAll();
  });
});

$("#addTaskBtn").addEventListener("click", async () => {
  const title = $("#newTaskTitle").value.trim();
  if (!title) return toast("Donnez un titre à la tâche");
  await api(`/api/projects/${currentProject.id}/tasks`, {
    method: "POST",
    json: {
      title,
      due_date: $("#newTaskDue").value,
      cost: parseFloat($("#newTaskCost").value) || 0,
    },
  });
  $("#newTaskTitle").value = "";
  $("#newTaskDue").value = "";
  $("#newTaskCost").value = "";
  await loadAll();
});

// ---------- planning ----------

async function renderPlanning() {
  const sorted = [...tasks].filter((t) => t.due_date).sort((a, b) => a.due_date.localeCompare(b.due_date));
  const today = new Date().toISOString().slice(0, 10);
  const undated = tasks.filter((t) => !t.due_date);
  $("#timeline").innerHTML =
    sorted.map((t) => `
      <div class="tl-item ${t.status === "done" ? "done" : t.status !== "done" && t.due_date < today ? "late" : ""}">
        <div class="tl-date">${t.due_date} · ${t.status === "done" ? "terminé" : t.status === "doing" ? "en cours" : "à faire"}${t.cost ? ` · ${fmt(t.cost)}` : ""}</div>
        <div class="tl-title">${escapeHtml(t.title)}</div>
      </div>`).join("") +
    (undated.length ? `<p class="muted">Sans date : ${undated.map((t) => escapeHtml(t.title)).join(", ")}</p>` : "") ||
    "<p class='muted'>Aucune tâche planifiée. Ajoutez-en dans le Kanban.</p>";
}

// ---------- budget ----------

async function renderBudget() {
  const o = await api(`/api/projects/${currentProject.id}/overview`);
  $("#budgetCards").innerHTML = `
    <div class="card"><div class="label">Revenus</div><div class="value ok">${fmt(o.income)}</div></div>
    <div class="card"><div class="label">Dépenses</div><div class="value bad">${fmt(o.expenses)}</div></div>
    <div class="card"><div class="label">Solde</div><div class="value ${o.balance < 0 ? "bad" : "ok"}">${fmt(o.balance)}</div></div>
    <div class="card"><div class="label">Coût planifié restant</div><div class="value warn">${fmt(o.planned_cost)}</div></div>
    <div class="card"><div class="label">Argent libre / mois</div><div class="value ${o.free_money_monthly < 0 ? "bad" : "ok"}">${fmt(o.free_money_monthly)}</div></div>`;

  const tbody = $("#txTable tbody");
  tbody.innerHTML = transactions.map((t) => `
    <tr>
      <td>${t.date}</td>
      <td>${escapeHtml(t.label)}</td>
      <td>${escapeHtml(t.category || "")}</td>
      <td class="amount-${t.kind}">${t.kind === "income" ? "+" : "−"}${fmt(t.amount)}</td>
      <td><button class="btn link" data-tx="${t.id}">🗑️</button></td>
    </tr>`).join("");
  tbody.querySelectorAll("[data-tx]").forEach((btn) =>
    btn.addEventListener("click", async () => {
      await api(`/api/transactions/${btn.dataset.tx}`, { method: "DELETE" });
      await loadAll();
    })
  );
}

$("#addTxBtn").addEventListener("click", async () => {
  const label = $("#txLabel").value.trim();
  const amount = parseFloat($("#txAmount").value);
  if (!label || !amount) return toast("Libellé et montant requis");
  await api(`/api/projects/${currentProject.id}/transactions`, {
    method: "POST",
    json: {
      kind: $("#txKind").value,
      label,
      amount,
      date: $("#txDate").value || new Date().toISOString().slice(0, 10),
      category: $("#txCategory").value,
    },
  });
  $("#txLabel").value = "";
  $("#txAmount").value = "";
  $("#txCategory").value = "";
  await loadAll();
});

// ---------- docs & mémoire ----------

async function renderDocs() {
  const files = await api(`/api/projects/${currentProject.id}/docs`);
  $("#docList").innerHTML = files.map((f) => `
    <li><span>📄 ${escapeHtml(f)}</span><span>
      <button class="btn link" data-view="${f}">voir</button>
      <button class="btn link" data-del="${f}">suppr.</button>
    </span></li>`).join("") || "<li><span class='muted'>Aucun document</span></li>";
  $("#docList").querySelectorAll("[data-view]").forEach((b) =>
    b.addEventListener("click", async () => {
      const doc = await api(`/api/projects/${currentProject.id}/docs/${encodeURIComponent(b.dataset.view)}`);
      alert(doc.content);
    })
  );
  $("#docList").querySelectorAll("[data-del]").forEach((b) =>
    b.addEventListener("click", async () => {
      await api(`/api/projects/${currentProject.id}/docs/${encodeURIComponent(b.dataset.del)}`, { method: "DELETE" });
      await renderDocs();
    })
  );
  const memory = await api(`/api/projects/${currentProject.id}/memory`);
  $("#memoryEditor").value = memory.content;
}

$("#docFile").addEventListener("change", async (e) => {
  const file = e.target.files[0];
  if (!file) return;
  const fd = new FormData();
  fd.append("file", file);
  await api(`/api/projects/${currentProject.id}/docs`, { method: "POST", body: fd });
  e.target.value = "";
  await renderDocs();
  toast("Document importé");
});

$("#saveMemoryBtn").addEventListener("click", async () => {
  await api(`/api/projects/${currentProject.id}/memory`, {
    method: "PUT",
    json: { content: $("#memoryEditor").value },
  });
  toast("Mémoire enregistrée");
});

// ---------- chat IA ----------

function renderMsg(m) {
  const div = document.createElement("div");
  div.className = `msg ${m.role}`;
  div.textContent = m.content;
  if (m.role === "assistant" && m.actions) {
    let log = [];
    try { log = JSON.parse(m.actions); } catch {}
    if (log.length) {
      const applied = document.createElement("div");
      applied.className = "applied";
      applied.textContent = "✅ " + log.join(" · ");
      div.appendChild(applied);
    }
  }
  return div;
}

async function renderChat() {
  const history = await api(`/api/projects/${currentProject.id}/chat`);
  const log = $("#chatLog");
  log.innerHTML = "";
  history.forEach((m) => log.appendChild(renderMsg(m)));
  log.scrollTop = log.scrollHeight;
}

$("#sendBtn").addEventListener("click", sendChat);
$("#chatText").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendChat(); }
});

async function sendChat() {
  const text = $("#chatText").value.trim();
  if (!text) return;
  $("#chatText").value = "";
  const log = $("#chatLog");
  log.appendChild(renderMsg({ role: "user", content: text }));
  log.scrollTop = log.scrollHeight;
  const waiting = renderMsg({ role: "assistant", content: "…" });
  log.appendChild(waiting);
  log.scrollTop = log.scrollHeight;
  try {
    const res = await api(`/api/projects/${currentProject.id}/chat`, { method: "POST", json: { message: text } });
    waiting.remove();
    log.appendChild(renderMsg({ role: "assistant", content: res.reply, actions: JSON.stringify(res.applied) }));
    log.scrollTop = log.scrollHeight;
    await Promise.all([renderDashboard(), renderKanban(), renderPlanning(), renderBudget()]);
  } catch (err) {
    waiting.remove();
    log.appendChild(renderMsg({ role: "assistant", content: "⚠️ " + err.message }));
  }
}

$("#clearChatBtn").addEventListener("click", async () => {
  await api(`/api/projects/${currentProject.id}/chat`, { method: "DELETE" });
  await renderChat();
});

// ---------- settings ----------

async function loadSettings() {
  const s = await api("/api/settings");
  $("#setWallosUrl").value = s.wallos_url || "";
  $("#setWallosKey").value = s.wallos_api_key || "";
  $("#setOrKey").value = s.openrouter_api_key || "";
  $("#setOrModel").value = s.openrouter_model || "openai/gpt-4o-mini";
  $("#setIncome").value = s.monthly_income || "";
  await renderWallosSummary();
}

async function renderWallosSummary() {
  const s = await api("/api/wallos/summary");
  const el = $("#wallosResult");
  if (!s.synced) {
    el.innerHTML = "<p class='muted'>Pas encore synchronisé.</p>";
    return;
  }
  el.innerHTML = `<p>Dernière synchro : ${s.last_sync} — Total mensuel : <strong>${fmt(s.monthly_total)}</strong> (${s.active_count} abonnements actifs)</p>
    <ul class="list">${s.subscriptions.map((sub) => `<li><span>${escapeHtml(sub.name)}</span><span>${fmt(sub.monthly_cost)}/mois</span></li>`).join("")}</ul>`;
}

$("#saveSettingsBtn").addEventListener("click", async () => {
  await api("/api/settings", {
    method: "PUT",
    json: {
      wallos_url: $("#setWallosUrl").value.trim(),
      wallos_api_key: $("#setWallosKey").value.trim(),
      openrouter_api_key: $("#setOrKey").value.trim(),
      openrouter_model: $("#setOrModel").value.trim(),
      monthly_income: parseFloat($("#setIncome").value) || 0,
    },
  });
  toast("Paramètres enregistrés");
});

$("#wallosSyncBtn").addEventListener("click", async () => {
  try {
    await api("/api/settings", {
      method: "PUT",
      json: {
        wallos_url: $("#setWallosUrl").value.trim(),
        wallos_api_key: $("#setWallosKey").value.trim(),
      },
    });
    await api("/api/wallos/sync", { method: "POST" });
    await renderWallosSummary();
    toast("Synchronisation Wallos réussie");
    await loadAll();
  } catch (err) { toast(err.message); }
});

// ---------- tabs ----------

document.querySelectorAll("#tabs button").forEach((btn) =>
  btn.addEventListener("click", () => {
    document.querySelectorAll("#tabs button").forEach((b) => b.classList.remove("active"));
    document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
    btn.classList.add("active");
    $(`#tab-${btn.dataset.tab}`).classList.add("active");
    if (btn.dataset.tab === "settings") loadSettings();
  })
);

function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

loadProjects();
