const state = {
  teams: [],
  venues: [],
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

function currentScenario() {
  return {
    weather: el("weather").value,
    venue: el("venueSelect").value,
    travel: Number(el("travel").value),
    fatigue: Number(el("fatigue").value),
    home_advantage: Number(el("homeAdvantage").value),
  };
}

async function api(path, options = {}) {
  const response = await fetch(path, {
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

function renderBracket(bracket) {
  el("championMetric").innerHTML = `${flagHtml(bracket.champion)} <span>${bracket.champion.name}</span>`;
  el("bracketSub").innerHTML = `${flagHtml(bracket.champion)} <span>${bracket.champion.name}</span>`;
  const matchById = Object.fromEntries(
    bracket.rounds.flatMap((round) => round.matches).map((match) => [match.id, match])
  );
  const byIds = (ids) => ids.map((id) => matchById[id]).filter(Boolean);
  const finalMatch = matchById[103] || bracket.rounds.at(-1).matches[0];
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
  return `
    <div class="match-card ${isFinal ? "final-card" : ""}">
      <div class="match-meta">
        <span>M${match.id || ""}</span>
        <span>${match.venue || ""}</span>
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
    .map((team) => `<option value="${team.name}">${team.flag} ${team.name}</option>`)
    .join("");
  ["teamA", "teamB", "liveTeamA", "liveTeamB", "eliminateTeam"].forEach((id) => {
    el(id).innerHTML = options;
  });
  el("teamA").value = "France";
  el("teamB").value = "Brazil";
  el("liveTeamA").value = "Mexico";
  el("liveTeamB").value = "South Africa";
}

function populateVenues(venues) {
  const options = venues.map((venue) => `<option value="${venue.venue}">${venue.venue}</option>`).join("");
  el("venueSelect").innerHTML = options;
  el("venueSelect").value = venues.find((venue) => venue.venue === "Mexico City") ? "Mexico City" : venues[0]?.venue || "";
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
        ...currentScenario(),
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
    ${renderAdvancedInsights(data)}
    ${renderScoreMatrix(data)}
    ${data.scorelines.map((line) => `
      <div class="scoreline">
        <span class="inline-team">${flagHtml(data.team_a)}<b>${line.team_a_score}-${line.team_b_score}</b>${flagHtml(data.team_b)}</span>
        <strong>${line.probability}%</strong>
      </div>
    `).join("")}
  `;
  window.setTimeout(() => drawScoreChart(data), 0);
}

function renderAdvancedInsights(data) {
  const insights = data.score_insights;
  const confidence = data.confidence;
  const shapDrivers = data.shap_drivers && data.shap_drivers.available ? data.shap_drivers.drivers : [];
  const drivers = [...shapDrivers, ...(data.model_drivers || []), ...(data.scenario_drivers || [])].slice(0, 8);
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
    <div id="scoreChart" class="score-chart"></div>
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
      inRange: { color: ["#eef0f3", "#f0b63d", "#c8202f"] },
    },
    series: [{ type: "heatmap", data: values, label: { show: true, formatter: (params) => `${params.value[2]}%` } }],
  });
}

async function refreshLiveData() {
  const button = el("refreshBtn");
  setButtonBusy(button, true, "Refresh Live Data", "Refreshing", "refresh-cw");
  try {
    const data = await api("/api/refresh-live-data", { method: "POST", body: "{}" });
    el("liveMetric").textContent = data.live_state.source;
    el("signalLive").textContent = data.live_state.source;
    alert(data.message);
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
        ...currentScenario(),
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
      itemStyle: { color: (params) => (params.value >= 0 ? "#0f7355" : "#d21f36") },
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
        itemStyle: { color: (params) => (params.value > 0 ? "#156f54" : "#c8202f") },
      },
    ],
  });
}

async function refreshVenueWeather() {
  const venue = el("venueSelect").value;
  if (!venue) return;
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
    const marker = new maplibregl.Marker({ color: "#c8202f" })
      .setLngLat([venue.longitude, venue.latitude])
      .setPopup(new maplibregl.Popup().setHTML(`<strong>${venue.venue}</strong><br>${venue.city}, ${venue.country}`))
      .addTo(state.venueMap);
    marker.getElement().addEventListener("click", () => {
      el("venueSelect").value = venue.venue;
      refreshVenueWeather();
    });
  });
}

async function init() {
  const [status, teams, groups, venues] = await Promise.all([
    api("/api/status"),
    api("/api/teams"),
    api("/api/groups"),
    api("/api/venues"),
  ]);
  state.teams = teams.teams;
  state.venues = venues.venues;
  el("modelStatus").textContent = status.model_exists ? "Random Forest ready" : "Baseline model";
  el("signalModel").textContent = status.model_exists ? "Random Forest" : "Baseline";
  el("signalIntelligence").textContent = `${status.intelligence.documents} evidence chunks`;
  el("signalLive").textContent = status.live_state.source || "manual";
  el("signalVenues").textContent = `${state.venues.length} mapped`;
  el("intelligenceStatus").textContent = `${status.intelligence.retriever} · ${status.intelligence.documents} chunks`;
  el("liveMetric").textContent = status.live_state.source || "manual";
  populateTeams();
  populateVenues(state.venues);
  renderGroups(groups.groups);
  renderVenueMap(state.venues);
  el("runBtn").addEventListener("click", runSimulation);
  el("matchBtn").addEventListener("click", predictMatch);
  el("refreshBtn").addEventListener("click", refreshLiveData);
  el("edgeBtn").addEventListener("click", analyzeEdges);
  el("askBtn").addEventListener("click", () => askIntelligence());
  el("lockMatchBtn").addEventListener("click", lockLiveScore);
  el("eliminateBtn").addEventListener("click", () => setEliminated(true));
  el("restoreBtn").addEventListener("click", () => setEliminated(false));
  el("venueSelect").addEventListener("change", refreshVenueWeather);
  ["weather", "travel", "fatigue", "homeAdvantage", "useModel"].forEach((id) => {
    el(id).addEventListener("change", predictMatch);
  });
  document.addEventListener("click", (event) => {
    const prompt = event.target.closest("[data-question]");
    if (prompt) askIntelligence(prompt.dataset.question);
  });
  refreshIcons();
  await refreshVenueWeather();
  await predictMatch();
}

init().catch((error) => {
  console.error(error);
  alert(error.message);
});
