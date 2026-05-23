/* ── Forever AI — Frontend JS ──────────────────────────────────────── */

// ── Panel switching ─────────────────────────────────────────────────────

document.querySelectorAll(".nav-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    const target = btn.dataset.panel;
    document.querySelectorAll(".nav-btn").forEach(b => b.classList.remove("active"));
    document.querySelectorAll(".panel").forEach(p => p.classList.remove("active"));
    btn.classList.add("active");
    document.getElementById(`panel-${target}`).classList.add("active");
    if (target === "notes") loadNotes();
  });
});


// ── Status bar ──────────────────────────────────────────────────────────

function setStatus(msg, color = "#7b82a0") {
  const bar = document.getElementById("status-bar");
  bar.textContent = msg;
  bar.style.color = color;
}


// ── Markdown renderer (minimal, no deps) ───────────────────────────────

function renderMarkdown(text) {
  text = text.replace(/```[\w]*\n([\s\S]*?)```/g, (_, code) =>
    `<pre><code>${escHtml(code.trimEnd())}</code></pre>`);
  text = text.replace(/`([^`]+)`/g, (_, c) => `<code>${escHtml(c)}</code>`);
  text = text.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
  text = text.replace(/\*(.+?)\*/g, "<em>$1</em>");
  text = text.replace(/^### (.+)$/gm, "<h4>$1</h4>");
  text = text.replace(/^## (.+)$/gm,  "<h3>$1</h3>");
  text = text.replace(/^# (.+)$/gm,   "<h2>$1</h2>");
  text = text.replace(/^[\*\-] (.+)$/gm, "<li>$1</li>");
  text = text.replace(/(<li>.*<\/li>)/s, "<ul>$1</ul>");
  text = text.replace(/\n\n/g, "<br/><br/>");
  text = text.replace(/(?<!>)\n(?!<)/g, "<br/>");
  return text;
}

function escHtml(s) {
  return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;")
                  .replace(/>/g,"&gt;").replace(/"/g,"&quot;");
}


// ── Chat ────────────────────────────────────────────────────────────────

const messagesEl = document.getElementById("messages");
const chatForm   = document.getElementById("chat-form");
const chatInput  = document.getElementById("chat-input");
const sendBtn    = chatForm.querySelector(".send-btn");

function addMessage(role, content) {
  const div    = document.createElement("div");
  div.className = `message ${role}`;
  const bubble  = document.createElement("div");
  bubble.className = "bubble";
  if (role === "assistant") bubble.innerHTML = renderMarkdown(content);
  else bubble.textContent = content;
  div.appendChild(bubble);
  messagesEl.appendChild(div);
  messagesEl.scrollTop = messagesEl.scrollHeight;
  return div;
}

function addTypingIndicator() {
  const div = document.createElement("div");
  div.className = "message assistant";
  div.id = "typing";
  div.innerHTML = `<div class="bubble typing-indicator"><span></span><span></span><span></span></div>`;
  messagesEl.appendChild(div);
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function removeTypingIndicator() {
  const el = document.getElementById("typing");
  if (el) el.remove();
}

chatInput.addEventListener("input", () => {
  chatInput.style.height = "auto";
  chatInput.style.height = Math.min(chatInput.scrollHeight, 180) + "px";
});

chatInput.addEventListener("keydown", e => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    chatForm.dispatchEvent(new Event("submit"));
  }
});

chatForm.addEventListener("submit", async e => {
  e.preventDefault();
  const message = chatInput.value.trim();
  if (!message) return;
  chatInput.value = "";
  chatInput.style.height = "auto";
  sendBtn.disabled = true;
  addMessage("user", message);
  addTypingIndicator();
  setStatus("Thinking…");
  try {
    const res  = await fetch("/api/chat", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message }),
    });
    removeTypingIndicator();
    if (!res.ok) {
      const text = await res.text();
      addMessage("assistant", `⚠️ Server error ${res.status}: ${text.slice(0, 200)}`);
      setStatus("Error", "#e05555");
    } else {
      const data = await res.json();
      if (data.error) { addMessage("assistant", `⚠️ Error: ${data.error}`); setStatus("Error", "#e05555"); }
      else            { addMessage("assistant", data.reply); setStatus(""); }
    }
  } catch (err) {
    removeTypingIndicator();
    addMessage("assistant", `⚠️ Could not reach the server: ${err.message || err}`);
    setStatus("Offline", "#e05555");
  } finally {
    sendBtn.disabled = false;
    chatInput.focus();
  }
});


// ── Reset / Reindex buttons ─────────────────────────────────────────────

document.getElementById("btn-reset").addEventListener("click", async () => {
  await fetch("/api/reset", { method: "POST" });
  messagesEl.innerHTML = "";
  addMessage("assistant", "Conversation cleared. Your vault memory is still intact.");
  setStatus("Conversation reset", "#4caf78");
  setTimeout(() => setStatus(""), 2000);
});

document.getElementById("btn-reindex").addEventListener("click", async () => {
  setStatus("Reindexing…");
  try {
    const res  = await fetch("/api/reindex", { method: "POST" });
    const data = await res.json();
    if (data.error) {
      setStatus(`Error: ${data.error}`, "#e05555");
    } else {
      const detail = data.notes != null
        ? `${data.notes} notes, ${data.chunks} chunks`
        : `${data.files} files, ${data.chunks} chunks`;
      setStatus(`Indexed: ${detail}`, "#4caf78");
      setTimeout(() => setStatus(""), 3000);
    }
  } catch { setStatus("Reindex failed", "#e05555"); }
});


// ── Notes ────────────────────────────────────────────────────────────────

let _currentNoteId = null;
let _notes = [];

async function loadNotes(folderFilter) {
  const url = folderFilter ? `/api/notes?folder=${encodeURIComponent(folderFilter)}` : "/api/notes";
  try {
    const res = await fetch(url);
    if (!res.ok) {
      // Notes API might return 400 in local mode — silently skip
      return;
    }
    _notes = await res.json();
    renderNotesList(_notes);
    await loadFolderFilter();
  } catch { /* silently skip in local mode */ }
}

async function loadFolderFilter() {
  try {
    const res = await fetch("/api/notes/folders");
    if (!res.ok) return;
    const folders = await res.json();
    const sel = document.getElementById("folder-filter");
    const current = sel.value;
    sel.innerHTML = '<option value="">All folders</option>';
    folders.forEach(f => {
      const opt = document.createElement("option");
      opt.value = f; opt.textContent = f;
      if (f === current) opt.selected = true;
      sel.appendChild(opt);
    });
  } catch {}
}

function renderNotesList(notes) {
  const ul = document.getElementById("notes-list");
  ul.innerHTML = "";
  if (!notes.length) {
    ul.innerHTML = '<li style="color:var(--text-dim);font-size:12px;text-align:center;padding:16px">No notes yet.<br/>Click "+ New Note" to start.</li>';
    return;
  }
  notes.forEach(note => {
    const li = document.createElement("li");
    if (note.id === _currentNoteId) li.classList.add("active");
    li.innerHTML = `<span class="note-item-title">${escHtml(note.title)}</span>
                    <span class="note-item-folder">${escHtml(note.folder)}</span>`;
    li.addEventListener("click", () => openNote(note.id));
    ul.appendChild(li);
  });
}

async function openNote(noteId) {
  try {
    const res  = await fetch(`/api/notes/${noteId}`);
    if (!res.ok) return;
    const note = await res.json();
    _currentNoteId = note.id;
    document.getElementById("note-title").value   = note.title   || "";
    document.getElementById("note-folder").value  = note.folder  || "general";
    document.getElementById("note-tags").value    = note.tags    || "";
    document.getElementById("note-content").value = note.content || "";
    document.getElementById("note-placeholder").classList.add("hidden");
    document.getElementById("note-form").classList.remove("hidden");
    document.getElementById("note-save-status").textContent = "";
    // Highlight active in list
    document.querySelectorAll("#notes-list li").forEach(li => li.classList.remove("active"));
    document.querySelectorAll("#notes-list li").forEach(li => {
      const t = li.querySelector(".note-item-title");
      const note_item = _notes.find(n => n.id === noteId);
      if (note_item && t && t.textContent === note_item.title) li.classList.add("active");
    });
  } catch {}
}

document.getElementById("btn-new-note").addEventListener("click", () => {
  _currentNoteId = null;
  document.getElementById("note-title").value   = "";
  document.getElementById("note-folder").value  = "general";
  document.getElementById("note-tags").value    = "";
  document.getElementById("note-content").value = "";
  document.getElementById("note-save-status").textContent = "";
  document.getElementById("note-placeholder").classList.add("hidden");
  document.getElementById("note-form").classList.remove("hidden");
  document.getElementById("note-title").focus();
  document.querySelectorAll("#notes-list li").forEach(li => li.classList.remove("active"));
});

document.getElementById("btn-save-note").addEventListener("click", async () => {
  const title   = document.getElementById("note-title").value.trim() || "Untitled";
  const folder  = document.getElementById("note-folder").value.trim() || "general";
  const tags    = document.getElementById("note-tags").value.trim();
  const content = document.getElementById("note-content").value;
  const statusEl = document.getElementById("note-save-status");

  statusEl.textContent = "Saving…";
  statusEl.style.color = "var(--text-dim)";

  try {
    let res;
    if (_currentNoteId) {
      res = await fetch(`/api/notes/${_currentNoteId}`, {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title, folder, tags, content }),
      });
    } else {
      res = await fetch("/api/notes", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title, folder, tags, content }),
      });
    }
    const note = await res.json();
    if (!res.ok) { statusEl.textContent = note.error || "Save failed"; statusEl.style.color = "#e05555"; return; }
    _currentNoteId = note.id;
    statusEl.textContent = "Saved ✓";
    statusEl.style.color = "#4caf78";
    setTimeout(() => { statusEl.textContent = ""; }, 2000);
    await loadNotes(document.getElementById("folder-filter").value || undefined);
  } catch { statusEl.textContent = "Save failed"; statusEl.style.color = "#e05555"; }
});

document.getElementById("btn-delete-note").addEventListener("click", async () => {
  if (!_currentNoteId) return;
  if (!confirm("Delete this note? This cannot be undone.")) return;
  try {
    const res = await fetch(`/api/notes/${_currentNoteId}`, { method: "DELETE" });
    if (res.ok) {
      _currentNoteId = null;
      document.getElementById("note-placeholder").classList.remove("hidden");
      document.getElementById("note-form").classList.add("hidden");
      await loadNotes(document.getElementById("folder-filter").value || undefined);
    }
  } catch {}
});

document.getElementById("folder-filter").addEventListener("change", e => {
  loadNotes(e.target.value || undefined);
});


// ── Search panel ────────────────────────────────────────────────────────

async function doSearch() {
  const q = document.getElementById("search-input").value.trim();
  if (!q) return;
  const resultsEl = document.getElementById("search-results");
  resultsEl.innerHTML = "<p style='color:#7b82a0'>Searching…</p>";
  try {
    const res  = await fetch(`/api/search?q=${encodeURIComponent(q)}&k=8`);
    const data = await res.json();
    if (!data.length) { resultsEl.innerHTML = "<p style='color:#7b82a0'>No matching notes found.</p>"; return; }
    resultsEl.innerHTML = data.map(c => `
      <div class="result-card">
        <div class="result-header">
          <span class="result-title">${escHtml(c.title)}</span>
          <span class="result-source">${escHtml(c.source)}</span>
          <span class="result-score">score ${c.score.toFixed(2)}</span>
        </div>
        <div class="result-text">${escHtml(c.text.slice(0, 300))}${c.text.length > 300 ? "…" : ""}</div>
        ${c.tags ? `<div class="result-tags">${escHtml(c.tags)}</div>` : ""}
      </div>
    `).join("");
  } catch { resultsEl.innerHTML = "<p style='color:#e05555'>Search request failed.</p>"; }
}

document.getElementById("search-btn").addEventListener("click", doSearch);
document.getElementById("search-input").addEventListener("keydown", e => {
  if (e.key === "Enter") doSearch();
});
