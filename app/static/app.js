const state = {
  teams: [],
  running: false,
};

const el = (id) => document.getElementById(id);

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
        <td><strong>${team.win_pct}%</strong></td>
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
  el("teamA").innerHTML = options;
  el("teamB").innerHTML = options;
  el("teamA").value = "France";
  el("teamB").value = "Brazil";
}

async function runSimulation() {
  if (state.running) return;
  state.running = true;
  const button = el("runBtn");
  button.disabled = true;
  button.textContent = "Running";
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
    button.disabled = false;
    button.textContent = "Run Simulation";
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
      <div class="prob-row">
        <span>${data.probabilities.team_a_win}%</span>
        <span>${data.probabilities.draw}%</span>
        <span>${data.probabilities.team_b_win}%</span>
      </div>
    </div>
    ${data.scorelines.map((line) => `
      <div class="scoreline">
        <span class="inline-team">${flagHtml(data.team_a)}<b>${line.team_a_score}-${line.team_b_score}</b>${flagHtml(data.team_b)}</span>
        <strong>${line.probability}%</strong>
      </div>
    `).join("")}
  `;
}

async function refreshLiveData() {
  const button = el("refreshBtn");
  button.disabled = true;
  button.textContent = "Refreshing";
  try {
    const data = await api("/api/refresh-live-data", { method: "POST", body: "{}" });
    el("liveMetric").textContent = data.live_state.source;
    alert(data.message);
  } finally {
    button.disabled = false;
    button.textContent = "Refresh Live Data";
  }
}

async function init() {
  const [status, teams, groups] = await Promise.all([
    api("/api/status"),
    api("/api/teams"),
    api("/api/groups"),
  ]);
  state.teams = teams.teams;
  el("modelStatus").textContent = status.model_exists ? "Random Forest ready" : "Baseline model";
  el("liveMetric").textContent = status.live_state.source || "manual";
  populateTeams();
  renderGroups(groups.groups);
  el("runBtn").addEventListener("click", runSimulation);
  el("matchBtn").addEventListener("click", predictMatch);
  el("refreshBtn").addEventListener("click", refreshLiveData);
  ["weather", "travel", "fatigue", "homeAdvantage", "useModel"].forEach((id) => {
    el(id).addEventListener("change", predictMatch);
  });
  await predictMatch();
}

init().catch((error) => {
  console.error(error);
  alert(error.message);
});
