const FIELD_LABELS = {
  title: "Название задачи", context: "Контекст — что происходит сейчас",
  need: "Потребность — что нужно изменить", users: "Пользователи",
  data: "Данные и материалы", constraints: "Ограничения",
  expected_result: "Ожидаемый результат", success_criteria: "Критерии успеха",
  contact: "Контакт бизнеса", interaction_format: "Формат взаимодействия"
};
const WEIGHTS = {context:10,need:10,data:20,expected_result:15,success_criteria:15,constraints:10,users:10,contact:5,interaction_format:5};
let currentTask = null;
const $ = (id) => document.getElementById(id);

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
    updateTask(task); buildQuestions(); showStage("questions");
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
  } catch(error) { showNotice(error.message,true); }
});
$("back-to-draft").addEventListener("click",()=>showStage("draft"));
(async()=>{
  const id = localStorage.getItem("mission100_task_id"); if (!id) return;
  try { updateTask(await request(`/api/tasks/${id}`)); buildCard(); showStage("card"); }
  catch { localStorage.removeItem("mission100_task_id"); }
})();
