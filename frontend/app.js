/* FilingLens frontend: plain JavaScript, no build step. */
(() => {
  const $ = (sel) => document.querySelector(sel);
  const el = {
    form: $("#ask-form"), q: $("#question"), btn: $("#ask-btn"), examples: $("#examples"),
    result: $("#result"), paperQ: $("#paper-question"), summary: $("#paper-summary"),
    claims: $("#claims"), legend: $("#legend"), trail: $("#trail"), sources: $("#sources"),
    coverage: $("#coverage-table"), coverageNote: $("#coverage-note"),
    model: $("#status-model"), db: $("#status-db"), theme: $("#theme-toggle"),
  };

  const state = { sources: [], claims: [], busy: false };

  // ------------------------------------------------------------------ helpers
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const withRefs = (html) => html.replace(/\[(\d+)\]/g, (_, n) => `<button type="button" class="ref" data-ref="${n}" aria-label="Source ${n}">${n}</button>`);
  const seconds = (ms) => (ms >= 1000 ? `${(ms / 1000).toFixed(1)} s` : `${ms} ms`);

  const TICKS = {
    verified: '<svg class="tick ok" viewBox="0 0 28 22" aria-hidden="true"><path d="M3 12 l7 7 L25 3"/></svg>',
    number_mismatch: '<svg class="tick bad" viewBox="0 0 28 22" aria-hidden="true"><circle cx="14" cy="11" r="8.5"/><path d="M11 8.5c0-2 1.3-3 3-3s3 1 3 2.6c0 2.2-3 2.3-3 4.4M14 15.6v.2"/></svg>',
    weak_support: '<svg class="tick weak" viewBox="0 0 28 22" aria-hidden="true"><path d="M6 11h16"/></svg>',
    uncited: '<svg class="tick weak" viewBox="0 0 28 22" aria-hidden="true"><path d="M6 11h16"/></svg>',
  };
  const STATUS_TEXT = {
    verified: "Agrees with the cited filing",
    number_mismatch: "A number isn't in the cited source",
    weak_support: "The cited source doesn't clearly say this",
    uncited: "No source cited",
  };

  // ------------------------------------------------------------------ theme
  const savedTheme = (() => { try { return localStorage.getItem("fl-theme"); } catch { return null; } })();
  if (savedTheme) document.documentElement.dataset.theme = savedTheme;
  el.theme.addEventListener("click", () => {
    const dark = document.documentElement.dataset.theme
      ? document.documentElement.dataset.theme === "dark"
      : matchMedia("(prefers-color-scheme: dark)").matches;
    const next = dark ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem("fl-theme", next); } catch { /* storage unavailable */ }
  });

  // ------------------------------------------------------------------ status
  async function loadHealth() {
    try {
      const h = await (await fetch("/api/health")).json();
      el.model.textContent = h.models_ready ? `${h.llm_model} via ${h.llm_provider}` : "Loading search models…";
      el.model.className = "status-item " + (h.warmup_error ? "bad" : h.models_ready ? "ok" : "");
      if (h.warmup_error) el.model.textContent = "Search models failed to load";
      el.db.textContent = h.database ? "Database connected" : "Database offline";
      el.db.className = "status-item " + (h.database ? "ok" : "bad");
      if (!h.models_ready && !h.warmup_error) setTimeout(loadHealth, 3000);
    } catch {
      el.model.textContent = "Server unreachable";
      el.model.className = "status-item bad";
      setTimeout(loadHealth, 5000);
    }
  }

  // ------------------------------------------------------------------ coverage + examples
  async function loadCoverage() {
    let data;
    try {
      const r = await fetch("/api/coverage");
      if (!r.ok) throw new Error((await r.json()).detail);
      data = await r.json();
    } catch (err) {
      el.coverageNote.textContent = "Can't read the database. Start Postgres, then refresh.";
      renderExamples(null);
      return;
    }
    const years = [...new Set(data.filings.map((f) => f.fiscal_year))].sort();
    if (!data.filings.length) {
      el.coverageNote.textContent = "Nothing is indexed yet. Run the download, parse and index steps from the README, then refresh.";
      renderExamples(null);
      return;
    }
    const byKey = new Map(data.filings.map((f) => [`${f.ticker}-${f.fiscal_year}`, f]));
    const head = `<thead><tr><th scope="col">Company</th>${years.map((y) => `<th scope="col">FY${y}</th>`).join("")}</tr></thead>`;
    const rows = data.companies.map((c) => {
      const cells = years.map((y) => {
        const f = byKey.get(`${c.ticker}-${y}`);
        return f ? `<td title="${f.chunks} passages, ${f.tables} tables">${f.chunks.toLocaleString()}</td>` : '<td class="missing">none</td>';
      }).join("");
      return `<tr><th scope="row"><button type="button" class="pick" data-name="${esc(c.name)}">${esc(c.name)}<span class="ticker">${c.ticker}</span></button></th>${cells}</tr>`;
    }).join("");
    el.coverage.innerHTML = `<caption class="visually-hidden">Passages indexed per company and fiscal year</caption>${head}<tbody>${rows}</tbody>`;
    el.coverage.querySelector("caption").style.cssText = "position:absolute;left:-9999px";
    renderExamples(data);
  }

  function renderExamples(data) {
    const has = (t) => data && data.filings.some((f) => f.ticker === t);
    const yearsOf = (t) => data ? data.filings.filter((f) => f.ticker === t).map((f) => f.fiscal_year).sort() : [];
    const list = [];
    if (!data || has("AAPL")) list.push("What supply chain risks does Apple describe?");
    const nv = yearsOf("NVDA");
    if (nv.length > 1) list.push(`How did NVIDIA's research and development expense change from ${nv[0]} to ${nv[nv.length - 1]}?`);
    else if (!data) list.push("How did NVIDIA's research and development expense change over the last two years?");
    const ms = yearsOf("MSFT"), go = yearsOf("GOOGL");
    const common = ms.filter((y) => go.includes(y)).pop();
    if (common) list.push(`Compare Microsoft and Alphabet total revenue in fiscal ${common}.`);
    if (!data || has("JPM")) list.push("How does JPMorgan Chase describe its cybersecurity risks?");
    list.push("What was Tesla's revenue in 1995?");
    el.examples.querySelectorAll(".example").forEach((b) => b.remove());
    for (const text of list.slice(0, 5)) {
      const b = document.createElement("button");
      b.type = "button"; b.className = "example"; b.textContent = text;
      b.addEventListener("click", () => { el.q.value = text; ask(); });
      el.examples.appendChild(b);
    }
  }

  el.coverage.addEventListener("click", (e) => {
    const b = e.target.closest(".pick");
    if (!b) return;
    const name = b.dataset.name;
    const q = el.q.value.trim();
    el.q.value = q ? (q.includes(name) ? q : `${q} ${name}`) : `What does ${name} say about `;
    el.q.focus();
    el.q.setSelectionRange(el.q.value.length, el.q.value.length);
    el.q.scrollIntoView({ behavior: "smooth", block: "center" });
  });

  // ------------------------------------------------------------------ rendering
  function resetResult(question) {
    state.sources = []; state.claims = [];
    el.result.hidden = false;
    el.paperQ.textContent = question;
    el.summary.textContent = "Working…";
    el.claims.innerHTML = "";
    el.trail.innerHTML = "";
    el.sources.innerHTML = "";
    el.legend.hidden = true;
  }

  function renderStep(ev) {
    let li = el.trail.querySelector(`[data-step="${ev.id}"]`);
    if (!li) {
      li = document.createElement("li");
      li.dataset.step = ev.id;
      li.innerHTML = '<span class="step-label"></span><span class="step-ms"></span><span class="step-detail"></span>';
      el.trail.appendChild(li);
    }
    li.className = ev.status;
    li.querySelector(".step-label").textContent = ev.label;
    li.querySelector(".step-ms").textContent = ev.ms != null ? seconds(ev.ms) : "";
    li.querySelector(".step-detail").textContent = ev.detail || "";
  }

  function splitSentences(text) {
    return text.replace(/([.!?])\s*((?:\[\d+\]\s*)+)/g, " $2$1 ").split(/(?<=[.!?])\s+(?=\S)/).map((s) => s.trim()).filter(Boolean);
  }

  function renderDraft(text) {
    el.claims.innerHTML = splitSentences(text).map((s) => `<p class="claim pending">${withRefs(esc(s))}</p>`).join("");
  }

  function renderRefusal(text, reason) {
    const searched = [...el.trail.querySelectorAll('[data-step^="search"] .step-label')].map((n) => n.textContent.replace(/^Search /, ""));
    el.claims.innerHTML = `<div class="refused">${esc(text)}
      <span class="claim-note">${esc(reason || "")}${searched.length ? ` Searched: ${esc(searched.join("; "))}.` : ""}</span></div>`;
  }

  function renderVerification(v) {
    state.claims = v.claims;
    el.claims.innerHTML = v.claims.map((c, i) => {
      const refs = c.cites.map((n) => `[${n}]`).join("");
      let note = "";
      if (c.status === "number_mismatch") note = `<span class="claim-note">Not found in the cited source: ${esc(c.numbers_missing.join(", "))}</span>`;
      else if (c.status === "weak_support") note = '<span class="claim-note muted">The cited source doesn\'t clearly say this.</span>';
      else if (c.status === "uncited") note = '<span class="claim-note muted">No source cited for this sentence.</span>';
      return `<p class="claim" data-claim="${i}" tabindex="0" title="${STATUS_TEXT[c.status]}">
        ${TICKS[c.status].replace('class="tick', 'class="tick draw')}${esc(c.text)} ${withRefs(refs)}${note}</p>`;
    }).join("");
    el.claims.querySelectorAll(".tick.draw").forEach((t, i) => {
      t.querySelectorAll("path, circle").forEach((p) => { p.style.animationDelay = `${i * 140}ms`; });
    });
    el.legend.hidden = false;
    el.summary.innerHTML = `<strong>${v.verified} of ${v.total}</strong> sentences agree with the filings they cite.`;
  }

  function sourceTitle(s) {
    return `${esc(s.company)}, fiscal ${s.fiscal_year}<span class="source-meta">Item ${esc(s.section_code)}, ${esc(s.section)}${s.kind === "table" ? " (table)" : ""}</span>`;
  }

  function sourceBody(s, evidence) {
    if (s.kind === "table") {
      const lines = s.content.split("\n").filter(Boolean);
      const width = Math.max(...lines.map((r) => r.split(" | ").length));
      const rows = lines.map((row) => {
        const hit = evidence && row.trim() === evidence.trim();
        const cells = row.split(" | ");
        // Header rows (years) have fewer cells: pad on the left so they sit over the numbers.
        const padded = Array(Math.max(0, width - cells.length)).fill("").concat(cells);
        return `<tr class="${hit ? "hit" : ""}">${padded.map((c) => `<td>${esc(c)}</td>`).join("")}</tr>`;
      }).join("");
      const cap = s.caption ? `<p class="source-caption">${esc(s.caption)}</p>` : "";
      return `${cap}<div class="fig-wrap"><table class="fig">${rows}</table></div>`;
    }
    const flat = s.content.replace(/\n/g, " ");
    if (evidence) {
      const at = flat.indexOf(evidence);
      if (at >= 0) return esc(flat.slice(0, at)) + `<mark>${esc(evidence)}</mark>` + esc(flat.slice(at + evidence.length));
    }
    return esc(flat);
  }

  function renderSources(sources) {
    state.sources = sources;
    if (!sources.length) { el.sources.innerHTML = '<p class="coverage-note">No passages matched.</p>'; return; }
    el.sources.innerHTML = sources.map((s) => {
      const score = s.rerank != null ? `Relevance ${s.rerank.toFixed(2)}` : s.dense != null ? `Similarity ${s.dense.toFixed(2)}` : "";
      return `<article class="source" id="source-${s.n}" data-n="${s.n}">
        <div class="source-head"><span class="source-n">${s.n}</span><h3 class="source-title">${sourceTitle(s)}</h3></div>
        <div class="source-body">${sourceBody(s, null)}</div>
        <button type="button" class="source-toggle">Show full passage</button>
        ${score ? `<div class="source-scores">${score}</div>` : ""}
      </article>`;
    }).join("");
  }

  function focusSource(n, evidence) {
    const s = state.sources.find((x) => x.n === n);
    const card = document.getElementById(`source-${n}`);
    if (!s || !card) return;
    document.querySelectorAll(".source.is-active").forEach((c) => c.classList.remove("is-active"));
    card.classList.add("is-active");
    card.querySelector(".source-body").innerHTML = sourceBody(s, evidence);
    const mark = card.querySelector("mark, tr.hit");
    if (mark) card.classList.add("is-open"), card.querySelector(".source-toggle").textContent = "Show less";
    card.scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "nearest" });
  }

  function activateClaim(i, preferredSource) {
    const c = state.claims[i];
    document.querySelectorAll(".claim.is-active").forEach((x) => x.classList.remove("is-active"));
    document.querySelector(`.claim[data-claim="${i}"]`)?.classList.add("is-active");
    if (!c || !c.cites.length) return;
    const n = preferredSource || c.evidence_source || c.cites[0];
    focusSource(n, n === c.evidence_source ? c.evidence : null);
  }

  el.claims.addEventListener("click", (e) => {
    const ref = e.target.closest(".ref");
    const claim = e.target.closest(".claim");
    if (claim?.dataset.claim) activateClaim(Number(claim.dataset.claim), ref ? Number(ref.dataset.ref) : null);
    else if (ref) focusSource(Number(ref.dataset.ref), null);
  });
  el.claims.addEventListener("keydown", (e) => {
    const claim = e.target.closest(".claim");
    if (claim?.dataset.claim && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); activateClaim(Number(claim.dataset.claim)); }
  });
  el.sources.addEventListener("click", (e) => {
    const t = e.target.closest(".source-toggle");
    if (!t) return;
    const card = t.closest(".source");
    card.classList.toggle("is-open");
    t.textContent = card.classList.contains("is-open") ? "Show less" : "Show full passage";
  });

  // ------------------------------------------------------------------ asking
  function options() {
    return {
      use_bm25: $("#opt-bm25").checked, use_rerank: $("#opt-rerank").checked,
      use_agent: $("#opt-agent").checked, use_verify: $("#opt-verify").checked,
    };
  }

    function showError(message) {
    el.trail.querySelectorAll("li.running").forEach((li) => { li.className = "done"; li.querySelector(".step-detail").textContent = "Stopped"; });
    el.summary.textContent = "Stopped.";
    }

  function handle(ev) {
    switch (ev.type) {
      case "step": renderStep(ev); break;
      case "sources": renderSources(ev.sources); break;
      case "answer":
        if (ev.refused) renderRefusal(ev.text, ev.reason);
        else { renderDraft(ev.text); el.summary.textContent = "Checking each sentence…"; }
        break;
      case "verification": renderVerification(ev); break;
      case "done":
        if (ev.refused) el.summary.textContent = `No answer given, after ${seconds(ev.total_ms)}.`;
        else {
          const base = el.summary.innerHTML.replace("Checking each sentence…", "");
          el.summary.innerHTML = `${base} Answered in ${seconds(ev.total_ms)}.`.trim();
        }
        break;
      case "error": showError(ev.message); break;
    }
  }

  async function ask() {
    const question = el.q.value.trim();
    if (question.length < 3 || state.busy) return;
    state.busy = true;
    el.btn.disabled = true; el.btn.textContent = "Asking…";
    resetResult(question);
    el.result.scrollIntoView({ behavior: "smooth", block: "start" });
    try {
      const res = await fetch("/api/ask/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question, options: options() }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(Array.isArray(body.detail) ? "Questions must be between 3 and 500 characters." : body.detail || `Server returned ${res.status}.`);
      }
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = "";
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        let cut;
        while ((cut = buf.indexOf("\n\n")) >= 0) {
          const chunk = buf.slice(0, cut); buf = buf.slice(cut + 2);
          const line = chunk.split("\n").find((l) => l.startsWith("data:"));
          if (line) handle(JSON.parse(line.slice(5)));
        }
      }
    } catch (err) {
      showError(`${err.message} Check that the server is running.`);
    } finally {
      state.busy = false;
      el.btn.disabled = false; el.btn.textContent = "Ask";
    }
  }

  el.form.addEventListener("submit", (e) => { e.preventDefault(); ask(); });
  el.q.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); ask(); }
  });

  loadHealth();
  loadCoverage();
})();
