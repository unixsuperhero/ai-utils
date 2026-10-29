"use strict";
const $ = (id) => document.getElementById(id);
const token = document.querySelector('meta[name="mgmt-token"]').content;
let catalog = [],
  current = null,
  number = 0,
  draft = null;
let timer,
  saving = null,
  saveError = null,
  navigating = false,
  noticeTimer;
const DEFAULT_ACTIONS = ["remove", "keep", "revise"];
const isLocked = (item) => ["applying", "done"].includes(item.status);
const actionsFor = () => current?.data.actions || DEFAULT_ACTIONS;
const label = (action) => action.charAt(0).toUpperCase() + action.slice(1);
const item = () => current?.data.items[number - 1];
const dirty = () =>
  draft &&
  item() &&
  (draft.action !== item().action || draft.note !== item().note);

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
  $("save-state").textContent = text;
  $("save-state").parentElement.classList.toggle("error", error);
  $("retry").hidden = !error || saveError?.status === 409;
  $("reload").hidden = !error;
}
function updateSummary() {
  if (!current) return;
  const selected = current.data.items.filter((i) => i.action).length;
  $("session-summary").textContent =
    `${current.data.items.length} items · Select any item. Every decision is reversible until applied.`;
  $("progress").replaceChildren(
    document.createTextNode(`${selected} / ${current.data.items.length}`),
  );
  const caption = document.createElement("small");
  caption.textContent = "WITH DECISIONS";
  $("progress").append(caption);
  const entry = catalog.find((s) => s.id === current.id);
  if (entry) entry.selected = selected;
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
    count.textContent = `${session.selected}/${session.total}`;
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
function renderItems() {
  $("items").replaceChildren();
  if (!current) return;
  const query = $("search").value.toLowerCase().trim();
  const filter = $("filter").value;
  let shown = 0;
  current.data.items.forEach((saved, index) => {
    const value =
      index + 1 === number && draft ? { ...saved, ...draft } : saved;
    if (
      (filter === "selected" && !value.action) ||
      (filter === "unselected" && value.action) ||
      (filter === "locked" && !isLocked(value))
    )
      return;
    if (
      query &&
      ![value.title, value.details, value.source, value.note, value.action]
        .join("\n")
        .toLowerCase()
        .includes(query)
    )
      return;
    shown++;
    const button = document.createElement("button");
    button.className = "item-button" + (index + 1 === number ? " active" : "");
    button.dataset.number = index + 1;
    button.setAttribute(
      "aria-current",
      index + 1 === number ? "true" : "false",
    );
    const label = document.createElement("span");
    label.className = "number";
    label.textContent = String(index + 1).padStart(2, "0");
    const body = document.createElement("span");
    const title = document.createElement("span");
    title.className = "title";
    title.textContent = value.title;
    const meta = document.createElement("span");
    meta.className =
      "item-meta" + (value.action === "remove" ? " remove-label" : "");
    meta.textContent = [
      value.action ||
        (value.recommended_action
          ? `undecided · rec. ${value.recommended_action}`
          : "undecided"),
      value.action && value.action === value.recommended_action
        ? "as recommended"
        : "",
      value.context_changed ? "context changed" : "",
      value.note ? "note" : "",
      isLocked(value)
        ? value.status + " · locked"
        : value.status === "failed"
          ? "failed"
          : "",
    ]
      .filter(Boolean)
      .join(" · ");
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
  $("visible-count").textContent = `${shown} shown`;
  if (!shown) {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent = "No matching items. Try another search or filter.";
    $("items").append(empty);
  }
}
function renderActionButtons(value) {
  const buttons = [...actionsFor(), ""].map((action) => {
    const button = document.createElement("button");
    button.type = "button";
    button.dataset.action = action;
    const index = actionsFor().indexOf(action);
    button.textContent = action ? label(action) : "Clear";
    if (action && index < 9) button.title = `Key ${index + 1}`;
    if (action === "remove") button.className = "remove";
    if (!action) button.className = "clear";
    if (action && action === value.recommended_action)
      button.classList.add("recommended");
    return button;
  });
  $("actions").replaceChildren(...buttons);
}
function renderActions() {
  document
    .querySelectorAll("[data-action]")
    .forEach((button) =>
      button.setAttribute(
        "aria-pressed",
        String(button.dataset.action === draft?.action),
      ),
    );
  const value = item();
  const rec = value?.recommended_action;
  const taken = Boolean(rec) && draft?.action === rec;
  $("recommendation").classList.toggle("accepted", taken);
  $("recommendation-state").textContent = taken
    ? `RECOMMENDED · ${rec.toUpperCase()} · ACCEPTED`
    : `RECOMMENDED · ${(rec || "").toUpperCase()} · NOT CONFIRMED`;
  $("accept").hidden = taken;
}
function accept() {
  const value = item();
  if (!value?.recommended_action || isLocked(value)) return;
  if (draft?.action === value.recommended_action) return;
  $("custom-action").value = value.recommended_action;
  changed(true);
}
function renderEditor() {
  const value = item();
  $("empty-detail").hidden = Boolean(value);
  $("editor").hidden = !value;
  if (!value) {
    draft = null;
    return;
  }
  draft = { action: value.action, note: value.note };
  saveError = null;
  $("item-number").textContent = `ITEM ${String(number).padStart(2, "0")}`;
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
  $("changed-flag").hidden = !value.context_changed;
  $("recommendation").hidden = !value.recommendation;
  $("recommendation-text").textContent = value.recommendation || "";
  $("accept").disabled = isLocked(value);
  renderActionButtons(value);
  renderActions();
  saveStatus(
    isLocked(value)
      ? "Locked while active or completed. Start a new session for further changes."
      : "All changes saved",
  );
  $("detail").scrollTop = 0;
}
async function openSession(id) {
  const next = await api("/api/session?id=" + encodeURIComponent(id));
  current = next;
  number = next.data.items.length ? 1 : 0;
  $("session-title").textContent = next.data.title;
  $("session-path").textContent = next.path;
  $("scope").textContent = next.data.scope;
  $("handoff").disabled = false;
  $("export").disabled = false;
  $("search").value = "";
  $("filter").value = "all";
  renderEditor();
  renderItems();
  updateSummary();
}
async function flush() {
  clearTimeout(timer);
  if (saving) return saving;
  if (saveError) throw saveError;
  if (!dirty()) return;
  saving = (async () => {
    while (dirty()) {
      const payload = {
        id: current.id,
        revision: current.revision,
        number,
        ...draft,
      };
      saveStatus("Saving…");
      try {
        current = await api("/api/session", payload);
        updateSummary();
        renderItems();
      } catch (error) {
        saveError = error;
        saveStatus(
          `Not saved — ${error.message} Your edits remain in this page.`,
          true,
        );
        throw error;
      }
    }
    saveStatus("All changes saved");
  })();
  try {
    await saving;
  } finally {
    saving = null;
  }
}
function changed(immediate = false) {
  draft = { action: $("custom-action").value, note: $("note").value };
  renderActions();
  $("changed-flag").hidden = true;
  renderItems();
  clearTimeout(timer);
  if (saveError) return;
  saveStatus("Unsaved changes…");
  if (immediate) flush().catch(() => {});
  else timer = setTimeout(() => flush().catch(() => {}), 450);
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
$("note").addEventListener("input", () => changed());
$("custom-action").addEventListener("input", () => changed());
$("actions").addEventListener("click", (event) => {
  const button = event.target.closest("[data-action]");
  if (!button) return;
  $("custom-action").value = button.dataset.action;
  changed(true);
});
$("accept").addEventListener("click", accept);
$("refresh").addEventListener("click", () => navigate(refresh));
$("retry").addEventListener("click", () => {
  saveError = null;
  flush().catch(() => {});
});
$("reload").addEventListener("click", async () => {
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
});
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
      "Markdown with a fenced JSON payload. Paste it back to your agent; answers that just accept the recommendation are listed separately.",
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
function step(delta, undecidedOnly = false) {
  const buttons = [...$("items").querySelectorAll(".item-button")];
  if (!buttons.length) return;
  let index = buttons.findIndex((b) => Number(b.dataset.number) === number);
  for (let tries = 0; tries < buttons.length; tries++) {
    index = Math.min(buttons.length - 1, Math.max(0, index + delta));
    const candidate = current.data.items[Number(buttons[index].dataset.number) - 1];
    if (!undecidedOnly || !candidate.action) {
      buttons[index].click();
      buttons[index].scrollIntoView({ block: "nearest" });
      return;
    }
    if (index === 0 || index === buttons.length - 1) break;
  }
  notice("No undecided item further down. Try the Undecided filter.");
}
document.addEventListener("keydown", (event) => {
  const target = event.target;
  if (["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName)) {
    if (event.key === "Escape") target.blur();
    return;
  }
  if ($("handoff-dialog").open || event.metaKey || event.ctrlKey || event.altKey)
    return;
  const value = item();
  const actions = actionsFor();
  if (event.key === "j") step(1);
  else if (event.key === "k") step(-1);
  else if (event.key === "u") step(1, true);
  else if (event.key === "a") accept();
  else if (event.key === "e") openExport();
  else if (event.key === "i" && value) $("note").focus();
  else if (/^[1-9]$/.test(event.key) && value && !isLocked(value)) {
    const action = actions[Number(event.key) - 1];
    if (action === undefined) return;
    $("custom-action").value = action;
    changed(true);
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
  if (dirty() || saving) {
    event.preventDefault();
    event.returnValue = "";
  }
});
refresh().catch((error) => {
  $("session-errors").textContent = error.message;
  notice("Could not load sessions. Use Refresh to try again.");
});
