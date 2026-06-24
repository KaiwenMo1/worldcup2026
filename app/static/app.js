const state = {
  teams: [],
  venues: [],
  penaltyOptions: { kickers: [], keepers: [] },
  venueMap: null,
  running: false,
};

const el = (id) => document.getElementById(id);

function refreshIcons() {
  if (window.lucide) window.lucide.createIcons();
}

function setButtonBusy(button, busy, label, busyLabel, icon = null) {
  button.disabled = busy;
  const text = busy ? busyLabel : label;
  button.innerHTML = `${icon ? `<i data-lucide="${busy ? "loader-circle" : icon}"></i>` : ""}<span>${text}</span>`;
  refreshIcons();
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function teamLabel(team) {
  return `${team.flag || ""} ${team.name}`;
}

function flagHtml(team) {
  const label = team.flag || "";
  if (!team.flag_image) {
    return `<span class="flag text-flag">${label}</span>`;
  }
  return `<span class="flag"><img src="${team.flag_image}" alt="${label}" onerror="this.remove(); this.parentElement.textContent='${label}'" /></span>`;
}

function teamHtml(team) {
  return `${flagHtml(team)}<span>${team.name}</span>`;
}

function currentScenario(options = {}) {
  const includeVenue = options.includeVenue ?? true;
  const scenario = {
    weather: el("weather").value,
    travel: Number(el("travel").value),
    fatigue: Number(el("fatigue").value),
    home_advantage: Number(el("homeAdvantage").value),
  };
  if (includeVenue) scenario.venue = el("venueSelect").value;
  return scenario;
}

async function api(path, options = {}) {
  const response = await fetch(window.wcApiUrl ? window.wcApiUrl(path) : path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text);
  }
  return response.json();
}

function renderGroups(groups) {
  el("groups").innerHTML = Object.entries(groups)
    .map(([group, teams]) => `
      <div class="group-card">
        <h3>Group ${group}</h3>
        ${teams.map((team) => `<div class="team-row">${teamHtml(team)}<span class="rank">${team.rank}</span></div>`).join("")}
      </div>
    `)
    .join("");
}

function metricValue(value, digits = 3) {
  return Number.isFinite(Number(value)) ? Number(value).toFixed(digits) : "-";
}

function renderModelReport(payload) {
  if (!payload.available || !payload.report) {
    el("modelReportBody").innerHTML = `<div class="empty">Train the ensemble to publish its chronological report.</div>`;
    return;
  }
  const report = payload.report;
  const periods = report.periods;
  const ensemble = report.models.ensemble;
  const rows = Object.entries(report.models)
    .map(([name, metrics]) => `
      <tr class="${name === "ensemble" ? "report-winner" : ""}">
        <td>${escapeHtml(name.replaceAll("_", " "))}</td>
        <td>${metricValue(metrics.accuracy)}</td>
        <td>${metricValue(metrics.log_loss)}</td>
        <td>${metricValue(metrics.brier_score)}</td>
        <td>${metricValue(metrics.ranked_probability_score)}</td>
      </tr>
    `)
    .join("");
  el("reportPeriod").textContent = `${periods.test.from} to ${periods.test.through} · ${periods.test.rows} unseen matches`;
  el("modelReportBody").innerHTML = `
    <div class="report-scoreboard">
      <div><span>Accuracy</span><strong>${metricValue(ensemble.accuracy)}</strong><small>3-way result</small></div>
      <div><span>Log loss</span><strong>${metricValue(ensemble.log_loss)}</strong><small>lower is better</small></div>
      <div><span>Brier score</span><strong>${metricValue(ensemble.brier_score)}</strong><small>probability error</small></div>
      <div><span>DC coverage</span><strong>${(report.dixon_coles_test_coverage * 100).toFixed(1)}%</strong><small>test matches</small></div>
    </div>
    <div class="report-layout">
      <div class="report-table-wrap">
        <div class="report-block-head"><strong>Component comparison</strong><span>Final chronological holdout</span></div>
        <table class="report-table">
          <thead><tr><th>Model</th><th>Accuracy</th><th>Log loss</th><th>Brier</th><th>RPS</th></tr></thead>
          <tbody>${rows}</tbody>
        </table>
        <div class="report-periods">
          ${Object.entries(periods).map(([name, period]) => `
            <div><span>${name}</span><strong>${period.rows} matches</strong><small>${period.from} → ${period.through}</small></div>
          `).join("")}
        </div>
      </div>
      <div class="report-chart-wrap">
        <div class="report-block-head"><strong>Probability calibration</strong><span>Predicted vs observed</span></div>
        <div id="calibrationChart" class="calibration-chart"></div>
      </div>
    </div>
    <div class="feature-contract">
      <i data-lucide="shield-check"></i>
      <div>
        <strong>Leakage-safe historical features</strong>
        <span>${escapeHtml(report.historical_feature_contract.note)}</span>
      </div>
      <b>${report.historical_feature_contract.included.length} pre-match signals</b>
    </div>
  `;
  refreshIcons();
  window.setTimeout(() => drawCalibrationChart(report.calibration), 0);
}

function drawCalibrationChart(calibration) {
  if (!window.echarts || !el("calibrationChart")) return;
  const chart = echarts.init(el("calibrationChart"));
  chart.setOption({
    animationDuration: 500,
    grid: { left: 42, right: 18, top: 22, bottom: 38 },
    tooltip: {
      formatter: (point) => `Predicted ${(point.value[0] * 100).toFixed(1)}%<br/>Observed ${(point.value[1] * 100).toFixed(1)}%`,
    },
    xAxis: { type: "value", min: 0, max: 1, name: "Predicted", axisLabel: { formatter: (v) => `${v * 100}%` } },
    yAxis: { type: "value", min: 0, max: 1, name: "Observed", axisLabel: { formatter: (v) => `${v * 100}%` } },
    series: [
      { type: "line", data: [[0, 0], [1, 1]], symbol: "none", lineStyle: { type: "dashed", color: "#9ca2a8" } },
      {
        type: "line",
        data: calibration.map((row) => [row.predicted, row.observed]),
        symbolSize: 8,
        lineStyle: { color: "#0071e3", width: 3 },
        itemStyle: { color: "#0071e3" },
      },
    ],
  });
}

function renderBracket(bracket) {
  el("championMetric").innerHTML = `${flagHtml(bracket.champion)} <span>${bracket.champion.name}</span>`;
  el("bracketSub").innerHTML = `${flagHtml(bracket.champion)} <span>${bracket.champion.name}</span>`;
  const matchById = Object.fromEntries(
    bracket.rounds.flatMap((round) => round.matches).map((match) => [match.id, match])
  );
  const byIds = (ids) => ids.map((id) => matchById[id]).filter(Boolean);
  const finalMatch = matchById[104] || matchById[103] || bracket.rounds.at(-1).matches[0];
  el("bracket").innerHTML = `
    <div class="bracket-stage">
      ${renderRoundColumn("R32", byIds([74, 77, 73, 75, 83, 84, 81, 82]))}
      ${renderRoundColumn("R16", byIds([89, 90, 93, 94]))}
      ${renderRoundColumn("QF", byIds([97, 98]))}
      ${renderRoundColumn("SF", byIds([101]))}
      <div class="final-column">
        <div class="trophy">★</div>
        ${renderMatchCard(finalMatch, true)}
      </div>
      ${renderRoundColumn("SF", byIds([102]), "right")}
      ${renderRoundColumn("QF", byIds([99, 100]), "right")}
      ${renderRoundColumn("R16", byIds([91, 92, 95, 96]), "right")}
      ${renderRoundColumn("R32", byIds([76, 78, 79, 80, 86, 88, 85, 87]), "right")}
    </div>
  `;
}

function renderRoundColumn(title, matches, side = "left") {
  return `
    <div class="round ${side}">
      <div class="round-title">${title}</div>
      <div class="round-stack">
        ${matches.map((match) => renderMatchCard(match)).join("")}
      </div>
    </div>
  `;
}

function renderMatchCard(match, isFinal = false) {
  const aWinner = match.winner === match.team_a.name;
  const bWinner = match.winner === match.team_b.name;
  const meta = [
    match.id ? `M${match.id}` : "",
    match.kickoff_local ? dateLabel(match.kickoff_local) : "",
    match.venue || "",
  ].filter(Boolean);
  return `
    <div class="match-card ${isFinal ? "final-card" : ""}">
      <div class="match-meta">
        <span>${escapeHtml(meta[0] || "")}</span>
        <span>${escapeHtml(meta.slice(1).join(" · "))}</span>
      </div>
      <div class="team-row ${aWinner ? "winner" : ""}">
        ${flagHtml(match.team_a)}
        <span>${match.team_a.name}</span>
        <span class="score">${match.score_a}</span>
      </div>
      <div class="team-row ${bWinner ? "winner" : ""}">
        ${flagHtml(match.team_b)}
        <span>${match.team_b.name}</span>
        <span class="score">${match.score_b}</span>
      </div>
    </div>
  `;
}

function renderOdds(odds) {
  el("oddsBody").innerHTML = odds.slice(0, 24)
    .map((team) => `
      <tr>
        <td><div class="inline-team">${flagHtml(team)}<span>${team.name}</span></div><div class="bar"><span style="width:${Math.min(team.win_pct * 4, 100)}%"></span></div></td>
        <td>${team.final_pct}%</td>
        <td><strong>${team.win_pct}%</strong><span class="ci">${team.win_ci_low}-${team.win_ci_high}%</span></td>
      </tr>
    `)
    .join("");
}

function renderTopScorers(players) {
  if (!players || players.length === 0) {
    el("topScorers").innerHTML = `<div class="empty">Run simulation</div>`;
    el("topScorerMetric").textContent = "-";
    return;
  }
  const leader = players[0];
  el("topScorerMetric").innerHTML = `${flagHtml(leader)} <span>${leader.player}</span>`;
  el("topScorers").innerHTML = players.slice(0, 12)
    .map((player, index) => `
      <div class="scorer-card">
        <div class="scorer-rank">${index + 1}</div>
        <div>
          <strong class="inline-team">${flagHtml(player)}<span>${player.player}</span></strong>
          <span>${player.team} · ${player.avg_goals} avg</span>
          <div class="bar"><span style="width:${Math.min(player.golden_boot_pct * 4, 100)}%"></span></div>
        </div>
        <b>${player.golden_boot_pct}%</b>
      </div>
    `)
    .join("");
}

function populateTeams() {
  const options = state.teams
    .map((team) => `<option value="${team.name}">${team.name}</option>`)
    .join("");
  ["teamA", "teamB", "liveTeamA", "liveTeamB", "eliminateTeam", "briefTeamA", "briefTeamB", "arenaTeamA", "arenaTeamB"].forEach((id) => {
    if (el(id)) el(id).innerHTML = options;
  });
  el("teamA").value = "France";
  el("teamB").value = "Brazil";
  el("briefTeamA").value = "France";
  el("briefTeamB").value = "Brazil";
  if (el("arenaTeamA")) el("arenaTeamA").value = "France";
  if (el("arenaTeamB")) el("arenaTeamB").value = "Brazil";
  el("liveTeamA").value = "Mexico";
  el("liveTeamB").value = "South Africa";
  el("squadSelect").innerHTML = options;
  el("squadSelect").value = "France";
  el("xgTeam").innerHTML = options;
  el("xgTeam").value = "France";
}

function euros(value) {
  const amount = Number(value || 0);
  if (amount >= 1_000_000_000) return `€${(amount / 1_000_000_000).toFixed(2)}bn`;
  if (amount >= 1_000_000) return `€${(amount / 1_000_000).toFixed(1)}m`;
  if (amount >= 1_000) return `€${(amount / 1_000).toFixed(0)}k`;
  return amount ? `€${amount.toFixed(0)}` : "n/a";
}

function dateLabel(value) {
  if (!value) return "not synced";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function dateTimeLabel(value) {
  if (!value) return "not synced";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

function liveBoardMatchScore(row) {
  if (row.team_a_score === null || row.team_a_score === undefined || row.team_b_score === null || row.team_b_score === undefined) {
    return dateTimeLabel(row.kickoff_utc);
  }
  return `${row.team_a_score}-${row.team_b_score}`;
}

function liveBoardStatus(row) {
  if (row.status === "completed" || row.status === "final" || row.is_final) return "Final";
  if (row.status === "live" || row.is_live) return row.match_time ? `Live ${row.match_time}'` : "Live";
  if (row.status === "awaiting_result") return "Awaiting final";
  return "Scheduled";
}

function renderLatestResultsBoard(board) {
  const target = el("latestResultsBoard");
  if (!target) return;
  const updatedTarget = el("latestResultsUpdated");
  const current = (board?.current || []).filter((row) => row.status === "live" || row.is_live).slice(0, 3);
  const completed = (board?.recent_completed || []).slice(0, 9);
  const rows = [...current, ...completed].slice(0, 10);
  updatedTarget.textContent = board?.updated_at
    ? `Updated ${dateTimeLabel(board.updated_at)} · ${board.completed_count || 0} final`
    : "Not synced";
  target.innerHTML = rows.length ? rows.map((row) => `
    <div class="latest-result-card ${row.status === "live" ? "live" : ""}">
      <span>${escapeHtml(liveBoardStatus(row))}</span>
      <strong>${escapeHtml(row.team_a)} <b>${escapeHtml(liveBoardMatchScore(row))}</b> ${escapeHtml(row.team_b)}</strong>
      <small>${escapeHtml(row.group ? `Group ${row.group}` : row.stage || row.source || "World Cup")}</small>
    </div>
  `).join("") : `<div class="latest-results-empty">No completed official scores are synced yet.</div>`;
}

async function loadLatestResultsBoard() {
  const target = el("latestResultsBoard");
  if (!target) return null;
  try {
    const board = await api("/api/ai/live-board");
    renderLatestResultsBoard(board);
    if (el("signalLive")) el("signalLive").textContent = board.source || "manual";
    if (el("liveMetric")) el("liveMetric").textContent = `${board.completed_count || 0} final`;
    return board;
  } catch (error) {
    target.innerHTML = `<div class="latest-results-empty error">${escapeHtml(error.message)}</div>`;
    return null;
  }
}

function num(value, digits = 1) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed.toFixed(digits) : "-";
}

function renderLineupStatus(status) {
  if (!status) return;
  const coverage = Number(status.teams_with_lineups || 0);
  const refreshed = status.fetched_at ? ` · ${dateLabel(status.fetched_at)}` : "";
  el("lineupStatus").textContent = coverage
    ? `${coverage} teams with observed lineups${refreshed}`
    : status.configured
      ? "Provider ready · no observed lineups"
      : "Projection fallback · add Sportmonks token";
}

async function refreshSquad() {
  const data = await api(`/api/squads?team=${encodeURIComponent(el("squadSelect").value)}`);
  const summary = data.summaries[0];
  if (!summary) {
    el("squadPanel").innerHTML = `<div class="empty">Squad unavailable</div>`;
    return;
  }
  const playerRows = (players) => players
    .map((player) => `
      <tr>
        <td><strong>${escapeHtml(player.player)}</strong><span>${escapeHtml(player.club)}${player.availability < 1 ? ` · ${escapeHtml(player.availability_status)}` : ""}</span></td>
        <td>${escapeHtml(player.detailed_position || player.position)}</td>
        <td>${player.caps}</td>
        <td>${player.observed_start_rate > 0 ? `${Math.round(player.observed_start_rate * 100)}%` : player.projected_starter ? "Projected" : "-"}</td>
        <td>${euros(player.market_value_eur)}</td>
      </tr>
    `)
    .join("");
  const starters = data.players.filter((player) => player.projected_starter);
  const bench = data.players.filter((player) => !player.projected_starter);
  const factors = summary.model_factors;
  const traitCards = [
    ["Shooting", factors.player_shooting],
    ["Chance creation", factors.player_chance_creation],
    ["Passing", factors.player_passing],
    ["Progression", factors.player_progression],
    ["Pressing", factors.player_pressing],
    ["Defending", factors.player_defensive_activity],
    ["Goalkeeping", factors.player_goalkeeping],
    ["Late goals", factors.player_late_goals],
  ];
  const normalRows = [...(data.normal_time?.players || [])]
    .sort((a, b) => {
      const aScore = (a.xg_per90 * 4) + (a.xa_per90 * 3) + a.key_passes_per90 + (a.progressive_passes_per90 * 0.25) + (a.save_pct ? a.save_pct / 12 : 0);
      const bScore = (b.xg_per90 * 4) + (b.xa_per90 * 3) + b.key_passes_per90 + (b.progressive_passes_per90 * 0.25) + (b.save_pct ? b.save_pct / 12 : 0);
      return bScore - aScore;
    })
    .slice(0, 8);
  const normalTimeCards = normalRows.map((player) => `
    <div class="player-trait-card">
      <div><strong>${escapeHtml(player.player)}</strong><span>${escapeHtml(player.formation_role || player.position)} · ${escapeHtml(player.preferred_foot || "-")} foot · ${escapeHtml(player.club)}</span></div>
      ${player.position === "GK" ? `
        <div class="trait-pills">
          <span>Save <b>${num(player.save_pct, 1)}%</b></span>
          <span>PSxG +/- <b>${num(player.post_shot_xg_prevented_per90, 2)}</b></span>
          <span>Dives <b>${num(player.keeper_dives_per90, 2)}</b></span>
          <span>Claims <b>${num(player.keeper_claims_per90, 2)}</b></span>
          <span>Long pass <b>${num(player.keeper_long_pass_completion_pct, 1)}%</b></span>
          <span>Sweeper <b>${num(player.keeper_sweeper_actions_per90, 2)}</b></span>
          <span>PK dive <b>${escapeHtml(player.keeper_penalty_dive_preference || "-")}</b></span>
          <span>PK save <b>${num(player.keeper_penalty_save_pct, 1)}%</b></span>
        </div>
      ` : `
        <div class="trait-pills">
          <span>Weak foot <b>${num(player.weak_foot_usage_pct, 1)}%</b></span>
          <span>xG <b>${num(player.xg_per90, 2)}</b></span>
          <span>xA <b>${num(player.xa_per90, 2)}</b></span>
          <span>KP <b>${num(player.key_passes_per90, 2)}</b></span>
          <span>Pass <b>${num(player.pass_completion_pct, 1)}%</b></span>
          <span>Dribble <b>${num(player.dribble_success_pct, 1)}%</b></span>
          <span>Cross <b>${num(player.cross_completion_pct, 1)}%</b></span>
          <span>Prog P <b>${num(player.progressive_passes_per90, 2)}</b></span>
          <span>Tackle <b>${num(player.tackle_success_pct, 1)}%</b></span>
          <span>Press <b>${num(player.pressure_success_pct, 1)}%</b></span>
          <span>Aerial <b>${num(player.aerial_win_pct, 1)}%</b></span>
          <span>PK <b>${escapeHtml(player.penalty_preferred_placement || "-")}</b></span>
          <span>Win <b>${escapeHtml(player.likely_scoring_window)}</b></span>
        </div>
      `}
      <small>${escapeHtml(player.tactic_profile || "")}</small>
    </div>
  `).join("");
  el("squadPanel").innerHTML = `
    <div class="squad-scoreboard">
      <div class="squad-team">${flagHtml(summary)}<div><strong>${escapeHtml(summary.name)}</strong><span>${summary.players} listed${summary.roster_slots_open ? ` · ${summary.roster_slots_open} open slot${summary.roster_slots_open > 1 ? "s" : ""}` : ""} · ${summary.formation} · ${escapeHtml(summary.lineup_source)}</span></div></div>
      <div><span>Roster value</span><strong>${euros(summary.market_value_eur)}</strong></div>
      <div><span>Projected XI</span><strong>${euros(summary.projected_xi_value_eur)}</strong></div>
      <div><span>Lineup confidence</span><strong>${summary.lineup_confidence}%</strong><small>${summary.observed_lineups_count} observed · ${dateLabel(summary.lineup_updated_at)} · ${summary.unavailable_players} unavailable</small></div>
    </div>
    <div class="normal-time-board">
      <div class="report-block-head"><strong>Normal-time player traits</strong><span>${escapeHtml(data.normal_time_note)}</span></div>
      <div class="trait-score-grid">
        ${traitCards.map(([label, value]) => `<div><span>${escapeHtml(label)}</span><strong>${num(value, 1)}</strong></div>`).join("")}
      </div>
      <div class="player-trait-grid">${normalTimeCards || `<div class="empty compact">Run scripts/sync_player_match_stats.py</div>`}</div>
    </div>
    <div class="squad-columns">
      <div class="squad-list">
        <div class="report-block-head"><strong>Projected XI</strong><span>${escapeHtml(data.projection_note)}</span></div>
        <div class="table-wrap"><table><thead><tr><th>Player</th><th>Position</th><th>Caps</th><th>Start rate</th><th>Value</th></tr></thead><tbody>${playerRows(starters)}</tbody></table></div>
      </div>
      <div class="squad-list">
        <div class="report-block-head"><strong>Bench and depth</strong><span>${bench.length} players</span></div>
        <div class="table-wrap"><table><thead><tr><th>Player</th><th>Position</th><th>Caps</th><th>Start rate</th><th>Value</th></tr></thead><tbody>${playerRows(bench)}</tbody></table></div>
      </div>
    </div>
  `;
}

async function refreshLineups() {
  const button = el("refreshLineupsBtn");
  setButtonBusy(button, true, "Refresh lineups", "Refreshing", "refresh-cw");
  try {
    const data = await api("/api/refresh-lineups", { method: "POST", body: "{}" });
    renderLineupStatus(data.lineup_status);
    await refreshSquad();
  } catch (error) {
    console.error(error);
    alert(error.message);
  } finally {
    setButtonBusy(button, false, "Refresh lineups", "Refreshing", "refresh-cw");
  }
}

function populateVenues(venues) {
  const options = [
    `<option value="">Auto fixture venue</option>`,
    ...venues.map((venue) => `<option value="${venue.venue}">${venue.venue}</option>`),
  ].join("");
  el("venueSelect").innerHTML = options;
  el("venueSelect").value = "";
}

async function runSimulation() {
  if (state.running) return;
  state.running = true;
  const button = el("runBtn");
  setButtonBusy(button, true, "Run Simulation", "Running", "play");
  const seed = el("lockSeed").checked ? Number(el("seed").value) : Math.floor(Math.random() * 1000000000);
  el("seed").value = seed;
  try {
    const data = await api("/api/simulate", {
      method: "POST",
      body: JSON.stringify({
        sims: Number(el("simCount").value),
        seed,
        use_model: el("useModel").checked,
        ...currentScenario({ includeVenue: false }),
      }),
    });
    renderBracket(data.bracket.bracket);
    renderOdds(data.odds.odds);
    renderTopScorers(data.odds.top_scorers);
    el("modelMetric").textContent = data.bracket.model;
    el("liveMetric").textContent = data.bracket.live_state.source || "manual";
  } catch (error) {
    console.error(error);
    el("bracketSub").textContent = "Simulation failed";
    alert(error.message);
  } finally {
    state.running = false;
    setButtonBusy(button, false, "Run Simulation", "Running", "play");
  }
}

async function predictMatch() {
  const data = await api("/api/match", {
    method: "POST",
    body: JSON.stringify({
      team_a: el("teamA").value,
      team_b: el("teamB").value,
      use_model: el("useModel").checked,
      top_scores: 8,
      ...currentScenario(),
    }),
  });
  el("matchResult").innerHTML = `
    <div class="match-card">
      <strong class="match-title">${flagHtml(data.team_a)} <span>${data.team_a.name}</span> <b>${data.expected_score.team_a} - ${data.expected_score.team_b}</b> ${flagHtml(data.team_b)} <span>${data.team_b.name}</span></strong>
      ${renderOutcomeBars(data)}
    </div>
    ${renderForecastStack(data.forecast_stack)}
    ${renderAdvancedInsights(data)}
    <details class="detail-drawer">
      <summary>Exact-score matrix and alternate scorelines</summary>
      ${renderScoreMatrix(data)}
      ${data.scorelines.map((line) => `
        <div class="scoreline">
          <span class="inline-team">${flagHtml(data.team_a)}<b>${line.team_a_score}-${line.team_b_score}</b>${flagHtml(data.team_b)}</span>
          <strong>${line.probability}%</strong>
        </div>
      `).join("")}
    </details>
  `;
  window.setTimeout(() => drawScoreChart(data), 0);
}

function renderForecastStack(stack) {
  if (!stack) return "";
  const context = stack.context || {};
  const quality = stack.data_quality || {};
  const fixture = context.fixture || {};
  const contextChips = [
    fixture.venue ? `${fixture.venue}` : null,
    fixture.kickoff_local ? dateLabel(fixture.kickoff_local) : null,
    context.weather ? `Weather ${context.weather}` : null,
    quality.label ? `${quality.label} data` : null,
  ].filter(Boolean);
  return `
    <div class="forecast-stack">
      <div class="forecast-stack-head">
        <div>
          <span>Integrated forecast stack</span>
          <strong>Model inputs are fused into the score prediction</strong>
        </div>
        <b>${stack.expected_goals.base.team_a}-${stack.expected_goals.base.team_b} → ${stack.expected_goals.integrated.team_a}-${stack.expected_goals.integrated.team_b}</b>
      </div>
      <div class="context-chip-row">
        ${contextChips.map((chip) => `<span>${escapeHtml(chip)}</span>`).join("")}
      </div>
      <div class="stack-grid">
        ${(stack.modules || []).map((module) => `
          <div class="stack-card ${module.impact > 0 ? "active" : "context"}">
            <div><strong>${escapeHtml(module.label)}</strong><span>${escapeHtml(module.status)}${module.quality ? ` · ${escapeHtml(module.quality)}` : ""}</span></div>
            ${module.impact > 0 ? `<div class="driver-meter"><span style="width:${Math.min(module.impact, 100)}%"></span></div>` : ""}
            <p>${escapeHtml(module.detail)}</p>
          </div>
        `).join("")}
      </div>
    </div>
  `;
}

function renderAdvancedInsights(data) {
  const insights = data.score_insights;
  const confidence = data.confidence;
  const shapDrivers = data.shap_drivers && data.shap_drivers.available ? data.shap_drivers.drivers : [];
  const drivers = [...shapDrivers, ...(data.model_drivers || []), ...(data.scenario_drivers || [])].slice(0, 4);
  return `
    <div class="insight-grid">
      <div class="insight-panel">
        <span>Confidence</span>
        <strong>${confidence.label}</strong>
        <p>${confidence.favorite.label} by ${confidence.margin_pct} pts · uncertainty ${confidence.uncertainty_pct}%</p>
      </div>
      <div class="insight-panel">
        <span>Most Likely</span>
        <strong>${insights.most_likely_score.team_a_score}-${insights.most_likely_score.team_b_score}</strong>
        <p>${insights.most_likely_score.probability}% exact-score probability</p>
      </div>
      <div class="insight-panel">
        <span>Goal Shape</span>
        <strong>${insights.over_2_5_goals}%</strong>
        <p>Over 2.5 goals · BTTS ${insights.both_teams_score}%</p>
      </div>
    </div>
    <div id="scoreChart" class="score-chart"></div>
    <details class="detail-drawer compact">
      <summary>Top model drivers</summary>
      <div class="driver-list">
        ${drivers.map((driver) => `
          <div class="driver">
            <div>
              <strong>${driver.label}</strong>
              <span>${driver.favored_team}</span>
            </div>
            <div class="driver-meter"><span style="width:${Math.min(driver.impact, 100)}%"></span></div>
          </div>
        `).join("")}
      </div>
    </details>
  `;
}

function renderOutcomeBars(data) {
  const aggregate = data.score_aggregate_probabilities || data.probabilities;
  return `
    <div class="outcome-bars">
      ${outcomeBar(data.team_a.name, aggregate.team_a_win)}
      ${outcomeBar("Draw", aggregate.draw)}
      ${outcomeBar(data.team_b.name, aggregate.team_b_win)}
    </div>
  `;
}

function outcomeBar(label, value) {
  return `
    <div class="outcome-bar">
      <span>${label}</span>
      <strong>${value}%</strong>
      <div class="bar"><span style="width:${Math.min(value, 100)}%"></span></div>
    </div>
  `;
}

function renderScoreMatrix(data) {
  const maxScore = 6;
  const cells = new Map(data.score_matrix.map((cell) => [`${cell.team_a_score}-${cell.team_b_score}`, cell]));
  const rows = [];
  for (let a = 0; a <= maxScore; a += 1) {
    const row = [];
    for (let b = 0; b <= maxScore; b += 1) {
      const cell = cells.get(`${a}-${b}`);
      const opacity = Math.min(0.95, 0.08 + (cell.probability / 18));
      row.push(`<div class="score-cell ${cell.outcome}" style="--heat:${opacity}"><b>${a}-${b}</b><span>${cell.probability}%</span></div>`);
    }
    rows.push(row.join(""));
  }
  return `<div class="score-matrix">${rows.join("")}</div>`;
}

function drawScoreChart(data) {
  if (!window.echarts || !el("scoreChart")) return;
  const chart = echarts.init(el("scoreChart"));
  const values = data.score_matrix.map((cell) => [cell.team_b_score, cell.team_a_score, cell.probability]);
  chart.setOption({
    tooltip: {
      formatter: (params) => `${data.team_a.name} ${params.value[1]}-${params.value[0]} ${data.team_b.name}<br/>${params.value[2]}%`,
    },
    grid: { left: 42, right: 14, top: 18, bottom: 34 },
    xAxis: { type: "category", name: data.team_b.name, data: [0, 1, 2, 3, 4, 5, 6] },
    yAxis: { type: "category", name: data.team_a.name, data: [0, 1, 2, 3, 4, 5, 6] },
    visualMap: {
      min: 0,
      max: Math.max(...data.score_matrix.map((cell) => cell.probability)),
      show: false,
      inRange: { color: ["#f5f8ff", "#5ac8fa", "#0071e3"] },
    },
    series: [{ type: "heatmap", data: values, label: { show: true, formatter: (params) => `${params.value[2]}%` } }],
  });
}

async function refreshLiveData() {
  const button = el("refreshBtn");
  setButtonBusy(button, true, "Refresh Live Data", "Refreshing", "refresh-cw");
  try {
    const data = await api("/api/tournament-autopilot/run", {
      method: "POST",
      body: JSON.stringify({
        refresh_official: true,
        refresh_provider: false,
        run_arena: false,
        settle_and_evaluate: true,
      }),
    });
    await loadLatestResultsBoard();
    alert(`Official FIFA score sync complete. Completed matches: ${data.observed_matches}. New final rows: ${data.newly_observed_match_ids.length}.`);
  } finally {
    setButtonBusy(button, false, "Refresh Live Data", "Refreshing", "refresh-cw");
  }
}

async function lockLiveScore() {
  const data = await api("/api/live-state/match", {
    method: "POST",
    body: JSON.stringify({
      team_a: el("liveTeamA").value,
      team_b: el("liveTeamB").value,
      team_a_score: Number(el("liveScoreA").value),
      team_b_score: Number(el("liveScoreB").value),
    }),
  });
  el("liveMetric").textContent = data.live_state.source;
  await loadLatestResultsBoard();
  await runSimulation();
}

async function setEliminated(eliminated) {
  const data = await api("/api/live-state/elimination", {
    method: "POST",
    body: JSON.stringify({
      team: el("eliminateTeam").value,
      eliminated,
    }),
  });
  el("liveMetric").textContent = `${data.live_state.eliminated_teams.length} eliminated`;
  await loadLatestResultsBoard();
  await runSimulation();
}

async function analyzeEdges() {
  const button = el("edgeBtn");
  setButtonBusy(button, true, "Analyze Odds", "Analyzing", "chart-candlestick");
  try {
    const data = await api("/api/betting-edges", {
      method: "POST",
      body: JSON.stringify({
        bankroll: Number(el("bankroll").value),
        sims: Number(el("edgeSims").value),
        min_edge_pct: Number(el("minEdge").value),
        use_model: el("useModel").checked,
        ...currentScenario({ includeVenue: false }),
      }),
    });
    renderEdges(data);
  } catch (error) {
    console.error(error);
    el("edgeResult").innerHTML = `<div class="empty">Odds analysis failed</div>`;
    alert(error.message);
  } finally {
    setButtonBusy(button, false, "Analyze Odds", "Analyzing", "chart-candlestick");
  }
}

async function askIntelligence(question = null) {
  if (question) el("intelligenceQuestion").value = question;
  const prompt = el("intelligenceQuestion").value.trim();
  if (!prompt) return;
  const button = el("askBtn");
  setButtonBusy(button, true, "Run Analysis", "Analyzing", "sparkles");
  el("intelligenceResult").innerHTML = `<div class="empty">Routing tools and retrieving evidence</div>`;
  try {
    const data = await api("/api/intelligence", {
      method: "POST",
      body: JSON.stringify({
        question: prompt,
        use_llm: el("useLlm").checked,
        use_model: el("useModel").checked,
        ...currentScenario(),
      }),
    });
    renderIntelligence(data);
  } catch (error) {
    console.error(error);
    el("intelligenceResult").innerHTML = `<div class="empty">Analysis failed</div>`;
    alert(error.message);
  } finally {
    setButtonBusy(button, false, "Run Analysis", "Analyzing", "sparkles");
  }
}

async function runAnalystBrief(showAlert = true) {
  const button = el("analystBriefBtn");
  setButtonBusy(button, true, "Build Brief", "Building", "radar");
  el("analystBriefResult").innerHTML = `<div class="empty">Running forecast, market, squad, xG, weather, and evidence checks</div>`;
  try {
    const data = await api("/api/analyst-brief", {
      method: "POST",
      body: JSON.stringify({
        team_a: el("briefTeamA").value,
        team_b: el("briefTeamB").value,
        refresh_odds: el("briefRefreshOdds").checked,
        sims: Number(el("edgeSims").value || 250),
        use_model: el("useModel").checked,
        ...currentScenario(),
      }),
    });
    renderAnalystBrief(data);
  } catch (error) {
    console.error(error);
    el("analystBriefResult").innerHTML = `<div class="empty">Brief unavailable</div>`;
    if (showAlert) alert(error.message);
  } finally {
    setButtonBusy(button, false, "Build Brief", "Building", "radar");
  }
}

function renderAnalystBrief(data) {
  const a = data.teams.team_a;
  const b = data.teams.team_b;
  const probabilities = data.forecast.probabilities;
  const topScore = data.forecast.top_scoreline;
  const marketRows = data.market_edges.length
    ? data.market_edges.slice(0, 6).map((edge) => `
        <div class="market-row">
          <strong>${escapeHtml(edge.selection)}</strong>
          <span>${escapeHtml(edge.bookmaker)} · ${escapeHtml(edge.american_odds || edge.decimal_odds)}</span>
          <b>${edge.expected_value_pct}% EV</b>
        </div>
      `).join("")
    : `<div class="empty compact">${escapeHtml(data.market_status.message || "No matched market rows")}</div>`;
  el("analystBriefResult").innerHTML = `
    <div class="analyst-hero">
      <div class="analyst-team-card">
        <div>${flagHtml(a)}<strong>${escapeHtml(a.name)}</strong></div>
        <b>${probabilities.team_a_win}%</b>
        <span>win probability</span>
      </div>
      <div class="analyst-call">
        <span class="mode-badge">${escapeHtml(data.recommendation)}</span>
        <h3>${escapeHtml(data.headline)}</h3>
        <p>${escapeHtml(data.thesis)}</p>
        <div class="score-strip">
          <span>Expected ${data.forecast.expected_score.team_a}-${data.forecast.expected_score.team_b}</span>
          <span>Mode ${topScore.team_a_score}-${topScore.team_b_score} · ${topScore.probability}%</span>
          <span>Draw ${probabilities.draw}%</span>
        </div>
      </div>
      <div class="analyst-team-card right">
        <div>${flagHtml(b)}<strong>${escapeHtml(b.name)}</strong></div>
        <b>${probabilities.team_b_win}%</b>
        <span>win probability</span>
      </div>
    </div>
    <div class="analyst-factor-grid">
      ${data.factor_cards.map((card) => `
        <div class="factor-card ${escapeHtml(card.tone)}">
          <span>${escapeHtml(card.agent)}</span>
          <div><strong>${escapeHtml(card.title)}</strong><b>${escapeHtml(card.value)}</b></div>
          <p>${escapeHtml(card.detail)}</p>
        </div>
      `).join("")}
    </div>
    <div class="analyst-lower">
      <div>
        <div class="panel-title"><i data-lucide="chart-candlestick"></i><span>Market</span></div>
        <div class="market-list">${marketRows}</div>
      </div>
      <div>
        <div class="panel-title"><i data-lucide="list-checks"></i><span>Watchlist</span></div>
        <div class="watchlist">${data.watchlist.map((item) => `<span>${escapeHtml(item)}</span>`).join("")}</div>
      </div>
    </div>
    <div class="agent-inspection analyst-inspection">
      <div class="agent-trace">
        <h3>Agent trace</h3>
        ${data.agent_trace.map((item, index) => `
          <div class="trace-step ${escapeHtml(item.status)}">
            <span>${index + 1}</span>
            <div><strong>${escapeHtml(item.step.replaceAll("_", " "))}</strong><p>${escapeHtml(item.detail)}</p></div>
          </div>
        `).join("")}
      </div>
      <div class="evidence-list">
        <h3>Evidence</h3>
        ${data.evidence.length ? data.evidence.slice(0, 5).map((item, index) => `
          <div class="evidence-item">
            <span>${index + 1}</span>
            <div>
              <strong>${escapeHtml(item.title)}</strong>
              <p>${escapeHtml(item.excerpt)}</p>
              <small>${escapeHtml(item.source)} · relevance ${item.relevance}</small>
            </div>
          </div>
        `).join("") : `<div class="empty compact">No evidence chunks returned</div>`}
      </div>
    </div>
    <p class="agent-disclaimer">${escapeHtml(data.disclaimer)}</p>
  `;
  refreshIcons();
}

function renderIntelligence(data) {
  const answer = escapeHtml(data.answer)
    .split(/\n{2,}/)
    .map((paragraph) => `<p>${paragraph.replaceAll("\n", "<br>")}</p>`)
    .join("");
  el("intelligenceResult").innerHTML = `
    <div class="briefing-head">
      <div>
        <span class="mode-badge">${escapeHtml(data.mode.replaceAll("-", " "))}</span>
        <strong>Analyst briefing</strong>
      </div>
      <span>${data.evidence.length} sources · ${data.routed_tools.length} tools</span>
    </div>
    <div class="briefing-answer">${answer}</div>
    ${data.team_shortlist ? `<div id="intelligenceChart" class="intelligence-chart"></div>` : ""}
    <div class="agent-inspection">
      <div class="agent-trace">
        <h3>Agent trace</h3>
        ${data.trace.map((item, index) => `
          <div class="trace-step">
            <span>${index + 1}</span>
            <div><strong>${escapeHtml(item.step.replaceAll("_", " "))}</strong><p>${escapeHtml(item.detail)}</p></div>
          </div>
        `).join("")}
      </div>
      <div class="evidence-list">
        <h3>Retrieved evidence</h3>
        ${data.evidence.map((item, index) => `
          <div class="evidence-item">
            <span>${index + 1}</span>
            <div>
              <strong>${escapeHtml(item.title)}</strong>
              <p>${escapeHtml(item.excerpt)}</p>
              <small>${escapeHtml(item.source)} · relevance ${item.relevance}</small>
            </div>
          </div>
        `).join("")}
      </div>
    </div>
    <div class="followups">
      ${data.suggested_followups.map((item) => `<button class="prompt-chip" data-question="${escapeHtml(item)}">${escapeHtml(item)}</button>`).join("")}
    </div>
    <p class="agent-disclaimer">${escapeHtml(data.disclaimer)}</p>
  `;
  if (data.team_shortlist) window.setTimeout(() => drawIntelligenceChart(data.team_shortlist), 0);
}

function drawIntelligenceChart(shortlist) {
  if (!window.echarts || !el("intelligenceChart")) return;
  const teams = [...shortlist.teams].reverse();
  const chart = echarts.init(el("intelligenceChart"));
  chart.setOption({
    tooltip: {
      trigger: "axis",
      formatter: (params) => {
        const row = teams[params[0].dataIndex];
        return `${row.team}<br/>FIFA #${row.fifa_rank} · quality #${row.model_quality_rank}<br/>rank gap ${row.rank_gap}`;
      },
    },
    grid: { left: 104, right: 24, top: 20, bottom: 30 },
    xAxis: { type: "value", name: "FIFA rank - model quality rank" },
    yAxis: { type: "category", data: teams.map((row) => row.team) },
    series: [{
      type: "bar",
      data: teams.map((row) => row.rank_gap),
      itemStyle: { color: (params) => (params.value >= 0 ? "#0071e3" : "#8e8e93") },
    }],
  });
}

function renderEdges(data) {
  if (!data.ok || !data.edges || data.edges.length === 0) {
    el("edgeResult").innerHTML = `<div class="empty">${data.message || "No positive edge found"}</div>`;
    return;
  }
  el("edgeResult").innerHTML = `
    <div class="edge-grid">
      ${data.edges.slice(0, 12).map((edge) => `
        <div class="edge-card ${edge.expected_value_pct > 0 && edge.edge_pct > 0 ? "positive" : ""}">
          <div class="edge-top">
            <div>
              <strong>${edge.selection}</strong>
              <span>${edge.event}</span>
            </div>
            <b>${edge.expected_value_pct}% EV</b>
          </div>
          <div class="edge-stats">
            <span>Odds <b>${edge.american_odds || edge.decimal_odds}</b></span>
            <span>Model <b>${edge.model_probability}%</b></span>
            <span>No-vig <b>${edge.no_vig_probability}%</b></span>
            <span>Edge <b>${edge.edge_pct}%</b></span>
          </div>
          <div class="edge-stake">
            <span>${edge.grade}</span>
            <strong>$${edge.stake} · ${edge.stake_pct}%</strong>
          </div>
        </div>
      `).join("")}
    </div>
    <div id="edgeChart" class="edge-chart"></div>
    <div class="edge-note">${data.message}</div>
  `;
  window.setTimeout(() => drawEdgeChart(data.edges.slice(0, 10)), 0);
}

function drawEdgeChart(edges) {
  if (!window.echarts || !el("edgeChart")) return;
  const chart = echarts.init(el("edgeChart"));
  chart.setOption({
    tooltip: { trigger: "axis" },
    grid: { left: 44, right: 18, top: 20, bottom: 80 },
    xAxis: {
      type: "category",
      axisLabel: { rotate: 35 },
      data: edges.map((edge) => `${edge.selection} · ${edge.event}`),
    },
    yAxis: { type: "value", name: "EV %" },
    series: [
      {
        type: "bar",
        data: edges.map((edge) => edge.expected_value_pct),
        itemStyle: { color: (params) => (params.value > 0 ? "#0071e3" : "#8e8e93") },
      },
    ],
  });
}

async function refreshVenueWeather() {
  const venue = el("venueSelect").value;
  if (!venue) {
    el("weatherSummary").textContent = "Fixture auto";
    el("venueWeather").innerHTML = `<div class="empty">Scheduled matches use their own venue and kickoff automatically.</div>`;
    if (el("weather").value === "auto") await predictMatch();
    return;
  }
  el("venueWeather").innerHTML = `<div class="empty">Loading venue weather</div>`;
  try {
    const data = await api(`/api/venue-weather?venue=${encodeURIComponent(venue)}`);
    renderVenueWeather(data);
    if (el("weather").value === "auto") {
      await predictMatch();
    }
  } catch (error) {
    console.error(error);
    el("venueWeather").innerHTML = `<div class="empty">Weather unavailable</div>`;
  }
}

function renderVenueWeather(data) {
  const venue = data.venue_weather?.venue || state.venues.find((item) => item.venue === el("venueSelect").value);
  const current = data.venue_weather?.current || {};
  el("weatherSummary").textContent = `${data.weather || "normal"} · ${data.weather_source || "manual"}`;
  el("venueWeather").innerHTML = `
    <div class="weather-card">
      <strong>${venue?.venue || el("venueSelect").value}</strong>
      <span>${venue?.city || ""}, ${venue?.country || ""}</span>
      <div class="edge-stats">
        <span>Weather <b>${data.weather || "normal"}</b></span>
        <span>Temp <b>${current.temperature_2m ?? "-"}°C</b></span>
        <span>Wind <b>${current.wind_speed_10m ?? "-"} km/h</b></span>
        <span>Humidity <b>${current.relative_humidity_2m ?? "-"}%</b></span>
      </div>
    </div>
  `;
}

function populatePenaltyOptions(options) {
  state.penaltyOptions = options;
  const kickerOptions = options.kickers
    .map((player) => `<option value="${escapeHtml(player.player)}">${escapeHtml(player.player)} · ${escapeHtml(player.team)}</option>`)
    .join("");
  const keeperOptions = options.keepers
    .map((player) => `<option value="${escapeHtml(player.player)}">${escapeHtml(player.player)} · ${escapeHtml(player.team)}</option>`)
    .join("");
  el("penaltyKicker").innerHTML = kickerOptions;
  el("penaltyKeeper").innerHTML = keeperOptions;
  const mbappe = options.kickers.find((player) => player.player.includes("Mbapp")) || options.kickers[0];
  const keeper = options.keepers.find((player) => player.player === "Emiliano Martinez") || options.keepers[0];
  if (mbappe) el("penaltyKicker").value = mbappe.player;
  if (keeper) el("penaltyKeeper").value = keeper.player;
  updatePenaltyContext();
}

function selectedPenaltyPlayer(list, value) {
  return list.find((player) => player.player === value);
}

function penaltyContextHtml(kicker, keeper) {
  const kickerTraits = kicker?.normal_time || {};
  const keeperTraits = keeper?.normal_time || {};
  return `
    <div class="penalty-context-grid">
      <div>
        <span>Kicker profile</span>
        <strong>${escapeHtml(kicker?.player || "-")}</strong>
        <p>${escapeHtml(kickerTraits.preferred_foot || "Unknown")} foot · ${escapeHtml(kickerTraits.formation_role || kicker?.position || "-")} · ${escapeHtml(kickerTraits.tactic_profile || "")}</p>
        <div class="trait-pills">
          <span>PK goal <b>${num(kickerTraits.penalty_goal_pct, 1)}%</b></span>
          <span>Pref <b>${escapeHtml(kickerTraits.penalty_preferred_placement || "-")}</b></span>
          <span>L/C/R <b>${num(kickerTraits.penalty_left_pct, 0)}/${num(kickerTraits.penalty_center_pct, 0)}/${num(kickerTraits.penalty_right_pct, 0)}</b></span>
          <span>Weak foot <b>${num(kickerTraits.weak_foot_usage_pct, 1)}%</b></span>
          <span>xG <b>${num(kickerTraits.xg_per90, 2)}</b></span>
          <span>Pass <b>${num(kickerTraits.pass_completion_pct, 1)}%</b></span>
          <span>Dribble <b>${num(kickerTraits.dribble_success_pct, 1)}%</b></span>
        </div>
      </div>
      <div>
        <span>Keeper profile</span>
        <strong>${escapeHtml(keeper?.player || "-")}</strong>
        <p>${escapeHtml(keeperTraits.preferred_foot || "Unknown")} foot · ${escapeHtml(keeperTraits.formation_role || keeper?.position || "-")} · ${escapeHtml(keeperTraits.tactic_profile || "")}</p>
        <div class="trait-pills">
          <span>PK save <b>${num(keeperTraits.keeper_penalty_save_pct, 1)}%</b></span>
          <span>Dive pref <b>${escapeHtml(keeperTraits.keeper_penalty_dive_preference || "-")}</b></span>
          <span>L/C/R <b>${num(keeperTraits.keeper_penalty_dive_left_pct, 0)}/${num(keeperTraits.keeper_penalty_dive_center_pct, 0)}/${num(keeperTraits.keeper_penalty_dive_right_pct, 0)}</b></span>
          <span>Save <b>${num(keeperTraits.save_pct, 1)}%</b></span>
          <span>PSxG +/- <b>${num(keeperTraits.post_shot_xg_prevented_per90, 2)}</b></span>
          <span>Dives <b>${num(keeperTraits.keeper_dives_per90, 2)}</b></span>
        </div>
      </div>
    </div>
  `;
}

function updatePenaltyContext() {
  const kicker = selectedPenaltyPlayer(state.penaltyOptions.kickers, el("penaltyKicker").value);
  const keeper = selectedPenaltyPlayer(state.penaltyOptions.keepers, el("penaltyKeeper").value);
  const preferredFoot = kicker?.normal_time?.preferred_foot;
  if (preferredFoot === "Left" || preferredFoot === "Right") el("kickerFoot").value = preferredFoot;
  if (el("penaltyResult")) {
    el("penaltyResult").innerHTML = penaltyContextHtml(kicker, keeper);
    refreshIcons();
  }
}

function renderAdvancedModelStatus(xgStatus, penaltyStatus) {
  el("xgStatus").textContent = xgStatus.available
    ? `${xgStatus.metrics.rows} shots · Brier ${xgStatus.metrics.brier_score}`
    : "Run xG training";
  el("penaltyStatus").textContent = penaltyStatus.available
    ? `${penaltyStatus.metrics.rows} kicks · placement ${Math.round(penaltyStatus.metrics.placement_accuracy * 100)}%`
    : "Run penalty training";
}

async function predictXg() {
  const button = el("xgBtn");
  setButtonBusy(button, true, "Predict xG", "Predicting", "crosshair");
  try {
    const data = await api("/api/xg/predict", {
      method: "POST",
      body: JSON.stringify({
        team: el("xgTeam").value,
        player: el("xgPlayer").value,
        shot_x: Number(el("shotX").value),
        shot_y: Number(el("shotY").value),
        body_part: el("shotBodyPart").value,
        assist_type: el("assistType").value,
        defender_pressure: el("defenderPressure").value,
        game_state: el("gameState").value,
        shot_type: el("assistType").value === "Set Piece" ? "Set Piece" : "Open Play",
      }),
    });
    el("xgResult").innerHTML = `
      <div class="model-score-card">
        <span>${escapeHtml(data.shot.player)} · ${escapeHtml(data.shot.team)}</span>
        <strong>${data.xg_pct}% xG</strong>
        <small>${data.shot.distance_m}m · ${data.shot.angle_degrees}° · ${escapeHtml(data.shot.defender_pressure)} pressure</small>
      </div>
    `;
    drawXgChart(data);
    await renderXgDanger();
  } catch (error) {
    console.error(error);
    el("xgResult").innerHTML = `<div class="empty">xG model unavailable</div>`;
    alert(error.message);
  } finally {
    setButtonBusy(button, false, "Predict xG", "Predicting", "crosshair");
  }
}

async function renderXgDanger() {
  const data = await api(`/api/xg/danger?team=${encodeURIComponent(el("xgTeam").value)}`);
  el("xgDanger").innerHTML = data.zones.slice(0, 6)
    .map((zone) => `
      <div class="danger-card">
        <span>${escapeHtml(zone.x_zone)} · ${escapeHtml(zone.y_zone)}</span>
        <strong>${Math.round(zone.avg_xg * 100)}% avg xG</strong>
        <small>${zone.shots} shots · ${zone.predicted_goals} xG · ${zone.actual_goals} goals</small>
      </div>
    `)
    .join("");
}

function drawXgChart(data) {
  if (!window.echarts || !el("xgChart")) return;
  const chart = echarts.init(el("xgChart"));
  chart.setOption({
    grid: { left: 26, right: 20, top: 20, bottom: 26 },
    xAxis: { type: "value", min: 70, max: 120, show: false },
    yAxis: { type: "value", min: 0, max: 80, show: false },
    series: [
      {
        type: "scatter",
        symbolSize: Math.max(12, data.xg_pct * 1.2),
        data: [[data.shot.shot_x, data.shot.shot_y, data.xg_pct]],
        itemStyle: { color: "#0071e3" },
        label: { show: true, formatter: `${data.xg_pct}%`, color: "#1d1d1f", position: "right" },
      },
      {
        type: "line",
        data: [[120, 36], [120, 44]],
        symbol: "none",
        lineStyle: { color: "#1d1d1f", width: 6 },
      },
    ],
  });
}

async function predictPenalty() {
  const button = el("penaltyBtn");
  const kicker = state.penaltyOptions.kickers.find((player) => player.player === el("penaltyKicker").value);
  const keeper = state.penaltyOptions.keepers.find((player) => player.player === el("penaltyKeeper").value);
  setButtonBusy(button, true, "Predict Kick", "Predicting", "goal");
  try {
    const data = await api("/api/penalties/matchup", {
      method: "POST",
      body: JSON.stringify({
        kicker: el("penaltyKicker").value,
        goalkeeper: el("penaltyKeeper").value,
        kicker_foot: el("kickerFoot").value,
        kicker_position: kicker?.position || "FW",
        pressure_score: Number(el("penaltyPressure").value),
        score_state: el("penaltyScoreState").value,
        knockout_round: el("penaltyRound").value,
        kick_order: Number(el("kickOrder").value),
      }),
    });
    const matchup = data.matchup;
    el("penaltyResult").innerHTML = `
      <div class="model-score-card">
        <span>${escapeHtml(data.kicker)} vs ${escapeHtml(data.goalkeeper)}</span>
        <strong>${matchup.goal_probability}% score</strong>
        <small>Keeper read: ${escapeHtml(matchup.keeper_recommended_dive)} · save ${matchup.save_probability}% · miss ${matchup.miss_probability}%</small>
      </div>
      ${penaltyContextHtml(kicker, keeper)}
    `;
    drawPenaltyChart(matchup);
  } catch (error) {
    console.error(error);
    el("penaltyResult").innerHTML = `<div class="empty">Penalty model unavailable</div>`;
    alert(error.message);
  } finally {
    setButtonBusy(button, false, "Predict Kick", "Predicting", "goal");
  }
}

function drawPenaltyChart(matchup) {
  if (!window.echarts || !el("penaltyChart")) return;
  const placement = matchup.placement_probabilities;
  const outcome = matchup.outcome_probabilities;
  const chart = echarts.init(el("penaltyChart"));
  chart.setOption({
    tooltip: { trigger: "axis" },
    grid: [{ left: 42, right: 18, top: 18, height: 110 }, { left: 42, right: 18, top: 170, height: 110 }],
    xAxis: [
      { type: "category", data: Object.keys(placement), gridIndex: 0 },
      { type: "category", data: Object.keys(outcome), gridIndex: 1 },
    ],
    yAxis: [
      { type: "value", max: 100, gridIndex: 0 },
      { type: "value", max: 100, gridIndex: 1 },
    ],
    series: [
      { type: "bar", xAxisIndex: 0, yAxisIndex: 0, data: Object.values(placement), itemStyle: { color: "#0071e3" } },
      { type: "bar", xAxisIndex: 1, yAxisIndex: 1, data: Object.values(outcome), itemStyle: { color: "#5ac8fa" } },
    ],
  });
}

function renderVenueMap(venues) {
  if (!window.maplibregl || !el("venueMap")) {
    el("venueMap").innerHTML = `<div class="empty">Map library unavailable</div>`;
    return;
  }
  state.venueMap = new maplibregl.Map({
    container: "venueMap",
    style: "https://demotiles.maplibre.org/style.json",
    center: [-98.5, 39.5],
    zoom: 2.4,
  });
  state.venueMap.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
  venues.forEach((venue) => {
    const marker = new maplibregl.Marker({ color: "#0071e3" })
      .setLngLat([venue.longitude, venue.latitude])
      .setPopup(new maplibregl.Popup().setHTML(`<strong>${venue.venue}</strong><br>${venue.city}, ${venue.country}`))
      .addTo(state.venueMap);
    marker.getElement().addEventListener("click", () => {
      el("venueSelect").value = venue.venue;
      refreshVenueWeather();
    });
  });
}

function playerIdFor(team, player) {
  return `${team}_${player}`
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
}

function centerMessage(message, tone = "") {
  return `<div class="center-message ${tone}"><i data-lucide="${tone === "error" ? "circle-alert" : "database"}"></i><span>${escapeHtml(message)}</span></div>`;
}

function centerMetric(label, value, note = "") {
  return `<div class="center-metric"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong>${note ? `<small>${escapeHtml(note)}</small>` : ""}</div>`;
}

function initCenterTabs() {
  document.querySelectorAll("[data-center-tab]").forEach((button) => {
    button.addEventListener("click", () => {
      const target = button.dataset.centerTab;
      document.querySelectorAll("[data-center-tab]").forEach((tab) => {
        const active = tab.dataset.centerTab === target;
        tab.classList.toggle("active", active);
        tab.setAttribute("aria-selected", String(active));
      });
      document.querySelectorAll("[data-center-pane]").forEach((pane) => {
        const active = pane.dataset.centerPane === target;
        pane.classList.toggle("active", active);
        pane.hidden = !active;
      });
      refreshIcons();
    });
  });
}

function populateCenterTeams() {
  const options = state.teams.map((team) => `<option value="${escapeHtml(team.name)}">${escapeHtml(team.name)}</option>`).join("");
  ["formTeam", "injuryTeam", "lineupDeltaTeam", "reviewTeamA", "reviewTeamB"].forEach((id) => {
    el(id).innerHTML = options;
  });
  ["formTeam", "injuryTeam", "lineupDeltaTeam", "reviewTeamA"].forEach((id) => { el(id).value = "France"; });
  el("reviewTeamB").value = "Brazil";
}

async function populateFormPlayers(load = true) {
  const team = el("formTeam").value;
  const data = await api(`/api/squads?team=${encodeURIComponent(team)}`);
  const players = [...(data.players || [])].sort((a, b) => Number(b.projected_starter) - Number(a.projected_starter));
  el("formPlayer").innerHTML = players
    .map((player) => `<option value="${escapeHtml(playerIdFor(team, player.player))}">${escapeHtml(player.player)} · ${escapeHtml(player.position)}</option>`)
    .join("");
  if (team === "France" && [...el("formPlayer").options].some((option) => option.value === "france_kylian_mbappe")) {
    el("formPlayer").value = "france_kylian_mbappe";
  }
  if (load) await loadPlayerForm();
}

async function loadPlayerForm() {
  const output = el("playerFormCenter");
  output.innerHTML = centerMessage("Loading player role vector");
  try {
    const data = await api(`/api/player-role-vector/${encodeURIComponent(el("formPlayer").value)}`);
    if (!data.found) {
      output.innerHTML = centerMessage(data.fallback_note || "No player form data is available.");
      return;
    }
    const form = data.form;
    const roles = data.roles || [];
    const primary = roles[0];
    output.innerHTML = `
      <div class="center-scoreboard">
        ${centerMetric("Player", data.player, data.team)}
        ${centerMetric("Form", form ? `${num(form.form_score, 0)}/100` : "-", form ? `${form.recent_matches} recent matches` : "No recent sample")}
        ${centerMetric("Best role", primary ? primary.role_archetype.replaceAll("_", " ") : "-", primary ? `${num(primary.role_fit_score, 1)} fit score` : "No role vector")}
        ${centerMetric("Confidence", primary ? `${Math.round(primary.confidence * 100)}%` : "-", primary?.data_quality || "No role evidence")}
      </div>
      <div class="role-vector-grid">
        ${roles.map((role) => `
          <div class="role-vector-row">
            <div><strong>${escapeHtml(role.role_archetype.replaceAll("_", " "))}</strong><span>${num(role.role_fit_score, 1)} fit · ${escapeHtml(role.data_quality)}</span></div>
            <div class="role-bar"><span style="width:${Math.min(role.role_fit_score, 100)}%"></span></div>
            <div class="role-dimensions">
              <span>Shot <b>${num(role.shooting_score, 0)}</b></span><span>Create <b>${num(role.creation_score, 0)}</b></span>
              <span>Progress <b>${num(role.progression_score, 0)}</b></span><span>Press <b>${num(role.pressing_score, 0)}</b></span>
              <span>Defend <b>${num(role.defending_score, 0)}</b></span><span>Transition <b>${num(role.transition_score, 0)}</b></span>
            </div>
          </div>
        `).join("") || centerMessage("No role vectors are available.")}
      </div>
    `;
  } catch (error) {
    output.innerHTML = centerMessage(error.message, "error");
  }
  refreshIcons();
}

async function loadInjuryBoard() {
  const output = el("injuryCenter");
  output.innerHTML = centerMessage("Loading availability signals");
  try {
    const data = await api(`/api/injury-status?team=${encodeURIComponent(el("injuryTeam").value)}`);
    if (!data.available) {
      output.innerHTML = centerMessage(data.fallback_note || "No injury signals are available.");
      return;
    }
    output.innerHTML = `
      <div class="center-scoreboard">
        ${centerMetric("Players tracked", String(data.signals.length), data.team)}
        ${centerMetric("Manual review", String(data.manual_review_count), "Conflicting reports")}
        ${centerMetric("Highest risk", `${Math.round(Math.max(...data.signals.map((row) => row.risk_score)) * 100)}%`, "Availability impact")}
      </div>
      <div class="center-table-wrap"><table class="center-table"><thead><tr><th>Player</th><th>Status</th><th>Available</th><th>Minutes</th><th>Evidence</th></tr></thead><tbody>
        ${data.signals.map((row) => `<tr class="${row.needs_manual_review ? "review-row" : ""}"><td><strong>${escapeHtml(row.player)}</strong><span>${escapeHtml(row.reason)}</span></td><td><span class="status-tag ${escapeHtml(row.status)}">${escapeHtml(row.status.replaceAll("_", " "))}</span></td><td>${Math.round(row.availability_probability * 100)}%</td><td>${row.expected_minutes}</td><td>${row.evidence_count}${row.needs_manual_review ? " · review" : ""}</td></tr>`).join("")}
      </tbody></table></div>
    `;
  } catch (error) {
    output.innerHTML = centerMessage(error.message, "error");
  }
  refreshIcons();
}

async function populateManagerEvidence() {
  const data = await api("/api/tactics/managers");
  el("managerEvidenceSelect").innerHTML = (data.managers || [])
    .map((manager) => `<option value="${escapeHtml(manager.manager_id)}">${escapeHtml(manager.manager_name)} · ${escapeHtml(manager.team)}</option>`)
    .join("");
  if ([...el("managerEvidenceSelect").options].some((option) => option.value === "france_deschamps")) {
    el("managerEvidenceSelect").value = "france_deschamps";
  }
  await loadManagerEvidence();
}

async function loadManagerEvidence() {
  const output = el("managerEvidenceCenter");
  output.innerHTML = centerMessage("Loading manager evidence");
  try {
    const managerId = el("managerEvidenceSelect").value;
    const [data, evaluation] = await Promise.all([
      api(`/api/manager-evidence/${encodeURIComponent(managerId)}`),
      api(`/api/evaluation/manager/${encodeURIComponent(managerId)}`),
    ]);
    if (!data.found) {
      output.innerHTML = centerMessage(data.fallback_note || "No evidence exists for this manager.");
      return;
    }
    const ready = data.suggested_updates.filter((row) => row.review_status === "ready_for_review").length;
    output.innerHTML = `
      <div class="center-scoreboard">
        ${centerMetric("Manager", data.manager_name, data.team)}
        ${centerMetric("Evidence", String(data.evidence.length), "Normalized public claims")}
        ${centerMetric("Review queue", String(data.suggested_updates.length), `${ready} ready for review`)}
        ${centerMetric("Observed score", evaluation.summary.average_component_score == null ? "-" : `${Math.round(evaluation.summary.average_component_score * 100)}%`, `${evaluation.summary.matches} evaluated matches`)}
      </div>
      <div class="evidence-split">
        <div><div class="center-block-head"><strong>Evidence ledger</strong><span>Claim → proposed value</span></div>
          ${data.evidence.map((row) => `<div class="evidence-row"><span>${escapeHtml(row.tactical_topic.replaceAll("_", " "))}</span><strong>${escapeHtml(row.proposed_value.replaceAll("_", " "))}</strong><small>${escapeHtml(row.source_title)} · ${Math.round(row.confidence * 100)}%</small></div>`).join("")}
        </div>
        <div><div class="center-block-head"><strong>Skill update queue</strong><span>Evidence-backed, never auto-applied</span></div>
          ${data.suggested_updates.map((row) => `<div class="evidence-row"><span>${escapeHtml(row.review_status.replaceAll("_", " "))}</span><strong>${escapeHtml(row.tactical_topic.replaceAll("_", " "))}</strong><small>${row.evidence_count} evidence · ${escapeHtml(row.reason)}</small></div>`).join("") || centerMessage("No suggested updates.")}
        </div>
      </div>
    `;
  } catch (error) {
    output.innerHTML = centerMessage(error.message, "error");
  }
  refreshIcons();
}

async function loadLineupDelta() {
  const output = el("lineupDeltaCenter");
  output.innerHTML = centerMessage("Comparing lineup contracts");
  try {
    const team = el("lineupDeltaTeam").value;
    const matchId = el("lineupDeltaMatch").value.trim();
    const query = new URLSearchParams({ team });
    if (matchId) query.set("match_id", matchId);
    const data = await api(`/api/lineup-delta?${query.toString()}`);
    if (!data.available) {
      output.innerHTML = `
        ${centerMessage(data.fallback_note)}
        <div class="center-scoreboard">
          ${centerMetric("Projection", data.projected_formation || "-", `${data.projected_starters.length} likely starters`)}
          ${centerMetric("Confirmed XI", "Pending", matchId || "No match ID")}
        </div>
        <div class="lineup-list">${data.projected_starters.map((row) => `<span>${escapeHtml(row.position_slot)}<strong>${escapeHtml(row.player)}</strong><small>${Math.round(Number(row.starter_probability) * 100)}%</small></span>`).join("")}</div>
      `;
      refreshIcons();
      return;
    }
    output.innerHTML = `
      <div class="center-scoreboard">
        ${centerMetric("Projected", data.projected_formation || "-", `${data.projected_starters.length} starters`)}
        ${centerMetric("Confirmed", data.confirmed_formation || "-", `${data.confirmed_starters.length} starters`)}
        ${centerMetric("Unchanged", String(data.unchanged_starters.length), "Projection hits")}
        ${centerMetric("Surprises", String(data.unexpected_starters.length), "Unexpected starters")}
      </div>
      <div class="delta-grid">
        <div><span>Unexpected starters</span><strong>${data.unexpected_starters.map(escapeHtml).join(", ") || "None"}</strong></div>
        <div><span>Projected starters missing</span><strong>${data.missing_projected_starters.map(escapeHtml).join(", ") || "None"}</strong></div>
      </div>
    `;
  } catch (error) {
    output.innerHTML = centerMessage(error.message, "error");
  }
  refreshIcons();
}

function renderMatchReview(data) {
  const output = el("postMatchReviewCenter");
  if (!data.found) {
    output.innerHTML = centerMessage("No stored evaluation exists for this match. Run Evaluate to create one.");
    refreshIcons();
    return;
  }
  const model = data.model.at(-1);
  const matchupHits = data.matchups.filter((row) => row.edge_confirmed === true).length;
  output.innerHTML = `
    <div class="center-scoreboard">
      ${centerMetric("Result read", model?.winner_hit ? "Hit" : "Miss", model ? `${model.predicted_outcome} predicted` : "No model evaluation")}
      ${centerMetric("Exact score", model?.exact_score_hit ? "Hit" : "Miss", model ? `${model.predicted_team_a_score}-${model.predicted_team_b_score} vs ${model.actual_team_a_score}-${model.actual_team_b_score}` : "No model evaluation")}
      ${centerMetric("Brier score", model ? num(model.brier_score, 3) : "-", "Lower is better")}
      ${centerMetric("Matchup checks", `${matchupHits}/${data.matchups.length}`, "Event-derived confirmation")}
    </div>
    <div class="evidence-split">
      <div><div class="center-block-head"><strong>Manager hypotheses</strong><span>Observed vs expected</span></div>
        ${data.managers.map((row) => `<div class="evidence-row"><span>${escapeHtml(row.team)}</span><strong>${row.component_score == null ? "Not evaluable" : `${Math.round(row.component_score * 100)}%`}</strong><small>${escapeHtml(row.explanation)}</small></div>`).join("") || centerMessage("No manager evaluations.")}
      </div>
      <div><div class="center-block-head"><strong>Matchup evidence</strong><span>Top transparent checks</span></div>
        ${data.matchups.slice(0, 6).map((row) => `<div class="evidence-row"><span>${escapeHtml(row.matchup_type.replaceAll("_", " "))}</span><strong>${row.edge_confirmed == null ? "Partial" : row.edge_confirmed ? "Confirmed" : "Rejected"}</strong><small>${escapeHtml(row.evidence_metric)} · ${escapeHtml(row.observed_favored_team || "no edge")}</small></div>`).join("") || centerMessage("No matchup evaluations.")}
      </div>
    </div>
  `;
  refreshIcons();
}

async function loadMatchReview() {
  const output = el("postMatchReviewCenter");
  output.innerHTML = centerMessage("Loading evaluation");
  try {
    renderMatchReview(await api(`/api/evaluation/match/${encodeURIComponent(el("reviewMatchId").value.trim())}`));
  } catch (error) {
    output.innerHTML = centerMessage(error.message, "error");
  }
}

async function runMatchEvaluation() {
  const button = el("evaluateMatchBtn");
  setButtonBusy(button, true, "Evaluate", "Evaluating", "scan-search");
  try {
    await api("/api/evaluate-match", {
      method: "POST",
      body: JSON.stringify({
        match_id: el("reviewMatchId").value.trim(),
        team_a: el("reviewTeamA").value,
        team_b: el("reviewTeamB").value,
        team_a_score: Number(el("reviewScoreA").value),
        team_b_score: Number(el("reviewScoreB").value),
        use_model: el("useModel").checked,
      }),
    });
    await loadMatchReview();
  } catch (error) {
    el("postMatchReviewCenter").innerHTML = centerMessage(error.message, "error");
  } finally {
    setButtonBusy(button, false, "Evaluate", "Evaluating", "scan-search");
  }
}

async function refreshCenterData(buttonId, endpoint, label, after) {
  const button = el(buttonId);
  setButtonBusy(button, true, label, "Refreshing", "refresh-cw");
  try {
    const result = await api(endpoint, { method: "POST", body: "{}" });
    el("futureCenterStatus").textContent = `${result.run?.status || "refreshed"} · ${result.issue_count || 0} quality issues`;
    await after();
  } catch (error) {
    el("futureCenterStatus").textContent = "Refresh failed";
    alert(error.message);
  } finally {
    setButtonBusy(button, false, label, "Refreshing", "refresh-cw");
  }
}

async function initializeFutureCenters() {
  initCenterTabs();
  populateCenterTeams();
  el("formTeam").addEventListener("change", () => populateFormPlayers());
  el("loadPlayerFormBtn").addEventListener("click", loadPlayerForm);
  el("loadInjuryBtn").addEventListener("click", loadInjuryBoard);
  el("loadManagerEvidenceBtn").addEventListener("click", loadManagerEvidence);
  el("loadLineupDeltaBtn").addEventListener("click", loadLineupDelta);
  el("loadReviewBtn").addEventListener("click", loadMatchReview);
  el("evaluateMatchBtn").addEventListener("click", runMatchEvaluation);
  el("refreshPlayerStatsBtn").addEventListener("click", () => refreshCenterData("refreshPlayerStatsBtn", "/api/refresh-player-stats", "Refresh data", loadPlayerForm));
  el("refreshInjuryBtn").addEventListener("click", () => refreshCenterData("refreshInjuryBtn", "/api/refresh-injury-news", "Refresh data", loadInjuryBoard));
  el("refreshManagerEvidenceBtn").addEventListener("click", () => refreshCenterData("refreshManagerEvidenceBtn", "/api/refresh-tactical-evidence", "Refresh evidence", loadManagerEvidence));
  el("refreshLineupDeltaBtn").addEventListener("click", () => refreshCenterData("refreshLineupDeltaBtn", "/api/refresh-lineups", "Refresh lineups", loadLineupDelta));
  await Promise.allSettled([populateFormPlayers(), loadInjuryBoard(), populateManagerEvidence(), loadLineupDelta(), loadMatchReview()]);
}

function arenaPercent(value) {
  const number = Number(value);
  return Number.isFinite(number) ? `${Math.round(number * 100)}%` : "-";
}

function arenaResultOptions() {
  const teamA = el("arenaTeamA").value;
  const teamB = el("arenaTeamB").value;
  const previous = el("arenaResult").value;
  el("arenaResult").innerHTML = [teamA, "Draw", teamB]
    .map((value) => `<option value="${escapeHtml(value)}">${escapeHtml(value)}</option>`)
    .join("");
  if ([teamA, "Draw", teamB].includes(previous)) el("arenaResult").value = previous;
}

function arenaList(items, fallback) {
  if (!items?.length) return `<div class="arena-empty compact"><span>${escapeHtml(fallback)}</span></div>`;
  return items.map((item) => `<div class="arena-list-row"><i data-lucide="chevron-right"></i><span>${escapeHtml(item)}</span></div>`).join("");
}

function arenaTarget(target) {
  if (!target) return { pick: "Unavailable", score: "-", confidence: null, qualification: null };
  return {
    pick: target.regular_time_90?.pick || "Unavailable",
    score: target.regular_time_90?.score || "-",
    confidence: target.regular_time_90?.confidence,
    qualification: target.qualification?.pick || null,
  };
}

function arenaAgentRow(name, label, pick, score, confidence, reason, tone = "") {
  return `
    <article class="arena-agent-row ${tone}">
      <div class="arena-agent-name"><span>${escapeHtml(label)}</span><strong>${escapeHtml(name)}</strong></div>
      <div class="arena-agent-call"><strong>${escapeHtml(pick || "Unavailable")}</strong><span>${escapeHtml(score || "-")}</span></div>
      <p>${escapeHtml(reason || "No supporting explanation is available.")}</p>
      <b>${confidence == null ? "-" : arenaPercent(confidence)}</b>
    </article>
  `;
}

function arenaRowsFromRun(run) {
  if (!run) return "";
  const baseProbabilities = run.base_forecast?.probabilities || {};
  const baseChoices = [
    [run.team_a, Number(baseProbabilities.team_a_win || 0)],
    ["Draw", Number(baseProbabilities.draw || 0)],
    [run.team_b, Number(baseProbabilities.team_b_win || 0)],
  ].sort((a, b) => b[1] - a[1]);
  const baseScore = run.base_forecast?.scorelines?.[0]
    ? `${run.base_forecast.scorelines[0].team_a_score}-${run.base_forecast.scorelines[0].team_b_score}`
    : "-";
  const expert = arenaTarget(run.expert?.prediction_target);
  const kevin = arenaTarget(run.kevin?.prediction_target);
  const upset = arenaTarget(run.upset?.prediction_target);
  const final = arenaTarget(run.final_forecast?.final_prediction);
  return [
    arenaAgentRow("Base ML Model", "Probability anchor", baseChoices[0][0], baseScore, baseChoices[0][1] / 100, "Existing ensemble and exact-score distribution.", "base"),
    arenaAgentRow("Expert Agent", "Tactical read", expert.pick, expert.score, run.expert?.confidence, run.expert?.expected_match_shape, "expert"),
    arenaAgentRow("Kevin Agent", "Decisive intuition", kevin.pick, kevin.score, run.kevin?.confidence, `${run.kevin?.bold_pick || ""}. ${run.kevin?.core_reason || ""}`, "kevin"),
    arenaAgentRow("Upset Agent", "Underdog path", upset.pick, upset.score, run.upset?.confidence, run.upset?.upset_path, "upset"),
    arenaAgentRow("Skeptic Agent", "Audit layer", "No pick", run.skeptic?.overall_risk_level || "-", null, (run.skeptic?.missing_data || []).concat(run.skeptic?.unsupported_assumptions || [])[0] || "No major audit warning.", "skeptic"),
    arenaAgentRow("Final Forecast", "Aggregated call", final.pick, final.score, run.final_forecast?.final_confidence, run.final_forecast?.top_reasons?.[0], "final"),
  ].join("");
}

function arenaRowsFromRecords(records = []) {
  if (!records.length) return "";
  return records.map((record) => arenaAgentRow(
    record.agent_name,
    record.agent_name === "Final Forecast Agent" ? "Aggregated call" : "Saved forecast",
    record.regular_time_pick,
    record.regular_time_score,
    record.confidence,
    record.core_reason,
    record.agent_name === "Final Forecast Agent" ? "final" : "",
  )).join("");
}

function renderArenaPublicCard(card) {
  if (!card?.available || !card.markdown) {
    el("arenaPublicCard").innerHTML = `<div class="arena-empty compact"><span>No public card published. Run the Arena, then publish the saved version.</span></div>`;
    return;
  }
  const preview = card.markdown
    .split("\n")
    .filter((line) => line.trim() && !line.startsWith("---"))
    .slice(0, 14)
    .join("\n");
  el("arenaPublicCard").innerHTML = `<pre>${escapeHtml(preview)}</pre><small>${escapeHtml(card.path || "")}</small>`;
}

function renderPredictionArena(payload) {
  const run = payload?.run || null;
  const match = payload?.match || payload || {};
  const records = match.records || [];
  const finalRecord = records.find((record) => record.agent_name === "Final Forecast Agent");
  const final = run?.final_forecast;
  const target = final ? arenaTarget(final.final_prediction) : {
    pick: finalRecord?.regular_time_pick || "No forecast yet",
    score: finalRecord?.regular_time_score || "-",
    confidence: finalRecord?.confidence,
    qualification: finalRecord?.qualification_pick,
  };
  const reasons = final?.top_reasons || (finalRecord ? [finalRecord.core_reason] : []);
  const fragile = final?.fragile_assumptions || finalRecord?.fragile_assumptions || [];
  const watch = final?.what_to_watch || [];
  const warnings = [...(run?.fallback_notes || []), ...(match.warnings || [])];

  el("arenaVersion").textContent = match.version ? `Version ${match.version} · ${records[0]?.status || "saved"}` : "No saved version";
  el("arenaStatus").textContent = warnings[0] || (match.found ? `Saved run, version ${match.version}` : "Ready for a matchup");
  el("arenaForecast").innerHTML = `
    <div class="arena-final-call">
      <div class="arena-final-label"><span>Final 90-minute call</span><small>${escapeHtml(run?.stage || match.stage || el("arenaStage").value)}</small></div>
      <div class="arena-score-call"><strong>${escapeHtml(target.pick)}</strong><b>${escapeHtml(target.score)}</b></div>
      <div class="arena-confidence"><span>Confidence</span><strong>${target.confidence == null ? "-" : arenaPercent(final?.final_confidence ?? target.confidence)}</strong><div><i style="width:${Math.min(100, Number(final?.final_confidence ?? target.confidence ?? 0) * 100)}%"></i></div></div>
      <p>${escapeHtml(reasons[0] || "Run the Arena to generate an audited forecast.")}</p>
      ${target.qualification ? `<div class="arena-qualification"><span>Qualification</span><strong>${escapeHtml(target.qualification)}</strong></div>` : ""}
    </div>
    <div class="arena-forecast-note">
      <i data-lucide="${warnings.length ? "triangle-alert" : "shield-check"}"></i>
      <div><strong>${warnings.length ? "Data notes" : "Forecast guardrail"}</strong><span>${escapeHtml(warnings[0] || "Technical entertainment forecast. Every call remains uncertain.")}</span></div>
    </div>
  `;
  el("arenaAgentBattle").innerHTML = arenaRowsFromRun(run) || arenaRowsFromRecords(records) || `<div class="arena-empty compact"><span>No agent outputs are saved for this match.</span></div>`;
  el("arenaFragile").innerHTML = arenaList(fragile, "No fragile assumptions are available.");
  el("arenaWatch").innerHTML = arenaList(watch, run ? "No additional watch signals were produced." : "Detailed watch signals are available immediately after a new run.");
  renderArenaPublicCard(match.public_card);
  refreshIcons();
}

function renderArenaLeaderboard(data) {
  const rows = data?.leaderboard || [];
  if (!rows.length) {
    el("arenaLeaderboard").innerHTML = `<div class="arena-empty compact"><span>No completed match evaluations yet.</span></div>`;
    return;
  }
  el("arenaLeaderboard").innerHTML = `
    <table class="arena-table"><thead><tr><th>Agent</th><th>Matches</th><th>Points</th><th>Result hit</th><th>Exact</th><th>Confidence</th></tr></thead><tbody>
      ${rows.map((row, index) => `<tr><td><span>${index + 1}</span><strong>${escapeHtml(row.agent_name)}</strong></td><td>${row.matches_predicted}</td><td><b>${row.total_points}</b></td><td>${arenaPercent(row.winner_accuracy)}</td><td>${row.exact_score_hits}</td><td>${arenaPercent(row.average_confidence)}${row.calibration_warning ? `<small>${escapeHtml(row.calibration_warning.replaceAll("_", " "))}</small>` : ""}</td></tr>`).join("")}
    </tbody></table>
  `;
}

function renderArenaCalibration(data) {
  const performance = data?.agent_performance || [];
  const warnings = data?.warnings || [];
  if (!performance.length && !warnings.length) {
    el("arenaCalibration").innerHTML = `<div class="arena-empty compact"><span>Calibration needs completed match evaluations.</span></div>`;
    return;
  }
  el("arenaCalibration").innerHTML = performance.map((row) => `
    <div class="arena-calibration-row">
      <strong>${escapeHtml(row.agent_name)}</strong>
      <span>${row.warnings?.length ? row.warnings.map((warning) => escapeHtml(warning.replaceAll("_", " "))).join(" · ") : "No current warning"}</span>
      <b>${arenaPercent(row.winner_accuracy)}</b>
    </div>
  `).join("") || arenaList(warnings, "No current warning");
}

async function loadArenaLeaderboard() {
  try {
    renderArenaLeaderboard(await api("/api/prediction-arena/leaderboard"));
  } catch (error) {
    el("arenaLeaderboard").innerHTML = `<div class="arena-empty compact error"><span>${escapeHtml(error.message)}</span></div>`;
  }
}

async function loadArenaCalibration() {
  try {
    renderArenaCalibration(await api("/api/prediction-arena/calibration"));
  } catch (error) {
    el("arenaCalibration").innerHTML = `<div class="arena-empty compact error"><span>${escapeHtml(error.message)}</span></div>`;
  }
}

async function runPredictionArena() {
  const button = el("arenaRunBtn");
  setButtonBusy(button, true, "Run Arena", "Running agents", "sparkles");
  el("arenaStatus").textContent = "Running model, tactical brief, agents, and skeptic audit";
  try {
    const data = await api("/api/prediction-arena/run", {
      method: "POST",
      body: JSON.stringify({
        match_id: el("arenaMatchId").value.trim(),
        team_a: el("arenaTeamA").value,
        team_b: el("arenaTeamB").value,
        stage: el("arenaStage").value,
      }),
    });
    renderPredictionArena(data);
  } catch (error) {
    el("arenaStatus").textContent = "Arena run failed";
    el("arenaForecast").innerHTML = `<div class="arena-empty error"><strong>Prediction Arena could not run.</strong><span>${escapeHtml(error.message)}</span></div>`;
  } finally {
    setButtonBusy(button, false, "Run Arena", "Running agents", "sparkles");
  }
}

async function loadPredictionArenaMatch() {
  const matchId = el("arenaMatchId").value.trim();
  if (!matchId) return;
  renderPredictionArena(await api(`/api/prediction-arena/match/${encodeURIComponent(matchId)}`));
}

async function arenaMatchAction(buttonId, endpoint, label, busyLabel) {
  const button = el(buttonId);
  setButtonBusy(button, true, label, busyLabel, buttonId === "arenaLockBtn" ? "lock-keyhole" : "send");
  try {
    const data = await api(endpoint, {
      method: "POST",
      body: JSON.stringify({ match_id: el("arenaMatchId").value.trim() }),
    });
    renderPredictionArena(data);
  } catch (error) {
    el("arenaStatus").textContent = error.message;
  } finally {
    setButtonBusy(button, false, label, busyLabel, buttonId === "arenaLockBtn" ? "lock-keyhole" : "send");
  }
}

async function settlePredictionArena() {
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
    renderPredictionArena(data);
    renderArenaLeaderboard(data.leaderboard);
    await loadArenaCalibration();
  } catch (error) {
    el("arenaStatus").textContent = error.message;
  } finally {
    setButtonBusy(button, false, "Evaluate Result", "Evaluating", "clipboard-check");
  }
}

async function initializePredictionArena() {
  if (!el("arenaRunBtn")) return;
  arenaResultOptions();
  el("arenaTeamA").addEventListener("change", arenaResultOptions);
  el("arenaTeamB").addEventListener("change", arenaResultOptions);
  el("arenaRunBtn").addEventListener("click", runPredictionArena);
  el("arenaLockBtn").addEventListener("click", () => arenaMatchAction("arenaLockBtn", "/api/prediction-arena/lock", "Lock", "Locking"));
  el("arenaPublishBtn").addEventListener("click", () => arenaMatchAction("arenaPublishBtn", "/api/prediction-arena/publish-card", "Publish", "Publishing"));
  el("arenaSettleBtn").addEventListener("click", settlePredictionArena);
  el("arenaRefreshBoardBtn").addEventListener("click", () => Promise.allSettled([loadArenaLeaderboard(), loadArenaCalibration()]));
  await Promise.allSettled([loadPredictionArenaMatch(), loadArenaLeaderboard(), loadArenaCalibration()]);
}

function initNavigationState() {
  const navLinks = [...document.querySelectorAll(".primary-nav a")];
  const anchorLinks = navLinks.filter((link) => link.getAttribute("href")?.startsWith("#"));
  const sections = anchorLinks
    .map((link) => document.querySelector(link.getAttribute("href")))
    .filter(Boolean);

  const setActive = (sectionId) => {
    navLinks.forEach((link) => {
      const active = link.getAttribute("href") === `#${sectionId}`;
      link.classList.toggle("active", active);
      if (active) link.setAttribute("aria-current", "page");
      else link.removeAttribute("aria-current");
    });
  };

  anchorLinks.forEach((link) => {
    link.addEventListener("click", () => {
      if (document.querySelector(link.getAttribute("href"))?.classList.contains("research-secondary")) {
        setResearchToolsVisibility(true);
      }
      setActive(link.getAttribute("href").slice(1));
      document.querySelector(".lab-section-menu")?.removeAttribute("open");
    });
  });

  if (!sections.length) return;
  setActive(sections[0].id);
  const observer = new IntersectionObserver(
    (entries) => {
      const visible = entries
        .filter((entry) => entry.isIntersecting)
        .sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
      if (visible) setActive(visible.target.id);
    },
    { rootMargin: "-140px 0px -65% 0px", threshold: [0, 0.1, 0.4] },
  );
  sections.forEach((section) => observer.observe(section));
}

function setResearchToolsVisibility(visible) {
  const button = el("researchToolsBtn");
  if (!button) return;
  document.body.classList.toggle("research-tools-visible", visible);
  button.innerHTML = visible
    ? '<i data-lucide="panel-top-close"></i><span>Hide Research Tools</span>'
    : '<i data-lucide="sliders-horizontal"></i><span>Show Research Tools</span>';
  refreshIcons();
}

function initResearchTools() {
  const button = el("researchToolsBtn");
  if (!button) return;
  button.addEventListener("click", () => setResearchToolsVisibility(!document.body.classList.contains("research-tools-visible")));
}

async function init() {
  initNavigationState();
  initResearchTools();
  const [status, teams, groups, venues, modelReport, lineupStatus, xgStatus, penaltyStatus, penaltyOptions] = await Promise.all([
    api("/api/status"),
    api("/api/teams"),
    api("/api/groups"),
    api("/api/venues"),
    api("/api/model-report"),
    api("/api/lineup-status"),
    api("/api/xg/status"),
    api("/api/penalties/status"),
    api("/api/penalties/options"),
  ]);
  state.teams = teams.teams;
  state.venues = venues.venues;
  el("modelStatus").textContent = status.model_exists ? "Ensemble ready" : "Baseline model";
  el("signalModel").textContent = status.model_exists ? "RF + DC + Elo" : "Baseline";
  el("signalIntelligence").textContent = `${status.intelligence.documents} evidence chunks`;
  el("signalLive").textContent = status.live_state.source || "manual";
  el("signalVenues").textContent = `${state.venues.length} venues · ${status.fixtures?.matches || 0} fixtures`;
  el("intelligenceStatus").textContent = `${status.intelligence.retriever} · ${status.intelligence.documents} chunks`;
  el("liveMetric").textContent = status.live_state.source || "manual";
  populateTeams();
  await Promise.allSettled([initializeFutureCenters(), initializePredictionArena(), loadLatestResultsBoard()]);
  populateVenues(state.venues);
  renderGroups(groups.groups);
  renderModelReport(modelReport);
  renderLineupStatus(lineupStatus);
  renderAdvancedModelStatus(xgStatus, penaltyStatus);
  populatePenaltyOptions(penaltyOptions);
  renderVenueMap(state.venues);
  el("runBtn").addEventListener("click", runSimulation);
  el("matchBtn").addEventListener("click", predictMatch);
  el("refreshBtn").addEventListener("click", refreshLiveData);
  el("edgeBtn").addEventListener("click", analyzeEdges);
  el("askBtn").addEventListener("click", () => askIntelligence());
  el("analystBriefBtn").addEventListener("click", () => runAnalystBrief());
  el("lockMatchBtn").addEventListener("click", lockLiveScore);
  el("eliminateBtn").addEventListener("click", () => setEliminated(true));
  el("restoreBtn").addEventListener("click", () => setEliminated(false));
  el("venueSelect").addEventListener("change", refreshVenueWeather);
  el("squadSelect").addEventListener("change", refreshSquad);
  el("refreshLineupsBtn").addEventListener("click", refreshLineups);
  el("xgBtn").addEventListener("click", predictXg);
  el("penaltyBtn").addEventListener("click", predictPenalty);
  el("penaltyKicker").addEventListener("change", updatePenaltyContext);
  el("penaltyKeeper").addEventListener("change", updatePenaltyContext);
  el("xgTeam").addEventListener("change", renderXgDanger);
  ["weather", "travel", "fatigue", "homeAdvantage", "useModel"].forEach((id) => {
    el(id).addEventListener("change", predictMatch);
  });
  document.addEventListener("click", (event) => {
    const prompt = event.target.closest("[data-question]");
    if (prompt) askIntelligence(prompt.dataset.question);
  });
  refreshIcons();
  await refreshVenueWeather();
  await refreshSquad();
  await predictMatch();
  await runAnalystBrief(false);
  if (xgStatus.available) {
    await predictXg();
  } else {
    el("xgResult").innerHTML = `<div class="empty">Run the xG trainer</div>`;
  }
  if (penaltyStatus.available) {
    await predictPenalty();
  } else {
    el("penaltyResult").innerHTML = `<div class="empty">Run the penalty trainer</div>`;
  }
}

init().catch((error) => {
  console.error(error);
  alert(error.message);
});
