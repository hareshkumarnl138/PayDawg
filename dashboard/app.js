const body = document.getElementById("paymentsBody");
const notice = document.getElementById("notice");
let allPayments = [];
let known = null, pulseId = null, lastSig = "";   // known: payment id -> the status Dawg last saw
let loadProblem = "";                              // the message a failed refresh put in the notice, cleared on recovery
// Plain words for the in-between states; the raw status stays in the row's tooltip and the details panel.
const STATUS_LABEL = {screened: "waiting for buyer", approved: "processing", created: "processing"};

let adminToken = "";
try { adminToken = sessionStorage.getItem("paydawgAdminToken") || ""; } catch (e) {}
let tokenDeclined = false;
async function api(path, options = {}, retried = false) {
  const headers = {"Content-Type": "application/json", ...(options.headers || {})};
  if (adminToken) headers["X-Admin-Token"] = adminToken;
  const response = await fetch(path, {...options, headers});
  if (response.status === 401 && !retried && !tokenDeclined) {
    // The server was started with ADMIN_TOKEN, so the merchant console needs it.
    const entered = window.prompt("This console is protected. Enter the admin token:");
    if (entered) {
      adminToken = entered.trim();
      try { sessionStorage.setItem("paydawgAdminToken", adminToken); } catch (e) {}
      return api(path, options, true);
    }
    tokenDeclined = true;
  } else if (response.status === 401 && retried) {
    adminToken = ""; tokenDeclined = true;  // wrong token: stop asking until the Refresh button is pressed
    try { sessionStorage.removeItem("paydawgAdminToken"); } catch (e) {}
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(data.detail || "Request failed");
    error.status = response.status;
    error.retryAfter = Number(response.headers.get("Retry-After")) || 0;
    throw error;
  }
  return data;
}
function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
}
function money(p) {
  try { return new Intl.NumberFormat(undefined, {style:"currency", currency:p.currency}).format(p.amount); }
  catch { return p.currency + " " + Number(p.amount).toFixed(2); }
}
async function load() {
  try {
    const health = await api("/health");
    document.getElementById("railBadge").textContent = health.simulated ? "SIMULATED · MOCK RAIL" : "PAYPAL SANDBOX";
    const note = document.getElementById("railNote");
    if (note) note.textContent = "Newest first · " + (health.simulated ? "mock mode is SIMULATED" : "real PayPal sandbox (test money)");
    const shop = document.getElementById("shop");
    if (shop) shop.hidden = !health.simulated;
    const list = await api("/v1/payments");
    allPayments = list.payments || [];
    try { renderNotebook(await api("/v1/notebook")); } catch (e) {}
    // The server counts every payment; the list itself stops at the newest 100.
    const totals = list.totals || {all: allPayments.length, Wag: allPayments.filter(p => p.verdict === "Wag").length,
      Growl: allPayments.filter(p => p.verdict === "Growl").length, Bark: allPayments.filter(p => p.verdict === "Bark").length};
    document.getElementById("totalCount").textContent = totals.all;
    document.getElementById("wagCount").textContent = totals.Wag;
    document.getElementById("growlCount").textContent = totals.Growl;
    document.getElementById("barkCount").textContent = totals.Bark;
    if (loadProblem && notice.textContent === loadProblem) notice.textContent = "";
    loadProblem = "";
    const seen = new Map(allPayments.map(p => [p.id, p.status]));
    if (known === null) known = seen;
    else {
      // Dawg speaks when a payment SETTLES (captured, held or blocked), not when it first appears. In PayPal mode a
      // payment shows up before the buyer has approved it, and a failed or abandoned one must never be announced as
      // charged. A held payment the merchant then captures is the merchant's own action, so he stays quiet for it.
      const settled = allPayments.filter(p => known.get(p.id) !== p.status && ["captured", "held", "blocked"].includes(p.status) &&
                                              !(p.verdict === "Growl" && p.status === "captured"));
      known = seen;
      if (settled.length) announce(settled);
    }
    // The glow belongs to a payment that is still waiting for the merchant; once it is captured or voided
    // (from here, from a script or by another tab) it stops.
    if (pulseId && !allPayments.some(p => p.id === pulseId && p.status === "held")) pulseId = null;
    // A half-finished capture gets its Retry button after 2 minutes, so let the clock re-draw those rows too.
    const sig = JSON.stringify(allPayments.map(p => [p.id, p.status, p.verdict, p.status === "approved" ? Math.floor(Date.now() / 30000) : 0])) + pulseId;
    if (sig !== lastSig) { lastSig = sig; render(); }
  } catch (error) {
    loadProblem = error instanceof TypeError
      ? "Can't reach the PayDawg server. Is its window (start.bat) still running?"
      : error.status === 401 ? "This console needs the admin token. Press Refresh to enter it." : error.message;
    notice.textContent = loadProblem;
  }
}
function usd(value) { return value == null ? "—" : "$" + Number(value).toFixed(2); }
function renderNotebook(nb) {
  const set = (id, text) => { const el = document.getElementById(id); if (el) el.textContent = text; };
  const learned = nb.learned_from || 0, simulated = nb.simulated_history || 0;
  set("nbNote", !learned
    ? "Nothing learned yet. A brand-new shop is judged by the default surge level and the review ceiling until payments are captured."
    : "Learned from " + learned + " captured payments" + (simulated ? " (" + simulated + " of them SIMULATED history, " + nb.live_learned + " live)." : "."));
  set("nbBasket", usd(nb.usual_basket));
  set("nbBiggest", learned ? "Biggest so far " + usd(nb.biggest) : "Nothing captured yet");
  set("nbUnusual", usd(nb.unusual_above));
  set("nbUnusualNote", learned ? "Anything bigger gets a Growl" : "Needs one captured payment");
  set("nbHours", (nb.usual_hours_text || "—").replace(/(\d\d:\d\d)-(\d\d:\d\d)/g, "$1–$2"));
  const hourNow = String(nb.now_hour).padStart(2, "0") + ":00";
  const inside = (nb.usual_hours || []).includes(nb.now_hour);
  set("nbHoursNote", nb.hours_judged === false
    ? "Dawg judges the hour once he has seen " + nb.hours_need + " captured payments (" + learned + " so far)."
    : ((nb.added_hours || []).length ? "Includes hours learned from sales. " : "The default hours, until sales show others. ") +
      "Now " + hourNow + (inside ? ", a usual hour." : ", outside them: new customers are flagged."));
  const recent = nb.recent_count || 0, level = Math.max(1, nb.surge_above || 1);
  set("nbPace", recent + (recent === 1 ? " payment" : " payments"));
  const ratio = Math.min(1, recent / level);
  const meter = document.getElementById("nbMeter"), box = document.getElementById("nbMeterBox");
  if (meter) meter.style.width = (ratio * 100).toFixed(1) + "%";
  if (box) {
    box.className = "meter" + (recent >= level ? " over" : ratio >= .75 ? " warn" : "");
    box.setAttribute("aria-valuemax", String(level)); box.setAttribute("aria-valuenow", String(Math.min(recent, level)));
  }
  const note = document.getElementById("nbPaceNote");
  if (note) {
    note.className = recent >= level ? "alert" : "";
    note.textContent = recent >= level
      ? "Surge level " + level + " reached: payments from untrusted customers are held."
      : "Surge alert at " + level + (nb.busiest_window >= 1
          ? " (twice this shop's busiest normal 10 minutes, " + Math.round(nb.busiest_window) + ")."
          : " (the default for a new shop).");
  }
}
function announce(fresh) {
  const pick = fresh.find(p => p.verdict === "Growl" && p.status === "held") || fresh[0];
  if (window.Dawg) window.Dawg.react(pick);
  if (pick.verdict === "Growl" && pick.status === "held") {
    // Scroll to a newly held payment ONCE. Scrolling on every refresh dragged the merchant back to it
    // whenever any other payment arrived.
    pulseId = pick.id; lastSig = ""; scrollToPulse();
  }
}
function scrollToPulse() {
  setTimeout(() => { const row = body.querySelector('tr[data-id="' + pulseId + '"]'); if (row) row.scrollIntoView({behavior: "smooth", block: "center"}); }, 200);
}

// Shown only when an AI model contributed to the verdict ("ollama" or "http_api"); the rules still decide blocks.
function aiTag(p) {
  return (p.decision_source === "ollama" || p.decision_source === "http_api")
    ? ' <span class="aitag" title="An AI model also reviewed this payment">AI</span>' : "";
}
function render() {
  const filter = document.getElementById("filter").value;
  const rows = allPayments.filter(p => filter === "all" || p.verdict === filter);
  if (!rows.length) {
    body.innerHTML = '<tr><td colspan="7" class="empty">' + (allPayments.length
      ? "No " + escapeHtml(filter) + " payments among the latest " + allPayments.length + "."
      : "No payments yet. Buy something in the pet shop, or send one from the API docs.") + '</td></tr>';
    return;
  }
  body.innerHTML = rows.map(p => {
    const reasons = (p.reasons || []).map(escapeHtml).join(" ");
    const held = p.status === "held" && p.verdict === "Growl";
    // A capture that never finished (the server stopped half-way) can be retried after 2 minutes, as the API allows.
    const stuck = p.status === "approved" && Date.now() - new Date(p.updated_at).getTime() > 120000;
    // The PayPal link is only useful while the buyer has not finished at PayPal yet.
    const approval = p.approval_url && p.status === "screened" ? '<br><a target="_blank" rel="noopener noreferrer" href="' + escapeHtml(p.approval_url) + '">Buyer approval ↗</a>' : "";
    return '<tr data-id="' + escapeHtml(p.id) + '">' +
      '<td><span class="payment-id">' + escapeHtml(p.id.slice(0,8)) + '</span><br><small>' + escapeHtml(new Date(p.created_at).toLocaleString()) + '</small></td>' +
      '<td>' + escapeHtml(p.customer_id) + '</td><td class="amount">' + escapeHtml(money(p)) + '</td>' +
      '<td><span class="verdict ' + escapeHtml(p.verdict) + '">' + escapeHtml(p.verdict) + '</span>' + aiTag(p) + '</td>' +
      '<td class="status" title="status: ' + escapeHtml(p.status) + '">' + escapeHtml(STATUS_LABEL[p.status] || p.status) + (p.rail === "mock" ? '<br><small>SIMULATED</small>' : '') + approval + '</td>' +
      '<td class="reasons">' + reasons + '</td><td><div class="actions">' +
      (held ? '<button class="approve' + (p.id === pulseId ? " glow" : "") + '" data-action="approve" data-id="' + escapeHtml(p.id) + '">Capture</button><button class="void' + (p.id === pulseId ? " glow" : "") + '" data-action="void" data-id="' + escapeHtml(p.id) + '">Void</button>'
        : stuck ? '<button class="approve" data-action="approve" data-id="' + escapeHtml(p.id) + '" title="The capture did not finish. Try it again.">Retry capture</button>' : '—') +
      '</div></td></tr>';
  }).join("");
}
body.addEventListener("click", async event => {
  const action = event.target.closest("button[data-action]");
  if (action) {
    event.stopPropagation();
    // One click, one request: a double-click used to send a second Capture and show a confusing 409.
    const buttons = [...action.closest(".actions").querySelectorAll("button")];
    if (buttons.some(b => b.disabled)) return;
    buttons.forEach(b => { b.disabled = true; });
    try {
      const p = await api("/v1/payments/" + action.dataset.id + "/" + action.dataset.action, {method:"POST"});
      notice.textContent = p.status === "captured" ? "Captured: the money is charged." : p.status === "voided" ? "Voided: the hold is released, nothing was charged." : "Payment status: " + p.status;
      pulseId = null;
      if (window.Dawg) window.Dawg.say(p.status === "captured" ? "wag" : "idle", p.status === "captured" ? "Good call! Captured, and I wrote it in my Notebook." : "Hold released. No money moved. Back on guard.");
      await load();
      await showDetails(action.dataset.id);
    } catch (error) {
      notice.textContent = error instanceof TypeError ? "Can't reach the PayDawg server, so nothing was changed." : error.message;
      buttons.forEach(b => { b.disabled = false; });
    }
    return;
  }
  const row = event.target.closest("tr[data-id]");
  if (row) await showDetails(row.dataset.id);
});
async function showDetails(id) {
  try { document.getElementById("details").textContent = JSON.stringify(await api("/v1/payments/" + id), null, 2); }
  catch (error) { document.getElementById("details").textContent = error.message; }
}
document.getElementById("refreshBtn").addEventListener("click", () => { lastSig = ""; tokenDeclined = false; notice.textContent = ""; load(); });
document.getElementById("filter").addEventListener("change", render);
load();
setInterval(() => { if (!document.hidden && !tokenDeclined) load(); }, 3000);
