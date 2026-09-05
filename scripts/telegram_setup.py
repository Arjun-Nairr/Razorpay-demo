"""Safe Telegram setup helper - run AFTER putting TELEGRAM_ENABLED and
TELEGRAM_BOT_TOKEN in the gitignored root .env (see .env.example).

    python scripts/telegram_setup.py verify     # confirm the bot token (getMe)
    python scripts/telegram_setup.py chat-id    # list chat id candidates (getUpdates),
                                                 # after you have messaged the bot once

Never writes to .env and never prints a secret value in full - only
presence/shape (e.g. "bot_token_present: True") and the bot's own public
username/id. Fails with a plain, actionable message; never raises a raw
traceback for an expected configuration problem.
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from hermes.telegram_delivery import (  # noqa: E402
    TelegramConfig,
    fetch_chat_id_candidates,
    verify_bot,
)


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    load_dotenv(os.path.join(root, ".env"), override=False)


def _cmd_verify(config: TelegramConfig) -> int:
    if not config.bot_token:
        print("TELEGRAM_BOT_TOKEN is not set in .env. Add it, then re-run.", file=sys.stderr)
        return 2
    result = verify_bot(config)
    if not result["ok"]:
        print(f"Bot verification failed: {result['reason']}. Check the token in .env.",
              file=sys.stderr)
        return 3
    print(f"OK: bot verified - username=@{result['username']} bot_id={result['bot_id']}")
    print("Bot token is valid. Next: send /start to this bot in Telegram, then run "
          "`python scripts/telegram_setup.py chat-id`.")
    return 0


def _cmd_chat_id(config: TelegramConfig) -> int:
    if not config.bot_token:
        print("TELEGRAM_BOT_TOKEN is not set in .env. Add it, then re-run.", file=sys.stderr)
        return 2
    result = fetch_chat_id_candidates(config)
    if not result["ok"]:
        print(f"Could not fetch chat updates: {result['reason']}. Check the token in .env.",
              file=sys.stderr)
        return 3
    candidates = result["candidates"]
    if not candidates:
        print("No chat updates found yet. Open the bot in Telegram and send /start, "
              "then re-run this command.")
        return 0
    print("Candidate chat ids (pick the one for your own private chat with the bot):")
    for c in candidates:
        label = c["first_name"] or "(no name)"
        kind = "group/channel" if c["is_group"] else "private"
        print(f"  chat_id={c['chat_id']}  name={label}  kind={kind}")
    print("\nAdd the right one to .env as: TELEGRAM_CHAT_ID=<chat_id>")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("command", choices=["verify", "chat-id"])
    args = ap.parse_args()

    _load_dotenv()
    config = TelegramConfig.from_env()
    print(f"Config: {config.describe()}")  # presence/shape only - never a secret value
    if not config.enabled:
        print("TELEGRAM_ENABLED is not set to 1 in .env - delivery stays disabled "
              "regardless of the checks below.", file=sys.stderr)

    if args.command == "verify":
        return _cmd_verify(config)
    return _cmd_chat_id(config)


if __name__ == "__main__":
    raise SystemExit(main())
