/* Leash & Larder: the cart lives in the page; prices and the payment are handled by the server (app/shop.py). */
(function () {
  "use strict";
  const $ = id => document.getElementById(id);
  const ICONS = new Set(["bone", "fish", "ball", "rope", "leash", "bowl", "coat", "bed"]);
  const EMAIL = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;
  const state = { items: [], bySku: new Map(), cart: new Map(), attempt: null, busy: false, done: false, simulated: true, max: 10 };

  const cents = price => Math.round(Number(price) * 100);
  const money = c => "$" + (c / 100).toFixed(2);
  const esc = v => String(v ?? "").replace(/[&<>"']/g, ch => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[ch]));
  const say = text => { $("announce").textContent = text; };
  const setMood = mood => { const svg = document.querySelector(".mini svg.dawg"); if (svg) svg.setAttribute("class", "dawg mood-" + mood); };

  function newAttempt() {
    try { if (window.crypto && crypto.randomUUID) return crypto.randomUUID(); } catch (e) { /* not a secure context */ }
    const bytes = new Uint8Array(16);
    if (window.crypto && crypto.getRandomValues) crypto.getRandomValues(bytes);
    else bytes.forEach((_, i) => { bytes[i] = Math.floor(Math.random() * 256); });
    return Array.from(bytes, b => b.toString(16).padStart(2, "0")).join("");
  }

  function totals() {
    let count = 0, sum = 0;
    state.cart.forEach((qty, sku) => { count += qty; sum += qty * cents(state.bySku.get(sku).price); });
    return { count, sum };
  }

  function renderGrid() {
    const grid = $("grid");
    const focused = grid.contains(document.activeElement) ? document.activeElement.dataset : null;
    grid.innerHTML = state.items.map(item => {
      const qty = state.cart.get(item.sku) || 0;
      const icon = ICONS.has(item.icon) ? item.icon : "bone";
      const name = esc(item.name), sku = esc(item.sku);
      const control = qty
        ? '<div class="stepper" role="group" aria-label="' + name + ' in your order">' +
            '<button type="button" data-act="dec" data-sku="' + sku + '" aria-label="Remove one ' + name + '">&minus;</button>' +
            '<span><b>' + qty + '</b><span class="in"> in your order</span></span>' +
            '<button type="button" data-act="inc" data-sku="' + sku + '" aria-label="Add one more ' + name + '"' + (qty >= state.max ? " disabled" : "") + '>+</button>' +
          '</div>'
        : '<button type="button" class="add" data-act="inc" data-sku="' + sku + '">Add to order</button>';
      return '<li class="card"><div class="well" aria-hidden="true"><svg viewBox="0 0 64 64"><use href="#i-' + icon + '"/></svg></div>' +
        '<h3 class="name">' + name + '</h3><p class="detail">' + esc(item.detail) + '</p>' +
        '<p class="price">' + money(cents(item.price)) + '</p>' + control + '</li>';
    }).join("");
    if (focused && focused.sku) {  // keep keyboard focus on the same product after re-drawing
      const same = grid.querySelector('[data-sku="' + focused.sku + '"][data-act="' + focused.act + '"]:not(:disabled)')
        || grid.querySelector('[data-sku="' + focused.sku + '"]:not(:disabled)');
      if (same) same.focus();
    }
  }

  function renderReceipt() {
    const { count, sum } = totals();
    if (!state.done) {
      $("lines").innerHTML = [...state.cart].map(([sku, qty]) => {
        const item = state.bySku.get(sku);
        return '<li><span class="qty">' + qty + ' &times;</span><span>' + esc(item.name) + '</span><span class="lt">' +
          (qty * cents(item.price) / 100).toFixed(2) + '</span></li>';
      }).join("");
      $("total").textContent = money(sum);
      $("empty").hidden = count > 0;
      $("totalRow").hidden = count === 0;
    }
    $("payForm").hidden = count === 0 || state.done;
    if (!state.busy) $("payBtn").textContent = state.simulated ? "Pay " + money(sum) : "Pay " + money(sum) + " with PayPal";
    $("chip").hidden = count === 0 || state.done;
    $("chipText").textContent = count + (count === 1 ? " item, " : " items, ") + money(sum);
  }

  function render() { renderGrid(); renderReceipt(); }

  function startNewOrder() {
    state.cart.clear(); state.attempt = null; state.done = false;
    $("stampZone").hidden = true; $("result").textContent = ""; $("again").hidden = true; $("orderNo").textContent = "";
    setMood("idle");
  }

  function change(sku, delta) {
    if (state.busy || !state.bySku.has(sku)) return;
    if (state.done) startNewOrder();          // shopping again after a finished order starts a new one
    const qty = Math.max(0, Math.min(state.max, (state.cart.get(sku) || 0) + delta));
    if (qty) state.cart.set(sku, qty); else state.cart.delete(sku);
    state.attempt = null;                     // a different cart is a different checkout attempt
    render();
    const { count, sum } = totals();
    say((delta > 0 ? "Added " : "Removed ") + state.bySku.get(sku).name + ". Your order: " + count + (count === 1 ? " item, " : " items, ") + money(sum) + ".");
  }

  const STAMPS = { paid: ["PAID", "wag"], held: ["ON HOLD", "growl"], declined: ["DECLINED", "bark"] };

  function showReceiptFromServer(d) {
    if (!Array.isArray(d.lines)) return;
    $("lines").innerHTML = d.lines.map(l => '<li><span class="qty">' + esc(l.qty) + ' &times;</span><span>' + esc(l.name) +
      '</span><span class="lt">' + esc(l.line_total) + '</span></li>').join("");
    $("total").textContent = "$" + d.total;
    $("empty").hidden = true; $("totalRow").hidden = false;
  }

  function show(d) {
    const sim = d.simulated ? " (simulated)" : "";
    const total = d.total ? "$" + d.total : "your payment";
    let message;
    switch (d.outcome) {
      case "redirect":
        if (typeof d.url === "string" && /^https:\/\//i.test(d.url)) {
          $("result").textContent = "Opening PayPal so you can approve " + total + "…";
          window.location.assign(d.url);
          return;
        }
        message = "PayPal did not return a page to approve the payment, so nothing was charged. Try again in a moment.";
        state.attempt = null;
        break;
      case "paid": message = "Paid" + sim + ". Order " + d.order + " is confirmed."; break;
      case "held": message = "Order " + d.order + " is waiting for the shop to confirm it. " + total +
        " is reserved on your payment method but has not been charged" + sim + "."; break;
      case "declined": message = "This payment could not be completed, so nothing was charged. Check your order, or contact the shop if it keeps happening."; break;
      case "busy": message = "Too many payment attempts from your connection. Try again in " + (d.retry_after || 15) + " seconds."; break;
      case "unavailable": case "offline": message = "The payment service did not respond, so nothing was charged. Try again in a moment."; break;
      case "invalid": message = d.detail || "Something in this order could not be processed. Refresh the page and try again."; state.attempt = null; break;
      default: message = "This payment could not be completed, so nothing was charged. Try again in a moment."; state.attempt = null;
    }
    if (STAMPS[d.outcome]) {
      const [word, mood] = STAMPS[d.outcome];
      state.done = true;
      showReceiptFromServer(d);
      $("orderNo").textContent = "Order " + d.order;
      const stamp = $("stamp");
      stamp.textContent = word;
      stamp.className = "stamp " + d.outcome;
      $("stampZone").hidden = false;
      stamp.style.animation = "none"; void stamp.offsetWidth; stamp.style.animation = "";  // replay the stamp
      $("again").hidden = false;
      setMood(mood);
    }
    $("result").textContent = message;
    renderReceipt();
  }

  async function pay(event) {
    event.preventDefault();
    if (state.busy || state.done || !state.cart.size) return;
    const input = $("email"), email = input.value.trim();
    if (!EMAIL.test(email)) {
      $("emailError").hidden = false; input.setAttribute("aria-invalid", "true"); input.focus();
      return;
    }
    $("emailError").hidden = true; input.removeAttribute("aria-invalid");
    if (!state.attempt) state.attempt = newAttempt();
    state.busy = true;
    const button = $("payBtn");
    button.disabled = true; button.textContent = "Checking your payment…"; $("result").textContent = "";
    let data;
    try {
      const response = await fetch("/shop/api/checkout", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, attempt: state.attempt, items: [...state.cart].map(([sku, qty]) => ({ sku, qty })) })
      });
      data = await response.json().catch(() => ({}));
      if (!response.ok) data = { outcome: "invalid", detail: typeof data.detail === "string" ? data.detail : null };
    } catch (e) {
      data = { outcome: "offline" };
    }
    state.busy = false; button.disabled = false;
    show(data);
  }

  async function boot() {
    try {
      const response = await fetch("/shop/api/catalog");
      if (!response.ok) throw new Error("catalog " + response.status);
      const catalog = await response.json();
      state.items = catalog.items || [];
      state.items.forEach(item => state.bySku.set(item.sku, item));
      state.simulated = !!catalog.simulated;
      state.max = catalog.max_qty || 10;
      $("testmode").textContent = state.simulated
        ? "Test mode: payments here are simulated, so no money moves."
        : "Test mode: this shop uses the PayPal sandbox, so no real money moves.";
      $("payNote").textContent = state.simulated
        ? "Simulated: there is no PayPal step and no money moves."
        : "You will approve the payment on PayPal's sandbox page.";
      render();
    } catch (e) {
      $("grid").innerHTML = '<li class="loading">The shelves did not load. Check that the PayDawg server is running, then refresh this page.</li>';
    }
  }

  $("grid").addEventListener("click", e => {
    const button = e.target.closest("button[data-act]");
    if (button) change(button.dataset.sku, button.dataset.act === "inc" ? 1 : -1);
  });
  $("payForm").addEventListener("submit", pay);
  $("email").addEventListener("input", () => { state.attempt = null; $("emailError").hidden = true; $("email").removeAttribute("aria-invalid"); });
  $("again").addEventListener("click", () => { startNewOrder(); render(); $("grid").querySelector("button") && $("grid").querySelector("button").focus(); });
  boot();
})();
