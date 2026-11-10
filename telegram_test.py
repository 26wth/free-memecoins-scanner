#!/usr/bin/env python3
"""Send one test message using credentials supplied through environment variables."""
import json
import os
import sys
import urllib.error
import urllib.request


def main():
    token = os.getenv('TELEGRAM_BOT_TOKEN', '').strip()
    chat_id = os.getenv('TELEGRAM_CHAT_ID', '').strip()
    if not token or not chat_id:
        print('Missing Telegram bot token or chat ID. Add both as GitHub Actions secrets.', file=sys.stderr)
        return 1
    data = json.dumps({'chat_id': chat_id, 'text': 'Your memecoin scanner Telegram test is working. Alerts only; no trading.'}).encode()
    request = urllib.request.Request(
        'https://api.telegram.org/bot' + token + '/sendMessage',
        data=data, headers={'Content-Type': 'application/json'}, method='POST')
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.load(response)
        if not payload.get('ok'):
            print('Telegram did not accept the test. Check the bot token and chat ID.', file=sys.stderr)
            return 1
    except (urllib.error.URLError, OSError, ValueError):
        # Exception messages can include the request URL, which contains the secret token.
        print('Telegram test failed. Check your connection, bot token, and chat ID.', file=sys.stderr)
        return 1
    print('Telegram accepted the test message.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
