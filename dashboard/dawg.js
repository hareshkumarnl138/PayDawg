/* PayDawg mascot: a German Shepherd who changes face per verdict, trots in to speak, can be
   dragged, gets tired from too many attempts and falls asleep behind a "Beware of DAWGS" sign
   (rate-limit lockdown). Exposes window.Dawg. Dawg does not talk: he barks, growls and yips. If real recordings are in dashboard/sounds/ he plays those;
   otherwise he uses sounds synthesized in the browser (Web Audio). */
(function () {
  "use strict";
  const $ = id => document.getElementById(id);
  function dawgSVG(size, mood){
    return '<svg class="dawg mood-' + mood + '" viewBox="0 -14 200 224" width="' + size + '" height="' + Math.round(size*1.12) + '" role="img" aria-label="Dawg, a German Shepherd pup"><g class="dg">' +
    '<g class="tail"><path d="M136 194 Q190 176 184 120" stroke="#a8692f" stroke-width="24" fill="none" stroke-linecap="round"/><path d="M136 194 Q188 176 182 122" stroke="#d9a066" stroke-width="16" fill="none" stroke-linecap="round"/><path d="M182 132 Q183 120 182 108" stroke="#2b2118" stroke-width="22" fill="none" stroke-linecap="round"/><path d="M170 150 l-6 -6 M176 138 l-7 -4 M181 160 l-6 -5" stroke="#f0d3a8" stroke-width="2.4" stroke-linecap="round"/></g>' +
    '<path d="M50 166 Q100 146 150 166 L166 212 L34 212Z" fill="#d9a066"/><path d="M52 172 Q74 160 90 168 L84 212 L40 212Z M148 172 Q126 160 110 168 L116 212 L160 212Z" fill="#3a2a1c"/><path d="M80 160 Q100 152 120 160 L128 212 L72 212Z" fill="#f0d3a8"/><path d="M84 176 l6 8 l5 -9 l5 9 l5 -9 l5 9 l6 -8" stroke="#d9b98a" stroke-width="2.4" fill="none" stroke-linecap="round" stroke-linejoin="round"/>' +
    '<path d="M72 212 L72 190 Q72 182 80 182 Q88 182 88 190 L88 212Z M112 212 L112 190 Q112 182 120 182 Q128 182 128 190 L128 212Z" fill="#e6b377"/><ellipse cx="80" cy="206" rx="15" ry="8" fill="#f0d3a8"/><ellipse cx="120" cy="206" rx="15" ry="8" fill="#f0d3a8"/><path d="M74 204 v6 M80 203 v7 M86 204 v6 M114 204 v6 M120 203 v7 M126 204 v6" stroke="#b98a5a" stroke-width="1.8" stroke-linecap="round"/>' +
    '<path d="M44 150 L48 136 L56 146 L60 132 L70 144 L76 130 L86 144 L100 134 L114 144 L124 130 L130 144 L140 132 L144 146 L152 136 L156 150 L146 166 Q100 178 54 166Z" fill="#c88a4e"/>' +
    '<g class="ear l"><path d="M56 84 Q36 34 46 -8 Q82 12 100 52Z" fill="#2b2118"/><path d="M60 72 Q50 38 56 6 Q78 24 90 54Z" fill="#e8a39a"/><path d="M60 72 l5 -9 l4 7 l6 -10 l4 8 l7 -9 l3 12Z" fill="#f0d3a8"/></g>' +
    '<g class="ear r"><path d="M144 84 Q164 34 154 -8 Q118 12 100 52Z" fill="#2b2118"/><path d="M140 72 Q150 38 144 6 Q122 24 110 54Z" fill="#e8a39a"/><path d="M140 72 l-5 -9 l-4 7 l-6 -10 l-4 8 l-7 -9 l-3 12Z" fill="#f0d3a8"/></g>' +
    '<path d="M44 102 Q40 90 46 80 Q46 46 100 44 Q154 46 154 80 Q160 90 156 102 L150 108 L157 117 L146 121 Q130 148 100 150 Q70 148 54 121 L43 117 L50 108Z" fill="#d9a066"/>' +
    '<ellipse cx="74" cy="62" rx="22" ry="9" fill="#fff" opacity=".1" transform="rotate(-20 74 62)"/><path d="M52 110 Q60 134 80 142 Q60 140 50 118Z M148 110 Q140 134 120 142 Q140 140 150 118Z" fill="#a8692f" opacity=".35"/>' +
    '<path d="M100 46 Q81 58 87 90 L91 110 L109 110 L113 90 Q119 58 100 46Z" fill="#3a2a1c"/>' +
    '<path d="M66 108 Q100 90 134 108 Q144 140 126 160 Q100 170 74 160 Q56 140 66 108Z" fill="#f0d3a8"/>' +
    '<path d="M70 106 Q100 92 130 106 Q124 124 100 126 Q76 124 70 106Z" fill="#3a2a1c" opacity=".85"/>' +
    '<ellipse cx="100" cy="112" rx="12" ry="8" fill="#1a1410"/><ellipse cx="96" cy="109" rx="4" ry="1.9" fill="#fff" opacity=".6"/><path d="M95 116 Q100 119 105 116" stroke="#000" stroke-width="1.2" fill="none" opacity=".6"/>' +
    '<g fill="#b98a5a"><circle cx="82" cy="130" r="1.5"/><circle cx="88" cy="135" r="1.5"/><circle cx="84" cy="138" r="1.5"/><circle cx="118" cy="130" r="1.5"/><circle cx="112" cy="135" r="1.5"/><circle cx="116" cy="138" r="1.5"/></g>' +
    '<path d="M62 150 Q100 170 138 150" stroke="#a8182f" stroke-width="12" fill="none" stroke-linecap="round" transform="translate(0,8)"/><path d="M62 158 Q100 178 138 158" stroke="#e0445a" stroke-width="8" fill="none" stroke-linecap="round"/>' +
    '<g transform="translate(100,182)"><circle cx="0" cy="-3" r="2.6" fill="#b8860b"/><polygon points="0,-10 11,-5 11,6 0,12 -11,6 -11,-5" fill="#ffd166" stroke="#b8860b" stroke-width="1.6"/><text x="0" y="4" font-size="10" font-weight="800" text-anchor="middle" fill="#6b4a00" font-family="Inter,sans-serif">PD</text></g>' +
    '<circle class="blush" cx="62" cy="110" r="7" fill="#ff8fa3" opacity=".55"/><circle class="blush" cx="138" cy="110" r="7" fill="#ff8fa3" opacity=".55"/>' +
    /* eyes */
    '<g class="e e-idle"><g class="blink"><ellipse cx="78" cy="86" rx="8.5" ry="10.5" fill="#fff"/><ellipse cx="122" cy="86" rx="8.5" ry="10.5" fill="#fff"/><circle cx="79" cy="88" r="6.6" fill="#8a5424"/><circle cx="121" cy="88" r="6.6" fill="#8a5424"/><circle cx="79" cy="88" r="3.8" fill="#1a1410"/><circle cx="121" cy="88" r="3.8" fill="#1a1410"/><circle cx="81" cy="85" r="2" fill="#fff"/><circle cx="123" cy="85" r="2" fill="#fff"/></g><path d="M66 70 Q78 63 90 70M110 70 Q122 63 134 70" stroke="#1a1410" stroke-width="3.5" fill="none" stroke-linecap="round"/></g>' +
    '<g class="e e-wag"><path d="M67 90 Q78 74 89 90M111 90 Q122 74 133 90" stroke="#1a1410" stroke-width="5" fill="none" stroke-linecap="round"/><path d="M65 68 Q78 58 91 67M109 67 Q122 58 135 68" stroke="#1a1410" stroke-width="3.5" fill="none" stroke-linecap="round"/></g>' +
    '<g class="e e-growl"><ellipse cx="78" cy="89" rx="8.5" ry="6" fill="#fff"/><ellipse cx="122" cy="89" rx="8.5" ry="6" fill="#fff"/><circle cx="80" cy="90" r="4.6" fill="#1a1410"/><circle cx="120" cy="90" r="4.6" fill="#1a1410"/><path d="M62 70 L93 84M138 70 L107 84" stroke="#1a1410" stroke-width="6.5" stroke-linecap="round"/></g>' +
    '<g class="e e-bark"><ellipse cx="78" cy="86" rx="9" ry="11" fill="#fff"/><ellipse cx="122" cy="86" rx="9" ry="11" fill="#fff"/><circle cx="79" cy="87" r="6.5" fill="#1a1410"/><circle cx="121" cy="87" r="6.5" fill="#1a1410"/><circle cx="81.5" cy="84" r="2.3" fill="#fff"/><circle cx="123.5" cy="84" r="2.3" fill="#fff"/><path d="M64 68 L93 76M136 68 L107 76" stroke="#1a1410" stroke-width="4.5" stroke-linecap="round"/></g>' +
    /* mouths */
    '<g class="m m-idle"><path d="M100 120 V126" stroke="#1a1410" stroke-width="3" stroke-linecap="round"/><path d="M88 125 Q100 144 112 125Z" fill="#7a2433"/><ellipse cx="100" cy="134" rx="6" ry="3.6" fill="#ff8fa3"/></g>' +
    '<g class="m m-wag"><path d="M100 120 V126" stroke="#1a1410" stroke-width="3" stroke-linecap="round"/><path d="M82 124 Q100 156 118 124Z" fill="#7a2433"/><ellipse cx="100" cy="140" rx="9" ry="6" fill="#ff8fa3"/></g>' +
    '<g class="m m-growl"><path d="M100 120 V124" stroke="#1a1410" stroke-width="3" stroke-linecap="round"/><path d="M80 130 Q90 122 100 126 Q110 122 120 130 Q100 142 80 130Z" fill="#3a1620"/><polygon points="85,128 90,128 87.5,136" fill="#fff"/><polygon points="110,128 115,128 112.5,136" fill="#fff"/><polygon points="94,126 98,127 96,132" fill="#fff"/><polygon points="102,127 106,126 104,132" fill="#fff"/></g>' +
    '<g class="m m-bark"><path d="M100 120 V124" stroke="#1a1410" stroke-width="3" stroke-linecap="round"/><path d="M76 124 Q100 168 124 124Z" fill="#5a1224"/><polygon points="82,125 89,125 85.5,136" fill="#fff"/><polygon points="111,125 118,125 114.5,136" fill="#fff"/><ellipse cx="100" cy="148" rx="13" ry="8" fill="#ff7a93"/></g>' +
    '<g class="e e-tired"><ellipse cx="78" cy="89" rx="8.5" ry="5.5" fill="#fff"/><ellipse cx="122" cy="89" rx="8.5" ry="5.5" fill="#fff"/><circle cx="79" cy="91" r="3.8" fill="#1a1410"/><circle cx="121" cy="91" r="3.8" fill="#1a1410"/><path d="M68 85 Q78 80 88 86M112 86 Q122 80 132 85" stroke="#1a1410" stroke-width="3.4" fill="none" stroke-linecap="round"/><path d="M64 78 L91 70M136 78 L109 70" stroke="#1a1410" stroke-width="3.4" stroke-linecap="round"/></g>' +
    '<g class="e e-sleep"><path d="M67 88 Q78 98 89 88M111 88 Q122 98 133 88" stroke="#1a1410" stroke-width="4.5" fill="none" stroke-linecap="round"/><path d="M66 74 Q78 69 90 74M110 74 Q122 69 134 74" stroke="#1a1410" stroke-width="3" fill="none" stroke-linecap="round"/></g>' +
    '<g class="m m-tired"><path d="M100 120 V124" stroke="#1a1410" stroke-width="3" stroke-linecap="round"/><path d="M84 126 Q100 148 116 126Z" fill="#7a2433"/><path d="M92 136 Q100 166 108 136Z" fill="#ff8fa3"/></g>' +
    '<g class="m m-sleep"><path d="M100 120 V125" stroke="#1a1410" stroke-width="3" stroke-linecap="round"/><path d="M90 128 Q100 137 110 128" stroke="#1a1410" stroke-width="3" fill="none" stroke-linecap="round"/><ellipse cx="109" cy="138" rx="3" ry="4.2" fill="#8bd5ff" opacity=".85"/></g>' +
    '<g class="sweat"><path d="M153 62 q-7 11 0 15 q7 -4 0 -15z" fill="#8bd5ff" stroke="#fff" stroke-width="1"/></g>' +
    '<g class="zzz" font-family="Inter,sans-serif" font-weight="900" fill="#8bd5ff"><text x="150" y="28" font-size="22">z</text><text x="166" y="8" font-size="28">Z</text><text x="184" y="-6" font-size="20">z</text></g>' +
    '<g class="burst"><path d="M20 20 L40 34M14 44 L36 50M26 -2 L44 18" stroke="#ff9db0" stroke-width="4" stroke-linecap="round"/><path d="M180 20 L160 34M186 44 L164 50M174 -2 L156 18" stroke="#ff9db0" stroke-width="4" stroke-linecap="round"/></g>' +
    '</g></svg>';
  }

  const QUOTES = [
    "Per policy 429: even good dogs need a nap.",
    "This is a controlled cooldown, not a personal vendetta.",
    "Fraud can't tire me out. Your thumbs just did.",
    "My SLA includes sleep. Section 4, paragraph bark.",
    "Fun fact: a calm gateway is a secure gateway. Zzz."
  ];
  const WHY = { exact_duplicate: "that's an exact copy of a payment I just saw", velocity_breach: "way too many payments, way too fast", unusual_amount: "that amount is far above this shop's normal", new_customer: "I've never sniffed this customer before", odd_hour: "it's an odd hour for this shop", merchant_surge: "this whole shop is getting hammered with payments" };
  const TIPS = ["I sniff every payment before PayPal sees it.", "Wag means charge, Growl means hold for you, Bark means block.", "I only learn from payments that were really captured.", "A repeat purchase needs a new order reference, or I'll think it's a double-click."];
  const money = p => { try { return new Intl.NumberFormat(undefined, { style: "currency", currency: p.currency }).format(p.amount); } catch (e) { return p.currency + " " + Number(p.amount).toFixed(2); } };
  const why = p => { const w = (p.flags || []).map(f => WHY[f]).filter(Boolean); return w.length ? w.slice(0, 2).join(", and ") : "something about it smells off"; };

  let box, fig, bub, bt, typeT = 0, moodT = 0, speakT = 0, home = { x: 0, y: 0 }, lastSlide = 0;
  let lockUntil = 0, lockStart = 0, lockTotal = 15, lockTimer = 0, lockIdx = -1;

  /* ---- dog sounds: synthesized with Web Audio, so there are no sound files and nothing to license ---- */
  let ac = null, hum = null, soundOn = true;
  try { soundOn = localStorage.getItem("dawg-sound") !== "off"; } catch (e) {}
  function audio(){
    if (!soundOn) return null;
    try {
      const C = window.AudioContext || window.webkitAudioContext; if (!C) return null;
      if (!ac) ac = new C();
      if (ac.state === "suspended") ac.resume().catch(() => {});   // browsers wait for a click or key before allowing sound
      return ac.state === "closed" ? null : ac;
    } catch (e) { return null; }
  }
  function noise(a, t, dur, gain, freq, q){
    const len = Math.max(1, Math.floor(a.sampleRate * dur)), buf = a.createBuffer(1, len, a.sampleRate), d = buf.getChannelData(0);
    for (let i = 0; i < len; i++) d[i] = Math.random() * 2 - 1;
    const src = a.createBufferSource(), f = a.createBiquadFilter(), g = a.createGain();
    src.buffer = buf; f.type = "bandpass"; f.frequency.value = freq; f.Q.value = q;
    g.gain.setValueAtTime(0.0001, t); g.gain.exponentialRampToValueAtTime(gain, t + 0.01); g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
    src.connect(f); f.connect(g); g.connect(a.destination); src.start(t); src.stop(t + dur + 0.02);
  }
  function tone(a, t, o){
    const osc = a.createOscillator(), f = a.createBiquadFilter(), g = a.createGain();
    osc.type = o.type || "sawtooth"; osc.frequency.setValueAtTime(o.f0, t); osc.frequency.exponentialRampToValueAtTime(o.f1, t + o.dur);
    f.type = o.filter || "lowpass"; f.frequency.value = o.cut || 2400; f.Q.value = o.q || 0.8;
    g.gain.setValueAtTime(0.0001, t); g.gain.exponentialRampToValueAtTime(o.gain, t + (o.attack || 0.01)); g.gain.exponentialRampToValueAtTime(0.0001, t + o.dur);
    osc.connect(f); f.connect(g); g.connect(a.destination); osc.start(t); osc.stop(t + o.dur + 0.03);
    return osc;
  }
  const SOUNDS = {
    // happy: three quick rising yips and a little pant
    wag(a, t){
      [0, 0.15, 0.3].forEach((d, i) => { tone(a, t + d, { type: "triangle", f0: 780 + i * 90, f1: 1250 + i * 110, dur: 0.1, gain: 0.22, cut: 3200 }); noise(a, t + d, 0.07, 0.05, 2600, 1.5); });
      [0.5, 0.68].forEach(d => noise(a, t + d, 0.14, 0.07, 1800, 0.7));
    },
    // growl: a low rough rumble that swells and fades
    growl(a, t){
      const dur = 1.3, osc = tone(a, t, { f0: 88, f1: 70, dur, gain: 0.34, attack: 0.18, cut: 420, q: 2 });
      const lfo = a.createOscillator(), depth = a.createGain();
      lfo.frequency.value = 26; depth.gain.value = 9; lfo.connect(depth); depth.connect(osc.frequency); lfo.start(t); lfo.stop(t + dur + 0.05);
      noise(a, t, dur, 0.1, 260, 0.9);
    },
    // bark: two or three sharp barks, each a fast falling note with a burst of breath
    bark(a, t){
      [0, 0.23, 0.46].forEach((d, i) => {
        tone(a, t + d, { f0: 620 - i * 25, f1: 270, dur: 0.17, gain: 0.4, attack: 0.006, cut: 1700, q: 1.4 });
        noise(a, t + d, 0.09, 0.2, 1500, 0.9);
      });
    },
    // tired: a soft whine that sags, then slow pants
    tired(a, t){
      tone(a, t, { type: "sine", f0: 900, f1: 520, dur: 0.7, gain: 0.16, attack: 0.08, cut: 2000 });
      [0.85, 1.25, 1.65].forEach(d => noise(a, t + d, 0.3, 0.07, 1500, 0.6));
    },
    // asleep: one slow, soft snore
    sleep(a, t){ noise(a, t, 1.1, 0.09, 220, 0.7); noise(a, t + 0.1, 0.8, 0.05, 110, 0.5); }
  };
  /* Real recordings win when they exist: put bark / growl / happy / whine / snore (.ogg .wav .mp3 or .m4a) in
     dashboard/sounds/. Anything missing keeps its synthesized sound, so the folder can start empty. */
  const MAX_SECONDS = { bark: 2.4, growl: 2.2, wag: 1.8, tired: 2.2, sleep: 2.5 };
  const recordings = {};            // mood -> AudioBuffer (a mood with no recording is simply absent)
  let preloading = false;
  async function preload(){
    if (preloading) return; preloading = true;
    const a = audio(); if (!a || !window.fetch) return;
    let found = {};
    try { const r = await fetch("/dog-sounds"); if (r.ok) found = await r.json(); } catch (e) { return; }
    Object.keys(found).forEach(async mood => {
      try {
        const r = await fetch("/dashboard/sounds/" + encodeURIComponent(found[mood]));
        if (r.ok) recordings[mood] = await a.decodeAudioData(await r.arrayBuffer());
      } catch (e) { /* not usable audio: keep the built-in sound */ }
    });
  }
  function playRecording(a, mood, t){
    const buf = recordings[mood]; if (!buf) return false;
    const src = a.createBufferSource(), g = a.createGain(), len = Math.min(buf.duration, MAX_SECONDS[mood] || 2.4);
    src.buffer = buf; g.gain.setValueAtTime(0.9, t); g.gain.setValueAtTime(0.9, t + Math.max(0, len - 0.25)); g.gain.linearRampToValueAtTime(0.0001, t + len);
    src.connect(g); g.connect(a.destination); src.start(t, 0, len);
    return true;
  }
  function speak(text, mood){      // kept under its old name: a mood now makes a dog noise instead of words
    const a = audio(); if (!a) return;
    preload();
    const t = a.currentTime + 0.03;
    try { if (!playRecording(a, mood, t)) (SOUNDS[mood] || SOUNDS.wag)(a, t); } catch (e) {}
  }
  function setSound(on, quiet){
    soundOn = on;
    try { localStorage.setItem("dawg-sound", on ? "on" : "off"); } catch (e) {}
    const b = $("dawgSound"); if (b) { b.textContent = on ? "\u{1F50A}" : "\u{1F507}"; b.setAttribute("aria-pressed", on ? "false" : "true"); b.title = on ? "Mute Dawg" : "Unmute Dawg"; }
    if (on && !quiet) speak("", "wag");
  }
  function setMood(m){
    document.querySelectorAll("#dawgFig .dawg").forEach(el => { el.setAttribute("class", "dawg mood-" + m + (el.classList.contains("talking") ? " talking" : "")); });
    bub.className = m === "idle" ? "" : m;
  }
  function maybeSlide(){
    const t = Date.now(); if (t - lastSlide < 7000 || box.classList.contains("dragging")) return; lastSlide = t;
    box.style.transition = "none"; box.style.setProperty("--dx", (home.x + 380) + "px"); box.style.setProperty("--dy", home.y + "px"); void box.offsetWidth;
    box.style.transition = ""; fig.classList.add("walk"); box.style.setProperty("--dx", home.x + "px");
    setTimeout(() => fig.classList.remove("walk"), 900);
  }
  function say(mood, text){
    if (Date.now() < lockUntil) return;
    maybeSlide();
    clearTimeout(typeT); clearTimeout(moodT);
    const svg = fig.querySelector(".dawg"); setMood(mood); svg.classList.add("talking"); bt.textContent = "";
    speak(text, mood);
    let i = 0;
    (function step(){ i++; bt.textContent = text.slice(0, i); if (i < text.length) typeT = setTimeout(step, 24); else { svg.classList.remove("talking"); moodT = setTimeout(() => setMood("idle"), 4200); } })();
  }
  function react(p, opts){
    opts = opts || {};
    const a = money(p), talk = (m, t) => opts.tired ? say("tired", t + " ...Pant, pant. I'm getting tired, please slow down!") : say(m, t);
    if (p.verdict === "Wag") talk("wag", ["Tail wagging! " + a + " smells clean. Charged!", "Sniffed it, all good. " + a + " captured. Good human!"][Math.floor(Math.random() * 2)]);
    else if (p.verdict === "Growl") talk("growl", "Grrr... " + why(p) + ". I'm holding " + a + ". Your call: Capture or Void?");
    else talk("bark", "BARK! BARK! " + why(p).replace(/^./, c => c.toUpperCase()) + ". Blocked. No money moved!");
  }

  /* ---- rate-limit lockdown ---- */
  function lock(retryAfter, total){
    const now = Date.now();
    if (now < lockUntil) return;
    lockTotal = total || 15; retryAfter = Math.max(1, retryAfter || lockTotal);
    lockStart = now - Math.max(0, lockTotal - retryAfter) * 1000; lockUntil = now + retryAfter * 1000; lockIdx = -1;
    clearTimeout(typeT); clearTimeout(moodT); clearTimeout(speakT);
    $("lockDog").innerHTML = dawgSVG(190, "sleep");
    $("lock").hidden = false; box.style.opacity = "0"; box.style.pointerEvents = "none";
    lockTick(); lockTimer = setInterval(lockTick, 250);
  }
  function lockTick(){
    const t = Date.now();
    if (t >= lockUntil) { endLock(); return; }
    $("lockSec").textContent = Math.ceil((lockUntil - t) / 1000);
    $("lockFill").style.width = Math.max(0, (lockUntil - t) / (lockTotal * 1000) * 100) + "%";
    const i = Math.min(QUOTES.length - 1, Math.floor((t - lockStart) / 3000));
    if (i !== lockIdx) { lockIdx = i; const q = $("lockQuote"); q.textContent = QUOTES[i]; q.classList.remove("pop"); void q.offsetWidth; q.classList.add("pop"); speak(QUOTES[i], "sleep"); }
  }
  function endLock(){
    clearInterval(lockTimer); lockUntil = 0;
    $("lock").hidden = true; box.style.opacity = ""; box.style.pointerEvents = "";
    lastSlide = 0; say("wag", "Nap over! Back to sniffing. Please be gentle with me.");
    window.dispatchEvent(new CustomEvent("dawg:awake"));
  }

  function build(){
    const host = document.createElement("div");
    host.innerHTML =
      '<div id="lock" hidden role="alertdialog" aria-live="polite" aria-label="Dawg is resting"><div class="lockcard">' +
      '<svg class="ropes" viewBox="0 0 300 40" width="260" height="35" aria-hidden="true"><path d="M150 0 L40 40M150 0 L260 40" stroke="#c9a46a" stroke-width="3.5" stroke-linecap="round" stroke-dasharray="6 3"/></svg>' +
      '<div class="board"><span class="nail l"></span><span class="nail r"></span><b>BEWARE OF</b><strong>DAWGS</strong><small>(currently asleep. do not wake.)</small></div>' +
      '<div id="lockDog"></div><p class="lockmeta">429 Too Many Requests &middot; Dawg is back in <span id="lockSec">15</span>s</p><p id="lockQuote" class="lockquote"></p>' +
      '<div class="lockbar"><i id="lockFill"></i></div></div></div>' +
      '<aside id="dawgbox" aria-label="Dawg the mascot"><div id="bubble" role="status" aria-live="polite"><span id="bubbleText"></span><button type="button" id="dawgSound" aria-label="Dawg sounds" aria-pressed="false"></button></div><div id="dawgFig" title="Click me, or drag me"></div></aside>';
    while (host.firstChild) document.body.appendChild(host.firstChild);
    box = $("dawgbox"); fig = $("dawgFig"); bub = $("bubble"); bt = $("bubbleText");
    fig.innerHTML = dawgSVG(150, "idle");
    document.querySelectorAll("[data-dawg]").forEach(el => { el.innerHTML = dawgSVG(+el.dataset.dawg, el.dataset.mood || "idle"); });
    bt.textContent = "Hi, I'm Dawg! I sniff every payment before it gets charged.";
    setSound(soundOn, true);
    if (soundOn) ["pointerdown", "keydown"].forEach(ev => document.addEventListener(ev, preload, { once: true, passive: true }));
    $("dawgSound").addEventListener("click", e => { e.stopPropagation(); setSound(!soundOn); });
    let drag = null;
    fig.addEventListener("pointerdown", e => { drag = { sx: e.clientX, sy: e.clientY, moved: false }; try { fig.setPointerCapture(e.pointerId); } catch (x) {} box.classList.add("dragging"); });
    fig.addEventListener("pointermove", e => {
      if (!drag) return;
      const dx = e.clientX - drag.sx, dy = e.clientY - drag.sy;
      if (Math.hypot(dx, dy) > 5) drag.moved = true;
      if (!drag.moved) return;
      const nx = Math.min(10, Math.max(-(innerWidth - box.offsetWidth - 30), home.x + dx)), ny = Math.min(10, Math.max(-(innerHeight - box.offsetHeight - 20), home.y + dy));
      box.style.setProperty("--dx", nx + "px"); box.style.setProperty("--dy", ny + "px"); drag.nx = nx; drag.ny = ny;
    });
    const end = () => { if (!drag) return; box.classList.remove("dragging"); if (drag.moved) home = { x: drag.nx, y: drag.ny }; else say("wag", TIPS[Math.floor(Math.random() * TIPS.length)]); drag = null; };
    fig.addEventListener("pointerup", end); fig.addEventListener("pointercancel", end);
  }

  window.Dawg = { say, react, lock, isLocked: () => Date.now() < lockUntil };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", build); else build();
})();
