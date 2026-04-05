/* ===================================================================
   Math Agent -- Client-side JavaScript
   Connects to /ws for live updates and drives the two-panel UI.
   =================================================================== */

(function () {
  "use strict";

  // ---- DOM references ------------------------------------------------

  const providerSelect = document.getElementById("provider-select");
  const modelInput = document.getElementById("model-input");
  const problemSelect = document.getElementById("problem-select");
  const runBtn = document.getElementById("run-btn");
  const statusDot = document.getElementById("status-indicator");
  const clearLogBtn = document.getElementById("clear-log-btn");

  // Left panel
  const problemInfo = document.getElementById("problem-info");
  const problemQuestion = document.getElementById("problem-question");
  const problemDomain = document.getElementById("problem-domain");
  const problemDifficulty = document.getElementById("problem-difficulty");
  const roadmapSection = document.getElementById("roadmap-section");
  const roadmapSteps = document.getElementById("roadmap-steps");
  const propositionsSection = document.getElementById("propositions-section");
  const propositionsList = document.getElementById("propositions-list");
  const prevRoadmapsSection = document.getElementById("prev-roadmaps-section");
  const prevRoadmapsList = document.getElementById("prev-roadmaps-list");
  const idleMessage = document.getElementById("idle-message");

  // Right panel
  const thinkingLog = document.getElementById("thinking-log");
  const thinkingBody = document.getElementById("thinking-body");

  // Reconnect overlay
  const reconnectOverlay = document.getElementById("reconnect-overlay");

  // ---- Default model map ---------------------------------------------

  const DEFAULT_MODELS = {
    anthropic: "claude-opus-4-0626",
    openai: "o3",
    deepseek: "deepseek-reasoner",
    gemini: "gemini-2.5-pro",
  };

  // ---- State ---------------------------------------------------------

  let ws = null;
  let reconnectTimer = null;
  let problems = [];

  // ---- Initialization ------------------------------------------------

  loadProblems();
  connectWebSocket();

  providerSelect.addEventListener("change", function () {
    modelInput.placeholder = DEFAULT_MODELS[providerSelect.value] || "(default)";
  });

  runBtn.addEventListener("click", startRun);
  clearLogBtn.addEventListener("click", clearLog);

  // ---- Load problem list ---------------------------------------------

  async function loadProblems() {
    try {
      const res = await fetch("/api/problems");
      problems = await res.json();
      problemSelect.innerHTML = "";

      // Add a "Custom" option at the top.
      const customOpt = document.createElement("option");
      customOpt.value = "__custom__";
      customOpt.textContent = "-- Custom problem --";
      problemSelect.appendChild(customOpt);

      for (const p of problems) {
        const opt = document.createElement("option");
        opt.value = p.problem_id;
        opt.textContent = "[" + p.difficulty_label + "] " + p.problem_id;
        problemSelect.appendChild(opt);
      }

      // Select the first real problem by default if available.
      if (problems.length > 0) {
        problemSelect.value = problems[0].problem_id;
      }
    } catch (err) {
      console.error("Failed to load problems:", err);
      problemSelect.innerHTML = '<option value="">Failed to load</option>';
    }
  }

  // ---- Start a run ---------------------------------------------------

  async function startRun() {
    const provider = providerSelect.value;
    const model = modelInput.value.trim();
    const selectedProblem = problemSelect.value;

    let body;
    if (selectedProblem === "__custom__") {
      const question = prompt("Enter your math problem:");
      if (!question) return;
      body = {
        provider: provider,
        model: model || "",
        problem_id: null,
        custom_question: question,
        custom_domain: "general",
      };
    } else {
      body = {
        provider: provider,
        model: model || "",
        problem_id: selectedProblem,
      };
    }

    runBtn.disabled = true;
    runBtn.textContent = "Running...";

    try {
      const res = await fetch("/api/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await res.json();
      if (!res.ok) {
        alert("Error: " + (data.error || "Unknown error"));
        runBtn.disabled = false;
        runBtn.textContent = "Run";
      }
      // The button will be re-enabled when we receive the "Run finished" event.
    } catch (err) {
      alert("Network error: " + err.message);
      runBtn.disabled = false;
      runBtn.textContent = "Run";
    }
  }

  // ---- WebSocket connection ------------------------------------------

  function connectWebSocket() {
    const protocol = location.protocol === "https:" ? "wss:" : "ws:";
    const url = protocol + "//" + location.host + "/ws";

    ws = new WebSocket(url);

    ws.addEventListener("open", function () {
      statusDot.className = "status-dot connected";
      statusDot.title = "WebSocket connected";
      reconnectOverlay.classList.add("hidden");
      if (reconnectTimer) {
        clearTimeout(reconnectTimer);
        reconnectTimer = null;
      }
    });

    ws.addEventListener("message", function (event) {
      try {
        const msg = JSON.parse(event.data);
        handleMessage(msg);
      } catch (err) {
        console.error("Bad WS message:", err);
      }
    });

    ws.addEventListener("close", function () {
      statusDot.className = "status-dot disconnected";
      statusDot.title = "WebSocket disconnected";
      scheduleReconnect();
    });

    ws.addEventListener("error", function () {
      statusDot.className = "status-dot disconnected";
      statusDot.title = "WebSocket error";
    });
  }

  function scheduleReconnect() {
    reconnectOverlay.classList.remove("hidden");
    if (reconnectTimer) return;
    reconnectTimer = setTimeout(function () {
      reconnectTimer = null;
      connectWebSocket();
    }, 3000);
  }

  // ---- Message handler -----------------------------------------------

  function handleMessage(msg) {
    switch (msg.type) {
      case "memo_update":
        renderMemo(msg.data);
        break;
      case "thinking":
        appendThinking(msg.data);
        break;
      case "status":
        if (msg.data && !msg.data.running) {
          runBtn.disabled = false;
          runBtn.textContent = "Run";
        }
        break;
      case "pong":
        break;
      default:
        console.log("Unknown message type:", msg.type);
    }
  }

  // ---- Render MEMO state (left panel) --------------------------------

  function renderMemo(data) {
    // Hide idle message once we have data.
    idleMessage.classList.add("hidden");

    // Problem info
    if (data.problem) {
      problemInfo.classList.remove("hidden");
      problemQuestion.textContent = data.problem.question;
      problemDomain.textContent = data.problem.domain;
      problemDifficulty.textContent = data.problem.difficulty_label;
    }

    // Current roadmap
    if (data.current_roadmap && data.current_roadmap.length > 0) {
      roadmapSection.classList.remove("hidden");
      roadmapSteps.innerHTML = "";

      for (const step of data.current_roadmap) {
        const li = document.createElement("li");
        li.className = "status-" + step.status;

        const num = document.createElement("span");
        num.className = "step-number";
        num.textContent = step.step_index;

        const desc = document.createElement("span");
        desc.className = "step-desc";
        desc.textContent = step.description;

        const statusBadge = document.createElement("span");
        statusBadge.className = "step-status";
        statusBadge.textContent = step.status;

        li.appendChild(num);
        li.appendChild(desc);
        li.appendChild(statusBadge);
        roadmapSteps.appendChild(li);
      }
    } else {
      roadmapSection.classList.add("hidden");
    }

    // Proved propositions
    if (data.proved_propositions && data.proved_propositions.length > 0) {
      propositionsSection.classList.remove("hidden");
      propositionsList.innerHTML = "";

      for (const prop of data.proved_propositions) {
        const li = document.createElement("li");
        const idSpan = document.createElement("span");
        idSpan.className = "prop-id";
        idSpan.textContent = prop.prop_id + ":";

        const stmtText = document.createTextNode(" " + prop.statement);

        const srcSpan = document.createElement("span");
        srcSpan.className = "prop-source";
        srcSpan.textContent = "(" + prop.source + ")";

        li.appendChild(idSpan);
        li.appendChild(stmtText);
        li.appendChild(srcSpan);
        propositionsList.appendChild(li);
      }
    } else {
      propositionsSection.classList.add("hidden");
    }

    // Previous roadmaps
    if (data.previous_roadmaps && data.previous_roadmaps.length > 0) {
      prevRoadmapsSection.classList.remove("hidden");
      prevRoadmapsList.innerHTML = "";

      for (const rm of data.previous_roadmaps) {
        const div = document.createElement("div");
        div.className = "prev-roadmap";

        const nameDiv = document.createElement("div");
        nameDiv.className = "prev-roadmap-name";
        nameDiv.textContent = rm.name;

        const detailDiv = document.createElement("div");
        detailDiv.className = "prev-roadmap-detail";
        let detail = "";
        if (rm.approach) detail += "Approach: " + rm.approach + "\n";
        if (rm.failure_reason) detail += "Failed: " + rm.failure_reason + "\n";
        if (rm.lesson) detail += "Lesson: " + rm.lesson;
        detailDiv.textContent = detail;

        div.appendChild(nameDiv);
        div.appendChild(detailDiv);
        prevRoadmapsList.appendChild(div);
      }
    } else {
      prevRoadmapsSection.classList.add("hidden");
    }
  }

  // ---- Append thinking event (right panel) ---------------------------

  function appendThinking(data) {
    const entry = document.createElement("div");
    entry.className = "log-entry";

    // Timestamp
    const timeSpan = document.createElement("span");
    timeSpan.className = "log-time";
    const ts = data.timestamp ? new Date(data.timestamp * 1000) : new Date();
    timeSpan.textContent =
      pad2(ts.getHours()) +
      ":" +
      pad2(ts.getMinutes()) +
      ":" +
      pad2(ts.getSeconds());

    // Tag (event type + step)
    const tagSpan = document.createElement("span");
    const eventType = data.event_type || "info";
    tagSpan.className = "log-tag log-tag-" + eventType;
    let tagText = eventType;
    if (data.step !== undefined && data.step !== null && data.step !== 0) {
      tagText += " #" + data.step;
    }
    if (data.module_name) {
      tagText += " [" + data.module_name + "]";
    }
    tagSpan.textContent = tagText;

    // Content
    const contentSpan = document.createElement("span");
    contentSpan.className = "log-content";
    contentSpan.textContent = data.content || "";

    entry.appendChild(timeSpan);
    entry.appendChild(tagSpan);
    entry.appendChild(contentSpan);
    thinkingLog.appendChild(entry);

    // Auto-scroll to bottom.
    thinkingBody.scrollTop = thinkingBody.scrollHeight;

    // Re-enable Run button when we see the final "Run finished" event.
    if (
      eventType === "system" &&
      data.content &&
      data.content.indexOf("Run finished") !== -1
    ) {
      runBtn.disabled = false;
      runBtn.textContent = "Run";
    }
  }

  // ---- Clear log -----------------------------------------------------

  function clearLog() {
    thinkingLog.innerHTML = "";
  }

  // ---- Helpers -------------------------------------------------------

  function pad2(n) {
    return n < 10 ? "0" + n : "" + n;
  }

  // ---- Heartbeat (keep connection alive) -----------------------------

  setInterval(function () {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: "ping" }));
    }
  }, 30000);
})();
