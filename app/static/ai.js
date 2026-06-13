const state = {
  stories: new Map(),
  offset: 0,
  limit: 4,
  totalUpcoming: 0,
  loading: false,
};

const el = (id) => document.getElementById(id);

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
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

function flag(team) {
  const source = team.flag_image || "https://flagcdn.com/w80/un.png";
  return `<img src="${escapeHtml(source)}" alt="" loading="lazy">`;
}

function score(story) {
  const value = story.observed_score || story.predicted_score || {};
  return `${value.team_a ?? "?"}-${value.team_b ?? "?"}`;
}

function kickoff(story) {
  const value = story.kickoff_local || story.kickoff_utc;
  if (!value) return "Schedule pending";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(parsed);
}

function confidenceText(story) {
  const label = story.confidence?.label || "Unknown";
  return `${label} confidence`;
}

function storyHtml(story) {
  const deduction = story.deduction || {};
  return `
    <article class="match-story">
      <button class="match-story-button" type="button" data-story-match="${escapeHtml(story.match_id)}" aria-label="Open ${escapeHtml(story.team_a.name)} versus ${escapeHtml(story.team_b.name)} deduction">
        <div class="match-summary">
          <span class="match-meta">${escapeHtml(kickoff(story))}<br>${escapeHtml(story.venue || "Venue pending")}</span>
          <div class="team-line">${flag(story.team_a)}<strong>${escapeHtml(story.team_a.name)}</strong></div>
          <div class="score-call"><strong>${escapeHtml(score(story))}</strong><span>${story.observed_score ? "Observed result" : "Predicted score"}</span></div>
          <div class="team-line">${flag(story.team_b)}<strong>${escapeHtml(story.team_b.name)}</strong></div>
          <span class="pick-line">${escapeHtml(story.pick)} ${escapeHtml(story.pick_probability)}% / ${escapeHtml(confidenceText(story))}</span>
        </div>
        <div class="match-deduction">
          <div class="deduction-heading">
            <span>${escapeHtml(story.stage)}${story.group ? ` / Group ${escapeHtml(story.group)}` : ""}</span>
            <h2>${escapeHtml(story.headline)}</h2>
          </div>
          <p class="deduction-preview">${escapeHtml(deduction.why_this_score || deduction.likely_script)}</p>
          <span class="open-read">Open analysis <i data-lucide="arrow-up-right"></i></span>
        </div>
      </button>
    </article>
  `;
}

function errorHtml(error) {
  return `<div class="error-state"><strong>Could not load predictions.</strong><span>${escapeHtml(error.message)}</span></div>`;
}

function renderStories(stories, append = false) {
  stories.forEach((story) => state.stories.set(String(story.match_id), story));
  const html = stories.map(storyHtml).join("");
  if (append) {
    el("matchStories").insertAdjacentHTML("beforeend", html);
  } else {
    el("matchStories").innerHTML = html || `<div class="empty-state"><strong>No upcoming matches found.</strong><span>Refresh when new fixtures are available.</span></div>`;
  }
  lucide.createIcons();
}

function managerRow(manager) {
  return `
    <div class="manager-read">
      <span>${escapeHtml(manager.team)}</span>
      <strong>${escapeHtml(manager.name || "Manager profile pending")}</strong>
      <small>${escapeHtml(manager.formation || "Flexible shape")} / ${escapeHtml(manager.style || "Flexible style")}</small>
    </div>
  `;
}

function deductionBlock(label, text) {
  return `
    <section class="detail-read">
      <strong>${escapeHtml(label)}</strong>
      <p>${escapeHtml(text || "No reliable deduction is available yet.")}</p>
    </section>
  `;
}

function openStory(story) {
  if (!story) return;
  const deduction = story.deduction || {};
  const probabilities = story.probabilities || {};
  el("matchDetailTitle").textContent = `${story.team_a.name} vs ${story.team_b.name}`;
  el("matchDetailBody").innerHTML = `
    <div class="detail-scoreboard">
      <div>${flag(story.team_a)}<strong>${escapeHtml(story.team_a.name)}</strong></div>
      <div class="detail-score"><strong>${escapeHtml(score(story))}</strong><span>${escapeHtml(story.headline)}</span></div>
      <div class="right">${flag(story.team_b)}<strong>${escapeHtml(story.team_b.name)}</strong></div>
    </div>
    <div class="probability-numbers">
      <div><span>${escapeHtml(story.team_a.name)}</span><strong>${escapeHtml(probabilities.team_a_win ?? 0)}%</strong></div>
      <div><span>Draw</span><strong>${escapeHtml(probabilities.draw ?? 0)}%</strong></div>
      <div><span>${escapeHtml(story.team_b.name)}</span><strong>${escapeHtml(probabilities.team_b_win ?? 0)}%</strong></div>
    </div>
    <div class="detail-reads">
      ${deductionBlock("Why this score", deduction.why_this_score)}
      ${deductionBlock("Likely match script", deduction.likely_script)}
      ${deductionBlock("Decisive clash", deduction.decisive_clash)}
      ${deductionBlock("Manager move", deduction.manager_move)}
      ${deductionBlock("Player to watch", deduction.player_watch)}
      ${deductionBlock("Opponent path", deduction.opponent_path)}
    </div>
    <section class="manager-matchup">
      <h3>Manager matchup</h3>
      ${(story.managers || []).map(managerRow).join("")}
    </section>
    <p class="boundary-note">${escapeHtml(story.reasoning_boundary)}</p>
  `;
  el("matchDetailShell").hidden = false;
  document.body.style.overflow = "hidden";
  lucide.createIcons();
}

function closeStory() {
  el("matchDetailShell").hidden = true;
  document.body.style.overflow = "";
}

async function loadStories({ reset = false } = {}) {
  if (state.loading) return;
  state.loading = true;
  const button = el("loadMore");
  button.disabled = true;
  if (reset) {
    state.offset = 0;
    el("matchStories").innerHTML = `<article class="story-skeleton"></article><article class="story-skeleton"></article><article class="story-skeleton"></article>`;
  }
  try {
    const payload = await api(`/api/ai/match-stories?limit=${state.limit}&offset=${state.offset}&use_model=true`);
    state.totalUpcoming = payload.total_upcoming || 0;
    renderStories(payload.stories || [], !reset && state.offset > 0);
    state.offset = payload.next_offset ?? state.offset + (payload.stories || []).length;
    button.hidden = !payload.has_more;
    el("coverageLine").textContent = `${state.offset} of ${state.totalUpcoming} predictions ready`;
  } catch (error) {
    el("matchStories").innerHTML = errorHtml(error);
    button.hidden = true;
  } finally {
    state.loading = false;
    button.disabled = false;
  }
}

async function loadStatus() {
  const status = await api("/api/ai/status");
  const curation = status.manager_curation || {};
  el("liveStatus").textContent = `${status.live.completed_count} results recorded`;
  el("coverageLine").textContent = `${curation.observed_managers || 0} manager profiles ready`;
}

el("matchStories").addEventListener("click", (event) => {
  const target = event.target.closest("[data-story-match]");
  if (target) openStory(state.stories.get(target.dataset.storyMatch));
});

el("loadMore").addEventListener("click", () => loadStories());

el("refreshLive").addEventListener("click", async () => {
  const button = el("refreshLive");
  button.disabled = true;
  try {
    await api("/api/ai/refresh-live", { method: "POST", body: "{}" });
    await Promise.all([loadStatus(), loadStories({ reset: true })]);
  } catch (error) {
    el("coverageLine").textContent = error.message;
  } finally {
    button.disabled = false;
  }
});

el("closeMatchDetail").addEventListener("click", closeStory);
el("closeMatchDetailBackdrop").addEventListener("click", closeStory);
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !el("matchDetailShell").hidden) closeStory();
});

Promise.all([loadStatus(), loadStories({ reset: true })]).catch((error) => {
  el("matchStories").innerHTML = errorHtml(error);
});

lucide.createIcons();
