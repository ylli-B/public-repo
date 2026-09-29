"""Notification delivery with fallbacks, so one blocked channel is not fatal.

Channels are tried in priority order until one succeeds:

  ntfy     primary channel (working). POST to an unguessable topic; iOS/Android
           via the ntfy app.
  telegram optional backup if TELEGRAM_* is set.
  twilio   optional SMS only if credentials are present. Account resources were
           torn down; leave Twilio unset unless you intentionally re-enable it.

Everything is logged locally regardless of channel.

.env keys (all gitignored):
    NTFY_TOPIC                    unguessable topic string
    NTFY_SERVER                   defaults to https://ntfy.sh
    TELEGRAM_BOT_TOKEN            from @BotFather
    TELEGRAM_CHAT_ID              your chat id
    NOTIFY_CHANNELS               override order, e.g. "ntfy,telegram"
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")
# Domain-neutral default; override per deployment with EVMAX_NOTIFY_LOG.
LOG = Path(os.getenv("EVMAX_NOTIFY_LOG",
                     ROOT / "ml" / "artifacts" / "mlb" / "gameday" / "sms_log.txt"))
TWILIO_API = "https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"
DEFAULT_ORDER = ("ntfy", "telegram")


def _log(body: str, note: str) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(f"\n----- {datetime.now(UTC).isoformat(timespec='seconds')} "
                 f"{note} -----\n{body}\n")


def send_ntfy(body: str, title: str) -> bool:
    topic = os.getenv("NTFY_TOPIC")
    if not topic:
        return False
    server = os.getenv("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
    r = httpx.post(f"{server}/{topic}", content=body.encode("utf-8"), timeout=30.0,
                   headers={"Title": title, "Priority": "high", "Tags": "baseball"})
    ok = r.status_code < 300
    print(f"[notify] ntfy {'ok' if ok else r.status_code}: {server}/{topic}")
    return ok


def send_telegram(body: str, title: str) -> bool:
    tok, chat = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if not (tok and chat):
        return False
    r = httpx.post(f"https://api.telegram.org/bot{tok}/sendMessage", timeout=30.0,
                   data={"chat_id": chat, "text": f"{title}\n\n{body}"})
    ok = r.status_code < 300
    print(f"[notify] telegram {'ok' if ok else r.text[:160]}")
    return ok


def sender() -> dict:
    """Messaging Service if registered, otherwise the bare number."""
    svc = os.getenv("TWILIO_MESSAGING_SERVICE_SID")
    if svc:
        return {"MessagingServiceSid": svc}
    frm = os.getenv("TWILIO_FROM_NUMBER")
    return {"From": frm} if frm else {}


def send_twilio(body: str, to: str | None = None) -> bool:
    sid, tok = os.getenv("TWILIO_ACCOUNT_SID"), os.getenv("TWILIO_AUTH_TOKEN")
    to = to or os.getenv("ALERT_TO_NUMBER")
    if not (sid and tok and to and sender()):
        return False
    r = httpx.post(TWILIO_API.format(sid=sid), auth=(sid, tok), timeout=30.0,
                   data={"To": to, "Body": body, **sender()})
    if r.status_code >= 300:
        print(f"[notify] twilio {r.status_code}: {r.text[:200]}")
        return False
    # accepted is not delivered; 30034 shows up asynchronously on the message record
    print(f"[notify] twilio queued to {to} "
          f"({len(body)} chars, {-(-len(body) // 153)} segments)")
    return True


def configured() -> list[str]:
    out = []
    if os.getenv("NTFY_TOPIC"):
        out.append("ntfy")
    if os.getenv("TELEGRAM_BOT_TOKEN") and os.getenv("TELEGRAM_CHAT_ID"):
        out.append("telegram")
    if os.getenv("TWILIO_ACCOUNT_SID") and os.getenv("ALERT_TO_NUMBER") and sender():
        out.append("twilio")
    return out


def send(body: str, *, title: str = "MLB DFS", dry_run: bool = False,
         all_channels: bool = False) -> bool:
    order = [c.strip() for c in os.getenv("NOTIFY_CHANNELS", "").split(",") if c.strip()]
    order = order or list(DEFAULT_ORDER)
    available = configured()
    _log(body, f"channels={available} dry_run={dry_run}")

    if dry_run or not available:
        why = "dry run" if dry_run else "no channel configured, printing instead"
        print(f"[notify: {why}]\n{body}")
        return False

    sent = False
    for ch in order:
        if ch not in available:
            continue
        ok = {"ntfy": lambda: send_ntfy(body, title),
              "telegram": lambda: send_telegram(body, title),
              "twilio": lambda: send_twilio(body)}[ch]()
        sent = sent or ok
        if ok and not all_channels:
            break
    if not sent:
        print("[notify] every configured channel failed")
    return sent


# kept so existing callers keep working
def send_sms(body: str, *, to: str | None = None, dry_run: bool = False) -> bool:
    return send(body, dry_run=dry_run)


if __name__ == "__main__":
    import sys

    msg = " ".join(a for a in sys.argv[1:] if not a.startswith("--")) or "nfl-edge test"
    print(f"configured channels: {configured() or 'none'}")
    send(msg, dry_run="--dry-run" in sys.argv, all_channels="--all" in sys.argv)
