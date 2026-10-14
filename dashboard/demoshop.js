/* Demo shop for the dashboard: sends real requests to POST /v1/payments (mock mode only). */
(function () {
  "use strict";
  const $ = id => document.getElementById(id);
  const panel = $("shop"); if (!panel) return;
  const note = $("shopNote");
  let busy = false, counter = 0;
  const ref = () => "order-" + Date.now().toString(36) + "-" + (++counter);
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const say = (text, err) => { note.textContent = text; note.className = err ? "err" : ""; };

  async function post(body, key) {
    const headers = {"Content-Type": "application/json"};
    if (key) headers["Idempotency-Key"] = key;
    const response = await fetch("/v1/payments", {method: "POST", headers, body: JSON.stringify(body)});
    const data = await response.json().catch(() => ({}));
    const left = response.headers.get("X-RateLimit-Remaining");
    if (left !== null) window.rlRemaining = Number(left);
    if (response.status === 429) {
      const retry = Number(response.headers.get("Retry-After")) || 15;
      if (window.Dawg) window.Dawg.lock(retry, 15);
      const error = new Error(data.detail || "Too many requests"); error.status = 429; throw error;
    }
    if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Request failed");
    return data;
  }
  const send = (amount, customer, desc, order, key) =>
    post({amount, currency: "USD", customer_id: customer, description: desc, order_ref: order || null}, key);

  const scenarios = {
    normal: async () => { await send(18, "demo-customer-01", "Normal demo purchase", ref()); say("Sent one normal purchase."); },
    again: async () => { await send(18, "demo-customer-01", "Bought the same thing again", ref()); say("Same customer and amount, but a NEW order ref: a genuine repeat purchase, not a duplicate."); },
    bulk: async () => { await send(72, "demo-customer-01", "4 items in one order (4 x 18)", ref()); say("One payment of 72 for 4 items. Far below 5x the shop average, so no alarm once the Notebook has learned a few payments."); },
    four: async () => { for (let i = 1; i <= 4; i++) await send(18, "demo-customer-01", "Separate purchase " + i, ref()); say("Four separate purchases of 18, each with its own order ref. One customer stays under the velocity limit of 5 (if you already bought several times in the last 10 minutes, the limit can still stop the later ones)."); },
    dbl: async () => { const r = ref(); await send(18, "demo-customer-03", "Double-clicked Pay", r); await send(18, "demo-customer-03", "Double-clicked Pay", r); say("Same order ref sent twice within 2 minutes: the second is blocked, so nobody is charged twice."); },
    large: async () => { await send(950, "demo-customer-02", "Out-of-pattern demo purchase", ref()); say("A large amount from a new customer."); },
    rapid: async () => { for (let i = 1; i <= 6; i++) await send(10 + i, "rapid-buyer", "Rapid purchase " + i, ref()); say("One customer, 6 payments in a row. The 6th trips the per-customer velocity limit."); },
    burst: async () => {
      for (let i = 1; i <= 17; i++) { await send(1 + (i % 3), "bot-" + i + "-" + Date.now().toString(36), "Tiny test payment " + i, ref()); await window.load(); await sleep(900); }
      say("17 tiny payments from 17 different customers: a card-testing pattern. Past 15 in 10 minutes, new ones are flagged and held.");
    },
    hammer: async () => {
      let sent = 0;
      for (let i = 1; i <= 16; i++) { await send(1, "hammer-" + i + "-" + Date.now().toString(36), "Hammer test " + i, ref()); sent++; }
      say("Sent " + sent + " payments without being stopped.");
    },
    demo: async () => {
      await send(18.5, "demo-customer-01", "Normal demo purchase", null, "demo-normal-001");
      await send(950, "demo-customer-02", "Out-of-pattern demo purchase", null, "demo-large-001");
      await send(18.5, "demo-customer-01", "Repeated demo purchase", null, "demo-duplicate-001");
      say("Demo run: Wag (captured), Growl (held, waiting for you), Bark (blocked as a duplicate). If these keys were used before, the original payments are replayed. Press Reset demo for a fresh run.");
    }
  };

  async function run(fn) {
    if (busy) return;
    busy = true; panel.querySelectorAll("button").forEach(b => { b.disabled = true; });
    try { await fn(); }
    catch (error) { say(error.status === 429 ? "429 Too Many Requests. Dawg is resting, try again in a few seconds." : error.message, true); }
    finally { busy = false; panel.querySelectorAll("button").forEach(b => { b.disabled = false; }); await window.load(); }
  }

  $("shopScenarios").addEventListener("click", e => { const sc = e.target.dataset.sc; if (sc) run(scenarios[sc]); });
  $("shopForm").addEventListener("submit", e => {
    e.preventDefault();
    run(async () => {
      const amount = Math.round(parseFloat($("shopAmount").value) * 100) / 100;
      await post({amount, currency: ($("shopCurrency").value || "USD").toUpperCase().slice(0, 3), customer_id: $("shopCustomer").value.trim(),
        description: $("shopDesc").value.trim() || "Demo purchase", order_ref: $("shopOrder").value.trim() || null});
      say("Payment sent.");
    });
  });
  $("shopReset").addEventListener("click", () => run(async () => {
    const response = await fetch("/v1/demo/reset", {method: "POST"});
    if (!response.ok) throw new Error("Reset is only available in mock mode.");
    window.rlRemaining = 99; say("Demo reset: payments and the Notebook are cleared.");
  }));
  window.addEventListener("dawg:awake", () => { window.rlRemaining = 99; });
})();
