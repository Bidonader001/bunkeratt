const API = "/api/v1";
const CAPTURES = 5;

const pages = document.querySelectorAll(".page");
const navBtns = document.querySelectorAll(".nav-btn");
const enrollVideo = document.getElementById("enroll-video");
const checkinVideo = document.getElementById("checkin-video");
const canvas = document.getElementById("work-canvas");
const dotsEl = document.getElementById("enroll-dots");
const countEl = document.getElementById("enroll-count");
const enrollStatus = document.getElementById("enroll-status");
const btnCapture = document.getElementById("btn-capture");
const btnIssue = document.getElementById("btn-issue");
const enrollSuccess = document.getElementById("enroll-success");

let enrollStream = null;
let checkinStream = null;
let captures = [];
let checkinTimer = null;
let checkinBusy = false;
let lastMatchedId = null;

function frameToB64(videoEl, maxWidth = 480, quality = 0.72) {
  const ctx = canvas.getContext("2d");
  let w = videoEl.videoWidth || 640;
  let h = videoEl.videoHeight || 480;
  if (w > maxWidth) {
    h = Math.round((h * maxWidth) / w);
    w = maxWidth;
  }
  canvas.width = w;
  canvas.height = h;
  ctx.drawImage(videoEl, 0, 0, w, h);
  return canvas.toDataURL("image/jpeg", quality);
}

function stopStream(stream) {
  if (!stream) return;
  stream.getTracks().forEach((t) => t.stop());
}

async function startCamera(videoEl) {
  const attempts = [
    { video: { facingMode: "user", width: { ideal: 640 }, height: { ideal: 480 } }, audio: false },
    { video: { facingMode: "user" }, audio: false },
    { video: true, audio: false },
  ];
  let stream = null;
  let lastError = null;
  for (const c of attempts) {
    try {
      stream = await navigator.mediaDevices.getUserMedia(c);
      break;
    } catch (err) {
      lastError = err;
    }
  }
  if (!stream) throw lastError || new Error("Could not access camera");
  videoEl.muted = true;
  videoEl.playsInline = true;
  videoEl.autoplay = true;
  videoEl.srcObject = stream;
  await videoEl.play().catch(async () => {
    await new Promise((r) => setTimeout(r, 150));
    await videoEl.play();
  });
  return stream;
}

function apiError(data, fallback) {
  if (!data) return fallback;
  if (typeof data.detail === "string") return data.detail;
  if (Array.isArray(data.detail)) return data.detail.map((d) => d.msg || d).join("; ");
  return fallback;
}

async function api(path, options = {}) {
  const res = await fetch(`${API}${path}`, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(apiError(data, res.statusText));
  return data;
}

function renderDots() {
  dotsEl.innerHTML = "";
  for (let i = 0; i < CAPTURES; i += 1) {
    const s = document.createElement("span");
    if (i < captures.length) s.classList.add("on");
    dotsEl.appendChild(s);
  }
  countEl.textContent = `${captures.length} / ${CAPTURES}`;
  btnIssue.disabled = captures.length < CAPTURES;
}

async function showPage(key) {
  pages.forEach((p) => p.classList.toggle("active", p.id === `page-${key}`));
  navBtns.forEach((b) => b.classList.toggle("active", b.dataset.page === key));

  stopStream(enrollStream);
  stopStream(checkinStream);
  enrollStream = null;
  checkinStream = null;
  enrollVideo.srcObject = null;
  checkinVideo.srcObject = null;
  if (checkinTimer) {
    clearInterval(checkinTimer);
    checkinTimer = null;
  }

  if (key === "register") {
    try {
      enrollStream = await startCamera(enrollVideo);
      enrollStatus.textContent = "";
    } catch (e) {
      enrollStatus.textContent = e.message;
    }
  }

  if (key === "checkin") {
    lastMatchedId = null;
    setCheckinNeutral("Align your face in the viewfinder");
    setScan("SCANNING");
    try {
      checkinStream = await startCamera(checkinVideo);
      checkinTimer = setInterval(pollCheckin, 1200);
    } catch (e) {
      setScan("CAMERA ERROR");
      setCheckinNeutral(e.message);
    }
  }

  if (key === "log") {
    loadLog();
  }
}

function setScan(text) {
  document.getElementById("checkin-label").textContent = text;
}

function setCheckinNeutral(msg) {
  document.getElementById("checkin-neutral").classList.remove("hidden");
  document.getElementById("checkin-granted").classList.add("hidden");
  document.getElementById("checkin-msg").textContent = msg;
}

function setCheckinGranted(name, confidence) {
  document.getElementById("checkin-neutral").classList.add("hidden");
  document.getElementById("checkin-granted").classList.remove("hidden");
  document.getElementById("checkin-name").textContent = name;
  document.getElementById("checkin-meta").textContent = `MATCH  ${Math.round(confidence * 100)}%`;
}

async function pollCheckin() {
  if (checkinBusy || !checkinVideo.videoWidth) return;
  checkinBusy = true;
  try {
    const result = await api("/checkin", {
      method: "POST",
      body: JSON.stringify({ image_b64: frameToB64(checkinVideo) }),
    });
    if (result.status === "no_face") {
      if (!lastMatchedId) setCheckinNeutral("Align your face in the viewfinder");
      setScan("SCANNING");
    } else if (result.status === "multiple_faces") {
      setCheckinNeutral("One person at a time");
      setScan("MULTIPLE FACES");
    } else if (result.status === "unrecognized") {
      if (!lastMatchedId) setCheckinNeutral("No match — try again");
      setScan("NO MATCH");
    } else if (result.status === "matched") {
      setScan("ACCESS GRANTED");
      setCheckinGranted(result.name, result.confidence);
      lastMatchedId = result.employee_id;
    }
  } catch (e) {
    setScan("ERROR");
    setCheckinNeutral(e.message);
  } finally {
    checkinBusy = false;
  }
}

navBtns.forEach((btn) => {
  btn.addEventListener("click", () => showPage(btn.dataset.page));
});

btnCapture.addEventListener("click", async () => {
  if (captures.length >= CAPTURES) return;
  enrollStatus.textContent = "Processing…";
  btnCapture.disabled = true;
  try {
    const image_b64 = frameToB64(enrollVideo);
    await api("/captures/validate", {
      method: "POST",
      body: JSON.stringify({ image_b64 }),
    });
    captures.push(image_b64);
    renderDots();
    enrollStatus.textContent = "";
  } catch (e) {
    enrollStatus.textContent = e.message;
  } finally {
    btnCapture.disabled = false;
  }
});

btnIssue.addEventListener("click", async () => {
  const name = document.getElementById("enroll-name").value.trim();
  const employee_id = document.getElementById("enroll-id").value.trim();
  if (!name || !employee_id) {
    enrollStatus.textContent = "Enter name and pass ID";
    return;
  }
  btnIssue.disabled = true;
  enrollStatus.textContent = "Issuing…";
  try {
    await api("/passes/enroll", {
      method: "POST",
      body: JSON.stringify({ name, employee_id, images_b64: captures }),
    });
    enrollSuccess.classList.remove("hidden");
    enrollStatus.textContent = "";
    captures = [];
    document.getElementById("enroll-name").value = "";
    document.getElementById("enroll-id").value = "";
    renderDots();
    setTimeout(() => enrollSuccess.classList.add("hidden"), 2500);
  } catch (e) {
    enrollStatus.textContent = e.message;
    btnIssue.disabled = captures.length < CAPTURES;
  }
});

async function loadLog() {
  const name = document.getElementById("log-name").value.trim();
  const date = document.getElementById("log-date").value.trim();
  const qs = new URLSearchParams();
  if (name) qs.set("name", name);
  if (date) qs.set("date", date);
  const list = document.getElementById("log-list");
  try {
    const rows = await api(`/log?${qs.toString()}`);
    if (!rows.length) {
      list.innerHTML = `<p class="muted">No records found.</p>`;
      return;
    }
    list.innerHTML = rows
      .map((r) => {
        const dt = new Date(r.timestamp);
        const when = Number.isNaN(dt.getTime())
          ? r.timestamp
          : dt.toLocaleString();
        return `<article class="log-row">
          <header>
            <span>${r.employee_name}</span>
            <span class="granted-tag">GRANTED</span>
          </header>
          <p class="muted">${when} · MATCH ${Math.round(r.confidence * 100)}%</p>
        </article>`;
      })
      .join("");
  } catch (e) {
    list.innerHTML = `<p class="status">${e.message}</p>`;
  }
}

document.getElementById("log-name").addEventListener("input", loadLog);
document.getElementById("log-date").addEventListener("input", loadLog);

renderDots();
showPage("register");
