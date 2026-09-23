const FIELD_LABELS = {
  title: "Название задачи", context: "Контекст — что происходит сейчас",
  need: "Потребность — что нужно изменить", users: "Пользователи",
  data: "Данные и материалы", constraints: "Ограничения",
  expected_result: "Ожидаемый результат", success_criteria: "Критерии успеха",
  contact: "Контакт бизнеса", interaction_format: "Формат взаимодействия"
};
const WEIGHTS = {context:10,need:10,data:20,expected_result:15,success_criteria:15,constraints:10,users:10,contact:5,interaction_format:5};
const READINESS_LABELS = {low:"Нужно уточнить",medium:"Рабочая",high:"Готовая",priority:"Приоритетная"};
let currentTask = null;
let selectedCatalogTask = null;
let proposalTaskFilterValue = "";
const $ = (id) => document.getElementById(id);
const el = (tag, className, value) => { const node = document.createElement(tag); if (className) node.className = className; if (value !== undefined) node.textContent = value; return node; };

async function request(path, options = {}) {
  const response = await fetch(path, {headers:{"Content-Type":"application/json"}, ...options});
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "Не удалось выполнить действие.");
  return data;
}
function showNotice(message, error=false) {
  const element = $("notice"); element.textContent = message;
  element.classList.toggle("error", error); element.hidden = false;
}
function showStage(name) {
  for (const stage of ["draft","questions","card"]) $(stage+"-section").hidden = stage !== name;
  document.body.dataset.stage = name;
  $("notice").hidden = true;
  window.scrollTo({top:0,behavior:"smooth"});
}
function updateTask(task) { currentTask = task; localStorage.setItem("mission100_task_id", task.id); }
function buildQuestions() {
  $("raw-description").textContent = currentTask.raw_description;
  const list = $("questions-list"); list.replaceChildren();
  currentTask.questions.forEach((question, index) => {
    const row = document.createElement("div"); row.className = "question-row";
    const label = document.createElement("label"); label.htmlFor = "answer-"+index; label.textContent = `${String(index+1).padStart(2,"0")}. ${question.text}`;
    const input = document.createElement("textarea"); input.id = "answer-"+index; input.dataset.field = question.field;
    input.placeholder = "Ваш ответ…"; input.value = currentTask.fields[question.field] || "";
    row.append(label,input); list.append(row);
  });
}
function buildCard() {
  const container = $("card-fields"); container.className = "card-grid"; container.replaceChildren();
  Object.entries(FIELD_LABELS).forEach(([name,labelText]) => {
    const row = document.createElement("div"); row.className = "field-row" + (["context","need","data","expected_result","success_criteria"].includes(name) ? " full" : "");
    const label = document.createElement("label"); label.htmlFor = "field-"+name; label.textContent = labelText;
    const input = ["title","contact","interaction_format"].includes(name) ? document.createElement("input") : document.createElement("textarea");
    input.id = "field-"+name; input.name = name; input.value = currentTask.fields[name] || "";
    input.addEventListener("input", updatePreview);
    row.append(label,input); container.append(row);
  });
  updatePreview();
}
function fieldsFromForm() {
  return Object.fromEntries(Object.keys(FIELD_LABELS).map(name => [name, $("field-"+name).value.trim()]));
}
function updatePreview() {
  const fields = fieldsFromForm();
  const preview = Object.entries(WEIGHTS).reduce((sum,[name,weight])=>sum+(fields[name]?weight:0),0);
  const confirmed = currentTask.status === "confirmed" && !currentTask.needs_confirmation && JSON.stringify(fields) === JSON.stringify(currentTask.fields);
  $("score-number").textContent = confirmed ? currentTask.confirmed_score : preview;
  $("score-state").textContent = confirmed ? "Подтверждено" : "Возможный рейтинг";
  $("score-explain").textContent = confirmed
    ? "Баллы начислены за заполненные и подтверждённые сведения."
    : "Это предварительный результат. Баллы начислятся после подтверждения.";
  const breakdown = $("breakdown-list"); breakdown.replaceChildren();
  Object.entries(WEIGHTS).forEach(([name,weight]) => {
    const filled = Boolean(fields[name]);
    const row = el("div", "breakdown-item" + (filled ? "" : " missing"));
    row.append(el("span", "", FIELD_LABELS[name]), el("b", "", filled ? (confirmed ? `${weight}/${weight}` : `+${weight} после подтверждения`) : `0/${weight}`));
    breakdown.append(row);
  });
  const missing = $("missing-list"); missing.replaceChildren();
  const entries = Object.entries(WEIGHTS).filter(([name])=>!fields[name]);
  if (!entries.length) missing.textContent = "Все поля рейтинга заполнены ✓";
  entries.forEach(([name,weight])=>{
    const row = document.createElement("div"); row.className = "missing-item";
    const title = document.createElement("span"); title.textContent = FIELD_LABELS[name];
    const points = document.createElement("b"); points.textContent = `+${weight}`;
    row.append(title,points); missing.append(row);
  });
}
$("draft-form").addEventListener("submit",async (event)=>{
  event.preventDefault();
  try {
    const task = await request("/api/tasks",{method:"POST",body:JSON.stringify({description:$("description").value,topic:$("topic").value})});
    updateTask(task); buildQuestions(); $("question-source").textContent = "Уточняющие вопросы по шаблону"; showStage("questions");
  } catch(error) { showNotice(error.message,true); }
});
$("questions-form").addEventListener("submit",async(event)=>{
  event.preventDefault();
  const fields = Object.fromEntries([...$("questions-list").querySelectorAll("textarea")].map(input=>[input.dataset.field,input.value]));
  try {
    const task = await request(`/api/tasks/${currentTask.id}`,{method:"PATCH",body:JSON.stringify({fields})});
    updateTask(task); buildCard(); showStage("card");
  } catch(error) { showNotice(error.message,true); }
});
$("card-form").addEventListener("submit",async(event)=>{
  event.preventDefault(); await saveCard();
});
async function saveCard() {
  try {
    const task = await request(`/api/tasks/${currentTask.id}`,{method:"PATCH",body:JSON.stringify({fields:fieldsFromForm()})});
    updateTask(task); updatePreview(); showNotice("Изменения сохранены. Подтвердите карточку для начисления баллов.");
    return true;
  } catch(error) { showNotice(error.message,true); return false; }
}
$("confirm-button").addEventListener("click",async()=>{
  if (!(await saveCard())) return;
  try {
    updateTask(await request(`/api/tasks/${currentTask.id}/confirm`,{method:"POST",body:"{}"}));
    updatePreview(); showNotice(`Карточка подтверждена. Рейтинг готовности: ${currentTask.confirmed_score}/100.`);
    await loadCatalog();
  } catch(error) { showNotice(error.message,true); }
});
$("back-to-draft").addEventListener("click",()=>showStage("draft"));
(async()=>{
  const id = localStorage.getItem("mission100_task_id"); if (!id) return;
  try { updateTask(await request(`/api/tasks/${id}`)); buildCard(); showStage("card"); }
  catch { localStorage.removeItem("mission100_task_id"); }
})();

function showView(view) {
  for (const name of ["constructor", "workspace", "catalog", "proposals"]) {
    $(name+"-view").hidden = name !== view;
    document.querySelector(`[data-view="${name}"]`).classList.toggle("active", name === view);
  }
  document.querySelectorAll("[data-mobile-view]").forEach(link => {
    const active = link.dataset.mobileView === view;
    link.classList.toggle("active", active);
    if (active) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  });
  $("notice").hidden = true;
  $("task-detail").hidden = true;
  $("current-view-label").textContent = {constructor:"Конструктор задачи",workspace:"Задачи бизнеса",catalog:"Каталог задач",proposals:"Отклики команд"}[view];
  if (view === "workspace") loadWorkspace();
  if (view === "catalog") { loadCatalog(); loadRecommendations(); }
  if (view === "proposals") loadProposals();
  window.scrollTo(0, 0);
}
window.addEventListener("hashchange", () => showView(["workspace", "catalog", "proposals"].includes(location.hash.slice(1)) ? location.hash.slice(1) : "constructor"));
showView(["workspace", "catalog", "proposals"].includes(location.hash.slice(1)) ? location.hash.slice(1) : "constructor");
const scoreBreakpoint = window.matchMedia("(max-width: 700px)");
function syncScoreDetails(event) {
  $("score-details").open = !event.matches;
  $("recommendation-details").open = !event.matches;
}
syncScoreDetails(scoreBreakpoint);
scoreBreakpoint.addEventListener("change", syncScoreDetails);

async function loadWorkspace() {
  try {
    const tasks = await request("/api/workspace/tasks");
    const stats = $("workspace-stats"); stats.replaceChildren();
    for (const [label, count] of [["Всего задач", tasks.length], ["Черновиков", tasks.filter(task => task.status !== "confirmed").length], ["В каталоге", tasks.filter(task => task.status === "confirmed").length]]) {
      const item = el("div", "workspace-stat"); item.append(el("b", "", String(count)), el("span", "", label)); stats.append(item);
    }
    const list = $("workspace-list"); list.replaceChildren();
    if (!tasks.length) list.append(el("p", "empty-state", "Задач пока нет. Начните с нового черновика."));
    tasks.forEach(task => {
      const card = el("article", "workspace-card");
      card.append(el("span", "step-tag", task.topic),
        el("h2", "", task.fields.title || task.raw_description),
        el("p", "", task.fields.need || task.raw_description));
      const meta = el("div", "workspace-meta");
      meta.append(el("span", task.status === "confirmed" ? (task.needs_confirmation ? "draft-chip" : "") : "draft-chip",
        task.status === "confirmed" ? (task.needs_confirmation ? `Правки ждут подтверждения · опубликовано ${task.confirmed_score}/100` : `В каталоге · ${task.confirmed_score}/100`) : `Черновик · возможные ${task.preview_score}/100`),
        el("span", "", `${task.proposal_count} откл.`));
      const actions = el("div", "workspace-actions-row");
      const edit = el("button", "secondary-button", "Редактировать"); edit.type = "button";
      edit.addEventListener("click", () => openEditor(task.id)); actions.append(edit);
      if (task.status === "confirmed") {
        const catalog = el("button", "primary-button", "В каталоге →"); catalog.type = "button";
        catalog.addEventListener("click", async () => { location.hash = "catalog"; await loadCatalog(); await openTask(task.id); });
        actions.append(catalog);
        if (task.proposal_count) {
          const proposals = el("button", "secondary-button", `Отклики (${task.proposal_count})`); proposals.type = "button";
          proposals.addEventListener("click", () => {
            proposalTaskFilterValue = task.id;
            if (location.hash === "#proposals") loadProposals();
            else location.hash = "proposals";
          });
          actions.append(proposals);
        }
      } else {
        const questions = el("button", "primary-button", "Уточнить →"); questions.type = "button";
        questions.addEventListener("click", () => openEditor(task.id, true)); actions.append(questions);
      }
      card.append(meta, actions); list.append(card);
    });
  } catch (error) { $("workspace-list").textContent = error.message; }
}
async function openEditor(id, questions=false) {
  try {
    updateTask(await request(`/api/tasks/${id}`));
    location.hash = "constructor";
    if (questions) { buildQuestions(); $("question-source").textContent = "Уточняющие вопросы по шаблону"; showStage("questions"); }
    else { buildCard(); showStage("card"); }
  } catch (error) { alert(error.message); }
}
$("new-task-button").addEventListener("click", () => {
  currentTask = null; localStorage.removeItem("mission100_task_id");
  $("description").value = ""; $("topic").selectedIndex = 0;
  location.hash = "constructor"; showStage("draft");
});

async function loadCatalog() {
  try {
    const topic = encodeURIComponent($("catalog-topic").value);
    const sort = encodeURIComponent($("catalog-sort").value);
    const readiness = encodeURIComponent($("catalog-readiness").value);
    const tasks = await request(`/api/tasks?topic=${topic}&sort=${sort}&readiness=${readiness}`);
    const list = $("catalog-list"); list.replaceChildren();
    if (!tasks.length) list.append(el("p", "empty-state", "Задач пока нет. Создайте первую или добавьте демо-данные."));
    tasks.forEach(task => {
      const card = el("article", "catalog-card");
      card.append(el("span", "step-tag", task.topic), el("h2", "", task.fields.title || task.raw_description),
        el("p", "", task.fields.need || task.raw_description));
      const footer = el("div", "catalog-footer");
      footer.append(el("span", `rating-chip rating-${task.readiness_level}`, `${task.confirmed_score}/100 · ${READINESS_LABELS[task.readiness_level]}`),
        el("span", "", `${task.proposal_count} откл.`));
      const button = el("button", "secondary-button", "Открыть →"); button.type = "button";
      button.addEventListener("click", () => openTask(task.id)); footer.append(button);
      card.append(footer); list.append(card);
    });
  } catch (error) { $("catalog-list").textContent = error.message; }
}
async function loadRecommendations() {
  const select = $("recommendation-team");
  const list = $("recommendations-list");
  try {
    const selected = select.value;
    const teams = await request("/api/teams");
    select.replaceChildren(new Option("Выберите команду", ""));
    teams.forEach(team => select.append(new Option(team.name, team.id)));
    select.value = selected;
    list.replaceChildren();
    if (!select.value) return;
    const matches = await request(`/api/teams/${encodeURIComponent(select.value)}/recommendations`);
    if (!matches.length) {
      list.append(el("p", "", "Совпадений пока нет. Укажите интересы команды или изучите весь каталог ниже."));
      return;
    }
    matches.forEach(match => {
      const card = el("article", "recommendation-card");
      card.append(el("strong", "", match.title), el("span", "", `${match.score}/100 · совпало: ${match.matched_terms.join(", ")}`));
      const button = el("button", "secondary-button", "Открыть задачу →"); button.type = "button";
      button.addEventListener("click", () => openTask(match.task_id));
      card.append(button); list.append(card);
    });
  } catch (error) { list.textContent = error.message; }
}
$("recommendation-team").addEventListener("change", loadRecommendations);
$("catalog-topic").addEventListener("change", loadCatalog);
$("catalog-readiness").addEventListener("change", loadCatalog);
$("catalog-sort").addEventListener("change", loadCatalog);
$("seed-button").addEventListener("click", async () => {
  try {
    const result = await request("/api/demo/seed", {method:"POST", body:"{}"});
    await loadCatalog(); await loadRecommendations();
    alert(result.created ? "Добавлены 5 синтетических карточек, 5 черновиков, 5 команд и 5 откликов." : "В базе уже есть задачи — демо-данные не добавлены.");
  } catch (error) { alert(error.message); }
});

async function openTask(id) {
  selectedCatalogTask = await request(`/api/tasks/${id}?published=1`);
  const task = selectedCatalogTask;
  const detail = $("task-detail"); detail.replaceChildren(); detail.hidden = false;
  detail.append(el("span", "step-tag", task.topic), el("h2", "", task.fields.title || "Черновик задачи"),
    el("p", "", `Рейтинг: ${task.confirmed_score}/100 · ${READINESS_LABELS[task.readiness_level]} · подтверждено бизнесом`));
  const grid = el("div", "detail-grid");
  Object.entries(FIELD_LABELS).forEach(([key, label]) => {
    const row = el("div", "detail-field"); row.append(el("strong", "", label), el("p", "", task.fields[key] || "Не указано")); grid.append(row);
  });
  detail.append(grid, el("h3", "", "Предложить решение"));
  const form = el("form", "proposal-form"); form.id = "proposal-form";
  const teamSelect = el("select"); teamSelect.id = "proposal-team";
  teamSelect.setAttribute("aria-label", "Команда");
  teamSelect.append(new Option("Создать новую команду", ""));
  (await request("/api/teams")).forEach(team => teamSelect.append(new Option(`${team.name} · ${team.interests || team.skills || "без описания"}`, team.id)));
  const teamName = el("input"); teamName.placeholder = "Название новой команды"; teamName.maxLength = 100;
  const teamSkills = el("input"); teamSkills.placeholder = "Навыки команды"; teamSkills.maxLength = 500;
  const teamInterests = el("input"); teamInterests.placeholder = "Интересы команды (например, образование)"; teamInterests.maxLength = 500;
  const teamTechnologies = el("input"); teamTechnologies.placeholder = "Технологии (например, Python, JavaScript)"; teamTechnologies.maxLength = 500;
  const idea = el("textarea"); idea.placeholder = "Идея решения (обязательно)"; idea.required = true; idea.minLength = 10;
  const plan = el("textarea"); plan.placeholder = "План работы (обязательно)"; plan.required = true; plan.minLength = 10;
  const deadline = el("input"); deadline.placeholder = "Срок выполнения (например, 2 недели)"; deadline.maxLength = 120;
  const link = el("input"); link.placeholder = "Ссылка на прототип (необязательно)"; link.type = "url";
  for (const input of [teamName, teamSkills, teamInterests, teamTechnologies, idea, plan, deadline, link]) {
    input.setAttribute("aria-label", input.placeholder);
  }
  const button = el("button", "primary-button", "Отправить предложение →"); button.type = "submit";
  teamSelect.addEventListener("change", () => { for (const input of [teamName, teamSkills, teamInterests, teamTechnologies]) input.hidden = Boolean(teamSelect.value); });
  form.append(teamSelect, teamName, teamSkills, teamInterests, teamTechnologies, idea, plan, deadline, link, button);
  form.addEventListener("submit", async event => {
    event.preventDefault(); button.disabled = true;
    try {
      let teamId = teamSelect.value;
      if (!teamId) {
        const team = await request("/api/teams", {method:"POST", body:JSON.stringify({name:teamName.value, skills:teamSkills.value, interests:teamInterests.value, technologies:teamTechnologies.value})});
        teamId = team.id;
      }
      await request("/api/proposals", {method:"POST", body:JSON.stringify({task_id:task.id, team_id:teamId, idea:idea.value, plan:plan.value, deadline:deadline.value, prototype_url:link.value})});
      await loadCatalog(); await openTask(task.id); alert("Предложение отправлено. Решение остаётся за бизнесом.");
    } catch (error) { alert(error.message); }
    finally { button.disabled = false; }
  });
  detail.append(form); detail.scrollIntoView({behavior:"smooth"});
}

async function loadProposals() {
  try {
    const [allProposals, teams, tasks] = await Promise.all([request("/api/proposals"), request("/api/teams"), request("/api/workspace/tasks")]);
    const taskFilter = $("proposal-task-filter");
    const previousTask = proposalTaskFilterValue || taskFilter.value;
    taskFilter.replaceChildren(new Option("Все задачи", ""));
    tasks.filter(task => task.status === "confirmed" || task.proposal_count).forEach(task =>
      taskFilter.append(new Option(task.fields.title || task.raw_description, task.id)));
    taskFilter.value = previousTask;
    proposalTaskFilterValue = taskFilter.value;
    const status = $("proposal-status-filter").value;
    const proposals = allProposals.filter(proposal =>
      (!proposalTaskFilterValue || proposal.task_id === proposalTaskFilterValue) && (!status || proposal.status === status));
    const taskById = new Map(tasks.map(task => [task.id, task]));
    const leaderboard = $("leaderboard"); leaderboard.replaceChildren();
    leaderboard.append(el("strong", "", "Прогресс команд"));
    teams.forEach((team, index) => {
      const row = el("div", "leader-row", `${index + 1}. ${team.name}`);
      row.append(el("b", "", `${team.points} баллов`)); leaderboard.append(row);
    });
    const list = $("proposals-list"); list.replaceChildren();
    if (!proposals.length) list.append(el("p", "empty-state", "По выбранным фильтрам откликов нет."));
    for (const proposal of proposals) {
      const task = taskById.get(proposal.task_id);
      if (!task) continue;
      const card = el("article", "stage-card proposal-card");
      const statusLabel = {pending:"ожидает решения",selected:"выбрана",rejected:"отклонена"}[proposal.status] || proposal.status;
      card.append(el("span", "step-tag", `${proposal.team_name} · ${statusLabel}`),
        el("h2", "", task.fields.title || task.raw_description),
        el("p", "", `Навыки: ${proposal.team_skills || "не указаны"}`),
        el("p", "", proposal.idea), el("p", "", `План: ${proposal.plan}`));
      if (proposal.team_interests) card.append(el("p", "", `Интересы: ${proposal.team_interests}`));
      if (proposal.team_technologies) card.append(el("p", "", `Технологии: ${proposal.team_technologies}`));
      if (proposal.deadline) card.append(el("p", "", `Срок: ${proposal.deadline}`));
      if (proposal.prototype_url) {
        const link = el("a", "", "Открыть прототип ↗"); link.href = proposal.prototype_url;
        link.target = "_blank"; link.rel = "noopener noreferrer"; card.append(link);
      }
      const actions = el("div", "actions");
      for (const [decision, label] of [["selected","Выбрать"],["rejected","Отклонить"],["pending","Сбросить решение"]]) {
        const button = el("button", decision === "selected" ? "primary-button" : "secondary-button", label);
        button.addEventListener("click", async () => {
          await request(`/api/proposals/${proposal.id}/decision`, {method:"POST", body:JSON.stringify({decision})});
          await loadProposals();
        }); actions.append(button);
      }
      card.append(actions);
      if (proposal.status === "selected") await addProgress(card, proposal.id);
      list.append(card);
    }
  } catch (error) { $("proposals-list").textContent = error.message; }
}
$("proposal-task-filter").addEventListener("change", () => { proposalTaskFilterValue = $("proposal-task-filter").value; loadProposals(); });
$("proposal-status-filter").addEventListener("change", loadProposals);
async function addProgress(card, proposalId) {
  card.append(el("h3", "", "Этапы работы · +10 за подтверждение"));
  const progress = await request(`/api/proposals/${proposalId}/progress`);
  progress.forEach(item => {
    const row = el("div", "progress-row");
    row.append(el("span", "", `${item.description} · ${item.status === "confirmed" ? "+10 баллов" : "ожидает подтверждения"}`));
    if (item.status === "pending") {
      const button = el("button", "secondary-button", "Подтвердить этап");
      button.addEventListener("click", async () => { await request(`/api/progress/${item.id}/confirm`, {method:"POST",body:"{}"}); await loadProposals(); });
      row.append(button);
    }
    card.append(row);
  });
  const form = el("form", "progress-form");
  const input = el("input"); input.placeholder = "Что команда выполнила на этом этапе?"; input.required = true; input.minLength = 10;
  const button = el("button", "secondary-button", "Отправить этап"); form.append(input,button);
  form.addEventListener("submit", async event => {
    event.preventDefault();
    try { await request(`/api/proposals/${proposalId}/progress`, {method:"POST", body:JSON.stringify({description:input.value})}); await loadProposals(); }
    catch (error) { alert(error.message); }
  });
  card.append(form);
}

request("/api/health").then(status => {
  $("ai-questions-button").disabled = !status.ai_enabled;
  if (!status.ai_enabled) $("ai-questions-button").title = "Для AI нужен OPENAI_API_KEY на сервере";
}).catch(() => {});
$("ai-questions-button").addEventListener("click", async () => {
  const button = $("ai-questions-button"); button.disabled = true;
  $("question-source").textContent = "AI составляет вопросы…";
  try {
    const result = await request(`/api/tasks/${currentTask.id}/ai-questions`, {method:"POST", body:"{}"});
    currentTask.questions = result.questions; buildQuestions();
    $("question-source").textContent = "Вопросы предложены AI · ответы проверяете вы";
  } catch (error) {
    $("question-source").textContent = "Локальные вопросы · AI недоступен";
    showNotice(error.message, true);
  } finally { button.disabled = false; }
});
