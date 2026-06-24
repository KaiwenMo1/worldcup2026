const el = (id) => document.getElementById(id);
let arenaLiveBoard = null;

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function refreshIcons() {
  if (window.lucide) window.lucide.createIcons();
}

async function api(path, options = {}) {
  const response = await fetch(window.wcApiUrl ? window.wcApiUrl(path) : path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.detail || payload.message || `Request failed: ${response.status}`);
  return payload;
}

function setButtonBusy(button, busy, label, busyLabel, icon) {
  button.disabled = busy;
  button.innerHTML = `<i data-lucide="${busy ? "loader-circle" : icon}"></i><span>${busy ? busyLabel : label}</span>`;
  refreshIcons();
}

function percent(value) {
  const number = Number(value);
  return Number.isFinite(number) ? `${Math.round(number * 100)}%` : "-";
}

function dateLabel(value) {
  if (!value) return "time TBD";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

function matchScore(row) {
  const scoreA = row.team_a_score;
  const scoreB = row.team_b_score;
  if (scoreA === null || scoreA === undefined || scoreB === null || scoreB === undefined) return dateLabel(row.kickoff_utc);
  return `${scoreA}-${scoreB}`;
}

function liveStatusLabel(row) {
  if (row.status === "completed" || row.status === "final" || row.is_final) return "Final";
  if (row.status === "live" || row.is_live) return row.match_time ? `Live ${row.match_time}'` : "Live";
  if (row.status === "awaiting_result") return "Awaiting final";
  return "Scheduled";
}

function liveBoardRows(board) {
  const current = (board?.current || []).filter((row) => row.status === "live" || row.is_live).slice(0, 3);
  const completed = (board?.recent_completed || []).slice(0, 9);
  return [...current, ...completed].slice(0, 10);
}

function renderLiveScoreBoard(board) {
  const target = el("arenaLatestResults");
  if (!target) return;
  arenaLiveBoard = board || null;
  const updated = board?.updated_at ? `Updated ${dateLabel(board.updated_at)}` : "Not synced";
  el("arenaLiveUpdated").textContent = `${updated} · ${board?.completed_count || 0} final`;
  const rows = liveBoardRows(board);
  target.innerHTML = rows.length ? rows.map((row) => `
    <button class="latest-result-card ${row.status === "live" ? "live" : ""}" type="button" data-live-match="${escapeHtml(row.match_id || row.provider_match_id || "")}">
      <span>${escapeHtml(liveStatusLabel(row))}</span>
      <strong>${escapeHtml(row.team_a)} <b>${escapeHtml(matchScore(row))}</b> ${escapeHtml(row.team_b)}</strong>
      <small>${escapeHtml(row.group ? `Group ${row.group}` : row.stage || row.source || "World Cup")}</small>
    </button>
  `).join("") : `<div class="latest-results-empty">No completed official scores are synced yet.</div>`;
  refreshIcons();
}

async function loadLiveScoreBoard() {
  try {
    const board = await api("/api/ai/live-board");
    renderLiveScoreBoard(board);
    return board;
  } catch (error) {
    el("arenaLatestResults").innerHTML = `<div class="latest-results-empty error">${escapeHtml(error.message)}</div>`;
    return null;
  }
}

function applyLiveBoardMatch(matchId) {
  if (!matchId || !arenaLiveBoard) return;
  const rows = [
    ...(arenaLiveBoard.current || []),
    ...(arenaLiveBoard.recent_completed || []),
    ...(arenaLiveBoard.upcoming || []),
  ];
  const match = rows.find((row) => String(row.match_id || row.provider_match_id || "") === String(matchId));
  if (!match) return;
  el("arenaTeamA").value = match.team_a;
  el("arenaTeamB").value = match.team_b;
  el("arenaStage").value = String(match.stage || "").toLowerCase().includes("knockout") ? "knockout" : "group";
  el("arenaMatchId").value = String(match.match_id || `${match.team_a}-${match.team_b}`).trim();
  resultOptions();
  if (match.team_a_score !== null && match.team_a_score !== undefined) el("arenaScoreA").value = match.team_a_score;
  if (match.team_b_score !== null && match.team_b_score !== undefined) el("arenaScoreB").value = match.team_b_score;
  if (match.team_a_score !== null && match.team_a_score !== undefined && match.team_b_score !== null && match.team_b_score !== undefined) {
    const result = Number(match.team_a_score) === Number(match.team_b_score)
      ? "Draw"
      : Number(match.team_a_score) > Number(match.team_b_score) ? match.team_a : match.team_b;
    el("arenaResult").value = result;
    el("arenaStatus").textContent = `Observed ${liveStatusLabel(match)}: ${match.team_a} ${match.team_a_score}-${match.team_b_score} ${match.team_b}`;
  }
  loadMatch().catch((error) => { el("arenaStatus").textContent = error.message; });
}

function resultOptions() {
  const teamA = el("arenaTeamA").value;
  const teamB = el("arenaTeamB").value;
  const previous = el("arenaResult").value;
  el("arenaResult").innerHTML = [teamA, "Draw", teamB]
    .map((value) => `<option value="${escapeHtml(value)}">${escapeHtml(value)}</option>`)
    .join("");
  if ([teamA, "Draw", teamB].includes(previous)) el("arenaResult").value = previous;
}

function syncMatchId() {
  const slug = (value) => String(value || "").trim().toUpperCase().replaceAll(/[^A-Z0-9]+/g, "-").replaceAll(/^-|-$/g, "");
  el("arenaMatchId").value = `${slug(el("arenaTeamA").value)}-${slug(el("arenaTeamB").value)}-ANALYSIS`;
}

function listHtml(items, fallback) {
  if (!items?.length) return `<div class="arena-empty compact"><span>${escapeHtml(fallback)}</span></div>`;
  return items.map((item) => `<div class="arena-list-row"><i data-lucide="chevron-right"></i><span>${escapeHtml(item)}</span></div>`).join("");
}

function targetView(target) {
  if (!target) return { pick: "Unavailable", score: "-", confidence: null, qualification: null };
  return {
    pick: target.regular_time_90?.pick || "Unavailable",
    score: target.regular_time_90?.score || "-",
    confidence: target.regular_time_90?.confidence,
    qualification: target.qualification?.pick || null,
  };
}

function agentRow(name, label, pick, score, confidence, reason, tone = "") {
  return `
    <article class="arena-agent-row ${tone}">
      <div class="arena-agent-name"><span>${escapeHtml(label)}</span><strong>${escapeHtml(name)}</strong></div>
      <div class="arena-agent-call"><strong>${escapeHtml(pick || "Unavailable")}</strong><span>${escapeHtml(score || "-")}</span></div>
      <p>${escapeHtml(reason || "No supporting explanation is available.")}</p>
      <b>${confidence == null ? "-" : percent(confidence)}</b>
    </article>
  `;
}

function rowsFromRun(run) {
  if (!run) return "";
  const probabilities = run.base_forecast?.probabilities || {};
  const baseChoices = [
    [run.team_a, Number(probabilities.team_a_win || 0)],
    ["Draw", Number(probabilities.draw || 0)],
    [run.team_b, Number(probabilities.team_b_win || 0)],
  ].sort((a, b) => b[1] - a[1]);
  const baseScore = run.base_forecast?.scorelines?.[0]
    ? `${run.base_forecast.scorelines[0].team_a_score}-${run.base_forecast.scorelines[0].team_b_score}`
    : "-";
  const expert = targetView(run.expert?.prediction_target);
  const kevin = targetView(run.kevin?.prediction_target);
  const upset = targetView(run.upset?.prediction_target);
  const final = targetView(run.final_forecast?.final_prediction);
  return [
    agentRow("Base ML Model", "Probability anchor", baseChoices[0][0], baseScore, baseChoices[0][1] / 100, "Existing ensemble and exact-score distribution.", "base"),
    ...(run.model_opinions || []).map((opinion) => agentRow(
      `${opinion.provider_name} · ${opinion.model}`,
      "External model opinion",
      opinion.regular_time_pick,
      opinion.regular_time_score,
      opinion.confidence,
      opinion.core_reason,
      "expert",
    )),
    agentRow("Expert Agent", "Tactical read", expert.pick, expert.score, run.expert?.confidence, run.expert?.expected_match_shape, "expert"),
    agentRow("Kevin Agent", "Decisive intuition", kevin.pick, kevin.score, run.kevin?.confidence, `${run.kevin?.bold_pick || ""}. ${run.kevin?.core_reason || ""}`, "kevin"),
    agentRow("Upset Agent", "Underdog path", upset.pick, upset.score, run.upset?.confidence, run.upset?.upset_path, "upset"),
    agentRow("Skeptic Agent", "Audit layer", "No pick", run.skeptic?.overall_risk_level || "-", null, (run.skeptic?.missing_data || []).concat(run.skeptic?.unsupported_assumptions || [])[0] || "No major audit warning.", "skeptic"),
    agentRow("Final Forecast", "Aggregated call", final.pick, final.score, run.final_forecast?.final_confidence, run.final_forecast?.top_reasons?.[0], "final"),
  ].join("");
}

function rowsFromRecords(records = []) {
  return records.map((record) => agentRow(
    record.agent_name,
    record.agent_name === "Final Forecast Agent" ? "Aggregated call" : "Saved forecast",
    record.regular_time_pick,
    record.regular_time_score,
    record.confidence,
    record.core_reason,
    record.agent_name === "Final Forecast Agent" ? "final" : "",
  )).join("");
}

function renderPublicCard(card) {
  if (!card?.available || !card.markdown) {
    el("arenaPublicCard").innerHTML = `<div class="arena-empty compact"><span>No public card published. Analyze the match, then publish the saved version.</span></div>`;
    return;
  }
  const preview = card.markdown
    .split("\n")
    .filter((line) => line.trim() && !line.startsWith("---"))
    .slice(0, 14)
    .join("\n");
  el("arenaPublicCard").innerHTML = `<pre>${escapeHtml(preview)}</pre><small>${escapeHtml(card.path || "")}</small>`;
}

function renderArena(payload) {
  const run = payload?.run || null;
  const match = payload?.match || payload || {};
  const records = match.records || [];
  const finalRecord = records.find((record) => record.agent_name === "Final Forecast Agent");
  const final = run?.final_forecast;
  const target = final ? targetView(final.final_prediction) : {
    pick: finalRecord?.regular_time_pick || "No forecast yet",
    score: finalRecord?.regular_time_score || "-",
    confidence: finalRecord?.confidence,
    qualification: finalRecord?.qualification_pick,
  };
  const reasons = final?.top_reasons || (finalRecord ? [finalRecord.core_reason] : []);
  const fragile = final?.fragile_assumptions || finalRecord?.fragile_assumptions || [];
  const watch = final?.what_to_watch || [];
  const warnings = [...(run?.fallback_notes || []), ...(match.warnings || [])];
  const confidence = final?.final_confidence ?? target.confidence;

  el("arenaVersion").textContent = match.version ? `Version ${match.version} · ${records[0]?.status || "saved"}` : "No saved version";
  el("arenaStatus").textContent = warnings[0] || (match.found ? `Saved run, version ${match.version}` : "Ready for a matchup");
  el("arenaForecast").innerHTML = `
    <div class="arena-final-call">
      <div class="arena-final-label"><span>Final 90-minute call</span><small>${escapeHtml(run?.stage || match.stage || el("arenaStage").value)}</small></div>
      <div class="arena-score-call"><strong>${escapeHtml(target.pick)}</strong><b>${escapeHtml(target.score)}</b></div>
      <div class="arena-confidence"><span>Confidence</span><strong>${confidence == null ? "-" : percent(confidence)}</strong><div><i style="width:${Math.min(100, Number(confidence || 0) * 100)}%"></i></div></div>
      <p>${escapeHtml(reasons[0] || "Analyze the match to generate an audited forecast.")}</p>
      ${target.qualification ? `<div class="arena-qualification"><span>Qualification</span><strong>${escapeHtml(target.qualification)}</strong></div>` : ""}
    </div>
    <div class="arena-forecast-note">
      <i data-lucide="${warnings.length ? "triangle-alert" : "shield-check"}"></i>
      <div><strong>${warnings.length ? "Data notes" : "Forecast guardrail"}</strong><span>${escapeHtml(warnings[0] || "Technical entertainment forecast. Every call remains uncertain.")}</span></div>
    </div>
  `;
  el("arenaAgentBattle").innerHTML = rowsFromRun(run) || rowsFromRecords(records) || `<div class="arena-empty compact"><span>No agent outputs are saved for this match.</span></div>`;
  el("arenaFragile").innerHTML = listHtml(fragile, "No fragile assumptions are available.");
  el("arenaWatch").innerHTML = listHtml(watch, run ? "No additional watch signals were produced." : "Detailed watch signals are available immediately after a new run.");
  renderPublicCard(match.public_card);
  refreshIcons();
}

function renderLeaderboard(data) {
  const rows = data?.leaderboard || [];
  el("arenaLeaderboard").innerHTML = rows.length ? `
    <table class="arena-table"><thead><tr><th>Agent</th><th>Matches</th><th>Points</th><th>Result hit</th><th>Exact</th><th>Confidence</th></tr></thead><tbody>
      ${rows.map((row, index) => `<tr><td><span>${index + 1}</span><strong>${escapeHtml(row.agent_name)}</strong></td><td>${row.matches_predicted}</td><td><b>${row.total_points}</b></td><td>${percent(row.winner_accuracy)}</td><td>${row.exact_score_hits}</td><td>${percent(row.average_confidence)}${row.calibration_warning ? `<small>${escapeHtml(row.calibration_warning.replaceAll("_", " "))}</small>` : ""}</td></tr>`).join("")}
    </tbody></table>
  ` : `<div class="arena-empty compact"><span>No completed match evaluations yet.</span></div>`;
}

function renderCalibration(data) {
  const performance = data?.agent_performance || [];
  el("arenaCalibration").innerHTML = performance.length ? performance.map((row) => `
    <div class="arena-calibration-row">
      <strong>${escapeHtml(row.agent_name)}</strong>
      <span>${row.warnings?.length ? row.warnings.map((warning) => escapeHtml(warning.replaceAll("_", " "))).join(" · ") : "No current warning"}</span>
      <b>${percent(row.winner_accuracy)}</b>
    </div>
  `).join("") : `<div class="arena-empty compact"><span>Calibration needs completed match evaluations.</span></div>`;
}

async function loadLeaderboard() {
  try {
    renderLeaderboard(await api("/api/prediction-arena/leaderboard"));
  } catch (error) {
    el("arenaLeaderboard").innerHTML = `<div class="arena-empty compact error"><span>${escapeHtml(error.message)}</span></div>`;
  }
}

async function loadCalibration() {
  try {
    renderCalibration(await api("/api/prediction-arena/calibration"));
  } catch (error) {
    el("arenaCalibration").innerHTML = `<div class="arena-empty compact error"><span>${escapeHtml(error.message)}</span></div>`;
  }
}

async function loadMatch() {
  const matchId = el("arenaMatchId").value.trim();
  if (matchId) renderArena(await api(`/api/prediction-arena/match/${encodeURIComponent(matchId)}`));
}

async function runArena() {
  const button = el("arenaRunBtn");
  setButtonBusy(button, true, "Analyze Match", "Analyzing", "sparkles");
  el("arenaStatus").textContent = "Building match analysis";
  try {
    renderArena(await api("/api/prediction-arena/run", {
      method: "POST",
      body: JSON.stringify({
        match_id: el("arenaMatchId").value.trim(),
        team_a: el("arenaTeamA").value,
        team_b: el("arenaTeamB").value,
        stage: el("arenaStage").value,
      }),
    }));
  } catch (error) {
    el("arenaStatus").textContent = "Match analysis failed";
    el("arenaForecast").innerHTML = `<div class="arena-empty error"><strong>Match analysis could not run.</strong><span>${escapeHtml(error.message)}</span></div>`;
  } finally {
    setButtonBusy(button, false, "Analyze Match", "Analyzing", "sparkles");
  }
}

async function matchAction(buttonId, endpoint, label, busyLabel, icon) {
  const button = el(buttonId);
  setButtonBusy(button, true, label, busyLabel, icon);
  try {
    renderArena(await api(endpoint, {
      method: "POST",
      body: JSON.stringify({ match_id: el("arenaMatchId").value.trim() }),
    }));
  } catch (error) {
    el("arenaStatus").textContent = error.message;
  } finally {
    setButtonBusy(button, false, label, busyLabel, icon);
  }
}

async function settleArena() {
  const button = el("arenaSettleBtn");
  setButtonBusy(button, true, "Evaluate Result", "Evaluating", "clipboard-check");
  try {
    const qualification = el("arenaQualification").value.trim();
    const data = await api("/api/prediction-arena/settle", {
      method: "POST",
      body: JSON.stringify({
        match_id: el("arenaMatchId").value.trim(),
        actual_score: `${Number(el("arenaScoreA").value)}-${Number(el("arenaScoreB").value)}`,
        regular_time_result: el("arenaResult").value,
        qualification_result: qualification || null,
      }),
    });
    renderArena(data);
    renderLeaderboard(data.leaderboard);
    await loadCalibration();
  } catch (error) {
    el("arenaStatus").textContent = error.message;
  } finally {
    setButtonBusy(button, false, "Evaluate Result", "Evaluating", "clipboard-check");
  }
}

async function init() {
  const teams = await api("/api/teams");
  const options = teams.teams.map((team) => `<option value="${escapeHtml(team.name)}">${escapeHtml(team.name)}</option>`).join("");
  el("arenaTeamA").innerHTML = options;
  el("arenaTeamB").innerHTML = options;
  el("arenaTeamA").value = teams.teams.some((team) => team.name === "France") ? "France" : teams.teams[0]?.name;
  el("arenaTeamB").value = teams.teams.some((team) => team.name === "Brazil") ? "Brazil" : teams.teams[1]?.name;
  resultOptions();
  syncMatchId();
  el("arenaTeamA").addEventListener("change", () => { resultOptions(); syncMatchId(); });
  el("arenaTeamB").addEventListener("change", () => { resultOptions(); syncMatchId(); });
  el("arenaMatchId").addEventListener("change", () => loadMatch().catch((error) => { el("arenaStatus").textContent = error.message; }));
  el("arenaRunBtn").addEventListener("click", runArena);
  el("arenaLockBtn").addEventListener("click", () => matchAction("arenaLockBtn", "/api/prediction-arena/lock", "Lock", "Locking", "lock-keyhole"));
  el("arenaPublishBtn").addEventListener("click", () => matchAction("arenaPublishBtn", "/api/prediction-arena/publish-card", "Publish", "Publishing", "send"));
  el("arenaSettleBtn").addEventListener("click", settleArena);
  el("arenaRefreshBoardBtn").addEventListener("click", () => Promise.allSettled([loadLeaderboard(), loadCalibration()]));
  el("arenaLatestResults").addEventListener("click", (event) => {
    const card = event.target.closest("[data-live-match]");
    if (card) applyLiveBoardMatch(card.dataset.liveMatch);
  });
  refreshIcons();
  await Promise.allSettled([loadLiveScoreBoard(), loadMatch(), loadLeaderboard(), loadCalibration()]);
}

init().catch((error) => {
  el("arenaStatus").textContent = error.message;
  el("arenaForecast").innerHTML = `<div class="arena-empty error"><strong>Match analysis could not initialize.</strong><span>${escapeHtml(error.message)}</span></div>`;
});

refreshIcons();
