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

  // Every scenario is self-contained: it sends whatever baseline it needs and uses a fresh customer
  // each run, so a button shows what its label promises no matter what was clicked before.
  let run_no = 0;
  const who = name => name + "-" + Date.now().toString(36).slice(-4) + "-" + run_no;
  const scenarios = {
    normal: async () => { await send(18, who("shopper"), "Normal demo purchase", ref()); say("One ordinary purchase: Wag, charged straight away."); },
    again: async () => {
      const c = who("regular");
      await send(18, c, "First purchase", ref());
      await send(18, c, "Bought the same thing again", ref());
      say("Same customer, same amount, but a NEW order ref: a genuine repeat purchase, so both go through.");
    },
    bulk: async () => {
      const c = who("bulk-buyer");
      await send(18, c, "Single item", ref());
      await send(72, c, "4 items in one order (4 x 18)", ref());
      say("One payment of 72 for 4 items. That is below 5x the shop average, so it is not treated as unusual.");
    },
    four: async () => { const c = who("frequent"); for (let i = 1; i <= 4; i++) await send(18, c, "Separate purchase " + i, ref());
      say("Four separate purchases of 18, each with its own order ref. One customer stays under the velocity limit of 5."); },
    dbl: async () => { const c = who("clicker"), r = ref(); await send(18, c, "Double-clicked Pay", r); await send(18, c, "Double-clicked Pay", r);
      say("Same order ref sent twice within 2 minutes: the second is blocked, so nobody is charged twice."); },
    large: async () => {
      await send(18, who("regular-shopper"), "Ordinary purchase (sets the baseline)", ref());
      await send(950, who("stranger"), "Out-of-pattern demo purchase", ref());
      say("A baseline purchase first, then 950 from a customer never seen before: far above this shop's normal, so it is held for review.");
    },
    rapid: async () => { const c = who("rapid-buyer"); for (let i = 1; i <= 6; i++) await send(10 + i, c, "Rapid purchase " + i, ref());
      say("One customer, 6 payments in a row. The 6th trips the per-customer velocity limit and is blocked."); },
    burst: async () => {
      let flagged = 0;
      for (let i = 1; i <= 17; i++) {
        const p = await send(1 + (i % 3), who("bot" + i), "Tiny test payment " + i, ref());
        if ((p.flags || []).includes("merchant_surge")) flagged++;
        await window.load(); await sleep(1200);
      }
      let level = 15, floor = 15;
      try { const nb = await window.api("/v1/notebook"); level = nb.surge_above || level; floor = nb.surge_floor || floor; } catch (e) {}
      say(flagged
        ? "17 tiny payments from 17 different customers: a card-testing pattern. Past this shop's surge level (" + level + " in 10 minutes), " + flagged + " were flagged and held."
        : "17 tiny payments from 17 different customers. This shop has learned it normally handles more than that, so its surge level is " + level +
          " and nothing was flagged. Press Reset demo to try it on a brand-new shop, where the level starts at " + floor + ".");
    },
    hammer: async () => {
      // Deliberately exceed the per-client rate limit so the Dawg falls asleep behind the sign.
      let sent = 0;
      for (let i = 1; i <= 16; i++) { await send(1, who("hammer" + i), "Hammer test " + i, ref()); sent++; }
      say("Sent " + sent + " payments without being stopped.");
    },
    demo: async () => {
      await send(18.5, "demo-customer-01", "Normal demo purchase", null, "demo-normal-001");
      await send(950, "demo-customer-02", "Out-of-pattern demo purchase", null, "demo-large-001");
      await send(18.5, "demo-customer-01", "Repeated demo purchase", null, "demo-duplicate-001");
      say("Demo run: Wag (captured), Growl (held, waiting for you), Bark (blocked as a duplicate). If these keys were used before, the original payments are replayed. Press Reset demo for a fresh run.");
    }
  };

  async function run(fn, name) {
    if (typeof fn !== "function") { say("No such scenario: " + name, true); return; }
    if (busy) return;
    run_no++;
    busy = true; panel.querySelectorAll("button").forEach(b => { b.disabled = true; });
    try { await fn(); }
    catch (error) { say(error.status === 429 ? "429 Too Many Requests. Dawg is resting, try again in a few seconds." : error.message, true); }
    finally { busy = false; panel.querySelectorAll("button").forEach(b => { b.disabled = false; }); await window.load(); }
  }

  $("shopScenarios").addEventListener("click", e => { const sc = e.target.dataset.sc; if (sc) run(scenarios[sc], sc); });
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
    await window.api("/v1/demo/reset", {method: "POST"});
    window.rlRemaining = 99; say("Demo reset: payments and the Notebook are cleared.");
  }));
  window.addEventListener("dawg:awake", () => { window.rlRemaining = 99; });
})();
