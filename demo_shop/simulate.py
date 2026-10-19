"""Live traffic for the PayDawg dashboard: a stream of realistic orders from Leash & Larder's customers.

  python demo_shop/simulate.py                 run until Ctrl+C (about 7 orders a minute)
  python demo_shop/simulate.py --minutes 3     stop after 3 minutes
  python demo_shop/simulate.py --speed 2       twice as busy
  python demo_shop/simulate.py --reset         clear the demo first
  python demo_shop/simulate.py --no-history    start from a brand-new shop and watch Dawg learn from zero
  python demo_shop/simulate.py --review        also play the shop owner: capture or void held payments

Mock mode only (PAYPAL_MODE=mock): a real PayPal order needs a person to approve it on PayPal, so use the
shop page (/shop) for real sandbox payments. Everything goes through PayDawg's public API, as a shop would.
Unless --no-history is given, an empty shop first gets about two weeks of SIMULATED trading history in its
Notebook, so the stream starts from a shop with a normal to compare against.
Set ADMIN_TOKEN in this window if the server has one (needed for --reset, the history and --review).

Most orders are ordinary: returning customers and some first-time ones buying 1-3 things. Mixed in, in a
random order, are the things Dawg is there for: an order far bigger than usual, a double-clicked Pay button,
and a card tester firing quick orders of the cheapest item.
"""
import argparse
import json
import os
import random
import sys
import time
import urllib.request
import uuid
from urllib.error import HTTPError, URLError

BASE = os.getenv("PAYDAWG_URL", "http://127.0.0.1:8000").rstrip("/")
TOKEN = os.getenv("ADMIN_TOKEN", "")
MERCHANT = "demo-merchant"
SHOP = "Leash & Larder"
NAMES = ["aarav", "diya", "kabir", "meera", "rohan", "ananya", "liam", "sofia", "noah", "amara", "kenji", "lucia",
         "omar", "priya", "maya", "arjun", "zara", "leo", "ines", "tariq", "nina", "vikram", "chloe", "mateo",
         "aisha", "felix", "isha", "jonas", "keya", "marco", "nora", "ravi", "sana", "theo", "uma", "yusuf",
         "elena", "hari", "lena", "dev"]
# Ordinary traffic and the occasional trouble, dealt from a shuffled deck so every ~2 minutes has a bit of everything.
DECK = ["returning"] * 9 + ["first_time"] * 2 + ["repeat", "big", "double_click", "card_test"]
FALLBACK_CATALOG = [("biscuits", "Peanut butter biscuits", "8.50"), ("salmon", "Salmon training treats", "6.75"),
                    ("ball", "Rubber fetch ball", "7.25"), ("rope", "Rope tug toy", "12.00"),
                    ("leash", "Reflective leash", "18.00"), ("bowls", "Steel bowl pair", "22.00"),
                    ("jacket", "Rain jacket", "29.00"), ("bed", "Orthopedic bed", "64.00")]
# Treats and toys sell far more often than beds.
POPULARITY = {"biscuits": 9, "salmon": 9, "ball": 6, "rope": 5, "leash": 3, "bowls": 2, "jacket": 2, "bed": 1}


class Gateway:
    def __init__(self, base, token):
        self.base, self.token = base, token

    def call(self, method, path, body=None, key=None, admin=False):
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if key:
            headers["Idempotency-Key"] = key
        if admin and self.token:
            headers["X-Admin-Token"] = self.token
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(self.base + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=30) as reply:
                return reply.status, json.loads(reply.read().decode() or "{}"), reply.headers
        except HTTPError as exc:
            try:
                detail = json.loads(exc.read().decode() or "{}")
            except ValueError:
                detail = {}
            return exc.code, detail, exc.headers


def money(value):
    return f"${value:,.2f}"


class Simulator:
    def __init__(self, gateway, args):
        self.gw, self.args = gateway, args
        self.rng = random.Random(args.seed)
        self.run = uuid.uuid4().hex[:6]
        self.n = 0
        self.deck = []
        self.recent_customers = []
        self.held = []          # (due_time, payment_id)
        self.counts = {"Wag": 0, "Growl": 0, "Bark": 0}
        self.limited = 0
        self.catalog = []
        self.customers = [f"{name}-{self.rng.randint(100, 999)}" for name in NAMES]

    # ---------- setup ----------
    def start(self):
        try:
            status, health, _ = self.gw.call("GET", "/health")
        except URLError:
            sys.exit(f"PayDawg is not reachable at {self.gw.base}. Start it with start.bat, or set PAYDAWG_URL.")
        if status != 200 or not health.get("simulated"):
            sys.exit("The simulator needs PAYPAL_MODE=mock. Real PayPal orders need a person to approve each one on "
                     "PayPal, so for the sandbox use the shop page (/shop) instead.")
        self.load_catalog()
        if self.args.reset:
            self.admin("POST", "/v1/demo/reset", "reset the demo")
            print("Demo reset: payments and the Notebook are cleared.")
        status, notebook, _ = self.gw.call("GET", "/v1/notebook", admin=True)
        if status == 401:
            sys.exit("This server has an ADMIN_TOKEN. Set the same ADMIN_TOKEN in this window and run again.")
        if status == 200 and not notebook.get("learned_from") and not self.args.no_history:
            notebook = self.admin("POST", "/v1/demo/seed", "give the shop its simulated history")
            print("The shop was empty, so its Notebook got about two weeks of SIMULATED trading history.")
        if status == 200:
            self.print_notebook(notebook)
        per_minute = 60 / (self.args.every / self.args.speed)
        print(f"Live traffic for {SHOP}: about {per_minute:.0f} orders a minute (mock mode, SIMULATED). Ctrl+C to stop.")
        print(f"Dashboard: {self.gw.base}/    Shop: {self.gw.base}/shop\n")

    def admin(self, method, path, what):
        status, body, _ = self.gw.call(method, path, body={}, admin=True)
        if status == 401:
            sys.exit(f"Could not {what}: this server has an ADMIN_TOKEN. Set the same ADMIN_TOKEN in this window.")
        if status != 200:
            sys.exit(f"Could not {what} ({status}): {body.get('detail', body)}")
        return body

    def load_catalog(self):
        status, body, _ = self.gw.call("GET", "/shop/api/catalog")
        if status == 200 and body.get("items"):
            self.catalog = [(i["sku"], i["name"], i["price"]) for i in body["items"]]
        else:
            self.catalog = FALLBACK_CATALOG
        self.price = {sku: float(price) for sku, _, price in self.catalog}
        self.name = {sku: name for sku, name, _ in self.catalog}

    def print_notebook(self, nb):
        if not nb.get("learned_from"):
            print(f"Notebook: empty. Dawg starts strict (surge alert at {nb.get('surge_above')}) and relaxes as he learns;"
                  " the surge level can at most double every 10 minutes.")
            return
        sim = f" ({nb['simulated_history']} SIMULATED)" if nb.get("simulated_history") else ""
        print(f"Notebook: learned from {nb['learned_from']} payments{sim}. Usual basket {money(nb['usual_basket'])}, "
              f"unusual above {money(nb['unusual_above'])}, usual hours {nb['usual_hours_text']}, "
              f"surge alert at {nb['surge_above']} in 10 minutes.")

    # ---------- orders ----------
    def basket(self, lines=None):
        skus = [sku for sku, _, _ in self.catalog]
        weights = [POPULARITY.get(sku, 2) for sku in skus]
        chosen = []
        for _ in range(lines or self.rng.choices([1, 2, 3], weights=[5, 4, 2])[0]):
            sku = self.rng.choices(skus, weights=weights)[0]
            if sku not in chosen:
                chosen.append(sku)
        return [(sku, 1 if self.rng.random() < 0.8 else 2) for sku in chosen]

    def body(self, customer, items, ref):
        total = round(sum(self.price[sku] * qty for sku, qty in items), 2)
        summary = ", ".join(f"{qty} x {self.name[sku]}" for sku, qty in items)
        return {"merchant_id": MERCHANT, "amount": total, "currency": "USD", "customer_id": customer,
                "description": f"{SHOP} order {ref}: {summary}"[:255], "order_ref": ref}

    def ref(self):
        return "LL-" + uuid.uuid4().hex[:8].upper()

    def send(self, body, story):
        self.n += 1
        status, paid, headers = self.gw.call("POST", "/v1/payments", body=body, key=f"sim-{self.run}-{self.n}")
        if status == 429:
            wait = int(headers.get("Retry-After") or 15) if headers else 15
            self.limited += 1
            self.line("-", body, story, f"flood guard: PayDawg is refusing this client for {wait}s (HTTP 429)")
            self.sleep(wait)
            return None
        if status != 200:
            self.line("!", body, story, f"HTTP {status}: {paid.get('detail', paid)}")
            return None
        verdict = paid.get("verdict", "?")
        self.counts[verdict] = self.counts.get(verdict, 0) + 1
        reasons = [r for r in paid.get("reasons", []) if not r.startswith("No deterministic")]
        note = story if verdict == "Wag" else story + ": " + (reasons[0] if reasons else "")
        if paid.get("decision_source") in ("ollama", "http_api"):
            note = "[AI] " + note
        self.line(verdict, body, story, note)
        if paid.get("status") == "held" and self.args.review:
            self.held.append((time.monotonic() + self.rng.uniform(6, 20), paid["id"]))
        if story in ("returning customer", "first-time customer") and verdict == "Wag":
            self.recent_customers = (self.recent_customers + [body["customer_id"]])[-6:]   # who may "buy again"
        return paid

    def line(self, verdict, body, story, note):
        stamp = time.strftime("%H:%M:%S")
        text = f"{stamp}  {verdict:<6} {money(body['amount']):>9}  {body['customer_id']:<15} {note}"
        print(text if len(text) <= 150 else text[:147] + "...", flush=True)

    def play(self, story):
        if story == "returning":
            self.send(self.body(self.rng.choice(self.customers), self.basket(), self.ref()), "returning customer")
        elif story == "first_time":
            guest = "guest-" + uuid.uuid4().hex[:5]
            self.send(self.body(guest, self.basket(), self.ref()), "first-time customer")
        elif story == "repeat":
            who = self.rng.choice(self.recent_customers or self.customers)
            self.send(self.body(who, self.basket(1), self.ref()), "bought again a moment later")
        elif story == "big":
            who = self.rng.choice(self.customers + ["guest-" + uuid.uuid4().hex[:5]])
            bed = "bed" if "bed" in self.price else max(self.price, key=self.price.get)
            self.send(self.body(who, [(bed, self.rng.randint(6, 8))], self.ref()), "far bigger order than usual")
        elif story == "double_click":
            body = self.body(self.rng.choice(self.customers), self.basket(), self.ref())
            self.send(body, "pressed Pay")
            self.sleep(self.rng.uniform(0.3, 0.7))
            self.send(body, "pressed Pay again (double-click)")
        elif story == "card_test":
            bot = "guest-" + uuid.uuid4().hex[:5]
            cheapest = min(self.price, key=self.price.get)
            for i in range(self.rng.randint(6, 7)):
                self.send(self.body(bot, [(cheapest, 1)], self.ref()), f"card tester, quick order {i + 1}")
                self.sleep(self.rng.uniform(0.6, 1.0))

    def review_due(self):
        now = time.monotonic()
        due = [h for h in self.held if h[0] <= now]
        self.held = [h for h in self.held if h[0] > now]
        for _, pid in due:
            action = "approve" if self.rng.random() < 0.75 else "void"
            status, paid, _ = self.gw.call("POST", f"/v1/payments/{pid}/{action}", body={}, admin=True)
            if status == 200:
                label = "captured it" if action == "approve" else "voided it"
                print(f"{time.strftime('%H:%M:%S')}  owner  {money(paid['amount']):>9}  {paid['customer_id']:<15} "
                      f"the shop owner checked the held order and {label}", flush=True)

    def sleep(self, seconds):
        end = time.monotonic() + seconds
        while True:
            left = end - time.monotonic()
            if left <= 0:
                return
            if self.held:
                self.review_due()
            time.sleep(min(left, 0.5))

    def loop(self):
        stop_at = time.monotonic() + self.args.minutes * 60 if self.args.minutes else None
        while True:
            if stop_at and time.monotonic() >= stop_at:
                break
            if self.args.orders and self.n >= self.args.orders:
                break
            if not self.deck:
                self.deck = DECK[:]
                self.rng.shuffle(self.deck)
            self.play(self.deck.pop())
            gap = min(max(self.rng.expovariate(1 / self.args.every), 1.5), 25) / self.args.speed
            self.sleep(gap)

    def summary(self):
        total = sum(self.counts.values())
        print(f"\nSent {total} payments: {self.counts.get('Wag', 0)} Wag, {self.counts.get('Growl', 0)} Growl (held for review), "
              f"{self.counts.get('Bark', 0)} Bark (blocked)" + (f", {self.limited} refused by the flood guard." if self.limited else "."))
        status, nb, _ = self.gw.call("GET", "/v1/notebook", admin=True)
        if status == 200:
            self.print_notebook(nb)


def build_parser():
    parser = argparse.ArgumentParser(description="Stream realistic demo orders into PayDawg (mock mode).")
    parser.add_argument("--minutes", type=float, default=0, help="stop after this many minutes (default: run until Ctrl+C)")
    parser.add_argument("--orders", type=int, default=0, help="stop after this many payments")
    parser.add_argument("--speed", type=float, default=1.0, help="2 = twice as busy")
    parser.add_argument("--every", type=float, default=8.0, help=argparse.SUPPRESS)  # average seconds between orders
    parser.add_argument("--reset", action="store_true", help="clear the demo payments and Notebook first")
    parser.add_argument("--no-history", action="store_true", help="do not give an empty shop its simulated history")
    parser.add_argument("--review", action="store_true", help="capture or void held payments like a shop owner")
    parser.add_argument("--seed", type=int, default=None, help="random seed, for a repeatable run")
    parser.add_argument("--url", default=BASE, help="PayDawg address (default %(default)s or PAYDAWG_URL)")
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.speed <= 0 or args.every <= 0:
        parser.error("--speed must be above 0")
    sim = Simulator(Gateway(args.url.rstrip("/"), TOKEN), args)
    sim.start()
    try:
        sim.loop()
    except KeyboardInterrupt:
        pass
    sim.summary()


if __name__ == "__main__":
    main()
