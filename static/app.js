const FIELD_LABELS = {
  title: "Название задачи", context: "Контекст — что происходит сейчас",
  need: "Потребность — что нужно изменить", users: "Пользователи",
  data: "Данные и материалы", constraints: "Ограничения",
  expected_result: "Ожидаемый результат", success_criteria: "Критерии успеха",
  contact: "Контакт бизнеса", interaction_format: "Формат взаимодействия"
};
const WEIGHTS = {context:10,need:10,data:20,expected_result:15,success_criteria:15,constraints:10,users:10,contact:5,interaction_format:5};
const IMPROVEMENT_QUESTIONS = {
  context: "Как устроен процесс сейчас и где возникает проблема?",
  need: "Что конкретно должно измениться для бизнеса?",
  data: "Какие данные, примеры или источники получит команда?",
  expected_result: "Что именно команда должна передать в конце?",
  success_criteria: "Как бизнес измерит, что решение сработало?",
  constraints: "Какие сроки, доступы и технические границы нужно учесть?",
  users: "Кто будет пользоваться результатом?",
  contact: "Как команда свяжется с ответственным представителем?",
  interaction_format: "Как часто бизнес сможет давать обратную связь?"
};
const PLACEHOLDERS = new Set(["тест","test","нет","незнаю","потом","заполнить","xxx","asdf","qwerty","йцукен"]);
const READINESS_LABELS = {low:"Черновик · требует уточнения",medium:"Рабочая",high:"Готовая",priority:"Приоритетная"};
let currentTask = null;
let selectedCatalogTask = null;
let proposalTaskFilterValue = "";
let pendingQuestionAnswers = {};
let catalogTasks = [];
let catalogRequestId = 0;
const $ = (id) => document.getElementById(id);
const el = (tag, className, value) => { const node = document.createElement(tag); if (className) node.className = className; if (value !== undefined) node.textContent = value; return node; };

const themeToggle = $("theme-toggle");
function setTheme(theme) {
  const dark = theme === "dark";
  document.documentElement.dataset.theme = dark ? "dark" : "light";
  themeToggle.setAttribute("aria-pressed", String(dark));
  themeToggle.setAttribute("aria-label", dark ? "Включить светлую тему" : "Включить тёмную тему");
  themeToggle.querySelector("span").textContent = dark ? "☀" : "☾";
  localStorage.setItem("tulgalyq_theme", dark ? "dark" : "light");
}
setTheme(localStorage.getItem("tulgalyq_theme"));
themeToggle.addEventListener("click", () => setTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark"));

const menuToggle = $("mobile-menu-toggle");
const menuBackdrop = $("menu-backdrop");
const menuClose = $("mobile-menu-close");
function setMenuOpen(open, restoreFocus = false) {
  document.body.classList.toggle("menu-open", open);
  menuToggle.setAttribute("aria-expanded", String(open));
  menuBackdrop.hidden = !open;
  if (open) menuClose.focus();
  else if (restoreFocus) menuToggle.focus();
}
menuToggle.addEventListener("click", () => setMenuOpen(!document.body.classList.contains("menu-open")));
menuClose.addEventListener("click", () => setMenuOpen(false, true));
menuBackdrop.addEventListener("click", () => setMenuOpen(false, true));
$("primary-nav").querySelectorAll("a").forEach(link => link.addEventListener("click", () => {
  if (document.body.classList.contains("menu-open")) setMenuOpen(false, true);
}));
document.addEventListener("keydown", event => {
  if (event.key === "Escape" && document.body.classList.contains("menu-open")) setMenuOpen(false, true);
});
window.matchMedia("(min-width: 701px)").addEventListener("change", event => {
  if (event.matches) setMenuOpen(false);
});

function qualityIssue(name, value) {
  const text = value.trim();
  if (!text) return "Поле пока пустое.";
  const compact = [...text].filter(char => /[\p{L}\p{N}]/u.test(char)).join("").toLocaleLowerCase("ru");
  const tokens = (text.toLocaleLowerCase("ru").match(/[\p{L}\p{N}_]+/gu) || []);
  if (compact.length < 4 || PLACEHOLDERS.has(compact) || new Set(compact).size === 1 ||
      (tokens.length > 1 && new Set(tokens).size === 1)) return "Замените заглушку или повторы конкретными сведениями.";
  if (name === "contact") {
    const hasEmail = /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(text);
    const hasHandle = /^@[\p{L}\p{N}_.]{4,}$/u.test(text);
    const hasPhone = (text.match(/\p{N}/gu) || []).length >= 7;
    let hasLink = false;
    try { const url = new URL(text); hasLink = ["https:","http:"].includes(url.protocol) && Boolean(url.hostname); } catch {}
    if (!hasEmail && !hasHandle && !hasPhone && !hasLink) return "Укажите email, @ник, ссылку или телефон минимум из 7 цифр.";
  } else if (!/\p{L}/u.test(text)) return "Опишите сведения словами, а не только цифрами или символами.";
  return null;
}

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
function updateTask(task) {
  if (currentTask?.id !== task.id) pendingQuestionAnswers = {};
  currentTask = task;
  localStorage.setItem("mission100_task_id", task.id);
}
function buildQuestions(answers = {}) {
  $("raw-description").textContent = currentTask.raw_description;
  const list = $("questions-list"); list.replaceChildren();
  currentTask.questions.forEach((question, index) => {
    const row = document.createElement("div"); row.className = "question-row";
    const label = document.createElement("label"); label.htmlFor = "answer-"+index; label.textContent = `${String(index+1).padStart(2,"0")}. ${question.text}`;
    const input = document.createElement("textarea"); input.id = "answer-"+index; input.dataset.field = question.field;
    input.placeholder = "Ваш ответ…"; input.value = answers[question.field] ?? currentTask.fields[question.field] ?? "";
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
    const hint = el("small", "field-hint"); hint.id = "hint-"+name; hint.hidden = true;
    input.setAttribute("aria-describedby", hint.id);
    row.append(label,input,hint); container.append(row);
  });
  updatePreview();
}
function fieldsFromForm() {
  return Object.fromEntries(Object.keys(FIELD_LABELS).map(name => [name, $("field-"+name).value.trim()]));
}
function updatePreview() {
  const fields = fieldsFromForm();
  const issues = Object.fromEntries(Object.keys(FIELD_LABELS).map(name => [name, qualityIssue(name, fields[name])]));
  const preview = Object.entries(WEIGHTS).reduce((sum,[name,weight])=>sum+(issues[name] ? 0 : weight),0);
  Object.keys(FIELD_LABELS).forEach(name => {
    const hint = $("hint-"+name);
    hint.textContent = fields[name] && issues[name] ? issues[name] : "";
    hint.hidden = !hint.textContent;
    $("field-"+name).setAttribute("aria-invalid", hint.hidden ? "false" : "true");
  });
  const confirmed = currentTask.status === "confirmed" && !currentTask.needs_confirmation && !currentTask.rating_needs_review && JSON.stringify(fields) === JSON.stringify(currentTask.fields);
  $("score-number").textContent = confirmed ? currentTask.confirmed_score : preview;
  $("score-state").textContent = confirmed ? "Подтверждено" : "Возможный рейтинг";
  $("score-explain").textContent = confirmed
    ? "Баллы начислены за заполненные и подтверждённые сведения."
    : currentTask.rating_needs_review
      ? `Опубликовано ${currentTask.confirmed_score}/100 по прежним правилам. Подтвердите карточку, чтобы пересчитать рейтинг.`
      : "Это предварительный результат. Баллы начислятся после подтверждения.";
  const blocker = ["title", "need"].find(name => issues[name]);
  const nextField = blocker || Object.keys(WEIGHTS).filter(name => issues[name]).sort((a,b) => WEIGHTS[b] - WEIGHTS[a])[0];
  const next = $("passport-next");
  const nextButton = $("passport-next-button");
  nextButton.hidden = !nextField;
  nextButton.dataset.field = nextField || "";
  if (nextField) {
    $("passport-next-title").textContent = blocker ? `Для понятной карточки: ${FIELD_LABELS[nextField]}` : `${FIELD_LABELS[nextField]} · до +${WEIGHTS[nextField]}`;
    $("passport-next-text").textContent = blocker === "title" ? "Назовите миссию так, чтобы команда сразу поняла её суть." : IMPROVEMENT_QUESTIONS[nextField];
  } else {
    $("passport-next-title").textContent = confirmed ? "Миссия опубликована" : "Карточка готова к подтверждению";
    $("passport-next-text").textContent = confirmed ? "Все поля рейтинга заполнены и подтверждены бизнесом." : "Проверьте факты и подтвердите публикацию.";
  }
  next.classList.toggle("complete", !nextField);
  const breakdown = $("breakdown-list"); breakdown.replaceChildren();
  Object.entries(WEIGHTS).forEach(([name,weight]) => {
    const filled = !issues[name];
    const row = el("div", "breakdown-item" + (filled ? "" : " missing"));
    row.append(el("span", "", FIELD_LABELS[name]), el("b", "", filled ? (confirmed ? `${weight}/${weight}` : `+${weight} после подтверждения`) : `0/${weight}`));
    breakdown.append(row);
  });
  const missing = $("missing-list"); missing.replaceChildren();
  const entries = Object.entries(WEIGHTS).filter(([name])=>issues[name]);
  if (!entries.length) missing.textContent = "Все поля рейтинга заполнены ✓";
  entries.forEach(([name,weight])=>{
    const row = document.createElement("div"); row.className = "missing-item";
    const title = document.createElement("span"); title.textContent = fields[name] ? `${FIELD_LABELS[name]} · ${issues[name]}` : FIELD_LABELS[name];
    const points = document.createElement("b"); points.textContent = `+${weight}`;
    row.append(title,points); missing.append(row);
  });
}
$("passport-next-button").addEventListener("click", () => {
  const field = $("passport-next-button").dataset.field;
  if (!field) return;
  const input = $("field-"+field);
  input.scrollIntoView({behavior:"smooth",block:"center"});
  input.focus({preventScroll:true});
});
$("draft-form").addEventListener("submit",async (event)=>{
  event.preventDefault();
  try {
    const task = await request("/api/tasks",{method:"POST",body:JSON.stringify({description:$("description").value,topic:$("topic").value})});
    updateTask(task); buildQuestions(); showStage("questions"); refreshAiQuestions();
  } catch(error) { showNotice(error.message,true); }
});
$("questions-form").addEventListener("submit",async(event)=>{
  event.preventDefault();
  const fields = {...pendingQuestionAnswers, ...Object.fromEntries([...$("questions-list").querySelectorAll("textarea")].map(input=>[input.dataset.field,input.value]))};
  try {
    const task = await request(`/api/tasks/${currentTask.id}`,{method:"PATCH",body:JSON.stringify({fields})});
    updateTask(task); pendingQuestionAnswers = {}; buildCard(); showStage("card");
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
  const button = $("confirm-button");
  if (button.disabled) return;
  button.disabled = true;
  try {
    if (!(await saveCard())) return;
    const published = await request(`/api/tasks/${currentTask.id}/confirm`,{method:"POST",body:"{}"});
    $("publish-success-text").textContent = `Рейтинг готовности: ${published.confirmed_score}/100. Карточка сохранена здесь — её можно открыть, дополнить и повторно подтвердить.`;
    $("publish-success").hidden = false;
    resetConstructor();
    if (location.hash === "#workspace") showView("workspace");
    else location.hash = "workspace";
  } catch(error) { showNotice(error.message,true); }
  finally { button.disabled = false; }
});
function resetConstructor() {
  currentTask = null;
  pendingQuestionAnswers = {};
  localStorage.removeItem("mission100_task_id");
  $("draft-form").reset();
  $("questions-list").replaceChildren();
  $("card-fields").replaceChildren();
  showStage("draft");
}
function startNewTask() {
  $("publish-success").hidden = true;
  resetConstructor();
  location.hash = "constructor";
  $("description").focus({preventScroll:true});
}
$("back-to-draft").addEventListener("click", startNewTask);
(async()=>{
  const id = localStorage.getItem("mission100_task_id"); if (!id) return;
  try { updateTask(await request(`/api/tasks/${id}`)); buildCard(); showStage("card"); }
  catch { localStorage.removeItem("mission100_task_id"); }
})();

function showView(view) {
  for (const name of ["constructor", "workspace", "catalog", "proposals"]) {
    $(name+"-view").hidden = name !== view;
    const link = document.querySelector(`[data-view="${name}"]`);
    link.classList.toggle("active", name === view);
    if (name === view) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  }
  document.querySelectorAll("[data-mobile-view]").forEach(link => {
    const active = link.dataset.mobileView === view;
    link.classList.toggle("active", active);
    if (active) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  });
  $("notice").hidden = true;
  $("task-detail").hidden = true;
  if (view !== "workspace") $("publish-success").hidden = true;
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
      meta.append(el("span", task.status === "confirmed" ? (task.needs_confirmation || task.rating_needs_review ? "draft-chip" : "") : "draft-chip",
        task.status === "confirmed" ? (task.needs_confirmation ? `Правки ждут подтверждения · опубликовано ${task.confirmed_score}/100` : task.rating_needs_review ? `Рейтинг ждёт перепроверки · опубликовано ${task.confirmed_score}/100` : `В каталоге · ${task.confirmed_score}/100`) : `Черновик · возможные ${task.preview_score}/100`),
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
    pendingQuestionAnswers = {};
    updateTask(await request(`/api/tasks/${id}`));
    location.hash = "constructor";
    if (questions) { buildQuestions(); $("question-source").textContent = "Уточняющие вопросы по шаблону"; showStage("questions"); }
    else { buildCard(); showStage("card"); }
  } catch (error) { alert(error.message); }
}
$("new-task-button").addEventListener("click", startNewTask);
$("publish-new-task").addEventListener("click", startNewTask);

async function loadCatalog() {
  const requestId = ++catalogRequestId;
  try {
    const topic = encodeURIComponent($("catalog-topic").value);
    const sort = encodeURIComponent($("catalog-sort").value);
    const readiness = encodeURIComponent($("catalog-readiness").value);
    const tasks = await request(`/api/tasks?topic=${topic}&sort=${sort}&readiness=${readiness}`);
    if (requestId !== catalogRequestId) return;
    catalogTasks = tasks;
    renderCatalog();
  } catch (error) {
    if (requestId === catalogRequestId) $("catalog-list").textContent = error.message;
  }
}
function renderCatalog() {
  const query = $("catalog-search").value.trim().toLocaleLowerCase("ru");
  const tasks = catalogTasks.filter(task => !query || [task.topic, task.fields.title, task.fields.need, task.raw_description]
    .some(value => (value || "").toLocaleLowerCase("ru").includes(query)));
  $("catalog-count").textContent = query ? `Найдено: ${tasks.length} из ${catalogTasks.length}` : `В каталоге: ${tasks.length}`;
  const list = $("catalog-list"); list.replaceChildren();
  if (!tasks.length) {
    const filtered = query || $("catalog-topic").value || $("catalog-readiness").value;
    list.append(el("p", "empty-state", filtered
      ? "По этому запросу миссий нет. Попробуйте другое слово или сбросьте фильтры."
      : "Задач пока нет. Создайте первую или добавьте демо-данные."));
  }
  tasks.forEach(task => {
    const card = el("article", "catalog-card");
    card.append(el("span", "step-tag", task.topic), el("h2", "", task.quality_issues.title ? task.raw_description : (task.fields.title || task.raw_description)),
      el("p", "", task.fields.need || task.raw_description));
    const nextField = Object.keys(WEIGHTS).filter(name => task.missing.includes(name)).sort((a,b) => WEIGHTS[b] - WEIGHTS[a])[0];
    if (task.rating_needs_review) card.append(el("div", "catalog-next", "Рейтинг ждёт перепроверки бизнесом"));
    else if (nextField) card.append(el("div", "catalog-next", `Что уточнить: ${FIELD_LABELS[nextField]} · до +${WEIGHTS[nextField]}`));
    const footer = el("div", "catalog-footer");
    footer.append(el("span", `rating-chip rating-${task.readiness_level}`, `${task.confirmed_score}/100 · ${READINESS_LABELS[task.readiness_level]}${task.rating_needs_review ? " · перепроверка" : ""}`),
      el("span", "", `${task.proposal_count} откл.`));
    const button = el("button", "secondary-button", "Открыть →"); button.type = "button";
    button.addEventListener("click", () => openTask(task.id)); footer.append(button);
    card.append(footer); list.append(card);
  });
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
$("catalog-search").addEventListener("input", renderCatalog);
$("catalog-reset").addEventListener("click", () => {
  $("catalog-search").value = "";
  $("catalog-topic").value = "";
  $("catalog-readiness").value = "";
  $("catalog-sort").value = "rating";
  loadCatalog();
  $("catalog-search").focus();
});
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
  detail.append(el("span", "step-tag", task.topic), el("h2", "", task.quality_issues.title ? task.raw_description : (task.fields.title || task.raw_description)),
    el("p", "", `Рейтинг: ${task.confirmed_score}/100 · ${READINESS_LABELS[task.readiness_level]} · ${task.rating_needs_review ? "ожидает перепроверки" : "подтверждено бизнесом"}`));
  const grid = el("div", "detail-grid");
  Object.entries(FIELD_LABELS).forEach(([key, label]) => {
    const row = el("div", "detail-field"); row.append(el("strong", "", label), el("p", "", task.fields[key] || "Не указано")); grid.append(row);
  });
  detail.append(grid);
  const passport = el("section", "passport-summary");
  passport.append(el("span", "passport-kicker", "ПАСПОРТ МИССИИ"), el("h3", "", "Что известно и что уточнить"),
    el("p", "", "Поля подтверждены представителем бизнеса. Система не проверяет достоверность фактов."));
  if (task.rating_needs_review) passport.append(el("p", "passport-review", "Оценка опубликована по прежним правилам. Бизнесу нужно перепроверить карточку и подтвердить новый расчёт."));
  const gaps = Object.keys(WEIGHTS).filter(name => task.missing.includes(name)).sort((a,b) => WEIGHTS[b] - WEIGHTS[a]).slice(0,3);
  if (gaps.length) {
    const gapList = el("ul", "passport-gap-list");
    gaps.forEach(name => gapList.append(el("li", "", task.rating_needs_review ? IMPROVEMENT_QUESTIONS[name] : `${IMPROVEMENT_QUESTIONS[name]} · до +${WEIGHTS[name]} после подтверждения`)));
    passport.append(gapList);
  } else passport.append(el("p", "", "Все поля рейтинга заполнены. Согласуйте детали с бизнесом перед началом работы."));
  detail.append(passport, el("h3", "", "Предложить решение"));
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
    const [allProposals, teams, tasks] = await Promise.all([request("/api/proposals"), request("/api/teams"), request("/api/tasks?sort=newest")]);
    const taskFilter = $("proposal-task-filter");
    const previousTask = proposalTaskFilterValue || taskFilter.value;
    taskFilter.replaceChildren(new Option("Все задачи", ""));
    tasks.forEach(task => taskFilter.append(new Option(task.fields.title || task.raw_description, task.id)));
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
  const button = $("ai-questions-button");
  button.textContent = status.ai_enabled ? `✦ Спросить ${status.ai_provider === "gemini" ? "Gemini" : "AI"}` : "↻ Локальные вопросы";
  button.title = status.ai_setup_issue === "web_link"
    ? "В переменной AI-ключа задана веб-ссылка. Нужен секретный API-ключ."
    : status.ai_enabled
      ? "AI предложит три вопроса; ответы останутся под вашим контролем"
      : "Для живого AI нужен GEMINI_API_KEY или OPENAI_API_KEY на сервере. Сейчас работают локальные правила.";
}).catch(() => {});
async function refreshAiQuestions() {
  if (!currentTask) return;
  const taskId = currentTask.id;
  const button = $("ai-questions-button"); button.disabled = true;
  const typedAnswers = Object.fromEntries([...$("questions-list").querySelectorAll("textarea")].map(input => [input.dataset.field, input.value]));
  pendingQuestionAnswers = {...pendingQuestionAnswers, ...typedAnswers};
  $("question-source").textContent = "Готовим уточняющие вопросы…";
  try {
    const result = await request(`/api/tasks/${taskId}/ai-questions`, {
      method:"POST", body:JSON.stringify({answers: pendingQuestionAnswers})
    });
    if (currentTask?.id !== taskId || $("questions-section").hidden) return;
    const latestAnswers = Object.fromEntries([...$("questions-list").querySelectorAll("textarea")].map(input => [input.dataset.field, input.value]));
    pendingQuestionAnswers = {...pendingQuestionAnswers, ...latestAnswers};
    currentTask.questions = result.questions; buildQuestions(pendingQuestionAnswers);
    const fallbackLabels = {
      invalid_configuration: "Вместо API-ключа задана ссылка · показаны локальные вопросы",
      auth_failed: "AI: доступ к API отклонён · показаны локальные вопросы",
      rate_limited: "AI: достигнут лимит API · показаны локальные вопросы",
      api_unavailable: "AI недоступен · показаны локальные вопросы"
    };
    $("question-source").textContent = result.source === "gemini" || result.source === "openai"
      ? `Вопросы предложены ${result.source === "gemini" ? "Gemini" : "AI"} · ответы проверяете вы`
      : fallbackLabels[result.fallback_reason] || "Локальные вопросы · API не подключён";
  } catch (error) {
    if (currentTask?.id !== taskId) return;
    $("question-source").textContent = "Не удалось обновить вопросы · ваши ответы сохранены";
    showNotice(error.message, true);
  } finally { button.disabled = false; }
}
$("ai-questions-button").addEventListener("click", refreshAiQuestions);
