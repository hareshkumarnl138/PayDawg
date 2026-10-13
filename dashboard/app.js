const body = document.getElementById("paymentsBody");
const notice = document.getElementById("notice");
let allPayments = [];

async function api(path, options = {}) {
  const response = await fetch(path, {headers: {"Content-Type": "application/json", ...(options.headers || {})}, ...options});
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || "Request failed");
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
    allPayments = (await api("/v1/payments")).payments || [];
    document.getElementById("totalCount").textContent = allPayments.length;
    document.getElementById("wagCount").textContent = allPayments.filter(p => p.verdict === "Wag").length;
    document.getElementById("growlCount").textContent = allPayments.filter(p => p.verdict === "Growl").length;
    document.getElementById("barkCount").textContent = allPayments.filter(p => p.verdict === "Bark").length;
    render();
  } catch (error) { notice.textContent = error.message; }
}
function render() {
  const filter = document.getElementById("filter").value;
  const rows = allPayments.filter(p => filter === "all" || p.verdict === filter);
  if (!rows.length) {
    body.innerHTML = '<tr><td colspan="7" class="empty">No payments yet. Submit one from API docs or run the demo script.</td></tr>';
    return;
  }
  body.innerHTML = rows.map(p => {
    const reasons = (p.reasons || []).map(escapeHtml).join(" ");
    const held = ["held","approved"].includes(p.status) && p.verdict === "Growl";
    const approval = p.approval_url ? '<br><a target="_blank" rel="noopener noreferrer" href="' + escapeHtml(p.approval_url) + '">Buyer approval ↗</a>' : "";
    return '<tr data-id="' + escapeHtml(p.id) + '">' +
      '<td><span class="payment-id">' + escapeHtml(p.id.slice(0,8)) + '</span><br><small>' + escapeHtml(new Date(p.created_at).toLocaleString()) + '</small></td>' +
      '<td>' + escapeHtml(p.customer_id) + '</td><td class="amount">' + escapeHtml(money(p)) + '</td>' +
      '<td><span class="verdict ' + escapeHtml(p.verdict) + '">' + escapeHtml(p.verdict) + '</span></td>' +
      '<td class="status">' + escapeHtml(p.status) + (p.rail === "mock" ? '<br><small>SIMULATED</small>' : '') + approval + '</td>' +
      '<td class="reasons">' + reasons + '</td><td><div class="actions">' +
      (held ? '<button class="approve" data-action="approve" data-id="' + escapeHtml(p.id) + '">Capture</button><button class="void" data-action="void" data-id="' + escapeHtml(p.id) + '">Void</button>' : '—') +
      '</div></td></tr>';
  }).join("");
}
body.addEventListener("click", async event => {
  const action = event.target.closest("button[data-action]");
  if (action) {
    event.stopPropagation();
    try {
      const p = await api("/v1/payments/" + action.dataset.id + "/" + action.dataset.action, {method:"POST"});
      notice.textContent = "Updated payment status: " + p.status;
      await load();
      await showDetails(action.dataset.id);
    } catch (error) { notice.textContent = error.message; }
    return;
  }
  const row = event.target.closest("tr[data-id]");
  if (row) await showDetails(row.dataset.id);
});
async function showDetails(id) {
  try { document.getElementById("details").textContent = JSON.stringify(await api("/v1/payments/" + id), null, 2); }
  catch (error) { document.getElementById("details").textContent = error.message; }
}
document.getElementById("refreshBtn").addEventListener("click", load);
document.getElementById("filter").addEventListener("change", render);
load();
