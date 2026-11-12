let state = null;
let step = 0;
let pollTimer = null;
let waitingJob = null; // { name, onDone, onError }
let boardsCache = [];
let boardsLoaded = false;

const $ = (id) => document.getElementById(id);

function selectedBoard() {
  const value = $("boardSelect").value;
  if (!value) return null;
  return boardsCache.find((b) => String(b.id) === String(value)) || null;
}

function requireBoard() {
  const board = selectedBoard();
  if (!board || !board.name || !board.url) {
    throw new Error("Selecione um board (obrigatório)");
  }
  return board;
}

function fillBoardSelect(boards, preferred) {
  boardsCache = boards || [];
  const select = $("boardSelect");
  const current = preferred?.id ?? select.value;
  select.innerHTML = "";
  if (!boardsCache.length) {
    const opt = document.createElement("option");
    opt.value = "";
    opt.textContent = state?.session_ok
      ? "Nenhum board encontrado"
      : "Faça login para carregar os boards";
    select.appendChild(opt);
    return;
  }
  const placeholder = document.createElement("option");
  placeholder.value = "";
  placeholder.textContent = "Selecione o board…";
  select.appendChild(placeholder);
  boardsCache.forEach((b) => {
    const opt = document.createElement("option");
    opt.value = String(b.id);
    const key = b.project_key ? `${b.project_key} · ` : "";
    opt.textContent = `${key}${b.name}`;
    select.appendChild(opt);
  });
  if (current && boardsCache.some((b) => String(b.id) === String(current))) {
    select.value = String(current);
  }
}

async function loadBoards({ force = false } = {}) {
  if (!state?.session_ok) {
    fillBoardSelect([], null);
    boardsLoaded = false;
    return;
  }
  if (boardsLoaded && !force) return;
  const data = await api("/api/boards");
  fillBoardSelect(data.boards || [], state.board);
  boardsLoaded = true;
  if (state.board?.id && $("boardSelect").value) {
    await api("/api/board", {
      method: "POST",
      body: JSON.stringify(requireBoard()),
    }).catch(() => {});
  }
}

function showMsg(el, text, kind = "") {
  if (!text) {
    el.classList.add("hidden");
    el.textContent = "";
    return;
  }
  el.classList.remove("hidden");
  el.className = `msg ${kind}`.trim();
  el.textContent = text;
}

function setButtonsBusy(busy) {
  document.querySelectorAll("button").forEach((b) => {
    if (busy) {
      b.dataset.prevDisabled = b.disabled ? "1" : "0";
      b.disabled = true;
    } else if (b.dataset.prevDisabled === "0") {
      b.disabled = false;
    }
  });
}

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = data.detail || data.message || res.statusText;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return data;
}

function goStep(n) {
  step = n;
  document.querySelectorAll(".steps button").forEach((btn) => {
    btn.classList.toggle("active", Number(btn.dataset.step) === n);
  });
  ["step0", "step1", "step2", "step3"].forEach((id, i) => {
    $(id).classList.toggle("hidden", i !== n);
  });
}

function updateProgressUI(job) {
  const panel = $("progressPanel");
  if (!job || !job.status || job.status === "idle") {
    panel.classList.add("hidden");
    return;
  }
  const pct = Math.max(0, Math.min(100, Number(job.progress || 0)));
  panel.classList.remove("hidden");
  $("progressBar").style.width = `${pct}%`;
  $("progressPct").textContent = `${pct}%`;

  const nameMap = {
    report: "Relatório",
    revise: "Revisão",
    slides: "Slides",
    video: "Vídeo",
  };
  const label = nameMap[job.name] || job.name || "Tarefa";
  if (job.status === "running") {
    $("progressLabel").textContent = `${label} em andamento`;
  } else if (job.status === "done") {
    $("progressLabel").textContent = `${label} concluído`;
  } else if (job.status === "error") {
    $("progressLabel").textContent = `${label} falhou`;
  } else {
    $("progressLabel").textContent = label;
  }

  const bits = [];
  if (job.message) bits.push(job.message);
  if (job.total) bits.push(`${job.current || 0}/${job.total}`);
  if (job.error) bits.push(job.error.split("\n")[0]);
  $("progressDetail").textContent = bits.join(" · ");
}

function render() {
  if (!state) return;
  const badge = $("sessionBadge");
  badge.textContent = state.session_ok ? "Sessão capturada" : "Sem sessão";
  badge.className = `badge ${state.session_ok ? "ok" : "bad"}`;
  $("jiraUrl").textContent = state.jira_base_url || "";

  if (!$("prompt").value) $("prompt").value = state.default_prompt || "";
  if (state.mid_sprint != null && document.activeElement !== $("midSprint")) {
    $("midSprint").value = state.mid_sprint || "";
  }
  if (state.renegotiations != null && document.activeElement !== $("renegotiations")) {
    $("renegotiations").value = state.renegotiations || "";
  }

  if (state.report_md) {
    $("reportEdit").value = state.report_md;
    $("reportHtml").innerHTML = state.report_html || "";
    $("reportPreview").innerHTML = state.report_html || "";
    $("reportPreview").classList.remove("hidden");
  }

  const voice = $("voice");
  const current = voice.value;
  voice.innerHTML = "";
  [...new Set(state.voices || [])].forEach((v) => {
    const opt = document.createElement("option");
    opt.value = v;
    opt.textContent = v;
    voice.appendChild(opt);
  });
  if (current) voice.value = current;

  $("slidesMeta").textContent = state.slides?.length
    ? `${state.slides.length} slides montados a partir do relatório`
    : "Aprove o relatório para montar os slides.";

  const theme = state.theme || {};
  if (theme.background) $("colorBg").value = theme.background;
  if (theme.title) $("colorTitle").value = theme.title;
  if (theme.body) $("colorBody").value = theme.body;
  if (theme.accent) $("colorAccent").value = theme.accent;

  const list = $("slidesList");
  list.innerHTML = "";
  (state.slides || []).forEach((s, i) => {
    const d = document.createElement("details");
    if (i < 2) d.open = true;
    const media = s.images ? ` · ${s.images} ilustração(ões)` : "";
    d.innerHTML = `<summary>${i + 1}. ${escapeHtml(s.title)}${media}</summary>
      <ul>${(s.bullets || []).map((b) => `<li>${escapeHtml(b)}</li>`).join("")}</ul>
      <p class="sub">Narração: ${escapeHtml(s.narration || "")}</p>`;
    list.appendChild(d);
  });

  const grid = $("previewGrid");
  grid.innerHTML = "";
  (state.png_urls || []).forEach((url) => {
    const img = document.createElement("img");
    img.src = `${url}?t=${Date.now()}`;
    img.alt = "slide";
    grid.appendChild(img);
  });

  const pptx = $("dlPptx");
  const pptx2 = $("dlPptx2");
  if (state.pptx_url) {
    pptx.href = state.pptx_url;
    pptx2.href = state.pptx_url;
    pptx.classList.remove("hidden");
    pptx2.classList.remove("hidden");
  } else {
    pptx.classList.add("hidden");
    pptx2.classList.add("hidden");
  }

  const dlVideo = $("dlVideo");
  const player = $("player");
  if (state.video_url) {
    dlVideo.href = state.video_url;
    dlVideo.classList.remove("hidden");
    player.src = state.video_url;
    player.classList.remove("hidden");
  } else {
    dlVideo.classList.add("hidden");
    player.classList.add("hidden");
  }

  const job = state.job || {};
  updateProgressUI(job);
  $("jobStatus").textContent =
    job.status && job.status !== "idle"
      ? `Status: ${job.status}${job.message ? " — " + job.message : ""}`
      : "";

  if (job.status === "running") {
    setButtonsBusy(true);
    startPoll();
  } else {
    setButtonsBusy(false);
    if (waitingJob && job.name === waitingJob.name) {
      const cb = waitingJob;
      waitingJob = null;
      if (job.status === "done" && cb.onDone) cb.onDone();
      if (job.status === "error" && cb.onError) cb.onError(job.error || "Falha");
    }
    if (job.status !== "running") stopPoll();
  }
}

function escapeHtml(str) {
  return String(str)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function startPoll() {
  if (pollTimer) return;
  pollTimer = setInterval(async () => {
    try {
      state = await api("/api/state");
      render();
    } catch (_) {
      /* ignore transient */
    }
  }, 1000);
}

function stopPoll() {
  if (pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
}

function watchJob(name, { onDone, onError } = {}) {
  waitingJob = { name, onDone, onError };
  startPoll();
}

async function refresh() {
  state = await api("/api/state");
  render();
  await loadBoards();
}

document.querySelectorAll(".steps button").forEach((btn) => {
  btn.addEventListener("click", () => goStep(Number(btn.dataset.step)));
});

$("btnLogin").addEventListener("click", async () => {
  setButtonsBusy(true);
  showMsg($("mainMsg"), "Abrindo Chromium — faça login no Jira...");
  try {
    state = await api("/api/login", { method: "POST", body: "{}" });
    showMsg($("sideMsg"), "Sessão extraída.", "ok");
    render();
    boardsLoaded = false;
    await loadBoards({ force: true });
    showMsg($("mainMsg"), "Selecione o board para continuar.", "ok");
  } catch (e) {
    showMsg($("sideMsg"), e.message, "error");
    showMsg($("mainMsg"), e.message, "error");
  } finally {
    setButtonsBusy(false);
  }
});

$("btnRelogin").addEventListener("click", async () => {
  setButtonsBusy(true);
  showMsg($("mainMsg"), "Relogando...");
  try {
    state = await api("/api/relogin", { method: "POST", body: "{}" });
    showMsg($("sideMsg"), "Nova sessão salva.", "ok");
    render();
    boardsLoaded = false;
    await loadBoards({ force: true });
    showMsg($("mainMsg"), "");
  } catch (e) {
    showMsg($("sideMsg"), e.message, "error");
    showMsg($("mainMsg"), e.message, "error");
  } finally {
    setButtonsBusy(false);
  }
});

$("btnReloadBoards").addEventListener("click", async () => {
  try {
    setButtonsBusy(true);
    await loadBoards({ force: true });
    showMsg($("mainMsg"), "Boards atualizados.", "ok");
  } catch (e) {
    showMsg($("mainMsg"), e.message, "error");
  } finally {
    setButtonsBusy(false);
  }
});

$("boardSelect").addEventListener("change", async () => {
  try {
    const board = selectedBoard();
    if (!board) return;
    state = await api("/api/board", {
      method: "POST",
      body: JSON.stringify(board),
    });
    render();
  } catch (e) {
    showMsg($("mainMsg"), e.message, "error");
  }
});

$("btnReport").addEventListener("click", async () => {
  try {
    const board = requireBoard();
    state = await api("/api/report", {
      method: "POST",
      body: JSON.stringify({
        prompt: $("prompt").value,
        mid_sprint: $("midSprint").value,
        renegotiations: $("renegotiations").value,
        board,
      }),
    });
    render();
    watchJob("report", {
      onDone: () => {
        goStep(1);
        showMsg($("mainMsg"), "Relatório gerado.", "ok");
        refresh();
      },
      onError: (err) => showMsg($("mainMsg"), err, "error"),
    });
  } catch (e) {
    showMsg($("mainMsg"), e.message, "error");
  }
});

$("btnSave").addEventListener("click", async () => {
  try {
    state = await api("/api/save-report", {
      method: "POST",
      body: JSON.stringify({ report_md: $("reportEdit").value }),
    });
    render();
    showMsg($("mainMsg"), "Texto salvo.", "ok");
  } catch (e) {
    showMsg($("mainMsg"), e.message, "error");
  }
});

$("btnRevise").addEventListener("click", async () => {
  try {
    const board = requireBoard();
    state = await api("/api/revise", {
      method: "POST",
      body: JSON.stringify({
        message: $("changeMsg").value,
        report_md: $("reportEdit").value,
        mid_sprint: $("midSprint").value,
        renegotiations: $("renegotiations").value,
        board,
      }),
    });
    $("changeMsg").value = "";
    render();
    watchJob("revise", {
      onDone: () => {
        showMsg($("mainMsg"), "Relatório atualizado.", "ok");
        refresh();
      },
      onError: (err) => showMsg($("mainMsg"), err, "error"),
    });
  } catch (e) {
    showMsg($("mainMsg"), e.message, "error");
  }
});

$("btnApprove").addEventListener("click", async () => {
  setButtonsBusy(true);
  try {
    state = await api("/api/approve", {
      method: "POST",
      body: JSON.stringify({ report_md: $("reportEdit").value }),
    });
    render();
    goStep(2);
  } catch (e) {
    showMsg($("mainMsg"), e.message, "error");
  } finally {
    setButtonsBusy(false);
  }
});

async function saveThemeFromInputs() {
  state = await api("/api/theme", {
    method: "POST",
    body: JSON.stringify({
      background: $("colorBg").value,
      title: $("colorTitle").value,
      body: $("colorBody").value,
      accent: $("colorAccent").value,
    }),
  });
  render();
}

["colorBg", "colorTitle", "colorBody", "colorAccent"].forEach((id) => {
  $(id).addEventListener("change", () => {
    saveThemeFromInputs().catch((e) => showMsg($("mainMsg"), e.message, "error"));
  });
});

$("btnThemeReset").addEventListener("click", async () => {
  $("colorBg").value = "#121c30";
  $("colorTitle").value = "#f0f4fa";
  $("colorBody").value = "#a0b0c6";
  $("colorAccent").value = "#22a898";
  try {
    await saveThemeFromInputs();
    showMsg($("mainMsg"), "Cores padrão restauradas. Regenere os slides.", "ok");
  } catch (e) {
    showMsg($("mainMsg"), e.message, "error");
  }
});

$("btnSlides").addEventListener("click", async () => {
  try {
    await saveThemeFromInputs();
    state = await api("/api/slides", { method: "POST", body: "{}" });
    render();
    watchJob("slides", {
      onDone: () => {
        showMsg($("mainMsg"), "Slides gerados.", "ok");
        refresh();
      },
      onError: (err) => showMsg($("mainMsg"), err, "error"),
    });
  } catch (e) {
    showMsg($("mainMsg"), e.message, "error");
  }
});

$("btnGoVideo").addEventListener("click", () => goStep(3));

$("btnVideo").addEventListener("click", async () => {
  try {
    state = await api("/api/video", {
      method: "POST",
      body: JSON.stringify({ voice: $("voice").value }),
    });
    render();
    watchJob("video", {
      onDone: () => {
        showMsg($("mainMsg"), "Vídeo pronto.", "ok");
        refresh();
      },
      onError: (err) => showMsg($("mainMsg"), err, "error"),
    });
  } catch (e) {
    showMsg($("mainMsg"), e.message, "error");
  }
});

refresh().catch((e) => showMsg($("mainMsg"), e.message, "error"));
