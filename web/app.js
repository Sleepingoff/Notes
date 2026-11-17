/* 화면 동작. 디자인은 styles.css, 기본 문서는 index.html에서 수정합니다. */
import { PdfEditor } from "/annotation_component/editor.js";
import { AutoSave } from "/autosave.js";
import { RegionSelector } from "/region_selector.js";
const $ = (s) => document.querySelector(s),
  content = $("#content");
const S = {
  subjects: [],
  subject: null,
  route: "lecture",
  data: null,
  bank: null,
  quiz: null,
  index: 0,
  round: null,
  page: 1,
  filter: null,
  editor: null,
  drafts: {},
  explanationDrafts: {},
};
const questionListObserver = new ResizeObserver(() => {
  const list = $("#question-list");
  if (list && Number(list.dataset.layoutWidth) !== list.clientWidth) summary();
});
const esc = (s) =>
  String(s ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const url = (path, params = {}) => path + "?" + new URLSearchParams(params);
async function api(path, data, options = {}) {
  const response = await fetch(
    path,
    data === undefined
      ? options
      : {
          ...options,
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(data),
        },
  );
  const result = await response.json();
  if (!response.ok)
    throw new Error(result.error || "요청을 처리하지 못했습니다.");
  return result;
}
function notify(message, error = false) {
  $("#notice").innerHTML = message
    ? `<div class="notice ${error ? "error" : ""}">${esc(message)}</div>`
    : "";
}
function action(fn) {
  return async (event) => {
    try {
      await fn(event);
    } catch (error) {
      notify(error.message, true);
    }
  };
}
const autoSaves = new Map();
const pendingUploads = new Set();
function autoSave(key, save, status) {
  const controller = new AutoSave(save, {
    onStatus: (state, error) => {
      if (!status) return;
      status.textContent = state === "error" ? `저장 실패: ${error}` : "";
      status.classList.toggle("error", state === "error");
    },
    onError: (error) => notify(`자동 저장 실패: ${error.message}`, true),
  });
  autoSaves.set(key, controller);
  return controller;
}
async function flushAutosaves() {
  await Promise.all([...pendingUploads]);
  await Promise.all([...autoSaves.values()].map((save) => save.flush()));
}
function autoInput(element, save) {
  let scheduledValue = element.value;
  const schedule = () => {scheduledValue = element.value; save.schedule();};
  element.addEventListener("input", (event) => {if (!event.isComposing) schedule();});
  element.addEventListener("compositionend", schedule);
  element.addEventListener("change", schedule);
  element.addEventListener("blur", () => {
    if (element.value !== scheduledValue) schedule();
    save.flush().catch(() => {});
  });
}
async function releaseEditor() {
  await flushAutosaves();
  if (S.editor) {
    await S.editor.flush();
    S.editor.destroy();
    S.editor = null;
  }
}
function subjectName() {
  return S.subjects.find((s) => s.id === S.subject)?.name || "과목";
}
function examName(item) {
  return `${item.exam_year ? item.exam_year + "년" : "연도 미확인"} · ${item.exam_term || "학기 미확인"}`;
}
async function bootstrap() {
  S.subjects = await api("/api/subjects");
  if (!S.subjects.some((s) => s.id === S.subject))
    S.subject = S.subjects[0]?.id || null;
  sidebar();
  await render();
}
function subjectIcon(kind) {
  const paths = kind === "rename"
    ? '<path d="m15 5 4 4M4 20l4-1L20 7a2.8 2.8 0 0 0-4-4L4 15l-1 6Z"/>'
    : '<path d="M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7M14 10v7"/>';
  return `<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths}</svg>`;
}
function sidebar() {
  const root = $("#sidebar");
  root.innerHTML = `<h1>Notes</h1><button id="open-ai-settings" type="button" class="ai-settings-button">AI 설정</button><form id="add-subject"><input aria-label="새 과목 이름" placeholder="새 과목 이름" required><button>추가</button></form><nav>${S.subjects
    .map(
      (s) =>
        `<div class="subject"><div class="subject-row"><button class="subject-name ${S.subject === s.id ? "active" : ""}" data-subject="${s.id}" title="${esc(s.name)}">${esc(s.name)}</button><div class="subject-actions"><button type="button" class="subject-icon" data-rename-subject="${s.id}" aria-label="${esc(s.name)} 과목 이름 수정" title="이름 수정">${subjectIcon("rename")}</button><button type="button" class="subject-icon subject-delete" data-delete-subject="${s.id}" aria-label="${esc(s.name)} 과목 삭제" title="과목 삭제">${subjectIcon("delete")}</button></div></div>${
          S.subject === s.id
            ? `<div class="subject-nav">${[
                ["lecture", "강의 자료 보기"],
                ["quiz", "문제 풀기"],
                ["answers", "정답표"],
                ["manage", "문제은행 관리"],
              ]
                .map(
                  ([route, label]) =>
                    `<button data-route="${route}" class="${S.route === route || (route === "manage" && S.route === "results") ? "active" : ""}">${label}</button>`,
                )
                .join("")}</div>`
            : ""
        }</div>`,
    )
    .join("")}</nav>`;
  $("#open-ai-settings").onclick = action(openAISettings);
  root.querySelector("form").onsubmit = action(async (e) => {
    e.preventDefault();
    const name = e.target.querySelector("input").value.trim();
    if (!name) return;
    await releaseEditor();
    const added = await api("/api/subject", { name });
    S.subject = added.id;
    S.route = "lecture";
    S.page = 1;
    await bootstrap();
  });
  root.querySelectorAll("[data-subject]").forEach(
    (b) =>
      (b.onclick = action(async () => {
        await releaseEditor();
        S.subject = b.dataset.subject;
        S.page = 1;
        S.bank = null;
        S.filter = null;
        S.route = "lecture";
        sidebar();
        await render();
      })),
  );
  root.querySelectorAll("[data-rename-subject]").forEach((button) => {
    button.onclick = action(() => openSubjectRename(button.dataset.renameSubject));
  });
  root.querySelectorAll("[data-delete-subject]").forEach((button) => {
    button.onclick = () => openSubjectDelete(button.dataset.deleteSubject);
  });
  root
    .querySelectorAll("[data-route]")
    .forEach((b) => (b.onclick = () => go(b.dataset.route)));
}
let aiSettingsSave = null;
async function openAISettings() {
  await flushAutosaves();
  const settings = await api("/api/settings/ai");
  for (const [id, key] of [["ai-host", "host"], ["ai-model", "model"], ["ai-context", "num_ctx"], ["ai-predict", "num_predict"]]) {
    const previous = $("#" + id), input = previous.cloneNode(true);
    previous.replaceWith(input);
    input.value = settings[key];
  }
  $("#ai-connection-status").textContent = "모델 설치 후 연결 확인을 눌러주세요.";
  $("#ai-save-status").textContent = "";
  aiSettingsSave = autoSave("ai-settings", async () => {
    await api("/api/settings/ai", {host: $("#ai-host").value, model: $("#ai-model").value,
      num_ctx: $("#ai-context").value, num_predict: $("#ai-predict").value});
    $("#ai-connection-status").textContent = "연결 확인을 눌러 변경한 모델을 확인해 주세요.";
  }, $("#ai-save-status"));
  for (const id of ["ai-host", "ai-model", "ai-context", "ai-predict"]) autoInput($("#" + id), aiSettingsSave);
  $("#ai-settings-dialog").showModal();
}
async function closeAISettings() {
  await aiSettingsSave?.flush();
  $("#ai-settings-dialog").close();
}
$("#ai-close").onclick = action(closeAISettings);
$("#ai-settings-dialog").oncancel = (event) => {event.preventDefault(); action(closeAISettings)();};
$("#ai-check").onclick = action(async () => {
  await aiSettingsSave?.flush();
  const status = $("#ai-connection-status"), button = $("#ai-check");
  status.textContent = "연결 확인 중…";
  button.disabled = true;
  try {
    const result = await api("/api/settings/ai/status");
    status.textContent = result.message;
    status.classList.toggle("error", !result.ok);
    $("#ai-models").innerHTML = result.models.map((name) => `<option value="${esc(name)}">`).join("");
  } catch (error) {
    status.textContent = `연결하지 못했습니다. Ollama가 실행 중인지 확인해 주세요. ${error.message}`;
    status.classList.add("error");
  } finally {button.disabled = false;}
});
let subjectRename = null;
async function openSubjectRename(identifier) {
  await flushAutosaves();
  const subject = S.subjects.find((item) => item.id === identifier);
  if (!subject) return;
  const previous = $("#subject-name-input"), input = previous.cloneNode(true);
  previous.replaceWith(input);
  input.value = subject.name;
  $("#subject-rename-status").textContent = "";
  const save = autoSave(`subject-name:${identifier}`, async () => {
    const name = input.value.trim();
    if (!name) throw new Error("과목명을 입력해 주세요.");
    const renamed = await api("/api/subject/rename", {id: identifier, name});
    if (S.subject === identifier && renamed.answerKeys) {
      S.data.answerKeys = renamed.answerKeys;
      if (S.route === "answers") answerTables(content);
      else if (S.route === "quiz" && $("#builtin-answer-keys"))
        quizAnswerTable($("#builtin-answer-keys"));
    }
    const item = S.subjects.find((row) => row.id === identifier);
    if (item) item.name = name;
    sidebar();
    if (S.subject === identifier && $("#page-header h1")) $("#page-header h1").textContent = name;
  }, $("#subject-rename-status"));
  subjectRename = {identifier, save};
  autoInput(input, save);
  $("#subject-rename-dialog").showModal();
  input.focus();
  input.select();
}
async function closeSubjectRename(cancel = false) {
  if (!subjectRename) return;
  if (cancel) await subjectRename.save.cancel();
  else await subjectRename.save.flush();
  autoSaves.delete(`subject-name:${subjectRename.identifier}`);
  subjectRename = null;
  $("#subject-rename-dialog").close();
}
$("#subject-rename-form").onsubmit = action(async (event) => {
  event.preventDefault();
  await closeSubjectRename();
});
$("#close-subject-rename").onclick = action(() => closeSubjectRename());
$("#subject-rename-dialog").oncancel = (event) => {
  event.preventDefault();
  action(() => closeSubjectRename(true))();
};
let subjectDeletion = null;
let deletingSubject = false;
function openSubjectDelete(identifier) {
  const subject = S.subjects.find((item) => item.id === identifier);
  if (!subject) return;
  subjectDeletion = identifier;
  $("#subject-delete-name").textContent = subject.name;
  $("#subject-delete-error").textContent = "";
  $("#subject-delete-dialog").showModal();
  $("#cancel-subject-delete").focus();
}
function clearSubjectState(identifier, banks) {
  delete S.drafts[identifier];
  const ids = banks.map((bank) => bank.id);
  for (const key of autoSaves.keys()) {
    if (key === `lectures:${identifier}` || key === `subject-name:${identifier}` ||
        ids.some((id) => key === `meta:${id}` || key === `answers:${id}` ||
          key.startsWith(`question:${id}:`) || key.startsWith(`explanations:${id}:`))) autoSaves.delete(key);
  }
  for (const key of Object.keys(S.explanationDrafts)) {
    if (ids.some((id) => key.startsWith(id))) delete S.explanationDrafts[key];
  }
  if (S.subject === identifier) {
    S.subject = null;
    S.bank = null;
    S.quiz = null;
    S.data = null;
    S.index = 0;
    S.round = null;
    S.filter = null;
    S.page = 1;
    S.route = "lecture";
  }
}
$("#subject-delete-form").onsubmit = async (event) => {
  event.preventDefault();
  if (!subjectDeletion || deletingSubject) return;
  const identifier = subjectDeletion;
  deletingSubject = true;
  $("#confirm-subject-delete").disabled = true;
  $("#cancel-subject-delete").disabled = true;
  $("#subject-delete-error").textContent = "";
  try {
    await releaseEditor();
    const data = await api(url("/api/subject", {id: identifier}));
    await api("/api/subject/delete", {id: identifier});
    clearSubjectState(identifier, data.banks);
    subjectDeletion = null;
    $("#subject-delete-dialog").close();
    await bootstrap();
    notify("과목을 삭제했습니다.");
  } catch (error) {
    $("#subject-delete-error").textContent = error.message;
    notify(error.message, true);
  } finally {
    deletingSubject = false;
    $("#confirm-subject-delete").disabled = false;
    $("#cancel-subject-delete").disabled = false;
  }
};
$("#cancel-subject-delete").onclick = () => {
  if (deletingSubject) return;
  subjectDeletion = null;
  $("#subject-delete-dialog").close();
};
$("#subject-delete-dialog").oncancel = (event) => {
  if (deletingSubject) event.preventDefault();
  else subjectDeletion = null;
};
async function go(route) {
  try {
    await releaseEditor();
    S.route = route;
    S.filter = null;
    notify("");
    sidebar();
    await render();
  } catch (e) {
    notify(e.message, true);
  }
}
async function render() {
  await flushAutosaves();
  questionListObserver.disconnect();
  if (!S.subject) {
    $("#page-header").innerHTML = "<h1>강의 노트</h1>";
    content.innerHTML =
      '<div class="empty">왼쪽에서 첫 과목을 추가해 주세요.</div>';
    return;
  }
  S.data = await api(url("/api/subject", { id: S.subject }));
  $("#page-header").innerHTML =
    `<h1>${esc(subjectName())}</h1><span class="muted">${{ lecture: "강의 자료 보기", quiz: "문제 풀기", answers: "정답표", manage: "문제은행 관리", results: "문제 추출 결과" }[S.route]}</span>`;
  if (S.route === "lecture") await lecture();
  else if (S.route === "manage") await manage();
  else if (S.route === "quiz") await quiz();
  else if (S.route === "answers") answerTables(content);
  else await results();
}
function clampPage(value, max) {
  return Math.max(1, Math.min(max, Math.floor(Number(value) || 1)));
}
async function editorAt(root, page) {
  const subject = S.subject, route = S.route;
  const request = (root.pageRequest || 0) + 1;
  root.pageRequest = request;
  root.inert = true;
  const current = () => root.pageRequest === request && root.isConnected !== false && subject === S.subject && route === S.route;
  try {
    // Finish writes using the previous page's callback before changing its destination.
    if (S.editor) await S.editor.flush();
    if (!current()) return null;
    const saved = await api(url("/api/lecture/annotations", { subject, page }));
    if (!current()) return null;
    if (S.editor && S.editor.root !== root) {
      S.editor.destroy();
      S.editor = null;
    }
    const editor = S.editor || new PdfEditor(root);
    editor.onChange = (payload) => api("/api/lecture/annotations", {
      subject, page, revision: payload.revision, marks: payload.marks,
    });
    editor.setPage({
      ...saved,
      image: url("/api/lecture/page", { subject, page, version: S.pdfRevision || 0 }),
    });
    S.editor = editor;
    return editor;
  } finally {
    if (root.pageRequest === request) root.inert = false;
  }
}
function lectureAnchor(bundle, page) {
  const chapter = bundle?.chapters.find((row) => row.start <= page && page <= row.end);
  return {chapter: chapter?.id, offset: chapter ? page - chapter.start : 0, page};
}
function anchoredLecturePage(bundle, anchor) {
  if (!bundle) return 1;
  const chapter = bundle.chapters.find((row) => row.id === anchor.chapter);
  return chapter ? Math.min(chapter.end, chapter.start + anchor.offset) : clampPage(anchor.page, bundle.pages);
}
async function lecture() {
  content.innerHTML = `<div id="lecture-tools" class="row between"></div><div class="viewer-grid section"><nav id="lecture-toc" class="toc toc-manager" aria-label="강의 목차 및 자료 관리"></nav><div id="lecture-document" class="document"></div></div>`;
  lectureManage($("#lecture-toc"));
  await paintLectureDocument();
}
let lectureViewVersion = 0;
async function paintLectureDocument() {
  const version = ++lectureViewVersion;
  const subject = S.subject, root = $("#lecture-document"), b = S.data.bundle;
  if (!root || S.route !== "lecture") return;
  if (root.bundle !== b) {
    $("#lecture-tools").innerHTML = b
      ? `<span class="muted">${b.chapters.length}개 회차 · ${b.pages}페이지</span><div class="row"><a class="button" href="${url("/api/lecture/pdf", {subject})}">원본 PDF</a><button id="export-ink">필기 포함 PDF 다운로드</button></div>`
      : '<span class="muted">강의 자료 보기</span>';
    root.bundle = b;
  }
  if (!b) {
    if (S.editor) {
      await S.editor.flush();
      S.editor.destroy();
      S.editor = null;
    }
    root.viewerMounted = false;
    root.innerHTML = '<p class="empty">목차 아래의 PDF 추가 버튼으로 강의자료를 추가하세요. 모든 자료가 제외된 경우 목차에서 포함을 선택하세요.</p>';
    syncLectureTOC();
    return;
  }
  S.page = clampPage(S.page, b.pages);
  if (!root.viewerMounted) {
    root.innerHTML = `<div class="viewer-position-top"><span class="page-position"><input class="page-jump" id="lecture-page" type="number" min="1" aria-label="이동할 PDF 페이지"><span id="lecture-position-top"></span></span></div><div id="lecture-editor"></div><div class="page-nav"><button id="lecture-prev">이전 페이지</button><span class="page-position"><input class="page-jump" id="lecture-page-bottom" type="number" min="1" aria-label="이동할 PDF 페이지"><span id="lecture-position"></span></span><button id="lecture-next">다음 페이지</button></div><div class="toolbar"><button id="related-page">이 페이지 관련 문제</button></div>`;
    root.viewerMounted = true;
    const move = action(async (page) => {
      await flushAutosaves();
      S.page = clampPage(page, S.data.bundle?.pages || 1);
      await paintLectureDocument();
    });
    for (const selector of ["#lecture-page", "#lecture-page-bottom"]) {
      $(selector).onchange = (event) => move(event.target.value);
      $(selector).onkeydown = (event) => {
        if (event.key === "Enter") {event.preventDefault(); return move(event.target.value);}
      };
    }
    $("#lecture-prev").onclick = () => move(S.page - 1);
    $("#lecture-next").onclick = () => move(S.page + 1);
  }
  const page = S.page;
  for (const selector of ["#lecture-page", "#lecture-page-bottom"]) {
    $(selector).max = b.pages;
    $(selector).value = page;
  }
  $("#lecture-position-top").textContent = `/ ${b.pages}`;
  $("#lecture-position").textContent = `/ ${b.pages}`;
  $("#lecture-prev").disabled = page === 1;
  $("#lecture-next").disabled = page === b.pages;
  $("#related-page").disabled = true;
  $("#export-ink").onclick = action(async () => {
    await S.editor?.flush();
    location.href = url("/api/lecture/pdf", {subject, annotated: 1});
  });
  syncLectureTOC();
  await editorAt($("#lecture-editor"), page);
  if (version !== lectureViewVersion || subject !== S.subject || root !== $("#lecture-document")) return;
  const mapping = await api(url("/api/related", {subject, page}));
  if (version !== lectureViewVersion || subject !== S.subject || root !== $("#lecture-document")) return;
  const count = Object.values(mapping).reduce((n, ids) => n + ids.length, 0);
  const button = $("#related-page");
  button.textContent = `이 페이지 관련 문제 풀기 (${count})`;
  button.disabled = !count;
  button.onclick = action(async () => {
    await releaseEditor();
    S.filter = {page: S.page, scope: "page", mapping};
    S.bank = Object.keys(mapping)[0];
    S.route = "quiz";
    S.index = 0;
    sidebar();
    await render();
  });
}
function syncLectureTOC() {
  const root = $("#lecture-order"), draft = S.drafts[S.subject], bundle = S.data.bundle;
  if (!root || !draft) return;
  const current = lectureAnchor(bundle, S.page).chapter;
  root.querySelectorAll(".order-row").forEach((row) => {
    const item = draft.order[Number(row.dataset.index)];
    const available = bundle?.chapters.some((chapter) => chapter.id === item.chapter);
    row.classList.toggle("active", Boolean(item.chapter && item.chapter === current));
    row.classList.toggle("excluded", !item.included);
    row.querySelector("[data-open]").disabled = !available || !item.included;
  });
}
async function readFiles(files) {
  return Promise.all(
    [...files].map(
      (file) =>
        new Promise((resolve, reject) => {
          const reader = new FileReader();
          reader.onload = () =>
            resolve({ name: file.name, data: reader.result.split(",")[1] });
          reader.onerror = () => reject(new Error("파일을 읽지 못했습니다."));
          reader.readAsDataURL(file);
        }),
    ),
  );
}
async function manage() {
  await flushAutosaves();
  content.innerHTML = '<div id="manage-body"></div>';
  bankManage();
}
function lectureManage(root) {
  const subject = S.subject;
  const draft = (S.drafts[subject] ||= {
    subject, uploads: [], order: S.data.lecturePlan.map((row) => ({...row})),
  });
  root.innerHTML = `<h2 class="toc-heading">목차</h2><div id="lecture-order"></div><p id="lecture-save-status" class="auto-save-status" role="status"></p><button id="add-lecture-pdf" class="toc-add">+ PDF 추가</button><input id="lecture-files" type="file" accept=".pdf,.hwp,.hwpx" multiple aria-label="강의자료 추가" hidden>`;
  $("#add-lecture-pdf").onclick = () => $("#lecture-files").click();
  draft.save = autoSave(`lectures:${subject}`, async () => {
    const document = S.subject === subject && S.route === "lecture" ? $("#lecture-document") : null;
    const anchor = lectureAnchor(S.data.bundle, S.page);
    if (document) document.inert = true;
    try {
      if (document) await S.editor?.flush();
      const indices = [...new Set(draft.order.filter((row) => row.upload !== undefined).map((row) => row.upload))];
      const order = draft.order.map((row) => ({...row,
        ...(row.upload !== undefined ? {upload: indices.indexOf(row.upload)} : {}),
      }));
      const result = await api("/api/lecture/auto", {
        subject, order, uploads: indices.map((index) => draft.uploads[index]),
      });
      for (const row of draft.order) {
        if (row.upload === undefined) continue;
        const chapter = result.upload_chapters[indices.indexOf(row.upload)];
        if (!chapter) continue; // uploads added while the preceding request was running
        draft.uploads[row.upload] = null;
        delete row.upload;
        delete row.client_id;
        row.chapter = chapter;
      }
      if (S.subject === subject) {
        S.pdfRevision = (S.pdfRevision || 0) + 1;
        S.data.bundle = result.bundle;
        S.data.lecturePlan = result.plan;
        S.page = anchoredLecturePage(result.bundle, anchor);
        if (document && document === $("#lecture-document") && S.route === "lecture") {
          syncLectureTOC();
          await paintLectureDocument();
        }
      }
    } finally {
      if (document) document.inert = false;
    }
  }, $("#lecture-save-status"));
  $("#lecture-files").onchange = action(async (event) => {
    const files = event.target.files;
    const reading = (async () => {
      for (const upload of await readFiles(files)) {
        const index = draft.uploads.push(upload) - 1;
        draft.order.push({upload: index, client_id: crypto.randomUUID(),
          title: upload.name.replace(/\.(pdf|hwpx?)$/i, ""), included: true});
      }
      if (S.subject === subject && S.route === "lecture" && $("#lecture-order")) orderRows(draft);
      draft.save.schedule();
    })();
    pendingUploads.add(reading);
    try { await reading; } finally { pendingUploads.delete(reading); }
  });
  orderRows(draft);
}
function orderRows(draft) {
  const root = $("#lecture-order");
  root.innerHTML = draft.order.length ? draft.order.map((row, i) =>
    `<div class="order-row toc-item" data-index="${i}"><span class="toc-drag" data-drag-handle draggable="true" title="드래그하여 순서 변경" aria-label="순서 변경">⠿</span><input type="checkbox" ${row.included ? "checked" : ""} aria-label="${i + 1}번째 자료 포함" title="자료 포함"><div class="toc-item-title"><button data-open="${i}" title="${esc(row.title)}">${i + 1}. ${esc(row.title)}</button><input class="toc-title-input" type="text" value="${esc(row.title)}" aria-label="${i + 1}번째 목차 이름" hidden><button class="toc-edit" data-edit-title="${i}" aria-label="${i + 1}번째 목차 이름 수정" title="목차 이름 수정">${subjectIcon("rename")}</button></div></div>`
  ).join("") : '<p class="hint">등록된 강의자료가 없습니다.</p>';
  root.querySelectorAll(".order-row").forEach((row) => {
    const i = Number(row.dataset.index), item = draft.order[i];
    const title = row.querySelector("[type=text]"), open = row.querySelector("[data-open]");
    open.onclick = action(async () => {
      await flushAutosaves();
      const chapter = S.data.bundle?.chapters.find((chapter) => chapter.id === item.chapter);
      if (!chapter) return;
      S.page = chapter.start;
      await paintLectureDocument();
    });
    row.querySelector("[data-edit-title]").onclick = () => {
      open.hidden = true;
      title.hidden = false;
      title.focus();
      title.select();
    };
    title.oninput = (event) => {
      item.title = event.target.value;
      open.textContent = `${i + 1}. ${item.title}`;
      open.title = item.title;
    };
    title.onblur = () => {title.hidden = true; open.hidden = false;};
    title.onkeydown = (event) => {
      if (!event.isComposing && (event.key === "Enter" || event.key === "Escape")) {
        event.preventDefault();
        title.blur();
      }
    };
    autoInput(title, draft.save);
    row.querySelector("[type=checkbox]").onchange = (event) => {
      item.included = event.target.checked;
      syncLectureTOC();
      draft.save.schedule();
    };
    row.ondragstart = (event) => {
      if (!event.target.closest("[data-drag-handle]")) {event.preventDefault(); return;}
      event.dataTransfer.setData("text/plain", String(i));
    };
    row.ondragover = (event) => event.preventDefault();
    row.ondrop = (event) => {
      event.preventDefault();
      const from = Number(event.dataTransfer.getData("text/plain"));
      if (!Number.isInteger(from) || from < 0 || from >= draft.order.length || from === i) return;
      draft.order.splice(i, 0, draft.order.splice(from, 1)[0]);
      orderRows(draft);
      draft.save.schedule();
    };
  });
  syncLectureTOC();
}
function badge(item) {
  const status = item.task?.status || "waiting";
  return `<span class="badge ${esc(status)}">${status === "done" ? '<span class="check-icon">✓</span>' : status === "running" ? '<span class="spinner"></span>' : status === "failed" ? "<span>!</span>" : ""}${{ done: "추출 완료", running: "추출 중", queued: "대기 중", failed: "추출 실패", waiting: "미추출" }[status]}</span>`;
}
const openExtractionErrors = new Set();
function extractionError(task) {
  if (task?.status !== "failed") return "";
  const code = task.error_code || "EXTRACTION_FAILED";
  const message = (task.error_message || "문제 추출에 실패했습니다. 아래 오류 상세 내용을 확인해 주세요.")
    .replaceAll("추출 현황에서 상세 내용을 확인해 주세요.", "아래 오류 상세 내용을 확인해 주세요.");
  const detail = task.error?.trim() || "저장된 상세 로그가 없습니다.";
  return `<div class="extraction-failure"><span class="extraction-error" role="status">${esc(code)} · ${esc(message)}</span><details class="extraction-details" data-error-details="${esc(task.id || "")}" ${openExtractionErrors.has(task.id) ? "open" : ""}><summary>오류 상세 내용</summary><pre>${esc(detail)}</pre></details>${task.id ? `<button type="button" data-retry="${esc(task.id)}">추출 다시 시도</button>` : ""}</div>`;
}
function bindExtractionErrors(root) {
  root.querySelectorAll("[data-error-details]").forEach((details) => {
    details.ontoggle = () => {
      if (details.isConnected === false) return;
      if (details.open) openExtractionErrors.add(details.dataset.errorDetails);
      else openExtractionErrors.delete(details.dataset.errorDetails);
    };
  });
  root.querySelectorAll("[data-retry]").forEach((button) => {
    button.onclick = action(async () => {
      button.disabled = true;
      try {
        await api("/api/job/retry", {id: button.dataset.retry});
        openExtractionErrors.delete(button.dataset.retry);
        await render();
      } finally {
        button.disabled = false;
      }
    });
  });
}
function bankManage() {
  $("#manage-body").innerHTML =
    `<p class="hint">새 자료를 등록하면 전체 페이지를 백그라운드에서 자동 추출합니다.</p><div class="file-picker"><input id="bank-files" type="file" accept=".pdf,.hwp,.hwpx" multiple aria-label="기말 문제은행 추가"></div><button id="show-results">추출 현황 보기</button><div id="bank-list"></div>`;
  $("#bank-files").onchange = action(async (e) => {
    notify("자료를 등록하고 있습니다.");
    await api("/api/bank/upload", {
      subject: S.subject,
      files: await readFiles(e.target.files),
    });
    S.data = await api(url("/api/subject", { id: S.subject }));
    notify("등록했습니다. 추출이 자동으로 시작됩니다.");
    bankList();
  });
  $("#show-results").onclick = () => {
    S.route = "results";
    sidebar();
    render().catch((e) => notify(e.message, true));
  };
  bankList();
}
function manualWriteButton(item) {
  return item.task?.status === "failed" ? `<button type="button" data-write-bank="${esc(item.id)}">실패 페이지 직접 작성</button>` : "";
}
function bindManualWriting(root) {
  root.querySelectorAll("[data-write-bank]").forEach((button) => {
    button.onclick = action(async () => {
      await releaseEditor();
      const item = S.data.banks.find((item) => item.id === button.dataset.writeBank);
      S.bank = item.id;
      const page = item.incompletePages?.[0] || item.task?.current_page || 1;
      await editQuestion({page, id: `page-${page}`}, true);
    });
  });
}
function bankList() {
  const root = $("#bank-list");
  if (!root || [...autoSaves.values()].some((save) => save.dirty || save.running)) return;
  root.innerHTML = S.data.banks
    .map(
      (item) =>
        `<article class="file-row"><div class="row"><span class="file-title">${esc(item.filename)}</span>${badge(item)}</div><span class="hint">${item.pages}페이지</span><form class="meta-form" data-meta="${item.id}"><label class="stack">연도<input type="number" name="year" value="${item.exam_year || ""}" placeholder="미확인"></label><label class="stack">학기<select name="term">${["", "1학기", "2학기", "하계", "동계", "계절학기"].map((v) => `<option value="${v}" ${v === item.exam_term ? "selected" : ""}>${v || "미확인"}</option>`).join("")}</select></label><span class="auto-save-status" role="status"></span></form><div class="file-actions"><button data-solve="${item.id}" ${item.ready ? "" : "disabled"}>문제 풀기</button>${manualWriteButton(item)}${extractionError(item.task)}</div></article>`,
    )
    .join("");
  root.querySelectorAll("form").forEach((form) => {
    const bank = form.dataset.meta;
    const year = form.elements.namedItem("year"), term = form.elements.namedItem("term");
    const save = autoSave(`meta:${bank}`, async () => {
      if (year.value && (!/^\d{4}$/.test(year.value) || Number(year.value) < 1900 || Number(year.value) > 2100))
        throw new Error("연도는 1900~2100 사이의 네 자리 숫자로 입력해 주세요.");
      const values = {bank, year: year.value, term: term.value};
      await api("/api/material/meta", values);
      const item = S.data?.banks.find((row) => row.id === bank);
      if (item) Object.assign(item, {exam_year: Number(values.year), exam_term: values.term});
    }, form.querySelector(".auto-save-status"));
    form.onsubmit = action(async (event) => {event.preventDefault(); await save.flush();});
    autoInput(year, save);
    autoInput(term, save);
  });
  bindExtractionErrors(root);
  bindManualWriting(root);
  root.querySelectorAll("[data-solve]").forEach(
    (button) =>
      (button.onclick = action(async () => {
        S.bank = button.dataset.solve;
        S.filter = null;
        S.route = "quiz";
        S.index = 0;
        sidebar();
        await render();
      })),
  );
}
function bankSelect(banks, id = "bank-select") {
  return `<select id="${id}" aria-label="기말 문제은행">${banks.map((b) => `<option value="${b.id}" ${b.id === S.bank ? "selected" : ""}>${esc(examName(b))}</option>`).join("")}</select>`;
}
const multipleAnswerSymbols = {"1,2":"A", "1,3":"B", "1,4":"C", "2,3":"D", "2,4":"E", "3,4":"F", "1,2,3":"G", "1,2,4":"H", "1,3,4":"I", "2,3,4":"J", "1,2,3,4":"K"};
function answerKeyText(answers) {
  return answers.map((choices) => choices.length === 0 ? "?" : choices.length === 1 ? String(choices[0]) : multipleAnswerSymbols[choices.join(",")]).join("");
}
function answerLabel(answer) {
  return Object.entries(multipleAnswerSymbols).find(([, symbol]) => symbol === answer)?.[0].replaceAll(",", ", ") || String(answer);
}
async function copyAnswerText(text) {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      return;
    }
  } catch { /* Older browsers can still copy through the selected text. */ }
  const previous = document.activeElement;
  const input = document.createElement("textarea");
  input.value = text;
  input.readOnly = true;
  input.style.cssText = "position:fixed;opacity:0;left:0;top:0";
  document.body.append(input);
  try {
    input.select();
    if (!document.execCommand?.("copy")) throw new Error("정답표를 복사하지 못했습니다. 브라우저의 클립보드 권한을 확인해 주세요.");
  } finally {
    input.remove();
    previous?.focus({preventScroll: true});
  }
}
function answerTables(root, preferred = {}) {
  const keys = S.data.answerKeys || [];
  if (!keys.length) {
    root.innerHTML = '<p class="hint">이 과목의 정답표가 없습니다. 과목명은 띄어쓰기를 무시하고 일치 여부를 확인합니다.</p>';
    return;
  }
  const years = [...new Set([...(preferred.year ? [Number(preferred.year)] : []), ...keys.map((key) => key.year)])].sort((a, b) => b - a);
  const exact = preferred.exact === true;
  root.innerHTML = `${exact ? "" : `<div class="row answer-key-filters"><label>연도 <select data-key-year aria-label="정답표 연도">${years.map((year) => `<option value="${year}">${year}년</option>`).join("")}</select></label><label>학기 <select data-key-term aria-label="정답표 학기"><option value="1">1학기</option><option value="2">2학기</option></select></label></div>`}<div data-key-tables></div>`;
  const yearSelect = exact ? {value: String(preferred.year)} : root.querySelector("[data-key-year]");
  const termSelect = exact ? {value: String(preferred.term).replace("학기", "")} : root.querySelector("[data-key-term]");
  yearSelect.value = String(preferred.year || keys[0].year);
  termSelect.value = String(preferred.term || keys[0].term).replace("학기", "");
  const paint = () => {
    const filtered = keys.filter((key) => key.year === Number(yearSelect.value) && key.term === Number(termSelect.value));
    root.querySelector("[data-key-tables]").innerHTML = filtered.length ? filtered.map((key) => {
      const rows = [];
      for (let start = 0; start < key.answers.length; start += 5) {
        rows.push(`<tr>${key.answers.slice(start, start + 5).map((choices, index) => `<th scope="row">${start + index + 1}번</th><td class="${choices.length ? "" : "answer-unknown"}">${choices.length ? choices.join(", ") : "확인 필요"}</td>`).join("")}</tr>`);
      }
      return `<section class="answer-key-section"><div class="row between answer-key-heading"><h3>${key.year}년 ${key.term}학기 · ${key.grade}학년</h3><button type="button" data-copy-key="${keys.indexOf(key)}" ${key.answers.length ? "" : "disabled"} aria-label="${key.year}년 ${key.term}학기 ${key.grade}학년 정답표 복사하기">복사하기</button></div>${key.issues.map((issue) => `<p class="hint error">${issue.questions[0]}~${issue.questions[1]}번: 원본 표기 ‘${esc(issue.raw)}’ 확인이 필요합니다.</p>`).join("")}${rows.length ? `<div class="answer-key-scroll"><table class="answer-key-table"><caption>${esc(key.subject)} · ${key.year}년 ${key.term}학기 · ${key.grade}학년 정답표</caption><tbody>${rows.join("")}</tbody></table></div>` : '<p class="hint">원본 정답표에 정답이 비어 있습니다.</p>'}</section>`;
    }).join("") : '<p class="hint">선택한 연도·학기의 정답표가 없습니다.</p>';
    root.querySelectorAll("[data-copy-key]").forEach((button) => {
      button.onclick = action(async () => {
        await copyAnswerText(answerKeyText(keys[Number(button.dataset.copyKey)].answers));
        button.textContent = "복사됨";
      });
    });
  };
  yearSelect.onchange = termSelect.onchange = paint;
  paint();
}
function answerCellSymbol(value) {
  const text = value.trim().toUpperCase();
  if (!text || text === "?") return "?";
  if (/^[1-9A-K]$/.test(text)) return text;
  const choices = [...new Set(text.split(/[,，/\s]+/).filter(Boolean))].sort();
  if (choices.length > 1 && choices.every((choice) => /^[1-4]$/.test(choice)))
    return multipleAnswerSymbols[choices.join(",")];
  throw new Error("정답은 보기 번호 또는 복수 정답(예: 1,2)으로 입력해 주세요.");
}
async function refreshAnswerRecords(bank, root) {
  const refreshed = await api(url("/api/quiz", {bank}));
  if (S.bank !== bank || root.isConnected === false) return;
  S.quiz.answers = refreshed.answers;
  S.quiz.answerOrigin = refreshed.answerOrigin;
  S.quiz.rounds = refreshed.rounds;
  summary();
  const question = S.quiz.questions[S.index];
  if (question) grade(S.quiz.rounds.find((round) => round.id === S.round)?.records[question.id]);
}
function quizAnswerTable(root) {
  const bank = S.bank, material = S.quiz.material;
  const keys = (S.data.answerKeys || []).filter((key) => key.year === Number(material.exam_year) && `${key.term}학기` === material.exam_term && key.answers.length);
  const currentText = Object.values(S.quiz.answers).map((answer) => answer ?? "?").join("");
  const manualOverride = S.quiz.answerOrigin === "manual" && !keys.some((key) => answerKeyText(key.answers) === currentText);
  if (keys.length && !manualOverride) {
    root.innerHTML = `${keys.length > 1 ? `<label class="row">학년 <select data-answer-grade aria-label="적용할 정답표 학년"><option value="">학년 선택</option>${keys.map((key, i) => `<option value="${i}">${key.grade}학년</option>`).join("")}</select></label>` : ""}<div data-exam-answers></div>`;
    answerTables(root.querySelector("[data-exam-answers]"), {year: material.exam_year, term: material.exam_term, exact: true});
    if (keys.length > 1) {
      const select = root.querySelector("[data-answer-grade]");
      const current = Object.values(S.quiz.answers).map((answer) => answer ?? "?").join("");
      const selected = keys.findIndex((key) => answerKeyText(key.answers) === current);
      select.value = selected < 0 ? "" : String(selected);
      select.onchange = action(async () => {
        if (select.value === "") return;
        await api("/api/answers", {bank, raw: answerKeyText(keys[Number(select.value)].answers)});
        await refreshAnswerRecords(bank, root);
      });
    }
    return;
  }
  const count = Math.max(1, ...S.quiz.questions.map((q) => q.number), ...Object.keys(S.quiz.answers).map(Number));
  const values = Array.from({length: count}, (_, index) => S.quiz.answers[String(index + 1)] == null ? "" : answerLabel(S.quiz.answers[String(index + 1)]));
  const rows = [];
  for (let start = 0; start < count; start += 5) {
    rows.push(`<tr>${values.slice(start, start + 5).map((value, offset) => `<th scope="row">${start + offset + 1}번</th><td><input class="answer-cell" data-answer-number="${start + offset + 1}" aria-label="${start + offset + 1}번 정답" value="${esc(value)}" placeholder="—" autocomplete="off"></td>`).join("")}</tr>`);
  }
  root.innerHTML = `<section class="answer-key-section"><h3>${esc(examName(material))}</h3><p class="hint">${manualOverride ? "직접 입력한 정답표입니다." : "해당 시험의 정답표가 없습니다."} 각 칸에 정답을 입력하세요. 복수 정답은 1,2처럼 입력할 수 있습니다.</p><div class="answer-key-scroll"><table class="answer-key-table"><caption>${esc(subjectName())} · ${esc(examName(material))} 정답표</caption><tbody>${rows.join("")}</tbody></table></div><span class="auto-save-status" role="status"></span></section>`;
  const save = autoSave(`answers:${bank}`, async () => {
    const symbols = values.map(answerCellSymbol);
    while (symbols.at(-1) === "?") symbols.pop();
    await api("/api/answers", {bank, raw: symbols.join("")});
    await refreshAnswerRecords(bank, root);
  }, root.querySelector(".auto-save-status"));
  root.querySelectorAll("[data-answer-number]").forEach((input) => {
    input.addEventListener("input", () => {values[Number(input.dataset.answerNumber) - 1] = input.value;});
    autoInput(input, save);
  });
}
async function quiz() {
  await flushAutosaves();
  let banks = S.data.banks.filter((b) => b.ready);
  if (S.filter) banks = banks.filter((b) => S.filter.mapping[b.id]);
  if (!banks.length) {
    content.innerHTML = `<p class="empty">아직 풀 수 있는 문제가 없습니다.</p>${S.data.banks.filter((item) => item.task?.status === "failed").map((item) => `<article class="file-row"><strong>${esc(item.filename)}</strong><div class="file-actions">${manualWriteButton(item)}${extractionError(item.task)}</div></article>`).join("")}<div id="builtin-answer-keys"></div>`;
    bindManualWriting(content);
    bindExtractionErrors(content);
    $("#builtin-answer-keys").innerHTML = '<p class="hint">풀이할 시험의 연도·학기를 선택하면 정답표를 볼 수 있습니다.</p>';
    return;
  }
  if (!banks.some((b) => b.id === S.bank)) S.bank = banks[0].id;
  const params = { bank: S.bank };
  if (S.filter)
    Object.assign(params, {
      lecturePage: S.filter.page,
      scope: S.filter.scope,
    });
  S.quiz = await api(url("/api/quiz", params));
  if (!S.quiz.rounds.some((r) => r.id === S.round))
    S.round = S.quiz.rounds.at(-1).id;
  S.index = Math.min(S.index, Math.max(0, S.quiz.questions.length - 1));
  content.innerHTML = `<div class="toolbar quiz-controls"><label>연도·학기 ${bankSelect(banks)}</label><label>풀이 회차 <select id="round-select">${S.quiz.rounds.map((r) => `<option value="${r.id}" ${r.id === S.round ? "selected" : ""}>${r.number}회차</option>`).join("")}</select></label><button id="new-round">새 회차 시작</button>${manualWriteButton(banks.find((item) => item.id === S.bank))}${S.filter ? `<span class="hint">강의 ${S.filter.page}페이지 연결 문제</span><button id="all-questions">전체 문제 보기</button>` : ""}</div><div id="quiz-summary"></div><section class="question-list-section"><h2>문제 목록·풀이 기록</h2><div id="question-list" class="question-list"></div></section><details><summary>정답표</summary><div id="builtin-answer-keys"></div></details><div id="question"></div>`;
  bindManualWriting(content);
  quizAnswerTable($("#builtin-answer-keys"));
  $("#bank-select").onchange = action(async (e) => {
    await releaseEditor();
    S.bank = e.target.value;
    S.round = null;
    S.index = 0;
    await quiz();
  });
  $("#all-questions")?.addEventListener(
    "click",
    action(async () => {
      await releaseEditor();
      S.filter = null;
      await quiz();
    }),
  );
  $("#round-select").onchange = action(async (e) => {
    await releaseEditor();
    S.round = Number(e.target.value);
    S.index = 0;
    await quiz();
  });
  $("#new-round").onclick = action(async () => {
    await releaseEditor();
    S.round = (await api("/api/round", { bank: S.bank })).id;
    S.index = 0;
    await quiz();
  });
  summary();
  await question();
}
function recordStatus(record) {
  return !record || record.selected == null
    ? "미풀이"
    : record.correct == null
      ? "채점 대기"
      : record.correct
        ? "정답"
        : "오답";
}
function summary() {
  const round = S.quiz.rounds.find((r) => r.id === S.round);
  const rows = S.quiz.questions.map((q) => ({
    q,
    status: recordStatus(round.records[q.id]),
  }));
  $("#quiz-summary").innerHTML =
    `<p class="hint">${round.number}회차 · 총 ${rows.length} · 풀이 ${rows.filter((r) => r.status !== "미풀이").length} · 정답 ${rows.filter((r) => r.status === "정답").length} · 오답 ${rows.filter((r) => r.status === "오답").length}</p>`;
  const list = $("#question-list");
  list.dataset.layoutWidth = String(list.clientWidth);
  const columns = Math.max(1, Math.min(rows.length || 1, Math.floor(list.clientWidth / 140)));
  questionListObserver.disconnect();
  questionListObserver.observe(list);
  const questionRows = [];
  for (let start = 0; start < rows.length; start += columns) {
    const group = rows.slice(start, start + columns);
    questionRows.push(
      `<tr>${group
        .map(
          (r, offset) =>
            `<td><a href="#question" data-question="${start + offset}">${r.q.number}번</a></td><td class="${r.status === "정답" ? "correct" : r.status === "오답" ? "wrong" : ""}">${r.status}</td>`,
        )
        .join("")}${group.length < columns ? `<td colspan="${(columns - group.length) * 2}"></td>` : ""}</tr>`,
    );
  }
  $("#question-list").innerHTML =
    `<table><caption>${round.number}회차 문제별 풀이 기록</caption><thead><tr>${'<th scope="col">문제</th><th scope="col">상태</th>'.repeat(columns)}</tr></thead><tbody>${questionRows.join("")}</tbody></table>`;
  $("#question-list")
    .querySelectorAll("[data-question]")
    .forEach(
      (link) =>
        (link.onclick = action(async (event) => {
          event.preventDefault();
          await releaseEditor();
          S.index = Number(link.dataset.question);
          await question();
          $("#question").scrollIntoView({ block: "start" });
        })),
    );

}
function stem(root, text, q) {
  const pattern = /!\[([^\]]*)\]\(([^)\n]+)\)/g;
  let start = 0,
    match;
  while ((match = pattern.exec(text))) {
    const block = document.createElement("div");
    block.className = "question-body";
    block.textContent = text.slice(start, match.index);
    root.append(block);
    const img = document.createElement("img");
    img.className = "question-image";
    img.alt = match[1];
    img.src = url("/api/question/image", {
      bank: S.bank,
      page: q.page,
      file: match[2],
    });
    root.append(img);
    start = pattern.lastIndex;
  }
  const block = document.createElement("div");
  block.className = "question-body";
  block.textContent = text.slice(start);
  root.append(block);
}
async function question() {
  const q = S.quiz.questions[S.index],
    root = $("#question");
  if (!q) {
    root.innerHTML = '<p class="empty">연결된 문제가 없습니다.</p>';
    return;
  }
  const round = S.quiz.rounds.find((r) => r.id === S.round),
    record = round.records[q.id];
  root.innerHTML = `<div class="page-nav"><button id="prev-question" ${S.index === 0 ? "disabled" : ""}>이전 문제</button><span>${S.index + 1} / ${S.quiz.questions.length}</span><button id="next-question" ${S.index === S.quiz.questions.length - 1 ? "disabled" : ""}>다음 문제</button></div><div class="row between"><span class="hint">${esc(examName(S.quiz.material))} · ${q.number}번</span><button id="edit-question">문제 수정하기</button></div>${(q.warnings || []).map((w) => `<div class="notice">${esc(w)}</div>`).join("")}<div id="question-stem"></div><div id="choices">${q.choices.map((c, i) => `<label class="choice"><input type="checkbox" value="${i + 1}" ${record?.selected === i + 1 ? "checked" : ""}><span>${esc(c)}</span></label>`).join("")}</div><div id="grade"></div><details id="explanation-view"><summary>해설</summary><div id="saved-explanations"></div></details><details id="explanation-add"><summary>해설 추가하기</summary><div id="explanation-editor"></div></details>`;
  stem($("#question-stem"), q.stem, q);
  $("#prev-question").onclick = () => move(-1);
  $("#next-question").onclick = () => move(1);
  async function move(delta) {
    try {
      await releaseEditor();
      S.index += delta;
      await question();
    } catch (e) {
      notify(e.message, true);
    }
  }
  $("#edit-question").onclick = () => editQuestion(q);
  $("#choices")
    .querySelectorAll("input")
    .forEach(
      (input) =>
        (input.onchange = action(async () => {
          const value = input.checked ? Number(input.value) : null;
          const record = await api("/api/select", {
            bank: S.bank,
            round: S.round,
            question: q.id,
            value,
          });
          round.records[q.id] = record;
          $("#choices")
            .querySelectorAll("input")
            .forEach((i) => (i.checked = Number(i.value) === value));
          grade(record);
          summary();
        })),
    );
  grade(record);
  await showExplanations(q);
  $("#explanation-add").ontoggle = action(async (e) => {
    if (e.target.open && !$("#explanation-editor").hasChildNodes())
      await explanationEditor(q);
  });
}
function grade(record) {
  const root = $("#grade");
  root.innerHTML =
    record?.selected == null
      ? ""
      : record.correct == null
        ? '<div class="grade wait">선택을 저장했습니다. 정답표가 확정되면 채점됩니다.</div>'
        : record.correct
          ? `<div class="grade good">정답입니다.${typeof record.answer === "string" && Object.values(multipleAnswerSymbols).includes(record.answer) ? ` 인정되는 정답은 ${esc(answerLabel(record.answer))}번 보기입니다.` : ""}</div>`
          : `<div class="grade bad">오답입니다. 채점 당시 정답은 ${esc(answerLabel(record.answer))}번 보기입니다.</div>`;
}
async function showExplanations(q) {
  const bank = S.bank;
  const [links, data] = await Promise.all([
    api(url("/api/explanations", {bank, question: q.id})),
    api(url("/api/explanation-note", {bank, question: q.id})),
  ]);
  const root = $("#saved-explanations");
  if (!root || bank !== S.bank || S.quiz.questions[S.index]?.id !== q.id) return;
  root.innerHTML = links.length || data.note
    ? `${data.note ? `<p>${esc(data.note)}</p>` : ""}${links.map((link) => `<p class="hint">${esc(link.title)} · ${link.page}페이지</p><img class="pdf-preview" alt="연결된 해설 페이지" src="${url("/api/lecture/page", {subject: S.subject, page: link.page, annotated: 1})}">`).join("")}`
    : '<p class="hint">등록된 해설이 없습니다.</p>';
}
async function explanationEditor(q) {
  const root = $("#explanation-editor"),
    b = S.data.bundle;
  if (!b) {
    root.innerHTML =
      '<p class="hint">자료 관리에서 강의자료를 먼저 만들어 주세요.</p>';
    return;
  }
  const links = await api(
    url("/api/explanations", { bank: S.bank, question: q.id }),
  );
  const bank = S.bank;
  const noteData = await api(url("/api/explanation-note", {bank, question: q.id}));
  const draft = (S.explanationDrafts[bank + q.id] ||= {
    page: 1,
    pages: links.map((l) => l.page),
    note: noteData.note,
  });
  root.innerHTML = `<div class="viewer-grid"><nav class="toc">${b.chapters.map((c) => `<button data-page="${c.start}">${esc(c.title)}</button>`).join("")}</nav><div class="document"><div class="row between"><strong>PDF 미리보기</strong><span class="page-position"><input id="explanation-page-top" class="page-jump" type="number" min="1" max="${b.pages}" aria-label="이동할 해설 PDF 페이지"><span>/ ${b.pages}</span></span><button id="select-explanation-page">이 페이지 선택</button></div><div id="explanation-canvas"></div><div class="page-nav"><button id="explanation-prev">이전 페이지</button><span class="page-position"><input id="explanation-page" class="page-jump" type="number" min="1" max="${b.pages}" aria-label="이동할 해설 PDF 페이지"><span id="explanation-position">/ ${b.pages}</span></span><button id="explanation-next">다음 페이지</button></div></div></div><div id="selected-pages" class="page-links"></div><label class="stack">해설 메모<textarea id="explanation-note">${esc(draft.note)}</textarea></label><span id="explanation-save-status" class="auto-save-status" role="status"></span>`;
  const save = autoSave(`explanations:${bank}:${q.id}`, async () => {
    await api("/api/explanations", {bank, question: q.id, pages: draft.pages, note: draft.note});
    if (S.bank === bank && S.quiz.questions[S.index]?.id === q.id) await showExplanations(q);
  }, $("#explanation-save-status"));
  const chips = () => {
    $("#selected-pages").innerHTML = draft.pages.length
      ? draft.pages
          .map(
            (p) =>
              `<button class="chip" data-remove="${p}">${p}페이지 ×</button>`,
          )
          .join("")
      : '<span class="hint">선택한 페이지가 없습니다.</span>';
    $("#selected-pages")
      .querySelectorAll("button")
      .forEach(
        (b) =>
          (b.onclick = () => {
            draft.pages = draft.pages.filter(
              (p) => p !== Number(b.dataset.remove),
            );
            chips();
            save.schedule();
          }),
      );
  };
  const paint = async (page) => {
    await flushAutosaves();
    draft.page = clampPage(page, b.pages);
    $("#explanation-page").value = draft.page;
    $("#explanation-page-top").value = draft.page;
    $("#explanation-prev").disabled = draft.page === 1;
    $("#explanation-next").disabled = draft.page === b.pages;
    await editorAt($("#explanation-canvas"), draft.page);
  };
  root
    .querySelectorAll("[data-page]")
    .forEach(
      (button) => (button.onclick = action(() => paint(button.dataset.page))),
    );
  for (const selector of ["#explanation-page", "#explanation-page-top"]) {
    $(selector).onchange = action((event) => paint(event.target.value));
    $(selector).onkeydown = action(async (event) => {
      if (event.key === "Enter") {event.preventDefault(); await paint(event.target.value);}
    });
  }
  $("#explanation-prev").onclick = action(() => paint(draft.page - 1));
  $("#explanation-next").onclick = action(() => paint(draft.page + 1));
  $("#select-explanation-page").onclick = () => {
    draft.pages = [...new Set([...draft.pages, draft.page])].sort((a, b) => a - b);
    chips();
    save.schedule();
  };
  const noteInput = $("#explanation-note");
  noteInput.oninput = (event) => {draft.note = event.target.value;};
  autoInput(noteInput, save);
  chips();
  await paint(draft.page);
}
let regionEditor = null;
let regionRequest = null;
let regionVersion = 0;
function cancelReextraction() {
  regionVersion++;
  regionRequest?.abort();
  regionRequest = null;
  regionEditor?.destroy();
  regionEditor = null;
}
function replacePageQuestion(text, number, replacement) {
  const headings = [...text.matchAll(/^(\d+)[.)][ \t]+.+$/gm)];
  const index = headings.findIndex((match) => Number(match[1]) === number);
  if (index < 0) return text.trimEnd() + "\n\n" + replacement;
  const start = headings[index].index, end = headings[index+1]?.index ?? text.length;
  return text.slice(0,start) + replacement.trim() + "\n\n" + text.slice(end);
}
function bindReextraction({bank, page, number, pageMode, editor, save}) {
  const version = regionVersion, svg = $("#edit-regions"), status = $("#region-status");
  svg.style.pointerEvents = "";
  editor.readOnly = false;
  const selector = new RegionSelector(svg, () => {
    status.textContent = `문제 영역 ${selector.problem ? "지정됨" : "미지정"} · 이미지 ${selector.images.length}개`;
  });
  regionEditor = selector;
  $("#region-number").value = number;
  $("#region-number").readOnly = !pageMode;
  $("#region-reextract").disabled = false;
  status.textContent = "원본 위를 드래그해 문제 영역을 지정하세요.";
  for (const mode of ["problem", "image"]) {
    $("#region-" + mode).classList.toggle("active", mode === "problem");
    $("#region-" + mode).onclick = () => {
      selector.mode = mode;
      for (const name of ["problem", "image"]) $("#region-" + name).classList.toggle("active", name === mode);
    };
  }
  $("#region-clear").onclick = () => selector.clear();
  $("#region-undo-image").onclick = () => selector.undoImage();
  $("#region-reextract").onclick = action(async () => {
    if (!selector.problem) throw new Error("원본에서 문제 영역을 먼저 드래그해 주세요.");
    const target = Number($("#region-number").value);
    if (!Number.isInteger(target) || target < 1) throw new Error("문제 번호를 확인해 주세요.");
    const controller = new AbortController();regionRequest = controller;
    const imageBoxes = selector.images.map(box => [...box]);
    const button = $("#region-reextract"), original = editor.value;
    button.disabled = true;editor.readOnly = true;svg.style.pointerEvents = "none";
    status.textContent = "선택한 문제와 이미지를 다시 추출 중…";
    try {
      const result = await api("/api/question/reextract", {bank, page, number: target, problem_box: selector.problem, image_boxes: imageBoxes}, {signal: controller.signal});
      if (version !== regionVersion || !$("#edit-dialog").open || editor.isConnected === false) return;
      let replacement = result.text;
      if (!imageBoxes.length) {
        const previous = pageMode ? [...original.matchAll(/^(\d+)[.)][ \t]+.+$/gm)] : [];
        const start = previous.findIndex((match) => Number(match[1]) === target);
        const block = pageMode ? (start < 0 ? "" : original.slice(previous[start].index, previous[start+1]?.index ?? original.length)) : original;
        const images = block.match(/!\[[^\]]*\]\([^)\n]+\)/g) || [];
        if (images.length) replacement = replacement.replace(/(?=^- \[[ xX]\])/m, images.join("\n\n") + "\n\n");
      }
      editor.value = pageMode ? replacePageQuestion(original,target,replacement) : replacement;
      save.schedule();
      status.textContent = "추출 결과를 반영했습니다. 원본과 비교해 확인해 주세요.";
    } catch (error) {
      if (error.name !== "AbortError" && version === regionVersion) {
        status.textContent = "다시 추출하지 못했습니다. 기존 문제는 유지됩니다.";
        throw error;
      }
    } finally {
      editor.readOnly = false;
      if (version === regionVersion) {button.disabled = false;svg.style.pointerEvents = "";regionRequest = null;}
    }
  });
}
let questionEdited = false;
async function editQuestion(q, pageMode = false) {
  cancelReextraction();
  try {
    await flushAutosaves();
    if (!$("#edit-dialog").open) questionEdited = false;
    const bank = S.bank;
    const data = await api(
      url("/api/question/raw", {
        bank: S.bank,
        page: q.page,
        ...(pageMode ? {mode: "page"} : {number: q.number}),
      }),
    );
    $("#edit-original").src = url("/api/question/page", {
      bank: S.bank,
      page: q.page,
    });
    const previous = $("#edit-text"), editor = previous.cloneNode(true);
    previous.replaceWith(editor);
    editor.value = data.text || `${data.suggestedNumber}) 문제 내용을 입력하세요.\n\n- [ ] 첫 번째 보기\n- [ ] 두 번째 보기\n- [ ] 세 번째 보기\n- [ ] 네 번째 보기\n`;
    $("#edit-title").textContent = pageMode ? "페이지 문제 직접 작성·수정" : "문제 수정";
    $("#edit-page-field").hidden = !pageMode;
    $("#edit-context").innerHTML = `${pageMode ? '<p>원본 문제 번호를 유지하세요. 한 페이지에 여러 문제를 입력할 수 있으며 보기는 ‘- [ ] 보기 내용’ 형식으로 작성합니다.</p>' : ""}${(data.warnings || []).filter((warning) => warning.original_values).map((warning) => `<details><summary>${esc(warning.message)}</summary><pre>${esc(JSON.stringify(warning.original_values, null, 2))}</pre></details>`).join("")}`;
    if (pageMode) {
      const item = S.data.banks.find((item) => item.id === bank);
      $("#edit-page").innerHTML = Array.from({length: item.pages}, (_, index) => `<option value="${index + 1}" ${index + 1 === q.page ? "selected" : ""}>${index + 1}페이지</option>`).join("");
      $("#edit-page").onchange = action(async (event) => {
        const page = Number(event.target.value);
        await editQuestion({page, id: `page-${page}`}, true);
      });
    }
    $("#edit-save-status").textContent = "";
    const save = autoSave(`question:${bank}:${q.id}`, async () => {
      await api("/api/question/edit", {bank, page: q.page, ...(pageMode ? {mode: "page"} : {number: q.number}), text: editor.value});
      questionEdited = true;
    }, $("#edit-save-status"));
    autoInput(editor, save);
    bindReextraction({bank, page: q.page, number: q.number || data.suggestedNumber, pageMode, editor, save});
    $("#crop-image").onclick = action(async () => {
      const bbox = ["left", "top", "right", "bottom"].map((side) =>
        Number($("#crop-" + side).value),
      );
      const result = await api("/api/question/crop", {
        bank: S.bank,
        page: q.page,
        bbox,
      });
      const editor = $("#edit-text");
      const insertion =
        editor.selectionStart ||
        (editor.value.indexOf("\n") >= 0
          ? editor.value.indexOf("\n")
          : editor.value.length);
      editor.setRangeText(
        "\n\n" + result.markdown + "\n\n",
        insertion,
        Math.max(insertion, editor.selectionEnd),
        "end",
      );
      save.schedule();
      notify("이미지를 추가했습니다.");
    });
    if (!$("#edit-dialog").open) $("#edit-dialog").showModal();
  } catch (e) {
    notify(e.message, true);
  }
}
async function closeQuestionEditor() {
  cancelReextraction();
  await flushAutosaves();
  $("#edit-dialog").close();
  if (questionEdited) {
    await releaseEditor();
    S.route = "quiz";
    S.filter = null;
    sidebar();
    await render();
    questionEdited = false;
  }
}
$("#close-edit").onclick = action(closeQuestionEditor);
$("#edit-dialog").oncancel = (event) => {
  event.preventDefault();
  action(closeQuestionEditor)();
};
async function results() {
  const banks = S.data.banks;
  if (!banks.length) {
    content.innerHTML = '<p class="empty">문제은행을 먼저 등록해 주세요.</p>';
    return;
  }
  if (!banks.some((b) => b.id === S.bank)) S.bank = banks[0].id;
  const selected = banks.find((b) => b.id === S.bank);
  content.innerHTML = `<div class="toolbar">${bankSelect(banks)}<button id="refresh-results">새로고침</button>${selected.ready ? `<a class="button" href="${url("/api/question/zip", { bank: S.bank })}">Markdown·이미지 ZIP</a>` : ""}</div><div>${banks.map((b) => `<article class="file-row"><div class="row"><strong>${esc(b.filename)}</strong>${badge(b)}</div><p class="hint">${b.task?.completed || 0}/${b.pages}페이지</p>${b.task?.status === "running" ? `<progress max="${b.pages}" value="${b.task.completed}"></progress>` : ""}${manualWriteButton(b)}${extractionError(b.task)}${b.task?.error && b.task.status !== "failed" ? `<pre class="status-error">${esc(b.task.error)}</pre>` : ""}</article>`).join("")}</div>${selected.ready ? '<button id="review-results">문제 검토·풀기</button>' : ""}`;
  $("#bank-select").onchange = action(async (e) => {
    S.bank = e.target.value;
    await results();
  });
  $("#refresh-results").onclick = () =>
    render().catch((e) => notify(e.message, true));
  bindExtractionErrors(content);
  bindManualWriting(content);
  $("#review-results")?.addEventListener("click", () => {
    S.route = "quiz";
    S.filter = null;
    S.index = 0;
    sidebar();
    render().catch((e) => notify(e.message, true));
  });
}
setInterval(async () => {
  if (!S.subject || !["manage", "results"].includes(S.route)) return;
  try {
    if ([...autoSaves.values()].some((save) => save.dirty || save.running)) return;
    const subject = S.subject, route = S.route;
    const data = await api(url("/api/subject", { id: subject }));
    if (subject !== S.subject || route !== S.route || [...autoSaves.values()].some((save) => save.dirty || save.running)) return;
    S.data = data;
    if (
      S.route === "manage" &&
      !$("#bank-list")?.contains(document.activeElement)
    )
      bankList();
    else if (S.route === "results" && !content.contains(document.activeElement))
      await results();
  } catch {}
}, 3000);
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "hidden") flushAutosaves().catch(() => {});
});
bootstrap().catch((e) => notify(e.message, true));
