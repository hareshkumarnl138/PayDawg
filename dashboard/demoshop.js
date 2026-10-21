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
    for (let attempt = 0; ; attempt++) {
      const response = await fetch("/v1/payments", {method: "POST", headers, body: JSON.stringify(body)});
      const data = await response.json().catch(() => ({}));
      if (response.status === 429 && attempt < 2) {
        // Clicking through several scenarios quickly sends more than the flood guard allows from one browser
        // (RATE_LIMIT_ATTEMPTS in 10 seconds). Wait it out and carry on, so the scenario still shows what it promises.
        const wait = Math.max(1, Number(response.headers.get("Retry-After")) || 15);
        say("Flood guard: this browser sent too many payments in a few seconds, so PayDawg is pausing it for " + wait +
            " s (HTTP 429). The scenario carries on after that…");
        await sleep(wait * 1000 + 300);
        continue;
      }
      if (response.status === 429) {
        const error = new Error(data.detail || "Too many requests"); error.status = 429; throw error;
      }
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Request failed");
      return data;
    }
  }
  let sent = [];   // the payments the running scenario sent, in order
  const send = async (amount, customer, desc, order, key) => {
    const p = await post({amount, currency: "USD", customer_id: customer, description: desc, order_ref: order || null}, key);
    sent.push(p);
    return p;
  };
  // Say what the scenario shows, but only claim the usual result if Dawg really gave it. Scenarios share one shop,
  // so after a lot of clicking the shop can be in a surge, or remember earlier payments, and say something else.
  function explain(text, expected) {
    const got = sent.map(p => p.verdict);
    if (got.join() === expected.join()) { say(text); return; }
    const surge = sent.some(p => (p.flags || []).includes("merchant_surge"));
    const replayed = sent.some(p => Date.now() - new Date(p.created_at).getTime() > 60000);
    say("This time Dawg said " + got.join(", ") + " instead of the usual " + expected.join(", ") + ": " +
        (surge ? "the shop is in a surge right now (lots of payments in the last 10 minutes), so newcomers are held."
         : replayed ? "these payments were replayed from an earlier run (same idempotency keys)."
         : "he still remembers earlier clicks (duplicate and velocity windows).") + " Press Reset demo for a clean run.");
  }

  // Every scenario is self-contained: it sends whatever baseline it needs and uses a fresh customer
  // each run, so a button shows what its label promises no matter what was clicked before.
  let run_no = 0;
  const who = name => name + "-" + Date.now().toString(36).slice(-4) + "-" + run_no;
  const scenarios = {
    normal: async () => { await send(18, who("shopper"), "Normal demo purchase", ref()); explain("One ordinary purchase: Wag, charged straight away.", ["Wag"]); },
    again: async () => {
      const c = who("regular");
      await send(18, c, "First purchase", ref());
      await send(18, c, "Bought the same thing again", ref());
      explain("Same customer, same amount, but a NEW order ref: a genuine repeat purchase, so both go through.", ["Wag", "Wag"]);
    },
    bulk: async () => {
      const c = who("bulk-buyer");
      await send(18, c, "Single item", ref());
      await send(72, c, "4 items in one order (4 x 18)", ref());
      explain("One payment of 72 for 4 items. That is below 5x the shop average, so it is not treated as unusual.", ["Wag", "Wag"]);
    },
    four: async () => { const c = who("frequent"); for (let i = 1; i <= 4; i++) await send(18, c, "Separate purchase " + i, ref());
      explain("Four separate purchases of 18, each with its own order ref. One customer stays under the velocity limit of 5.", ["Wag", "Wag", "Wag", "Wag"]); },
    dbl: async () => { const c = who("clicker"), r = ref(); await send(18, c, "Double-clicked Pay", r); await send(18, c, "Double-clicked Pay", r);
      explain("Same order ref sent twice within 2 minutes: the second is blocked, so nobody is charged twice.", ["Wag", "Bark"]); },
    large: async () => {
      await send(18, who("regular-shopper"), "Ordinary purchase (sets the baseline)", ref());
      await send(950, who("stranger"), "Out-of-pattern demo purchase", ref());
      explain("A baseline purchase first, then 950 from a customer never seen before: far above this shop's normal, so it is held for review.", ["Wag", "Growl"]);
    },
    rapid: async () => { const c = who("rapid-buyer"); for (let i = 1; i <= 6; i++) await send(10 + i, c, "Rapid purchase " + i, ref());
      explain("One customer, 6 payments in a row. The 6th trips the per-customer velocity limit and is blocked.", ["Wag", "Wag", "Wag", "Wag", "Wag", "Bark"]); },
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
    demo: async () => {
      await send(18.5, "demo-customer-01", "Normal demo purchase", null, "demo-normal-001");
      await send(950, "demo-customer-02", "Out-of-pattern demo purchase", null, "demo-large-001");
      await send(18.5, "demo-customer-01", "Repeated demo purchase", null, "demo-duplicate-001");
      explain("Demo run: Wag (captured), Growl (held, waiting for you), Bark (blocked as a duplicate).", ["Wag", "Growl", "Bark"]);
    }
  };

  async function run(fn, name) {
    if (typeof fn !== "function") { say("No such scenario: " + name, true); return; }
    if (busy) return;
    run_no++; sent = [];
    busy = true; panel.querySelectorAll("button").forEach(b => { b.disabled = true; });
    try { await fn(); }
    catch (error) { say(error.status === 429 ? "429 Too Many Requests: the flood guard is still refusing this browser. Try again in a few seconds." : error.message, true); }
    finally { busy = false; panel.querySelectorAll("button").forEach(b => { b.disabled = false; }); await window.load(); }
  }

  $("shopScenarios").addEventListener("click", e => { const sc = e.target.dataset.sc; if (sc) run(scenarios[sc], sc); });
  $("shopForm").addEventListener("submit", e => {
    e.preventDefault();
    run(async () => {
      const amount = Math.round(parseFloat($("shopAmount").value) * 100) / 100;
      const p = await post({amount, currency: ($("shopCurrency").value || "USD").toUpperCase().slice(0, 3), customer_id: $("shopCustomer").value.trim(),
        description: $("shopDesc").value.trim() || "Demo purchase", order_ref: $("shopOrder").value.trim() || null});
      say("Payment sent. Dawg says " + p.verdict + " (" + ({captured: "charged", held: "held for you", blocked: "blocked"}[p.status] || p.status) + ")" +
          ((p.reasons || []).length ? ": " + p.reasons[0] : "."));
    });
  });
  $("shopReset").addEventListener("click", () => run(async () => {
    await window.api("/v1/demo/reset", {method: "POST"});
    say("Demo reset: payments and the Notebook are cleared.");
  }));
})();
