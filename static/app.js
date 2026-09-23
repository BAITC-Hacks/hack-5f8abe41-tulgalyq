const FIELD_LABELS = {
  title: "Название задачи", context: "Контекст — что происходит сейчас",
  need: "Потребность — что нужно изменить", users: "Пользователи",
  data: "Данные и материалы", constraints: "Ограничения",
  expected_result: "Ожидаемый результат", success_criteria: "Критерии успеха",
  contact: "Контакт бизнеса", interaction_format: "Формат взаимодействия"
};
const WEIGHTS = {context:10,need:10,data:20,expected_result:15,success_criteria:15,constraints:10,users:10,contact:5,interaction_format:5};
let currentTask = null;
let selectedCatalogTask = null;
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
  $("score-number").textContent = currentTask.status === "confirmed" && JSON.stringify(fields) === JSON.stringify(currentTask.fields) ? currentTask.confirmed_score : preview;
  $("score-state").textContent = currentTask.status === "confirmed" && JSON.stringify(fields) === JSON.stringify(currentTask.fields) ? "Подтверждено" : "Возможный рейтинг";
  $("score-explain").textContent = currentTask.status === "confirmed" && JSON.stringify(fields) === JSON.stringify(currentTask.fields)
    ? "Баллы начислены за заполненные и подтверждённые сведения."
    : "Это предварительный результат. Баллы начислятся после подтверждения.";
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
  for (const name of ["constructor", "catalog", "proposals"]) {
    $(name+"-view").hidden = name !== view;
    document.querySelector(`[data-view="${name}"]`).classList.toggle("active", name === view);
  }
  $("notice").hidden = true;
  $("task-detail").hidden = true;
  $("current-view-label").textContent = {constructor:"Конструктор задачи",catalog:"Каталог задач",proposals:"Отклики команд"}[view];
  if (view === "catalog") loadCatalog();
  if (view === "proposals") loadProposals();
  window.scrollTo(0, 0);
}
window.addEventListener("hashchange", () => showView(["catalog", "proposals"].includes(location.hash.slice(1)) ? location.hash.slice(1) : "constructor"));
showView(["catalog", "proposals"].includes(location.hash.slice(1)) ? location.hash.slice(1) : "constructor");

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
      footer.append(el("span", "rating-chip", task.status === "confirmed" ? `${task.confirmed_score}/100 · подтверждено` : "Черновик · 0 подтверждено"),
        el("span", "", `${task.proposal_count} откл.`));
      const button = el("button", "secondary-button", "Открыть →"); button.type = "button";
      button.addEventListener("click", () => openTask(task.id)); footer.append(button);
      card.append(footer); list.append(card);
    });
  } catch (error) { $("catalog-list").textContent = error.message; }
}
$("catalog-topic").addEventListener("change", loadCatalog);
$("catalog-readiness").addEventListener("change", loadCatalog);
$("catalog-sort").addEventListener("change", loadCatalog);
$("seed-button").addEventListener("click", async () => {
  try {
    const result = await request("/api/demo/seed", {method:"POST", body:"{}"});
    await loadCatalog();
    alert(result.created ? "Добавлены 5 синтетических карточек, 5 черновиков, 5 команд и 5 откликов." : "В базе уже есть задачи — демо-данные не добавлены.");
  } catch (error) { alert(error.message); }
});

async function openTask(id) {
  selectedCatalogTask = await request(`/api/tasks/${id}`);
  const task = selectedCatalogTask;
  const detail = $("task-detail"); detail.replaceChildren(); detail.hidden = false;
  detail.append(el("span", "step-tag", task.topic), el("h2", "", task.fields.title || "Черновик задачи"),
    el("p", "", `Рейтинг: ${task.status === "confirmed" ? task.confirmed_score : 0}/100 · ${task.status === "confirmed" ? "подтверждено бизнесом" : "не подтверждено"}`));
  const grid = el("div", "detail-grid");
  Object.entries(FIELD_LABELS).forEach(([key, label]) => {
    const row = el("div", "detail-field"); row.append(el("strong", "", label), el("p", "", task.fields[key] || "Не указано")); grid.append(row);
  });
  detail.append(grid, el("h3", "", "Предложить решение"));
  const form = el("form", "proposal-form"); form.id = "proposal-form";
  const teamSelect = el("select"); teamSelect.id = "proposal-team";
  teamSelect.append(new Option("Создать новую команду", ""));
  (await request("/api/teams")).forEach(team => teamSelect.append(new Option(`${team.name} · ${team.skills}`, team.id)));
  const teamName = el("input"); teamName.placeholder = "Название новой команды"; teamName.maxLength = 100;
  const teamSkills = el("input"); teamSkills.placeholder = "Навыки команды"; teamSkills.maxLength = 500;
  const idea = el("textarea"); idea.placeholder = "Идея решения (обязательно)"; idea.required = true; idea.minLength = 10;
  const plan = el("textarea"); plan.placeholder = "План работы (обязательно)"; plan.required = true; plan.minLength = 10;
  const link = el("input"); link.placeholder = "Ссылка на прототип (необязательно)"; link.type = "url";
  const button = el("button", "primary-button", "Отправить предложение →"); button.type = "submit";
  teamSelect.addEventListener("change", () => { teamName.hidden = teamSkills.hidden = Boolean(teamSelect.value); });
  form.append(teamSelect, teamName, teamSkills, idea, plan, link, button);
  form.addEventListener("submit", async event => {
    event.preventDefault(); button.disabled = true;
    try {
      let teamId = teamSelect.value;
      if (!teamId) {
        const team = await request("/api/teams", {method:"POST", body:JSON.stringify({name:teamName.value, skills:teamSkills.value})});
        teamId = team.id;
      }
      await request("/api/proposals", {method:"POST", body:JSON.stringify({task_id:task.id, team_id:teamId, idea:idea.value, plan:plan.value, prototype_url:link.value})});
      await loadCatalog(); await openTask(task.id); alert("Предложение отправлено. Решение остаётся за бизнесом.");
    } catch (error) { alert(error.message); }
    finally { button.disabled = false; }
  });
  detail.append(form); detail.scrollIntoView({behavior:"smooth"});
}

async function loadProposals() {
  try {
    const [proposals, teams] = await Promise.all([request("/api/proposals"), request("/api/teams")]);
    const leaderboard = $("leaderboard"); leaderboard.replaceChildren();
    leaderboard.append(el("strong", "", "Прогресс команд"));
    teams.forEach((team, index) => {
      const row = el("div", "leader-row", `${index + 1}. ${team.name}`);
      row.append(el("b", "", `${team.points} баллов`)); leaderboard.append(row);
    });
    const list = $("proposals-list"); list.replaceChildren();
    if (!proposals.length) list.append(el("p", "empty-state", "Откликов пока нет. Команды могут предложить решение из каталога."));
    for (const proposal of proposals) {
      const task = await request(`/api/tasks/${proposal.task_id}`);
      const card = el("article", "stage-card proposal-card");
      card.append(el("span", "step-tag", `${proposal.team_name} · ${proposal.status}`),
        el("h2", "", task.fields.title || task.raw_description),
        el("p", "", proposal.idea), el("p", "", `План: ${proposal.plan}`));
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

const telegram = window.Telegram?.WebApp;
if (telegram?.initData) {
  document.body.classList.add("telegram-app");
  telegram.ready(); telegram.expand();
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
