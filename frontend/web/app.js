(() => {
  "use strict";

  const API_BASE = "/api/v1";
  const params = new URLSearchParams(location.search);
  const USE_MOCK = params.get("mock") === "1";
  const DEMO_TOKEN = params.get("token") || localStorage.getItem("cameraagent_demo_token") || "";

  /** @type {File | null} */
  let frameFile = null;
  /** @type {string | null} */
  let sessionId = null;
  /** @type {object | null} */
  let intentPhase = null;
  /** @type {Record<string, string>} */
  const answers = {};

  const els = {
    framePreview: document.getElementById("framePreview"),
    framePlaceholder: document.getElementById("framePlaceholder"),
    galleryInput: document.getElementById("galleryInput"),
    cameraInput: document.getElementById("cameraInput"),
    intentInput: document.getElementById("intentInput"),
    analyzeBtn: document.getElementById("analyzeBtn"),
    confirmBtn: document.getElementById("confirmBtn"),
    backToS0: document.getElementById("backToS0"),
    restartBtn: document.getElementById("restartBtn"),
    questionsMount: document.getElementById("questionsMount"),
    conflictsBox: document.getElementById("conflictsBox"),
    conflictsList: document.getElementById("conflictsList"),
    draftGoal: document.getElementById("draftGoal"),
    planGoal: document.getElementById("planGoal"),
    planAdvice: document.getElementById("planAdvice"),
    planSteps: document.getElementById("planSteps"),
    editInstruction: document.getElementById("editInstruction"),
    s0Status: document.getElementById("s0Status"),
    s1Status: document.getElementById("s1Status"),
    s2Status: document.getElementById("s2Status"),
    referencePreviewBox: document.getElementById("referencePreviewBox"),
    referencePreviewImg: document.getElementById("referencePreviewImg"),
    referencePreviewStatus: document.getElementById("referencePreviewStatus"),
  };

  const MOCK_INTENT = {
    draftGoal: "在断桥拍游客照，兼顾湖面远山与人物位置",
    questions: [
      {
        questionId: "q-mock-1",
        text: "人物与湖面远山的优先级？",
        options: ["人物为主，风景作背景", "风景为主，人物点缀", "两者同等重要"],
      },
      {
        questionId: "q-mock-2",
        text: "构图上人物更靠近哪一侧？",
        options: ["右侧三分线", "居中", "左侧三分线"],
      },
    ],
    conflicts: [
      {
        conflictId: "c-mock-1",
        summary: "意图要求人物在右侧，但当前帧人物偏左",
        userSide: "人物在右侧",
        aestheticSide: "建议人物落在右侧三分",
        sceneSide: "当前主体偏画面左侧",
      },
    ],
  };

  const MOCK_PLAN = {
    goal: "断桥游客照：人物右侧、保留湖面远山",
    steps: [
      { stepId: "s1", title: "调整站位", detail: "请人物向右移动至右侧三分线附近" },
      { stepId: "s2", title: "压低机位", detail: "略压机位以纳入更多湖面与远山" },
      { stepId: "s3", title: "确认地标", detail: "确保断桥栏杆与湖面进入画面" },
    ],
    coarseGuidance: {
      adviceText: "人物靠右，前景留白给湖面；远山压在画面上三分之一。",
    },
    editInstruction:
      "Keep the Broken Bridge and West Lake; move the person to the right third; preserve lake and distant hills.",
  };

  function showScreen(name) {
    document.querySelectorAll(".screen").forEach((el) => {
      el.classList.toggle("active", el.dataset.screen === name);
    });
  }

  function setStatus(el, text, isError = false) {
    el.textContent = text || "";
    el.classList.toggle("error", Boolean(isError));
  }

  function headers(json = false) {
    const h = {};
    if (json) h["Content-Type"] = "application/json";
    if (DEMO_TOKEN) h["X-Demo-Token"] = DEMO_TOKEN;
    return h;
  }

  function onFrameSelected(file) {
    if (!file || !file.type.startsWith("image/")) {
      setStatus(els.s0Status, "请选择 JPEG 或 PNG 图片", true);
      return;
    }
    frameFile = file;
    const url = URL.createObjectURL(file);
    els.framePreview.src = url;
    els.framePreview.hidden = false;
    els.framePlaceholder.hidden = true;
    els.analyzeBtn.disabled = false;
    setStatus(els.s0Status, `已选帧：${file.name || "camera capture"}`);
  }

  els.galleryInput.addEventListener("change", () => {
    const f = els.galleryInput.files && els.galleryInput.files[0];
    if (f) onFrameSelected(f);
  });
  els.cameraInput.addEventListener("change", () => {
    const f = els.cameraInput.files && els.cameraInput.files[0];
    if (f) onFrameSelected(f);
  });

  function renderQuestions(phase) {
    intentPhase = phase;
    Object.keys(answers).forEach((k) => delete answers[k]);
    els.draftGoal.textContent = phase.draftGoal || "确认几个细节";
    els.questionsMount.innerHTML = "";

    const conflicts = phase.conflicts || [];
    if (conflicts.length) {
      els.conflictsBox.hidden = false;
      els.conflictsList.innerHTML = conflicts
        .map((c) => `<li>${escapeHtml(c.summary || "")}</li>`)
        .join("");
    } else {
      els.conflictsBox.hidden = true;
      els.conflictsList.innerHTML = "";
    }

    (phase.questions || []).forEach((q) => {
      const card = document.createElement("div");
      card.className = "card";
      const qid = q.questionId || q.question_id;
      card.innerHTML = `<h2>${escapeHtml(q.text || "")}</h2>`;
      const opts = document.createElement("div");
      opts.className = "options";
      (q.options || []).forEach((opt) => {
        const chip = document.createElement("button");
        chip.type = "button";
        chip.className = "chip";
        chip.textContent = opt;
        chip.addEventListener("click", () => {
          answers[qid] = opt;
          opts.querySelectorAll(".chip").forEach((c) => c.classList.remove("selected"));
          chip.classList.add("selected");
          els.confirmBtn.disabled = !allQuestionsAnswered(phase.questions || []);
        });
        opts.appendChild(chip);
      });
      card.appendChild(opts);
      els.questionsMount.appendChild(card);
    });
    els.confirmBtn.disabled = true;
  }

  function allQuestionsAnswered(questions) {
    return questions.every((q) => {
      const qid = q.questionId || q.question_id;
      return Boolean(answers[qid]);
    });
  }

  function renderPlan(bundle) {
    const shootingPlan = bundle.shootingPlan || bundle.shooting_plan || bundle.plan || bundle;
    const guidance = bundle.coarseGuidance || bundle.coarse_guidance || shootingPlan.coarseGuidance || {};
    const steps = shootingPlan.steps || [];
    els.planGoal.textContent = shootingPlan.goal || "拍摄方案";
    els.planAdvice.textContent = guidance.adviceText || guidance.advice_text || "";
    els.planSteps.innerHTML = "";
    steps.forEach((step, i) => {
      const li = document.createElement("li");
      const status = step.status || "";
      if (status === "in_progress") li.className = "current";
      else if (status === "completed") li.className = "done";
      else if (i === 0) li.className = "current";
      const detail =
        step.detail ||
        (step.completionCriteria && step.completionCriteria.summary) ||
        (step.completion_criteria && step.completion_criteria.summary) ||
        "";
      li.innerHTML = `<span class="dot">${i + 1}</span><div><strong>${escapeHtml(
        step.title || ""
      )}</strong><div style="color:var(--muted);margin-top:0.25rem">${escapeHtml(
        detail
      )}</div></div>`;
      els.planSteps.appendChild(li);
    });
    els.editInstruction.textContent =
      bundle.editInstruction || bundle.edit_instruction || shootingPlan.editInstruction || "";
    if (!USE_MOCK && sessionId) {
      pollReferencePreview();
    }
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  async function ensureSession() {
    if (sessionId) return sessionId;
    if (USE_MOCK) {
      sessionId = "mock-session";
      return sessionId;
    }
    const res = await fetch(`${API_BASE}/sessions`, {
      method: "POST",
      headers: headers(true),
      body: "{}",
    });
    if (!res.ok) throw new Error(await errorText(res));
    const data = await res.json();
    sessionId = data.sessionId || data.session_id;
    if (!sessionId) throw new Error("服务未返回 sessionId");
    return sessionId;
  }

  async function errorText(res) {
    try {
      const j = await res.json();
      return j.detail || j.message || JSON.stringify(j);
    } catch {
      return `${res.status} ${res.statusText}`;
    }
  }

  els.analyzeBtn.addEventListener("click", async () => {
    if (!frameFile) return;
    const intent = (els.intentInput.value || "").trim();
    if (!intent) {
      setStatus(els.s0Status, "请填写拍摄意图", true);
      return;
    }
    els.analyzeBtn.disabled = true;
    setStatus(els.s0Status, USE_MOCK ? "Mock 分析中…" : "分析中，请稍候…");
    try {
      if (USE_MOCK) {
        await delay(400);
        renderQuestions(MOCK_INTENT);
        showScreen("s1");
        setStatus(els.s0Status, "");
        setStatus(els.s1Status, "设计稿 Mock 数据（?mock=1）");
        return;
      }
      await ensureSession();
      const fd = new FormData();
      fd.append("frame", frameFile, frameFile.name || "frame.jpg");
      fd.append("userIntent", intent);
      const res = await fetch(`${API_BASE}/sessions/${sessionId}/submit-intent`, {
        method: "POST",
        headers: headers(false),
        body: fd,
      });
      if (!res.ok) throw new Error(await errorText(res));
      const phase = await res.json();
      renderQuestions(phase);
      showScreen("s1");
      setStatus(els.s0Status, "");
      setStatus(els.s1Status, "");
    } catch (err) {
      setStatus(els.s0Status, String(err.message || err), true);
    } finally {
      els.analyzeBtn.disabled = !frameFile;
    }
  });

  els.confirmBtn.addEventListener("click", async () => {
    els.confirmBtn.disabled = true;
    setStatus(els.s1Status, USE_MOCK ? "Mock 生成方案…" : "生成方案中…");
    try {
      if (USE_MOCK) {
        await delay(350);
        renderPlan(MOCK_PLAN);
        showScreen("s2");
        setStatus(els.s1Status, "");
        return;
      }
      const payload = {
        answers: Object.entries(answers).map(([questionId, value]) => ({
          questionId,
          value,
        })),
      };
      const res = await fetch(`${API_BASE}/sessions/${sessionId}/confirm-intent`, {
        method: "POST",
        headers: headers(true),
        body: JSON.stringify(payload),
      });
      if (!res.ok) throw new Error(await errorText(res));
      const bundle = await res.json();
      renderPlan(bundle);
      showScreen("s2");
      setStatus(els.s1Status, "");
    } catch (err) {
      setStatus(els.s1Status, String(err.message || err), true);
      els.confirmBtn.disabled = !allQuestionsAnswered((intentPhase && intentPhase.questions) || []);
    }
  });

  els.backToS0.addEventListener("click", () => {
    showScreen("s0");
  });

  els.restartBtn.addEventListener("click", () => {
    stopReferencePoll();
    sessionId = null;
    intentPhase = null;
    frameFile = null;
    Object.keys(answers).forEach((k) => delete answers[k]);
    els.framePreview.hidden = true;
    els.framePreview.removeAttribute("src");
    els.framePlaceholder.hidden = false;
    els.analyzeBtn.disabled = true;
    els.galleryInput.value = "";
    els.cameraInput.value = "";
    if (els.referencePreviewBox) els.referencePreviewBox.hidden = true;
    if (els.referencePreviewImg) {
      els.referencePreviewImg.hidden = true;
      els.referencePreviewImg.removeAttribute("src");
    }
    showScreen("s0");
    setStatus(els.s0Status, "");
    setStatus(els.s1Status, "");
    setStatus(els.s2Status, "");
  });

  let referencePollTimer = null;
  function stopReferencePoll() {
    if (referencePollTimer) {
      clearInterval(referencePollTimer);
      referencePollTimer = null;
    }
  }

  async function pollReferencePreview() {
    stopReferencePoll();
    const box = els.referencePreviewBox;
    const img = els.referencePreviewImg;
    const status = els.referencePreviewStatus;
    if (!box || !sessionId) return;
    box.hidden = false;
    img.hidden = true;
    img.removeAttribute("src");
    status.classList.remove("error");
    status.textContent = "目标示意图生成中…（Qwen2511，首版 ≤30s）";
    const tick = async () => {
      try {
        const res = await fetch(`${API_BASE}/sessions/${sessionId}/reference-preview`, {
          headers: headers(false),
        });
        if (res.status === 404) return; // preview not kicked off yet; keep polling
        if (!res.ok) return;
        const p = await res.json();
        if (p.status === "ready") {
          stopReferencePoll();
          const imgRes = await fetch(
            `${API_BASE}/sessions/${sessionId}/reference-preview.png`,
            { headers: headers(false) }
          );
          if (imgRes.ok) {
            const blob = await imgRes.blob();
            img.src = URL.createObjectURL(blob);
            img.hidden = false;
          }
          status.textContent = p.latencyMs
            ? `示意图就绪（${(p.latencyMs / 1000).toFixed(1)}s · ${p.generator}）`
            : "示意图就绪";
        } else if (p.status === "failed") {
          stopReferencePoll();
          status.textContent =
            "示意图生成失败" + (p.errorMessage ? "：" + p.errorMessage : "");
          status.classList.add("error");
        }
      } catch (err) {
        // transient network blip — keep polling
      }
    };
    tick();
    referencePollTimer = setInterval(tick, 1500);
  }

  function delay(ms) {
    return new Promise((r) => setTimeout(r, ms));
  }

  if (USE_MOCK) {
    setStatus(els.s0Status, "设计稿模式：URL 带 ?mock=1");
  }
})();
