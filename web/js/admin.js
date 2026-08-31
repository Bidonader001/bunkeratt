const CAPTURES = 5;
const PROMPTS = [
  "Look straight at the camera.",
  "Turn a little to the left.",
  "Turn a little to the right.",
  "Look slightly up.",
  "Look straight again.",
];

const pages = document.querySelectorAll(".page");
const navBtns = document.querySelectorAll(".nav-btn[data-page]");
const video = document.getElementById("enroll-video");
const canvas = document.getElementById("work-canvas");
const dotsEl = document.getElementById("enroll-dots");
const countEl = document.getElementById("enroll-count");
const statusEl = document.getElementById("enroll-status");
const btnAuto = document.getElementById("btn-auto");
const btnStop = document.getElementById("btn-stop");
const successEl = document.getElementById("enroll-success");
const shiftSelect = document.getElementById("enroll-shift");
const loginScreen = document.getElementById("login-screen");
const appShell = document.getElementById("app-shell");

let stream = null;
let captures = [];
let autoTimer = null;
let autoBusy = false;
let running = false;
let editingId = null;
let currentRole = "admin";

function renderDots() {
  dotsEl.innerHTML = "";
  for (let i = 0; i < CAPTURES; i += 1) {
    const s = document.createElement("span");
    if (i < captures.length) s.classList.add("on");
    dotsEl.appendChild(s);
  }
  countEl.textContent = `${captures.length} / ${CAPTURES}`;
}

function applyRole(role) {
  currentRole = role === "super" ? "super" : "admin";
  document.body.classList.toggle("is-super", currentRole === "super");
}

function showApp(ok) {
  loginScreen.classList.toggle("hidden", ok);
  appShell.classList.toggle("hidden", !ok);
}

async function ensureAuth() {
  const token = localStorage.getItem("access_pass_token");
  if (!token) {
    showApp(false);
    return false;
  }
  try {
    const me = await api("/auth/me");
    applyRole(me.role);
    showApp(true);
    return true;
  } catch {
    localStorage.removeItem("access_pass_token");
    showApp(false);
    return false;
  }
}

document.getElementById("login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const status = document.getElementById("login-status");
  status.textContent = "";
  try {
    const data = await api("/auth/login", {
      method: "POST",
      body: JSON.stringify({
        username: document.getElementById("login-user").value.trim(),
        password: document.getElementById("login-pass").value,
      }),
    });
    localStorage.setItem("access_pass_token", data.token);
    applyRole(data.role);
    showApp(true);
    showPage("register");
  } catch (err) {
    status.textContent = err.message;
  }
});

document.getElementById("btn-logout").addEventListener("click", () => {
  localStorage.removeItem("access_pass_token");
  stopAuto();
  stopStream(stream);
  showApp(false);
});

async function loadShiftsIntoSelect() {
  const shifts = await api("/shifts");
  shiftSelect.innerHTML =
    `<option value="">Auto at clock-in</option>` +
    shifts.map((s) => `<option value="${s.id}">${s.name}  ${s.start_time}–${s.end_time}</option>`).join("");
  return shifts;
}

async function showPage(key) {
  pages.forEach((p) => p.classList.toggle("active", p.id === `page-${key}`));
  navBtns.forEach((b) => b.classList.toggle("active", b.dataset.page === key));
  stopAuto();
  stopStream(stream);
  stream = null;
  if (video) video.srcObject = null;

  if (key === "register") {
    await loadShiftsIntoSelect();
    try {
      stream = await startCamera(video);
      statusEl.textContent = editingId
        ? "Save details, or start auto capture to replace the face."
        : "Face the camera and start auto capture. Dim light is OK.";
    } catch (e) {
      statusEl.textContent = `${e.message} Tap START AUTO CAPTURE to allow the camera.`;
    }
  }
  if (key === "people") loadPeople();
  if (key === "shifts") loadShiftList();
  if (key === "reports") loadReports();
  if (key === "admins") {
    if (currentRole !== "super") {
      showPage("register");
      return;
    }
    loadStaff();
  }
}

function setEditing(person) {
  editingId = person ? person.employee_id : null;
  document.getElementById("edit-banner").classList.toggle("hidden", !person);
  document.getElementById("btn-save-person").classList.toggle("hidden", !person);
  document.getElementById("btn-cancel-edit").classList.toggle("hidden", !person);
  if (!person) {
    document.getElementById("enroll-name").value = "";
    document.getElementById("enroll-id").value = "";
    shiftSelect.value = "";
    return;
  }
  document.getElementById("enroll-name").value = person.name;
  document.getElementById("enroll-id").value = person.employee_id;
  shiftSelect.value = person.shift_id != null ? String(person.shift_id) : "";
}

function stopAuto() {
  running = false;
  autoBusy = false;
  if (autoTimer) {
    clearInterval(autoTimer);
    autoTimer = null;
  }
  btnAuto.disabled = false;
  btnStop.disabled = true;
}

async function captureOnce() {
  if (!running || autoBusy || captures.length >= CAPTURES || !video.videoWidth) return;
  autoBusy = true;
  try {
    const image_b64 = frameToB64(canvas, video, 720, 0.9);
    const previous_b64 = captures.length ? captures[captures.length - 1] : null;
    await api("/captures/validate", {
      method: "POST",
      body: JSON.stringify({ image_b64, previous_b64 }),
    });
    captures.push(image_b64);
    renderDots();
    const next = captures.length;
    if (next < CAPTURES) {
      const line = PROMPTS[next] || "Hold still.";
      statusEl.textContent = line;
      speak(line);
    } else {
      statusEl.textContent = "Saving…";
      speak("All captures taken. Saving.");
      await issuePass();
    }
  } catch (e) {
    statusEl.textContent = e.message;
  } finally {
    autoBusy = false;
  }
}

function personPayload(includeFace) {
  const name = document.getElementById("enroll-name").value.trim();
  const employee_id = document.getElementById("enroll-id").value.trim();
  const rawShift = shiftSelect.value;
  const shift_id = rawShift ? Number(rawShift) : null;
  const body = { name, employee_id, shift_id };
  if (includeFace) body.images_b64 = captures;
  return body;
}

async function issuePass() {
  const body = personPayload(true);
  try {
    if (editingId) {
      await api(`/passes/${encodeURIComponent(editingId)}`, {
        method: "PATCH",
        body: JSON.stringify({
          name: body.name,
          new_employee_id: body.employee_id,
          shift_id: body.shift_id,
          images_b64: captures,
        }),
      });
      successEl.textContent = "✓ EMPLOYEE UPDATED";
      speak(`${body.name} is updated.`);
      setEditing(null);
    } else {
      await api("/passes/enroll", {
        method: "POST",
        body: JSON.stringify(body),
      });
      successEl.textContent = "✓ EMPLOYEE REGISTERED";
      speak(`${body.name} is registered.`);
    }
    successEl.classList.remove("hidden");
    captures = [];
    renderDots();
    document.getElementById("enroll-name").value = "";
    document.getElementById("enroll-id").value = "";
    shiftSelect.value = "";
    stopAuto();
    setTimeout(() => successEl.classList.add("hidden"), 2500);
  } catch (e) {
    statusEl.textContent = e.message;
    speak(e.message);
    stopAuto();
  }
}

btnAuto.addEventListener("click", async () => {
  const name = document.getElementById("enroll-name").value.trim();
  const employee_id = document.getElementById("enroll-id").value.trim();
  if (!name || !employee_id) {
    statusEl.textContent = "Enter name and employee ID first.";
    return;
  }
  try {
    unlockSpeech();
    if (!stream) stream = await startCamera(video);
  } catch (e) {
    statusEl.textContent = e.message;
    return;
  }
  captures = [];
  renderDots();
  running = true;
  btnAuto.disabled = true;
  btnStop.disabled = false;
  const line = PROMPTS[0];
  statusEl.textContent = line;
  speak(`Hello ${name}. ${line}`);
  autoTimer = setInterval(captureOnce, 1600);
});

document.getElementById("btn-save-person").addEventListener("click", async () => {
  if (!editingId) return;
  const body = personPayload(false);
  if (!body.name || !body.employee_id) {
    statusEl.textContent = "Name and employee ID are required.";
    return;
  }
  try {
    await api(`/passes/${encodeURIComponent(editingId)}`, {
      method: "PATCH",
      body: JSON.stringify({
        name: body.name,
        new_employee_id: body.employee_id,
        shift_id: body.shift_id,
      }),
    });
    successEl.textContent = "✓ EMPLOYEE UPDATED";
    successEl.classList.remove("hidden");
    speak(`${body.name} is updated.`);
    setEditing(null);
    setTimeout(() => successEl.classList.add("hidden"), 2500);
  } catch (e) {
    statusEl.textContent = e.message;
  }
});

document.getElementById("btn-cancel-edit").addEventListener("click", () => {
  setEditing(null);
  captures = [];
  renderDots();
  statusEl.textContent = "Edit cancelled.";
});

btnStop.addEventListener("click", stopAuto);
navBtns.forEach((btn) => btn.addEventListener("click", () => showPage(btn.dataset.page)));

async function loadShiftList() {
  const list = document.getElementById("shift-list");
  const shifts = await api("/shifts");
  list.innerHTML = shifts
    .map(
      (s) => `<article class="log-row">
        <header>
          <span>${s.name}</span>
          <span class="granted-tag">${s.start_time} → ${s.end_time}</span>
        </header>
        <p class="muted">${s.end_time <= s.start_time ? "Overnight — same work date after midnight" : "Same calendar day"}</p>
        <button class="ghost small-del danger" data-del-shift="${s.id}" type="button">Delete</button>
      </article>`
    )
    .join("");
}

document.getElementById("shift-list").addEventListener("click", async (e) => {
  const btn = e.target.closest("[data-del-shift]");
  if (!btn) return;
  const id = btn.getAttribute("data-del-shift");
  if (!confirm("Delete this shift?")) return;
  try {
    await api(`/shifts/${id}`, { method: "DELETE" });
    document.getElementById("shift-status").textContent = "Shift deleted.";
    loadShiftList();
    loadShiftsIntoSelect();
  } catch (err) {
    document.getElementById("shift-status").textContent = err.message;
  }
});

document.getElementById("btn-add-shift").addEventListener("click", async () => {
  const name = document.getElementById("shift-name").value.trim();
  const start_time = document.getElementById("shift-start").value;
  const end_time = document.getElementById("shift-end").value;
  const status = document.getElementById("shift-status");
  try {
    await api("/shifts", {
      method: "POST",
      body: JSON.stringify({ name, start_time, end_time }),
    });
    status.textContent = "Shift added.";
    document.getElementById("shift-name").value = "";
    loadShiftList();
    loadShiftsIntoSelect();
  } catch (e) {
    status.textContent = e.message;
  }
});

function fmtTime(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

function reportQuery() {
  const dateEl = document.getElementById("report-date");
  if (!dateEl.value) dateEl.value = new Date().toISOString().slice(0, 10);
  const day = dateEl.value;
  const period = document.getElementById("report-period").value;
  const token = localStorage.getItem("access_pass_token") || "";
  return { day, period, token };
}

async function loadReports() {
  const { day, period, token } = reportQuery();
  const qs = `work_date=${day}&period=${period}&token=${encodeURIComponent(token)}`;
  document.getElementById("btn-pdf").href = `${API}/reports/pdf?${qs}`;
  document.getElementById("btn-xlsx").href = `${API}/reports/excel?${qs}`;
  const data = await api(`/reports?work_date=${day}&period=${period}`);
  document.getElementById("report-range").textContent = `${data.period} · ${data.date_from} to ${data.date_to}`;
  const body = document.getElementById("report-body");
  if (!data.rows.length) {
    body.innerHTML = `<tr><td colspan="7" class="muted">No sessions in this period.</td></tr>`;
    return;
  }
  body.innerHTML = data.rows
    .map((r) => {
      const cls =
        r.hours_status === "under"
          ? "hrs-under"
          : r.hours_status === "exact"
            ? "hrs-exact"
            : r.hours_status === "over"
              ? "hrs-over"
              : "";
      const lateCls = r.late ? " late-cell" : "";
      return `<tr class="${cls}${lateCls}">
        <td>${r.employee_name}</td>
        <td>${r.employee_id}</td>
        <td>${r.shift_name || "—"}</td>
        <td>${fmtTime(r.clock_in)}</td>
        <td>${r.clock_out ? fmtTime(r.clock_out) : "—"}</td>
        <td>${r.hours_formatted}</td>
        <td>${r.late_label || "On time"}</td>
      </tr>`;
    })
    .join("");
}

async function loadPeople() {
  const body = document.getElementById("people-body");
  const people = await api("/passes");
  if (!people.length) {
    body.innerHTML = `<tr><td colspan="4" class="muted">No employees yet.</td></tr>`;
    return;
  }
  body.innerHTML = people
    .map(
      (p) => `<tr>
        <td>${p.name}</td>
        <td>${p.employee_id}</td>
        <td>${p.shift_name || "Auto at clock-in"}</td>
        <td class="people-actions">
          <button class="ghost small-del" type="button" data-edit-person="${p.employee_id}">Edit</button>
          <button class="ghost small-del danger" type="button" data-del-person="${p.employee_id}">Delete</button>
        </td>
      </tr>`
    )
    .join("");
}

document.getElementById("people-body").addEventListener("click", async (e) => {
  const del = e.target.closest("[data-del-person]");
  const edit = e.target.closest("[data-edit-person]");
  const status = document.getElementById("people-status");
  if (del) {
    const id = del.getAttribute("data-del-person");
    if (!confirm(`Delete employee ${id}? This also removes their clock records.`)) return;
    try {
      await api(`/passes/${encodeURIComponent(id)}`, { method: "DELETE" });
      status.textContent = "Employee deleted.";
      loadPeople();
    } catch (err) {
      status.textContent = err.message;
    }
    return;
  }
  if (edit) {
    const id = edit.getAttribute("data-edit-person");
    const people = await api("/passes");
    const person = people.find((p) => p.employee_id === id);
    if (!person) return;
    await showPage("register");
    setEditing(person);
    statusEl.textContent = "Save details, or start auto capture to replace the face.";
  }
});

document.getElementById("report-date").addEventListener("change", loadReports);
document.getElementById("report-period").addEventListener("change", loadReports);

async function loadStaff() {
  const data = await api("/staff");
  document.getElementById("admin-quota").textContent =
    `${data.admins_used} of ${data.admins_max} admin seats used`;
  const body = document.getElementById("staff-body");
  body.innerHTML = data.users
    .map((u) => {
      const role = u.role === "super" ? "Super admin" : "Admin";
      const actions =
        u.role === "super"
          ? `<span class="muted">You</span>`
          : `<button class="ghost small-del" type="button" data-reset-staff="${u.id}" data-name="${u.username}">Reset password</button>
             <button class="ghost small-del danger" type="button" data-del-staff="${u.id}">Remove</button>`;
      return `<tr>
        <td>${u.username}</td>
        <td>${role}</td>
        <td class="people-actions">${actions}</td>
      </tr>`;
    })
    .join("");
}

document.getElementById("btn-add-admin").addEventListener("click", async () => {
  const status = document.getElementById("staff-status");
  const username = document.getElementById("staff-user").value.trim();
  const password = document.getElementById("staff-pass").value;
  status.textContent = "";
  try {
    await api("/staff", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    });
    document.getElementById("staff-user").value = "";
    document.getElementById("staff-pass").value = "";
    status.textContent = "Admin added.";
    loadStaff();
  } catch (e) {
    status.textContent = e.message;
  }
});

document.getElementById("staff-body").addEventListener("click", async (e) => {
  const status = document.getElementById("staff-status");
  const del = e.target.closest("[data-del-staff]");
  const reset = e.target.closest("[data-reset-staff]");
  if (del) {
    if (!confirm("Remove this admin?")) return;
    try {
      await api(`/staff/${del.getAttribute("data-del-staff")}`, { method: "DELETE" });
      status.textContent = "Admin removed.";
      loadStaff();
    } catch (err) {
      status.textContent = err.message;
    }
    return;
  }
  if (reset) {
    const next = prompt(`New password for ${reset.getAttribute("data-name")}`);
    if (!next) return;
    try {
      await api(`/staff/${reset.getAttribute("data-reset-staff")}`, {
        method: "PATCH",
        body: JSON.stringify({ password: next }),
      });
      status.textContent = "Password updated.";
    } catch (err) {
      status.textContent = err.message;
    }
  }
});

document.getElementById("btn-super-pass").addEventListener("click", async () => {
  const status = document.getElementById("staff-status");
  const password = document.getElementById("super-pass").value;
  try {
    await api("/staff/me", {
      method: "PATCH",
      body: JSON.stringify({ password }),
    });
    document.getElementById("super-pass").value = "";
    status.textContent = "Your password was updated.";
  } catch (e) {
    status.textContent = e.message;
  }
});

renderDots();
ensureAuth().then((ok) => {
  if (ok) showPage("register");
});
