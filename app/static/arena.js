const el = (id) => document.getElementById(id);

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
  const response = await fetch(path, {
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
  refreshIcons();
  await Promise.allSettled([loadMatch(), loadLeaderboard(), loadCalibration()]);
}

init().catch((error) => {
  el("arenaStatus").textContent = error.message;
  el("arenaForecast").innerHTML = `<div class="arena-empty error"><strong>Match analysis could not initialize.</strong><span>${escapeHtml(error.message)}</span></div>`;
});

refreshIcons();
