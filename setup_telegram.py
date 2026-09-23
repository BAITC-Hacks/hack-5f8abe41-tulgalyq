"""Configure a Telegram bot menu to open the deployed Mission 100 Mini App.

Requires TELEGRAM_BOT_TOKEN and MINI_APP_URL in the environment. Never prints
or stores the bot token. Run only after the user creates a bot in BotFather.
"""

import json
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    url = os.getenv("MINI_APP_URL", "")
    if not token or not url.startswith("https://"):
        print("Нужны TELEGRAM_BOT_TOKEN и публичный MINI_APP_URL с https://", file=sys.stderr)
        return 2
    payload = json.dumps({
        "menu_button": {"type": "web_app", "text": "Открыть Миссию 100", "web_app": {"url": url}}
    }).encode("utf-8")
    request = Request("https://api.telegram.org/bot%s/setChatMenuButton" % token,
                      data=payload, headers={"Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=20) as response:
            result = json.load(response)
    except (HTTPError, URLError) as error:
        print("Не удалось настроить меню бота: %s" % type(error).__name__, file=sys.stderr)
        return 1
    if not result.get("ok"):
        print("Telegram отклонил настройку меню.", file=sys.stderr)
        return 1
    print("Готово: меню бота открывает %s" % url)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
