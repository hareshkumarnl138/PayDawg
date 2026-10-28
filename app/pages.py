"""Small server-rendered pages for the buyer's side of the PayPal redirect.

The buyer lands here from PayPal's own site, so they see Dawg and a plain-language result instead of raw JSON.
Everything dynamic goes through html.escape, and the text per outcome is a fixed whitelist: the buyer is
never shown screening reasons or risk scores, only what happened to their payment.
"""
from html import escape

# outcome -> (mood, headline, message)
OUTCOMES = {
    "captured": ("wag", "Wag! All done.", "Dawg sniffed your payment and it smells clean. It has been charged. Thank you!"),
    "held": ("growl", "Grrr... one moment.", "Your payment is authorized and Dawg is holding it for the shop to confirm. Nothing has been charged yet."),
    "barked": ("bark", "Woof! Dawg says no.", "Dawg barked at this payment and stopped it. Nothing was charged. If you think this is a mistake, please contact the shop."),
    "cancelled": ("idle", "No problem.", "You cancelled at PayPal, so nothing was charged. Dawg understands."),
    "processed": ("idle", "Already handled.", "This payment was already processed. There is nothing more to do here."),
    "notfound": ("bark", "Woof? Can't find that.", "Dawg could not find a payment for this link. Please go back to the shop and try again."),
    "error": ("tired", "Dawg tripped over a cable.", "PayPal approved your payment, but the last step did not finish. Please do not pay twice: contact the shop."),
}

PAW_ICON = ("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Cg fill='%23c88a4e'%3E%3Cellipse cx='32' cy='42' rx='15' ry='13'/%3E%3Ccircle cx='13' cy='26' r='7'/%3E%3Ccircle cx='25' cy='13' r='7'/%3E%3Ccircle cx='39' cy='13' r='7'/%3E%3Ccircle cx='51' cy='26' r='7'/%3E%3C/g%3E%3C/svg%3E")

_CSS = (
    ":root{--bg:#fbf6ee;--card:#fff;--ink:#2b2118;--muted:#6b5a48;--accent:#c88a4e;--line:#ead9c0}"
    "@media(prefers-color-scheme:dark){:root{--bg:#1d1812;--card:#2a231a;--ink:#f3e8d6;--muted:#bfae95;--line:#403525}}"
    "*{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;padding:16px;"
    "background:var(--bg);color:var(--ink);font:16px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}"
    ".card{max-width:420px;width:100%;background:var(--card);border:1px solid var(--line);border-radius:20px;"
    "padding:28px 24px;text-align:center;box-shadow:0 8px 30px rgba(0,0,0,.08)}"
    "h1{font-size:1.5rem;margin:8px 0 6px}p{margin:0 0 12px;color:var(--muted)}"
    ".ref{font-size:.85rem;color:var(--muted);border-top:1px dashed var(--line);margin-top:16px;padding-top:12px}"
    ".brand{font-size:.8rem;letter-spacing:.12em;text-transform:uppercase;color:var(--accent);font-weight:700}"
    ".back{display:inline-block;margin-top:14px;color:var(--ink);font-weight:600;text-underline-offset:3px}"
    "[data-dawg]{display:flex;justify-content:center}"
    "#dawgbox,#lock{display:none!important}"  # the floating dashboard mascot is not wanted on this page
)


def result_page(outcome: str, payment: dict | None = None, back_url: str | None = None) -> str:
    mood, headline, message = OUTCOMES.get(outcome, OUTCOMES["error"])
    # Dawg's noise plays when the buyer lands here, but only for the three verdict pages.
    sound = ' data-sound="arrive"' if outcome in ("captured", "held", "barked") else ""
    ref = ""
    if payment:
        amount = payment.get("amount")
        currency = escape(str(payment.get("currency") or ""))
        amount_txt = f"{amount:.2f} {currency}".strip() if isinstance(amount, (int, float)) else ""
        ref = (f'<div class="ref">Payment {escape(str(payment.get("id", "")))}'
               + (f" &middot; {escape(amount_txt)}" if amount_txt else "") + "</div>")
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>PayDawg &mdash; {escape(headline)}</title>"
        '<link rel="stylesheet" href="/dashboard/dawg.css">'
        f'<link rel="icon" href="{PAW_ICON}">'
        f"<style>{_CSS}</style></head><body>"
        '<main class="card"><div class="brand">PayDawg</div>'
        f'<div data-dawg="190" data-mood="{escape(mood)}"{sound} aria-hidden="false"></div>'
        f"<h1>{escape(headline)}</h1><p>{escape(message)}</p>{ref}"
        + (f'<a class="back" href="{escape(back_url)}">Back to the shop</a>' if back_url else "")
        + "</main>"
        '<script src="/dashboard/dawg.js"></script></body></html>'
    )
