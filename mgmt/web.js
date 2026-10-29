"use strict";
const $ = (id) => document.getElementById(id);
const token = document.querySelector('meta[name="mgmt-token"]').content;
let catalog = [],
  current = null,
  number = 0;
// Unsaved edits by item number: {action, note}. Saved one at a time, in order.
const drafts = new Map();
let timer,
  saving = null,
  saveError = null,
  navigating = false,
  noticeTimer;
// Compact view state: rows whose note field is open, rows whose context is open, folded topics.
const notesOpen = new Set(),
  contextOpen = new Set();
let folded = new Set();
const VIEW_KEY = "mgmt.view";
const DEFAULT_ACTIONS = ["remove", "keep", "revise"];
const ASK = "ask";
const THREAD_TAIL = 3;
const NOTE_HELP =
  "A note alone does not select an action. To request changes, choose an action above.";
const ASK_HELP =
  "Asking leaves this item open. Write your question here, export, and paste it to your agent; its answer appears in the conversation after it regenerates.";
const isLocked = (item) => ["applying", "done"].includes(item.status);
const askOn = () => current?.data.ask !== false;
const isAsked = (value) => askOn() && value.action === ASK;
const isDecided = (value) => Boolean(value.action) && !isAsked(value);
const actionsFor = () => {
  const base = current?.data.actions || DEFAULT_ACTIONS;
  return askOn() && !base.includes(ASK) ? [...base, ASK] : base;
};
const label = (action) => action.charAt(0).toUpperCase() + action.slice(1);
const saved = (n) => current?.data.items[n - 1];
const valueOf = (n) => saved(n) && { ...saved(n), ...(drafts.get(n) || {}) };
const item = () => saved(number);
const isDirty = (n) => {
  const draft = drafts.get(n),
    base = saved(n);
  return Boolean(draft && base && (draft.action !== base.action || draft.note !== base.note));
};
const dirtyNumbers = () => [...drafts.keys()].filter(isDirty);
const pad = (n) => String(n).padStart(2, "0");

function storage(key, value) {
  try {
    if (value === undefined) return localStorage.getItem(key);
    localStorage.setItem(key, value);
  } catch {
    return null;
  }
}
let view = storage(VIEW_KEY) === "single" ? "single" : "compact";

// A topic is the item's group, else its source file without a trailing :line (as mgmt.py does).
function groupOf(value) {
  if (value.group) return value.group;
  const match = /^(.+):[\d-]+$/.exec(value.source);
  return match ? match[1] : value.source;
}
function groupOrder() {
  const order = [...new Set(current?.data.groups || [])];
  for (const value of current?.data.items || [])
    if (!order.includes(groupOf(value))) order.push(groupOf(value));
  return order;
}

async function api(path, body) {
  const response = await fetch(path, {
    method: body ? "POST" : "GET",
    headers: {
      "X-Mgmt-Token": token,
      ...(body ? { "Content-Type": "application/json" } : {}),
    },
    ...(body ? { body: JSON.stringify(body) } : {}),
    signal: AbortSignal.timeout(15000),
  });
  const data = await response.json();
  if (!response.ok)
    throw Object.assign(new Error(data.error || "Request failed"), {
      status: response.status,
    });
  return data;
}
function notice(message) {
  clearTimeout(noticeTimer);
  $("notice").textContent = message;
  $("notice").hidden = false;
  noticeTimer = setTimeout(() => {
    $("notice").hidden = true;
  }, 7000);
}
function saveStatus(text, error = false) {
  document.querySelectorAll("[data-save-state]").forEach((state) => {
    state.textContent = text;
    state.parentElement.classList.toggle("error", error);
  });
  document.querySelectorAll(".retry").forEach((b) => (b.hidden = !error || saveError?.status === 409));
  document.querySelectorAll(".reload").forEach((b) => (b.hidden = !error));
}
function updateSummary() {
  if (!current) return;
  const selected = current.data.items.filter(isDecided).length;
  const asked = current.data.items.filter(isAsked).length;
  $("session-summary").textContent =
    `${current.data.items.length} items · ${groupOrder().length} topics · Every decision is reversible until applied.`;
  $("progress").replaceChildren(
    document.createTextNode(`${selected} / ${current.data.items.length}`),
  );
  const caption = document.createElement("small");
  caption.textContent = asked ? `DECIDED · ${asked} ASKED` : "WITH DECISIONS";
  $("progress").append(caption);
  const entry = catalog.find((s) => s.id === current.id);
  if (entry) Object.assign(entry, { selected, asked });
  renderSessions();
}
function renderSessions() {
  $("sessions").replaceChildren();
  for (const session of catalog) {
    const button = document.createElement("button");
    button.className =
      "session-button" + (current?.id === session.id ? " active" : "");
    button.setAttribute(
      "aria-current",
      current?.id === session.id ? "true" : "false",
    );
    button.title = session.path;
    const label = document.createElement("span");
    label.textContent = session.title.replace(/^Znbu outline — /, "");
    const count = document.createElement("small");
    count.textContent =
      `${session.selected}/${session.total}` + (session.asked ? ` · ${session.asked}?` : "");
    button.append(label, count);
    button.addEventListener("click", () =>
      navigate(() => openSession(session.id)),
    );
    $("sessions").append(button);
  }
  if (!catalog.length)
    $("sessions").textContent =
      "No sessions found. Choose a session file or folder when starting the server.";
}
// One filter and search for both views.
function shown(value, query, filter) {
  if (
    (filter === "selected" && !isDecided(value)) ||
    (filter === "unselected" && value.action) ||
    (filter === "changed" && !value.context_changed && !value.new_reply) ||
    (filter === "asked" && !isAsked(value)) ||
    (filter === "locked" && !isLocked(value))
  )
    return false;
  return (
    !query ||
    [value.title, value.details, value.source, value.note, value.action, groupOf(value)]
      .join("\n")
      .toLowerCase()
      .includes(query)
  );
}
function metaText(value) {
  return [
    (isAsked(value) ? "asked · waiting for the agent" : value.action) ||
      (value.recommended_action
        ? `undecided · rec. ${value.recommended_action}`
        : "undecided"),
    value.action && value.action === value.recommended_action
      ? "as recommended"
      : "",
    value.new_reply ? "new reply" : value.context_changed ? "context changed" : "",
    value.note ? "note" : "",
    isLocked(value)
      ? value.status + " · locked"
      : value.status === "failed"
        ? "failed"
        : "",
  ]
    .filter(Boolean)
    .join(" · ");
}

// ---- One item at a time ----
function renderItems() {
  $("items").replaceChildren();
  if (!current || view !== "single") return;
  const query = $("search").value.toLowerCase().trim();
  const filter = $("filter").value;
  let count = 0;
  current.data.items.forEach((_, index) => {
    const value = valueOf(index + 1);
    if (!shown(value, query, filter)) return;
    count++;
    const button = document.createElement("button");
    button.className = "item-button" + (index + 1 === number ? " active" : "");
    button.dataset.number = index + 1;
    button.setAttribute(
      "aria-current",
      index + 1 === number ? "true" : "false",
    );
    const label = document.createElement("span");
    label.className = "number";
    label.textContent = pad(index + 1);
    const body = document.createElement("span");
    const title = document.createElement("span");
    title.className = "title";
    title.textContent = value.title;
    const meta = document.createElement("span");
    meta.className =
      "item-meta" + (value.action === "remove" ? " remove-label" : "");
    meta.textContent = groupOf(value) + " · " + metaText(value);
    body.append(title, meta);
    button.append(label, body);
    button.addEventListener("click", () =>
      navigate(async () => {
        number = index + 1;
        renderEditor();
        renderItems();
      }),
    );
    $("items").append(button);
  });
  $("visible-count").textContent = `${count} shown`;
  if (!count) {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent = "No matching items. Try another search or filter.";
    $("items").append(empty);
  }
}
function actionButton(action, value, small = false) {
  const button = document.createElement("button");
  button.type = "button";
  button.dataset.action = action;
  const index = actionsFor().indexOf(action);
  button.textContent = action ? label(action) : small ? "×" : "Clear";
  if (action && index > -1 && index < 9) button.title = `Key ${index + 1}`;
  if (!action) button.title = "Clear: leave this item untouched";
  if (action === "remove") button.className = "remove";
  if (action === ASK && askOn()) {
    button.className = "ask";
    button.title = (button.title ? button.title + " or " : "Key ") + "?";
  }
  if (!action) button.className = "clear";
  if (action && action === value.recommended_action) {
    button.classList.add("recommended");
    button.title += " · recommended";
  }
  return button;
}
function renderActionButtons(value) {
  $("actions").replaceChildren(...[...actionsFor(), ""].map((a) => actionButton(a, value)));
}
function renderActions() {
  const value = valueOf(number);
  $("actions")
    .querySelectorAll("[data-action]")
    .forEach((button) =>
      button.setAttribute(
        "aria-pressed",
        String(button.dataset.action === value?.action),
      ),
    );
  const rec = value?.recommended_action;
  const taken = Boolean(rec) && value?.action === rec;
  $("recommendation").classList.toggle("accepted", taken);
  $("recommendation-state").textContent = taken
    ? `RECOMMENDED · ${rec.toUpperCase()} · ACCEPTED`
    : `RECOMMENDED · ${(rec || "").toUpperCase()} · NOT CONFIRMED`;
  $("accept").hidden = taken;
  const asking = isAsked(value || {});
  $("note-help").textContent = asking ? ASK_HELP : NOTE_HELP;
  $("note").placeholder = asking
    ? "Your question for the agent…"
    : "A reminder for yourself, what to preserve, or instructions for your agent…";
}
function stamp(at) {
  const date = new Date(at);
  return at && !Number.isNaN(date.getTime())
    ? date.toLocaleString([], { dateStyle: "medium", timeStyle: "short" })
    : at || "";
}
function threadEntries(messages) {
  return messages.map((message) => {
    const entry = document.createElement("li");
    entry.className = "thread-message " + (message.role === "agent" ? "agent" : "owner");
    const who = document.createElement("span");
    who.className = "thread-who";
    who.textContent = message.role === "agent" ? "Agent" : "You";
    const when = document.createElement("time");
    when.textContent = stamp(message.at);
    if (message.at) when.dateTime = message.at;
    const text = document.createElement("p");
    text.textContent = message.text;
    entry.append(who, when, text);
    return entry;
  });
}
function renderThread(value, expanded = false) {
  const thread = value.thread || [];
  $("thread").hidden = !thread.length;
  if (!thread.length) return;
  $("thread-count").textContent =
    `${thread.length} message${thread.length === 1 ? "" : "s"} · read only`;
  const hidden = expanded || thread.length <= THREAD_TAIL + 1 ? 0 : thread.length - THREAD_TAIL;
  $("thread-earlier").hidden = !hidden;
  $("thread-earlier").textContent = `Show ${hidden} earlier message${hidden === 1 ? "" : "s"}`;
  $("thread-list").replaceChildren(...threadEntries(thread.slice(hidden)));
}
function renderEditor() {
  const value = valueOf(number);
  $("empty-detail").hidden = Boolean(value);
  $("editor").hidden = !value;
  if (!value) return;
  $("item-number").textContent = `ITEM ${pad(number)} · ${groupOf(value).toUpperCase()}`;
  $("item-status").textContent = isLocked(value)
    ? `${value.status} · locked`
    : value.status;
  $("item-title").textContent = value.title;
  $("item-source").textContent = value.source;
  $("item-details").textContent = value.details;
  $("item-details").scrollTop = 0;
  $("result").hidden = !value.result;
  $("result").textContent = value.result || "";
  $("custom-action").value = value.action;
  $("note").value = value.note;
  $("decision-fields").disabled = isLocked(value);
  $("changed-flag").hidden = !value.context_changed || isDirty(number);
  $("changed-flag").textContent = changedText(value);
  renderThread(value);
  $("recommendation").hidden = !value.recommendation;
  $("recommendation-text").textContent = value.recommendation || "";
  $("accept").disabled = isLocked(value);
  renderActionButtons(value);
  renderActions();
  if (isLocked(value))
    $("save-state").textContent = "Locked while active or completed. Start a new session for further changes.";
  $("detail").scrollTop = 0;
}
const changedText = (value) =>
  value.new_reply
    ? "New reply from the agent. Read the conversation; any change clears this flag."
    : "The source text changed since this decision was made. Recheck it; any change clears this flag.";

// ---- Compact: every item on one page, by topic ----
const rowOf = (n) => $("row-" + n);
function topicCounts(group) {
  const values = current.data.items.map((_, i) => valueOf(i + 1)).filter((v) => groupOf(v) === group);
  const decided = values.filter(isDecided).length,
    asked = values.filter(isAsked).length;
  return `${decided}/${values.length} decided` + (asked ? ` · ${asked} asked` : "");
}
function renderCompact() {
  $("topics").replaceChildren();
  if (!current || view !== "compact") return;
  const query = $("c-search").value.toLowerCase().trim();
  const filter = $("c-filter").value;
  const byGroup = new Map(groupOrder().map((g) => [g, []]));
  current.data.items.forEach((_, index) => {
    const value = valueOf(index + 1);
    if (shown(value, query, filter)) byGroup.get(groupOf(value)).push(index + 1);
  });
  let count = 0;
  for (const [group, numbers] of byGroup) {
    if (!numbers.length) continue;
    count += numbers.length;
    const topic = document.createElement("section");
    topic.className = "topic" + (folded.has(group) ? " folded" : "");
    topic.dataset.group = group;
    const head = document.createElement("button");
    head.type = "button";
    head.className = "topic-head";
    head.setAttribute("aria-expanded", String(!folded.has(group)));
    head.title = "Fold or unfold this topic (z)";
    const caret = document.createElement("span");
    caret.className = "caret";
    caret.setAttribute("aria-hidden", "true");
    const name = document.createElement("span");
    name.className = "topic-name";
    name.textContent = group;
    const counts = document.createElement("span");
    counts.className = "topic-count";
    counts.textContent = topicCounts(group);
    head.append(caret, name, counts);
    const rows = document.createElement("div");
    rows.className = "topic-rows";
    rows.append(...numbers.map(buildRow));
    topic.append(head, rows);
    $("topics").append(topic);
  }
  $("c-count").textContent = `${count} shown`;
  if (!count) {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent = "No matching items. Try another search or filter.";
    $("topics").append(empty);
  }
}
function buildRow(n) {
  const value = valueOf(n);
  const row = document.createElement("div");
  row.className = "row";
  row.id = "row-" + n;
  row.dataset.number = n;
  const num = document.createElement("span");
  num.className = "row-num";
  num.textContent = pad(n);
  const text = document.createElement("p");
  text.className = "row-text";
  text.textContent = value.title;
  const flags = document.createElement("span");
  flags.className = "row-flags";
  text.append(flags);
  const controls = document.createElement("div");
  controls.className = "row-controls";
  const chips = document.createElement("div");
  chips.className = "chips";
  chips.setAttribute("role", "group");
  chips.setAttribute("aria-label", "Outcome for item " + n);
  const notes = document.createElement("label");
  notes.className = "notes-toggle";
  notes.title = "Show or hide the note (n)";
  const box = document.createElement("input");
  box.type = "checkbox";
  box.className = "notes-box";
  notes.append(box, document.createTextNode("notes"));
  const why = document.createElement("button");
  why.type = "button";
  why.className = "why";
  why.title = "Details, recommendation and conversation (x)";
  const messages = (value.thread || []).length;
  why.textContent = (value.recommendation ? "why" : "context") + (messages ? ` · ${messages}` : "");
  controls.append(chips, notes, why);
  const main = document.createElement("div");
  main.className = "row-main";
  main.append(num, text, controls);
  const note = document.createElement("div");
  note.className = "row-note";
  const area = document.createElement("textarea");
  area.rows = 2;
  area.setAttribute("aria-label", "Note for item " + n);
  area.value = value.note;
  note.append(area);
  const context = document.createElement("div");
  context.className = "row-context";
  row.append(main, note, context);
  updateRow(n, row);
  return row;
}
function chipActions(value) {
  const actions = actionsFor();
  return value.action && !actions.includes(value.action) ? [...actions, value.action] : actions;
}
// Refresh a row in place; never touches a note field the owner is typing in.
function updateRow(n, row = rowOf(n)) {
  if (!row) return;
  const value = valueOf(n);
  const locked = isLocked(value);
  row.classList.toggle("focused", n === number);
  row.classList.toggle("decided", isDecided(value));
  row.classList.toggle("asked", isAsked(value));
  row.classList.toggle("locked", locked);
  const chips = row.querySelector(".chips");
  const wanted = [...chipActions(value), ""];
  if (chips.dataset.set !== wanted.join("\n")) {
    chips.replaceChildren(...wanted.map((a) => actionButton(a, value, true)));
    chips.dataset.set = wanted.join("\n");
  }
  chips.querySelectorAll("button").forEach((button) => {
    button.setAttribute("aria-pressed", String(Boolean(button.dataset.action) && button.dataset.action === value.action));
    button.disabled = locked;
    // Clear holds its place on undecided rows too, so the chips line up from row to row.
    if (!button.dataset.action) button.classList.toggle("idle", !value.action);
  });
  const flags = [
    value.new_reply ? "new reply" : value.context_changed && !isDirty(n) ? "changed" : "",
    locked ? value.status : value.status === "failed" ? "failed" : "",
  ].filter(Boolean);
  row.querySelector(".row-flags").textContent = flags.length ? " " + flags.map((f) => `[${f}]`).join(" ") : "";
  const open = notesOpen.has(n);
  row.querySelector(".notes-box").checked = open;
  row.querySelector(".notes-toggle").classList.toggle("has-note", Boolean(value.note.trim()));
  const area = row.querySelector("textarea");
  if (document.activeElement !== area && area.value !== value.note) area.value = value.note;
  area.readOnly = locked;
  area.placeholder = isAsked(value) ? "Your question for the agent…" : "A note or instructions for your agent…";
  row.querySelector(".row-note").hidden = !open;
  const context = row.querySelector(".row-context");
  context.hidden = !contextOpen.has(n);
  row.querySelector(".why").setAttribute("aria-expanded", String(contextOpen.has(n)));
  if (contextOpen.has(n) && !context.childElementCount) fillContext(context, value);
}
function fillContext(context, value) {
  const parts = [];
  if (value.context_changed) {
    const flag = document.createElement("div");
    flag.className = "changed-flag";
    flag.textContent = changedText(value);
    parts.push(flag);
  }
  if (value.result) {
    const result = document.createElement("div");
    result.className = "result";
    result.textContent = value.result;
    parts.push(result);
  }
  if (value.recommendation) {
    const rec = document.createElement("div");
    rec.className = "recommendation";
    const head = document.createElement("span");
    head.className = "eyebrow";
    head.textContent = `RECOMMENDED · ${(value.recommended_action || "").toUpperCase()}`;
    const text = document.createElement("p");
    text.textContent = value.recommendation;
    rec.append(head, text);
    parts.push(rec);
  }
  if ((value.thread || []).length) {
    const list = document.createElement("ol");
    list.className = "thread-list";
    list.append(...threadEntries(value.thread));
    parts.push(list);
  }
  const source = document.createElement("p");
  source.className = "source-location";
  source.textContent = value.source;
  const details = document.createElement("pre");
  details.textContent = value.details;
  parts.push(source, details);
  context.replaceChildren(...parts);
}
function updateTopic(group) {
  const topic = [...document.querySelectorAll(".topic")].find((t) => t.dataset.group === group);
  if (topic) topic.querySelector(".topic-count").textContent = topicCounts(group);
}
function focusRow(n, scroll = false) {
  const previous = number;
  number = n;
  updateRow(previous);
  updateRow(n);
  if (scroll) rowOf(n)?.scrollIntoView({ block: "nearest" });
}
function toggleNotes(n, open = !notesOpen.has(n), focus = open) {
  if (open) notesOpen.add(n);
  else notesOpen.delete(n);
  updateRow(n);
  const area = rowOf(n)?.querySelector("textarea");
  if (focus && area) area.focus();
  else if (!open && document.activeElement === area) area.blur();
}
function toggleContext(n) {
  if (contextOpen.has(n)) contextOpen.delete(n);
  else contextOpen.add(n);
  updateRow(n);
}
function foldKey() {
  return "mgmt.folded." + current?.id;
}
function toggleFold(group) {
  if (folded.has(group)) folded.delete(group);
  else folded.add(group);
  storage(foldKey(), JSON.stringify([...folded]));
  const topic = [...document.querySelectorAll(".topic")].find((t) => t.dataset.group === group);
  if (!topic) return;
  topic.classList.toggle("folded", folded.has(group));
  topic.querySelector(".topic-head").setAttribute("aria-expanded", String(!folded.has(group)));
}
$("topics").addEventListener("click", (event) => {
  const head = event.target.closest(".topic-head");
  if (head) return toggleFold(head.parentElement.dataset.group);
  const row = event.target.closest(".row");
  if (!row) return;
  const n = Number(row.dataset.number);
  if (n !== number) focusRow(n);
  const chip = event.target.closest("[data-action]");
  if (chip && !chip.disabled) setDraft(n, { action: chip.dataset.action }, true);
  else if (event.target.closest(".why")) toggleContext(n);
});
$("topics").addEventListener("change", (event) => {
  if (!event.target.classList.contains("notes-box")) return;
  const n = Number(event.target.closest(".row").dataset.number);
  toggleNotes(n, event.target.checked);
});
$("topics").addEventListener("input", (event) => {
  if (event.target.tagName !== "TEXTAREA") return;
  setDraft(Number(event.target.closest(".row").dataset.number), { note: event.target.value });
});
$("topics").addEventListener("focusin", (event) => {
  const row = event.target.closest(".row");
  if (row && Number(row.dataset.number) !== number) focusRow(Number(row.dataset.number));
});

// ---- Shared editing and saving ----
function afterEdit(n) {
  if (view === "single") {
    if (n === number) renderActions();
    renderItems();
  } else {
    updateRow(n);
    updateTopic(groupOf(saved(n)));
  }
}
function setDraft(n, patch, immediate = false) {
  const value = valueOf(n);
  if (!value || isLocked(value)) return;
  drafts.set(n, { action: value.action, note: value.note, ...patch });
  afterEdit(n);
  clearTimeout(timer);
  if (saveError) return;
  saveStatus("Unsaved changes…");
  if (immediate) flush().catch(() => {});
  else timer = setTimeout(() => flush().catch(() => {}), 450);
}
async function openSession(id) {
  const next = await api("/api/session?id=" + encodeURIComponent(id));
  current = next;
  drafts.clear();
  saveError = null;
  notesOpen.clear();
  contextOpen.clear();
  next.data.items.forEach((value, i) => value.note.trim() && notesOpen.add(i + 1));
  try {
    folded = new Set(JSON.parse(storage(foldKey()) || "[]"));
  } catch {
    folded = new Set();
  }
  number = next.data.items.length ? 1 : 0;
  $("session-title").textContent = next.data.title;
  $("session-path").textContent = next.path;
  $("scope").textContent = next.data.scope;
  $("handoff").disabled = false;
  $("export").disabled = false;
  $("view-toggle").disabled = false;
  for (const id of ["search", "c-search"]) $(id).value = "";
  for (const id of ["filter", "c-filter"]) $(id).value = "all";
  saveStatus("All changes saved");
  renderView();
  updateSummary();
}
async function flush() {
  clearTimeout(timer);
  if (saving) return saving;
  if (saveError) throw saveError;
  if (!dirtyNumbers().length) return;
  saving = (async () => {
    let n;
    while ((n = dirtyNumbers()[0]) !== undefined) {
      const draft = drafts.get(n);
      saveStatus("Saving…");
      try {
        current = await api("/api/session", {
          id: current.id,
          revision: current.revision,
          number: n,
          action: draft.action,
          note: draft.note,
        });
      } catch (error) {
        saveError = error;
        saveStatus(`Not saved — ${error.message} Your edits remain in this page.`, true);
        throw error;
      }
      for (const key of [...drafts.keys()]) if (!isDirty(key)) drafts.delete(key);
      updateSummary();
      afterEdit(n);
    }
    saveStatus("All changes saved");
  })();
  try {
    await saving;
  } finally {
    saving = null;
  }
}
async function navigate(action) {
  if (navigating) return;
  navigating = true;
  $("decision-fields").disabled = true;
  try {
    await flush();
    await action();
  } catch (error) {
    notice(`Could not continue: ${error.message}`);
  } finally {
    navigating = false;
    $("decision-fields").disabled = !item() || isLocked(item());
  }
}
function renderView() {
  $("compact").hidden = view !== "compact";
  $("single").hidden = view !== "single";
  $("view-toggle").textContent = view === "compact" ? "One at a time" : "Compact list";
  if (view === "compact") {
    renderCompact();
    rowOf(number)?.scrollIntoView({ block: "nearest" });
  } else {
    renderEditor();
    renderItems();
  }
}
function switchView() {
  if (!current) return;
  navigate(async () => {
    const [from, to] = view === "compact" ? ["c-", ""] : ["", "c-"];
    $(to + "search").value = $(from + "search").value;
    $(to + "filter").value = $(from + "filter").value;
    view = view === "compact" ? "single" : "compact";
    storage(VIEW_KEY, view);
    renderView();
  });
}
async function refresh() {
  const data = await api("/api/sessions");
  catalog = data.sessions;
  $("session-errors").textContent = data.errors
    .map((e) => `${e.path}: ${e.error}`)
    .join("\n");
  renderSessions();
  if (!current && catalog.length) await openSession(catalog[0].id);
}
$("search").addEventListener("input", renderItems);
$("filter").addEventListener("change", renderItems);
$("c-search").addEventListener("input", renderCompact);
$("c-filter").addEventListener("change", renderCompact);
$("view-toggle").addEventListener("click", switchView);
$("note").addEventListener("input", () => setDraft(number, { note: $("note").value }));
$("custom-action").addEventListener("input", () => setDraft(number, { action: $("custom-action").value }));
$("actions").addEventListener("click", (event) => {
  const button = event.target.closest("[data-action]");
  if (!button) return;
  $("custom-action").value = button.dataset.action;
  $("changed-flag").hidden = true;
  setDraft(number, { action: button.dataset.action }, true);
});
function accept(n = number) {
  const value = valueOf(n);
  if (!value?.recommended_action || isLocked(value) || value.action === value.recommended_action) return;
  if (view === "single") {
    $("custom-action").value = value.recommended_action;
    $("changed-flag").hidden = true;
  }
  setDraft(n, { action: value.recommended_action }, true);
}
$("accept").addEventListener("click", () => accept());
$("thread-earlier").addEventListener("click", () => item() && renderThread(item(), true));
$("refresh").addEventListener("click", () => navigate(refresh));
document.querySelectorAll(".retry").forEach((button) =>
  button.addEventListener("click", () => {
    saveError = null;
    flush().catch(() => {});
  }),
);
document.querySelectorAll(".reload").forEach((button) =>
  button.addEventListener("click", async () => {
    if (
      !confirm(
        "Discard your unsaved draft and load the current saved session? Copy any notes you want to keep before continuing.",
      )
    )
      return;
    try {
      await openSession(current.id);
    } catch (error) {
      notice(error.message);
    }
  }),
);
function showDialog(heading, help, text, download) {
  $("handoff-heading").textContent = heading;
  $("handoff-help").textContent = help;
  $("handoff-text").value = text;
  $("download-handoff").hidden = !download;
  $("copy-handoff").textContent = download ? "Copy export" : "Copy request";
  $("handoff-dialog").showModal();
}
function openExport() {
  if (!current) return;
  navigate(async () => {
    const result = await api("/api/export?id=" + encodeURIComponent(current.id));
    showDialog(
      "Export this session.",
      "Markdown with a fenced JSON payload, grouped by topic. Paste it back to your agent; answers that just accept the recommendation are listed separately.",
      result.text,
      true,
    );
  });
}
$("export").addEventListener("click", openExport);
$("download-handoff").addEventListener("click", () => {
  const link = document.createElement("a");
  link.href = URL.createObjectURL(
    new Blob([$("handoff-text").value], { type: "text/markdown" }),
  );
  const stamp = new Date().toISOString().replace(/[:.]/g, "-");
  link.download = `mgmt-export-${stamp}.md`;
  document.body.append(link);
  link.click();
  setTimeout(() => {
    URL.revokeObjectURL(link.href);
    link.remove();
  }, 1000);
});
// Visible rows of either view, in screen order (folded topics excluded).
function visibleNumbers() {
  const selector = view === "compact" ? ".topic:not(.folded) .row" : ".item-button";
  return [...document.querySelectorAll(selector)].map((el) => Number(el.dataset.number));
}
function moveTo(n) {
  if (view === "compact") focusRow(n, true);
  else {
    const button = $("items").querySelector(`.item-button[data-number="${n}"]`);
    button.click();
    button.scrollIntoView({ block: "nearest" });
  }
}
function step(delta, undecidedOnly = false) {
  const numbers = visibleNumbers();
  if (!numbers.length) return;
  // Screen order of every row, so a focused row that is folded or filtered out still has a place.
  const order =
    view === "compact"
      ? [...document.querySelectorAll(".row")].map((el) => Number(el.dataset.number))
      : current.data.items.map((_, i) => i + 1);
  const at = order.indexOf(number);
  const ahead = numbers.filter((n) => (delta > 0 ? order.indexOf(n) > at : order.indexOf(n) < at));
  if (delta < 0) ahead.reverse();
  const next = ahead.find((n) => !undecidedOnly || !valueOf(n).action);
  if (next !== undefined) moveTo(next);
  else if (undecidedOnly) notice("No undecided item further down. Try the Undecided filter.");
}
function pick(action) {
  if (view === "single") $("custom-action").value = action;
  setDraft(number, { action }, true);
}
const typing = (target) =>
  target.tagName === "TEXTAREA" ||
  target.tagName === "SELECT" ||
  (target.tagName === "INPUT" && target.type !== "checkbox");
document.addEventListener("keydown", (event) => {
  const target = event.target;
  if (typing(target)) {
    if (event.key === "Escape") target.blur();
    return;
  }
  if ($("handoff-dialog").open || event.metaKey || event.ctrlKey || event.altKey)
    return;
  const value = item();
  const actions = actionsFor();
  const compact = view === "compact";
  if (event.key === "j") step(1);
  else if (event.key === "k") step(-1);
  else if (event.key === "u") step(1, true);
  else if (event.key === "a") accept();
  else if (event.key === "e") openExport();
  else if (event.key === "v") switchView();
  else if (event.key === "i" && value) compact ? toggleNotes(number, true) : $("note").focus();
  else if (event.key === "n" && value) compact ? toggleNotes(number) : $("note").focus();
  else if (event.key === "x" && value && compact) toggleContext(number);
  else if (event.key === "z" && value && compact) toggleFold(groupOf(value));
  else if (event.key === "?" && value && askOn() && !isLocked(value)) {
    pick(ASK);
    if (compact) toggleNotes(number, true);
    else $("note").focus();
  } else if (/^[1-9]$/.test(event.key) && value && !isLocked(value)) {
    const action = actions[Number(event.key) - 1];
    if (action === undefined) return;
    pick(action);
  } else return;
  event.preventDefault();
});
$("handoff").addEventListener("click", () =>
  navigate(async () => {
    const selected = catalog.filter((s) => s.selected > s.done);
    showDialog(
      "Ready when you are.",
      "Copy this request to your assistant. It authorizes the selected actions; opening this dialog does not execute them.",
      selected.length
        ? "Apply the selected actions in these mgmt sessions. Respect each item’s notes, preserve unselected items, verify actual effects, and record per-item results:\n\n" +
            selected.map((s) => s.path).join("\n")
        : "No unfinished decisions selected yet. Choose actions on the items you want your assistant to handle.",
      false,
    );
  }),
);
$("close-handoff").addEventListener("click", () => $("handoff-dialog").close());
$("copy-handoff").addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText($("handoff-text").value);
    notice("Copied. Paste it into your assistant when ready.");
  } catch {
    $("handoff-text").focus();
    $("handoff-text").select();
    notice("Select and copy the request manually.");
  }
});
window.addEventListener("beforeunload", (event) => {
  if (dirtyNumbers().length || saving) {
    event.preventDefault();
    event.returnValue = "";
  }
});
$("compact").hidden = view !== "compact";
$("single").hidden = view !== "single";
refresh().catch((error) => {
  $("session-errors").textContent = error.message;
  notice("Could not load sessions. Use Refresh to try again.");
});
