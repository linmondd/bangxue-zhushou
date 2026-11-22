"use strict";
const el = id => document.getElementById(id);
const hash = location.hash.slice(1);
if (/^[\w-]{35,}$/.test(hash)) {
  sessionStorage.setItem("panel-key", hash);
  history.replaceState(null, "", location.pathname);
}
const token = sessionStorage.getItem("panel-key") || "";
const phaseNames = {ready:"待开始", running:"运行中", paused:"已暂停", attention:"待处理", complete:"已完成"};
const classNames = {waiting:"待学习", current:"当前班级", attention:"待处理", done:"已完成"};
const reasonNames = {user:"手动暂停", login:"需要重新登录", captcha:"需要在学习窗口完成验证",
  enroll_failed:"未能报名", no_table:"未读到课程表", capture_failed:"未能读取课程", manual:"需要人工学习",
  manual_required:"需要人工学习", unmapped:"未能识别部分课程", start_failed:"课程未能开始播放",
  removed:"课程已下架", table_unavailable:"暂时无法读取课程表"};
const busyNames = {setup:"正在检查环境…",repair:"正在安装组件，下载可能需要几分钟…",login:"正在打开学习窗口…",
  verify:"正在检查登录…",tabs:"正在读取资源栏目…",classes:"正在读取班级…",start:"正在开始学习…",
  cycle:"正在核对课程进度…",pause:"正在暂停…",retry:"正在重试…",resume:"正在恢复…"};
let state = null, submitting = false, localError = "", catalogKey = "", taskKey = "", historyKey = "", tabsKey = "";
let requests = 0, applied = 0, closed = false;
function node(tag, text, className) {
  const n = document.createElement(tag);
  if (text !== undefined) n.textContent = text;
  if (className) n.className = className;
  return n;
}
function note() {
  const text = localError || (state && state.error) || "";
  el("notice").textContent = text;
  el("notice").hidden = !text;
}
function selected() {
  return [...el("choices").querySelectorAll("input:checked")].map(x => x.value);
}
function tabName() {
  return el("tab").value === "__custom" ? el("custom").value.trim() : el("tab").value;
}
function refreshButtons() {
  if (!state || closed) return;
  const running = state.task?.phase === "running";
  const busy = Boolean(state.busy || submitting);
  for (const b of document.querySelectorAll("button[data-act]")) {
    const act = b.dataset.act;
    b.disabled = act === "pause" ? !running || state.pausing || submitting : busy || running;
    if (["login","verify","tabs","classes","start","resume","retry"].includes(act) && !state.setup.chromium) b.disabled = true;
    if (act === "classes" && !tabName()) b.disabled = true;
    if (act === "confirm" && (!selected().length || tabName() !== state.tab)) b.disabled = true;
  }
  el("tab").disabled = busy || running;
  el("custom").disabled = busy || running;
  el("history").disabled = busy || running;
  el("custom").hidden = el("tab").value !== "__custom";
  el("pick").hidden = !state.catalog.length || tabName() !== state.tab;
  const n = selected().length;
  el("selected").textContent = "已选 " + n + " 个班级";
  el("all").checked = n > 0 && n === state.catalog.length;
  el("all").indeterminate = n > 0 && n < state.catalog.length;
}
function renderResults(task) {
  const key = JSON.stringify([task.id,task.rows]);
  if (key === taskKey) return;
  const open = new Set([...el("results").querySelectorAll("details[open]")].map(d => d.dataset.wid));
  el("results").replaceChildren();
  for (const row of task.rows) {
    const group = node("details", undefined, "result");
    group.dataset.wid = row.wid;
    group.open = open.has(row.wid);
    const head = node("summary");
    head.append(node("strong", row.title));
    const finished = row.courses.filter(x => x.label === "已完成").length;
    const count = row.courses.length ? " · " + finished + "/" + row.courses.length + " 门" : "";
    head.append(node("small", classNames[row.status] + count));
    group.append(head);
    if (row.reason) group.append(node("p", reasonNames[row.reason] || row.reason, "sub"));
    if (!row.courses.length) group.append(node("p", row.status === "done" ? "班级课程表已确认全部完成。" : "读取课表后会显示各门课程。", "sub"));
    for (const course of row.courses) {
      const line = node("div", undefined, "course");
      line.append(node("span", course.title),node("span", course.detail ? course.label+" · "+course.detail : course.label));
      group.append(line);
    }
    el("results").append(group);
  }
  taskKey = key;
}
function render(s) {
  if ((!state || state.site !== s.site) && document.activeElement !== el("site")) el("site").value = s.site || "";
  state = s;
  const task = s.task;
  const total = task?.rows.length || 0;
  const done = task?.rows.filter(x => x.status === "done").length || 0;
  el("count").textContent = done + " / " + total;
  el("meter").max = total || 1;
  el("meter").value = done;
  const next = !s.setup.chromium ? "安装浏览器组件后，即可连接学习账号。" :
    s.login !== "authenticated" ? "打开学习窗口登录，再选择本次学习范围。" : "读取资源栏目，选择本次学习的班级。";
  el("guide").textContent = s.pausing ? "已请求暂停，当前操作结束后将关闭学习标签。" :
    (busyNames[s.busy] || (task ? task.note : next));
  el("python").textContent = s.setup.python || "检查中";
  el("browser-name").textContent = s.setup.browser_name || "浏览器";
  for (const k of ["playwright", "chromium"]) el(k).textContent = k in s.setup ? (s.setup[k] ? "已就绪" : "待安装") : "检查中";
  el("repair").hidden = !s.setup.python || s.setup.chromium;
  el("login-hint").textContent = {opened:"请在学习窗口登录及验证，然后点击「检查登录」。",
    authenticated:"已在学习窗口确认登录。",login:"请在学习窗口登录后重新检查。",
    unknown:"在独立学习窗口中完成登录及验证，登录信息保存在本机。"}[s.login] || "请检查学习窗口。";
  if (tabsKey !== JSON.stringify(s.tabs)) {
    const prior = el("tab").value;
    el("tab").replaceChildren(new Option("选择栏目",""),...s.tabs.map(x => new Option(x,x)), new Option("手动填写栏目","__custom"));
    el("tab").value = prior && [...el("tab").options].some(o => o.value === prior) ? prior : (s.tabs[0] || "");
    tabsKey = JSON.stringify(s.tabs);
  }
  const catalog = JSON.stringify([s.tab,s.catalog]);
  if (catalog !== catalogKey) {
    el("choices").replaceChildren();
    for (const c of s.catalog) {
      const label = node("label", undefined,"choice"), box = node("input");
      box.type = "checkbox"; box.value = c.wid;
      label.append(box,document.createTextNode(c.title));
      el("choices").append(label);
    }
    catalogKey = catalog;
  }
  if (historyKey !== JSON.stringify(s.history)) {
    el("history").replaceChildren(...s.history.map(x => new Option(x.created+" · "+x.name+" ("+x.count+" 班)",x.id)));
    historyKey = JSON.stringify(s.history);
  }
  el("history").hidden = s.history.length < 2;
  el("empty").hidden = Boolean(task);
  el("task").hidden = !task;
  if (task) {
    el("history").value = task.id;
    el("phase").textContent = phaseNames[task.phase] || task.phase;
    el("phase").className = "tag " + task.phase;
    el("task-title").textContent = task.name + " · 最多同时播放 " + (task.concurrency || 5) + " 门";
    el("task-note").textContent = (s.pausing ? "已请求暂停，等待本轮操作结束。" : task.note) +
      (task.reason ? " · " + (reasonNames[task.reason] || task.reason) : "");
    el("enroll").hidden = task.phase !== "ready";
    const action = {ready:["start","开始学习"],running:["pause","暂停学习"],paused:["resume","继续学习"],attention:["retry","处理后重试"]}[task.phase];
    const current = el("actions").firstChild;
    if (current?.dataset.act !== action?.[0]) {
      el("actions").replaceChildren();
      if (action) {
        const b = node("button",action[1],"primary"); b.dataset.act = action[0]; el("actions").append(b);
      }
    }
    renderResults(task);
    el("logs").textContent = task.logs.join("\n") || "尚无运行记录";
  }
  refreshButtons();
  note();
}
async function poll() {
  if (closed) return;
  const seq = ++requests;
  try {
    const r = await fetch("/api/state",{headers:{"X-Panel-Token":token},cache:"no-store"});
    if (!r.ok) throw new Error(r.status === 403 ? "此页面的启动链接已失效。请重新打开「帮学助手」。" : "读取面板状态失败。");
    const s = await r.json();
    if (seq < applied || closed) return;
    applied = seq;
    render(s);
  } catch(e) {
    if (seq < applied || closed) return;
    localError = e instanceof TypeError ? "与本机助手的连接已中断，请重新打开「帮学助手」。" : e.message;
    note();
  }
}
async function send(action, extra={}) {
  if (submitting || closed) return;
  if (action === "quit" && !window.confirm("退出帮学助手并关闭专用学习窗口？已保存的任务可以下次继续。")) return;
  submitting = true; localError = ""; refreshButtons();
  try {
    const r = await fetch("/api/action",{method:"POST",headers:{"Content-Type":"application/json","X-Panel-Token":token},
      body:JSON.stringify({action,...extra})});
    if (!r.ok) throw new Error((await r.text()) || "操作未完成，请重新打开面板。");
    if (action === "quit") {
      closed = true;
      document.querySelectorAll("button,input,select").forEach(n => { n.disabled = true; });
      localError = "帮学助手已退出，可以关闭此页。下次打开应用可查看本机记录。";
      el("guide").textContent = "助手已退出";
      note();
      return;
    }
    await poll();
    if (action === "confirm") el("records").scrollIntoView({block:"start"});
  } catch(e) { localError = e.message; note(); }
  finally { submitting = false; refreshButtons(); }
}
document.addEventListener("click", e => {
  const act = e.target.closest("button")?.dataset.act;
  if (act) send(act, act === "site" ? {url:el("site").value} : act === "confirm" ? {ids:selected(),tab:tabName(),concurrency:Number(el("concurrency").value)} : act === "classes" ? {tab:tabName()} : {id:state?.task?.id});
});
el("all").addEventListener("change",() => {
  for (const box of el("choices").querySelectorAll("input")) box.checked = el("all").checked;
  refreshButtons();
});
el("choices").addEventListener("change",refreshButtons);
el("tab").addEventListener("change",refreshButtons);
el("custom").addEventListener("input",refreshButtons);
el("history").addEventListener("change",e => send("history",{id:e.target.value}));
poll();
setInterval(poll,1200);
