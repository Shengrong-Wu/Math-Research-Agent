/* ===================================================================
   Math Agent -- Client-side JavaScript
   Connects to /ws for live updates and drives the three-panel UI.
   =================================================================== */

(function () {
  "use strict";

  // ---- Default model map ---------------------------------------------

  var DEFAULT_MODELS = {
    anthropic: "claude-opus-4-0626",
    openai: "o3",
    deepseek: "deepseek-reasoner",
    gemini: "gemini-2.5-pro",
  };

  // ---- DOM references ------------------------------------------------

  // Setup sidebar
  var providerMode = document.getElementById("provider-mode");
  var singleConfig = document.getElementById("single-config");
  var multiConfig = document.getElementById("multi-config");

  // Single provider
  var providerSelect = document.getElementById("provider-select");
  var modelSelect = document.getElementById("model-select");
  var modelCustom = document.getElementById("model-custom");
  var apiKeyInput = document.getElementById("api-key-input");
  var apiKeyHint = document.getElementById("api-key-hint");

  // Problem
  var problemSource = document.getElementById("problem-source");
  var builtinGroup = document.getElementById("builtin-problem-group");
  var customGroup = document.getElementById("custom-problem-group");
  var problemSelect = document.getElementById("problem-select");
  var customQuestion = document.getElementById("custom-question");
  var customDomain = document.getElementById("custom-domain");

  // Resume
  var resumeGroup = document.getElementById("resume-group");
  var resumeSelect = document.getElementById("resume-select");
  var resumeInfo = document.getElementById("resume-info");
  var resumeProblemText = document.getElementById("resume-problem-text");
  var resumeStatus = document.getElementById("resume-status");
  var resumeRoadmaps = document.getElementById("resume-roadmaps");
  var resumeProblemOverride = document.getElementById("resume-problem-override");
  var resumeProblemSelect = document.getElementById("resume-problem-select");

  // Options
  var skipLeanCheck = document.getElementById("skip-lean-check");
  var hyperN = document.getElementById("hyper-n");
  var hyperC = document.getElementById("hyper-c");
  var hyperK = document.getElementById("hyper-k");

  // Buttons
  var runBtn = document.getElementById("run-btn");
  var clearLogBtn = document.getElementById("clear-log-btn");
  var statusDot = document.getElementById("status-indicator");

  // Dialogue panel (center)
  var problemInfo = document.getElementById("problem-info");
  var problemQuestion = document.getElementById("problem-question");
  var problemDomain = document.getElementById("problem-domain");
  var problemDifficulty = document.getElementById("problem-difficulty");
  var roadmapSection = document.getElementById("roadmap-section");
  var roadmapSteps = document.getElementById("roadmap-steps");
  var propositionsSection = document.getElementById("propositions-section");
  var propositionsList = document.getElementById("propositions-list");
  var proofSection = document.getElementById("proof-section");
  var proofContent = document.getElementById("proof-content");
  var prevRoadmapsSection = document.getElementById("prev-roadmaps-section");
  var prevRoadmapsList = document.getElementById("prev-roadmaps-list");
  var idleMessage = document.getElementById("idle-message");

  // Thinking panel (right)
  var thinkingLog = document.getElementById("thinking-log");
  var thinkingBody = document.getElementById("thinking-body");

  // Reconnect overlay
  var reconnectOverlay = document.getElementById("reconnect-overlay");

  // ---- Agent config definitions (for multi-agent mode) ---------------

  var AGENT_ROLES = ["thinking", "assistant", "review", "cli"];

  // ---- State ---------------------------------------------------------

  var ws = null;
  var reconnectTimer = null;
  var problems = [];
  var envKeys = {}; // { provider: { configured, env_var, prefix } }
  var previousRuns = []; // loaded from /api/runs

  // ---- Initialization ------------------------------------------------

  loadProblems();
  loadEnvKeys();
  connectWebSocket();
  initModels(providerSelect, modelSelect, modelCustom, apiKeyInput, "anthropic");

  // Event listeners
  providerMode.addEventListener("change", onProviderModeChange);
  providerSelect.addEventListener("change", function () {
    onProviderChange(providerSelect, modelSelect, modelCustom, apiKeyInput, apiKeyHint);
  });
  modelSelect.addEventListener("change", function () {
    onModelSelectChange(modelSelect, modelCustom);
  });
  apiKeyInput.addEventListener("input", debounce(function () {
    fetchAndPopulateModels(providerSelect.value, apiKeyInput.value.trim(), modelSelect, modelCustom);
  }, 600));
  problemSource.addEventListener("change", onProblemSourceChange);
  runBtn.addEventListener("click", startRun);
  clearLogBtn.addEventListener("click", clearLog);

  // Setup multi-agent listeners
  AGENT_ROLES.forEach(function (role) {
    var prov = document.getElementById(role + "-provider");
    var mod = document.getElementById(role + "-model");
    var modCustom = document.getElementById(role + "-model-custom");
    var key = document.getElementById(role + "-api-key");
    var hint = document.getElementById(role + "-api-key-hint");

    prov.addEventListener("change", function () {
      onProviderChange(prov, mod, modCustom, key, hint);
    });
    mod.addEventListener("change", function () {
      onModelSelectChange(mod, modCustom);
    });
    key.addEventListener("input", debounce(function () {
      fetchAndPopulateModels(prov.value, key.value.trim(), mod, modCustom);
    }, 600));
  });

  // ---- Load problem list ---------------------------------------------

  async function loadProblems() {
    try {
      var res = await fetch("/api/problems");
      problems = await res.json();
      problemSelect.innerHTML = "";

      for (var i = 0; i < problems.length; i++) {
        var p = problems[i];
        var opt = document.createElement("option");
        opt.value = p.problem_id;
        opt.textContent = "L" + p.difficulty_level + " \u00B7 " + p.difficulty_label + " \u00B7 " + p.problem_id + " \u00B7 " + truncate(p.question, 30);
        problemSelect.appendChild(opt);
      }

      if (problems.length > 0) {
        problemSelect.value = problems[0].problem_id;
      }
    } catch (err) {
      console.error("Failed to load problems:", err);
      problemSelect.innerHTML = '<option value="">Failed to load</option>';
    }
  }

  // ---- Load env key status -------------------------------------------

  async function loadEnvKeys() {
    try {
      var res = await fetch("/api/env-keys");
      envKeys = await res.json();

      // Update hints for shared provider
      updateApiKeyHint(providerSelect.value, apiKeyHint);

      // Update hints for agent providers
      AGENT_ROLES.forEach(function (role) {
        var prov = document.getElementById(role + "-provider");
        var hint = document.getElementById(role + "-api-key-hint");
        updateApiKeyHint(prov.value, hint);
      });
    } catch (err) {
      console.error("Failed to load env keys:", err);
    }
  }

  function updateApiKeyHint(provider, hintEl) {
    if (!hintEl) return;
    var info = envKeys[provider];
    if (info && info.configured) {
      hintEl.textContent = "\u2713 " + info.prefix;
      hintEl.className = "hint hint-ok";
    } else {
      hintEl.textContent = "not in env";
      hintEl.className = "hint hint-missing";
    }
  }

  // ---- Model fetching and population ---------------------------------

  async function fetchModels(provider, apiKey) {
    try {
      var res = await fetch("/api/models", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ provider: provider, api_key: apiKey || "" }),
      });
      var data = await res.json();
      return data.models || [];
    } catch (err) {
      console.error("Failed to fetch models:", err);
      return [];
    }
  }

  function populateModelSelect(selectEl, models, defaultModel) {
    var currentValue = selectEl.value;
    selectEl.innerHTML = "";

    for (var i = 0; i < models.length; i++) {
      var opt = document.createElement("option");
      opt.value = models[i];
      opt.textContent = models[i];
      selectEl.appendChild(opt);
    }

    // Add custom option
    var customOpt = document.createElement("option");
    customOpt.value = "__custom__";
    customOpt.textContent = "Custom...";
    selectEl.appendChild(customOpt);

    // Try to preserve current selection, otherwise select default
    if (models.indexOf(currentValue) !== -1) {
      selectEl.value = currentValue;
    } else if (defaultModel && models.indexOf(defaultModel) !== -1) {
      selectEl.value = defaultModel;
    } else if (models.length > 0) {
      selectEl.value = models[0];
    }
  }

  async function fetchAndPopulateModels(provider, apiKey, selectEl, customEl) {
    var models = await fetchModels(provider, apiKey);
    populateModelSelect(selectEl, models, DEFAULT_MODELS[provider]);
    customEl.classList.add("hidden");
  }

  function initModels(providerEl, modelEl, customEl, keyEl, defaultProvider) {
    fetchAndPopulateModels(defaultProvider, "", modelEl, customEl);
  }

  // ---- Provider / model change handlers ------------------------------

  function onProviderChange(providerEl, modelEl, customEl, keyEl, hintEl) {
    var provider = providerEl.value;
    fetchAndPopulateModels(provider, keyEl ? keyEl.value.trim() : "", modelEl, customEl);
    updateApiKeyHint(provider, hintEl);
  }

  function onModelSelectChange(selectEl, customEl) {
    if (selectEl.value === "__custom__") {
      customEl.classList.remove("hidden");
      customEl.focus();
    } else {
      customEl.classList.add("hidden");
    }
  }

  function getModelValue(selectEl, customEl) {
    if (selectEl.value === "__custom__") {
      return customEl.value.trim();
    }
    return selectEl.value;
  }

  // ---- Provider mode toggle ------------------------------------------

  function onProviderModeChange() {
    if (providerMode.value === "multi") {
      singleConfig.classList.add("hidden");
      multiConfig.classList.remove("hidden");
      // Initialize multi-agent selects with current shared config
      var sharedProvider = providerSelect.value;
      var sharedModel = getModelValue(modelSelect, modelCustom);
      var sharedKey = apiKeyInput.value.trim();

      AGENT_ROLES.forEach(function (role) {
        var prov = document.getElementById(role + "-provider");
        var mod = document.getElementById(role + "-model");
        var modCustom = document.getElementById(role + "-model-custom");
        var key = document.getElementById(role + "-api-key");
        var hint = document.getElementById(role + "-api-key-hint");

        prov.value = sharedProvider;
        key.value = sharedKey;
        fetchAndPopulateModels(sharedProvider, sharedKey, mod, modCustom).then(function () {
          // Try to set the same model
          if (mod.querySelector('option[value="' + sharedModel + '"]')) {
            mod.value = sharedModel;
          }
        });
        updateApiKeyHint(sharedProvider, hint);
      });
    } else {
      singleConfig.classList.remove("hidden");
      multiConfig.classList.add("hidden");
    }
  }

  // ---- Problem source toggle -----------------------------------------

  function onProblemSourceChange() {
    builtinGroup.classList.add("hidden");
    customGroup.classList.add("hidden");
    resumeGroup.classList.add("hidden");

    if (problemSource.value === "custom") {
      customGroup.classList.remove("hidden");
    } else if (problemSource.value === "resume") {
      resumeGroup.classList.remove("hidden");
      loadPreviousRuns();
    } else {
      builtinGroup.classList.remove("hidden");
    }
  }

  // ---- Previous runs (resume) ----------------------------------------

  async function loadPreviousRuns() {
    try {
      var res = await fetch("/api/runs");
      previousRuns = await res.json();
      resumeSelect.innerHTML = "";

      if (previousRuns.length === 0) {
        var emptyOpt = document.createElement("option");
        emptyOpt.value = "";
        emptyOpt.textContent = "No previous runs found";
        resumeSelect.appendChild(emptyOpt);
        resumeInfo.classList.add("hidden");
        return;
      }

      for (var i = 0; i < previousRuns.length; i++) {
        var run = previousRuns[i];
        var opt = document.createElement("option");
        opt.value = run.run_id;

        var status = run.success === true ? "\u2713" : run.success === false ? "\u2717" : "?";
        var pid = run.problem_id || "unknown";
        var roadmaps = run.total_roadmaps !== undefined ? run.total_roadmaps + " rm" : "";

        opt.textContent = run.timestamp + "  " + status + "  " + pid + (roadmaps ? "  (" + roadmaps + ")" : "");
        resumeSelect.appendChild(opt);
      }

      // Auto-select first and show info
      onResumeSelectChange();
    } catch (err) {
      console.error("Failed to load previous runs:", err);
      resumeSelect.innerHTML = '<option value="">Failed to load</option>';
    }
  }

  function onResumeSelectChange() {
    var runId = resumeSelect.value;
    if (!runId) {
      resumeInfo.classList.add("hidden");
      resumeProblemOverride.classList.add("hidden");
      return;
    }

    var run = null;
    for (var i = 0; i < previousRuns.length; i++) {
      if (previousRuns[i].run_id === runId) {
        run = previousRuns[i];
        break;
      }
    }

    if (!run) {
      resumeInfo.classList.add("hidden");
      resumeProblemOverride.classList.add("hidden");
      return;
    }

    resumeInfo.classList.remove("hidden");

    // Problem text
    var hasProblem = !!(run.problem || run.problem_id);
    var problemText = run.problem || run.problem_id || "Unknown problem";
    resumeProblemText.textContent = problemText.length > 120
      ? problemText.substring(0, 117) + "..."
      : problemText;

    // Status badge
    if (run.success === true) {
      resumeStatus.textContent = "SUCCESS";
      resumeStatus.className = "badge badge-success";
    } else if (run.success === false) {
      resumeStatus.textContent = "INCOMPLETE";
      resumeStatus.className = "badge badge-fail";
    } else {
      resumeStatus.textContent = "NO SUMMARY";
      resumeStatus.className = "badge badge-unknown";
    }

    // Roadmaps badge
    if (run.total_roadmaps !== undefined) {
      resumeRoadmaps.textContent = run.total_roadmaps + " roadmap(s)";
      resumeRoadmaps.className = "badge";
      resumeRoadmaps.classList.remove("hidden");
    } else if (run.memo_proved !== undefined) {
      resumeRoadmaps.textContent = run.memo_proved + " proved";
      resumeRoadmaps.className = "badge";
      resumeRoadmaps.classList.remove("hidden");
    } else {
      resumeRoadmaps.classList.add("hidden");
    }

    // Show problem picker if run has no summary (crashed run)
    if (!hasProblem) {
      resumeProblemOverride.classList.remove("hidden");
      // Populate with the same problem list
      if (resumeProblemSelect.options.length <= 1) {
        resumeProblemSelect.innerHTML = "";
        for (var i = 0; i < problems.length; i++) {
          var p = problems[i];
          var opt = document.createElement("option");
          opt.value = p.problem_id;
          opt.textContent = "L" + p.difficulty_level + " \u00B7 " + p.problem_id;
          resumeProblemSelect.appendChild(opt);
        }
      }
    } else {
      resumeProblemOverride.classList.add("hidden");
    }
  }

  resumeSelect.addEventListener("change", onResumeSelectChange);

  // ---- Start a run ---------------------------------------------------

  async function startRun() {
    var body = {};

    // Provider config
    if (providerMode.value === "multi") {
      body.multi_agent = true;
      // Use first agent's provider as the shared default
      body.provider = document.getElementById("thinking-provider").value;
      body.model = getModelValue(
        document.getElementById("thinking-model"),
        document.getElementById("thinking-model-custom")
      );
      body.api_key = document.getElementById("thinking-api-key").value.trim();

      AGENT_ROLES.forEach(function (role) {
        body[role] = {
          provider: document.getElementById(role + "-provider").value,
          model: getModelValue(
            document.getElementById(role + "-model"),
            document.getElementById(role + "-model-custom")
          ),
          api_key: document.getElementById(role + "-api-key").value.trim(),
        };
      });
    } else {
      body.multi_agent = false;
      body.provider = providerSelect.value;
      body.model = getModelValue(modelSelect, modelCustom);
      body.api_key = apiKeyInput.value.trim();
    }

    // Problem
    if (problemSource.value === "resume") {
      var selectedRunId = resumeSelect.value;
      if (!selectedRunId) {
        alert("Please select a previous run to resume.");
        return;
      }
      body.resume_run_id = selectedRunId;
      // If the problem override selector is visible, send the selected problem_id
      if (!resumeProblemOverride.classList.contains("hidden") && resumeProblemSelect.value) {
        body.problem_id = resumeProblemSelect.value;
      }
    } else if (problemSource.value === "custom") {
      var question = customQuestion.value.trim();
      if (!question) {
        alert("Please enter a math problem.");
        return;
      }
      body.problem_id = null;
      body.custom_question = question;
      body.custom_domain = customDomain.value.trim() || "general";
    } else {
      body.problem_id = problemSelect.value;
      if (!body.problem_id) {
        alert("Please select a problem.");
        return;
      }
    }

    // Options
    body.skip_lean = skipLeanCheck.checked;
    body.N = parseInt(hyperN.value, 10) || 7;
    body.C = parseInt(hyperC.value, 10) || 8;
    body.K = parseInt(hyperK.value, 10) || 3;

    runBtn.disabled = true;
    runBtn.textContent = problemSource.value === "resume" ? "Resuming..." : "Running...";

    try {
      var res = await fetch("/api/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      var data = await res.json();
      if (!res.ok) {
        alert("Error: " + (data.error || "Unknown error"));
        runBtn.disabled = false;
        runBtn.textContent = "Run";
      }
    } catch (err) {
      alert("Network error: " + err.message);
      runBtn.disabled = false;
      runBtn.textContent = "Run";
    }
  }

  // ---- WebSocket connection ------------------------------------------

  function connectWebSocket() {
    var protocol = location.protocol === "https:" ? "wss:" : "ws:";
    var url = protocol + "//" + location.host + "/ws";

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
        var msg = JSON.parse(event.data);
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

  // ---- Render MEMO state (centre panel) ------------------------------

  function renderMemo(data) {
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

      for (var s = 0; s < data.current_roadmap.length; s++) {
        var step = data.current_roadmap[s];
        var li = document.createElement("li");
        li.className = "status-" + step.status;

        var num = document.createElement("span");
        num.className = "step-number";
        num.textContent = step.step_index;

        var desc = document.createElement("span");
        desc.className = "step-desc";
        desc.textContent = step.description;

        var statusBadge = document.createElement("span");
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

      for (var p = 0; p < data.proved_propositions.length; p++) {
        var prop = data.proved_propositions[p];
        var pli = document.createElement("li");
        var idSpan = document.createElement("span");
        idSpan.className = "prop-id";
        idSpan.textContent = prop.prop_id + ":";

        var stmtText = document.createTextNode(" " + prop.statement);

        var srcSpan = document.createElement("span");
        srcSpan.className = "prop-source";
        srcSpan.textContent = "(" + prop.source + ")";

        pli.appendChild(idSpan);
        pli.appendChild(stmtText);
        pli.appendChild(srcSpan);
        propositionsList.appendChild(pli);
      }
    } else {
      propositionsSection.classList.add("hidden");
    }

    // Complete proof
    if (data.complete_proof) {
      proofSection.classList.remove("hidden");
      proofContent.textContent = data.complete_proof;
    } else {
      proofSection.classList.add("hidden");
    }

    // Previous roadmaps
    if (data.previous_roadmaps && data.previous_roadmaps.length > 0) {
      prevRoadmapsSection.classList.remove("hidden");
      prevRoadmapsList.innerHTML = "";

      for (var r = 0; r < data.previous_roadmaps.length; r++) {
        var rm = data.previous_roadmaps[r];
        var div = document.createElement("div");
        div.className = "prev-roadmap";

        var nameDiv = document.createElement("div");
        nameDiv.className = "prev-roadmap-name";
        nameDiv.textContent = rm.name;

        var detailDiv = document.createElement("div");
        detailDiv.className = "prev-roadmap-detail";
        var detail = "";
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
    var entry = document.createElement("div");
    entry.className = "log-entry";

    // Timestamp
    var timeSpan = document.createElement("span");
    timeSpan.className = "log-time";
    var ts = data.timestamp ? new Date(data.timestamp * 1000) : new Date();
    timeSpan.textContent =
      pad2(ts.getHours()) +
      ":" +
      pad2(ts.getMinutes()) +
      ":" +
      pad2(ts.getSeconds());

    // Tag
    var tagSpan = document.createElement("span");
    var eventType = data.event_type || "info";
    tagSpan.className = "log-tag log-tag-" + eventType;
    var tagText = eventType;
    if (data.step !== undefined && data.step !== null && data.step !== 0) {
      tagText += " #" + data.step;
    }
    if (data.module_name) {
      tagText += " [" + data.module_name + "]";
    }
    tagSpan.textContent = tagText;

    // Content
    var contentSpan = document.createElement("span");
    contentSpan.className = "log-content";
    contentSpan.textContent = data.content || "";

    entry.appendChild(timeSpan);
    entry.appendChild(tagSpan);
    entry.appendChild(contentSpan);
    thinkingLog.appendChild(entry);

    // Auto-scroll
    thinkingBody.scrollTop = thinkingBody.scrollHeight;

    // Re-enable Run button when we see the final event
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

  function truncate(s, maxLen) {
    if (s.length <= maxLen) return s;
    return s.substring(0, maxLen - 3) + "...";
  }

  function debounce(fn, delay) {
    var timer = null;
    return function () {
      var args = arguments;
      var ctx = this;
      clearTimeout(timer);
      timer = setTimeout(function () {
        fn.apply(ctx, args);
      }, delay);
    };
  }

  // ---- Heartbeat (keep connection alive) -----------------------------

  setInterval(function () {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: "ping" }));
    }
  }, 30000);
})();
