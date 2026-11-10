#!/usr/bin/env python3
"""Set up Telegram on this computer without displaying the bot token."""
import getpass
import json
import os
import re
import secrets
from pathlib import Path
import urllib.error
import urllib.request


def telegram_request(token, method, data=None):
    request = urllib.request.Request(
        f'https://api.telegram.org/bot{token}/{method}',
        data=json.dumps(data).encode() if data is not None else None,
        headers={'Content-Type': 'application/json'},
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        payload = json.load(response)
    if not payload.get('ok'):
        raise ValueError('Telegram did not accept the request')
    return payload['result']


def main():
    print('Paste the bot token below. It will not appear as you paste; press Return afterwards.')
    token = getpass.getpass('Bot token: ').strip()
    if not re.fullmatch(r'[0-9]+:[A-Za-z0-9_-]+', token):
        print('That does not look like a bot token; nothing was saved.')
        return 1
    try:
        bot = telegram_request(token, 'getMe')
    except (urllib.error.URLError, OSError, ValueError):
        # Exceptions can contain the URL (and therefore the token); never print them.
        print('Could not reach Telegram or the token was not accepted. Check the token and internet, then try again.')
        return 1
    code = 'test-' + secrets.token_hex(3)
    print(f"Open this bot in Telegram: https://t.me/{bot['username']}")
    print(f'Tap Start if needed, then send this exact message to the bot: {code}')
    input('After sending the message in Telegram, press Return here. ')
    try:
        updates = telegram_request(token, 'getUpdates', {'allowed_updates': ['message']})
    except urllib.error.HTTPError as error:
        if error.code == 409:
            print('Telegram says another app is receiving messages for this bot. Close it and try again.')
        else:
            print('Telegram could not retrieve your message. Try again in a moment.')
        return 1
    except (OSError, ValueError):
        print('Telegram could not retrieve your message. Check your connection and try again.')
        return 1
    chat_ids = set()
    for update in updates:
        message = update.get('message') or {}
        chat = message.get('chat') or {}
        if chat.get('type') == 'private' and message.get('text', '').strip() == code:
            chat_ids.add(str(chat['id']))
    if len(chat_ids) != 1:
        print(f"Could not find your setup message in a private chat with @{bot['username']}.")
        print('Run the setup again and send the new code shown in Terminal.')
        return 1
    chat_id = chat_ids.pop()
    # Restrict initial creation permissions. Never print token or file contents.
    path = Path(__file__).resolve().parent / '.env'
    existing = path.read_text() if path.exists() else ''
    lines = [line for line in existing.splitlines() if not line.startswith(('TELEGRAM_BOT_TOKEN=', 'TELEGRAM_CHAT_ID='))]
    lines.extend(['TELEGRAM_BOT_TOKEN=' + token, 'TELEGRAM_CHAT_ID=' + chat_id])
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, 'w') as output:
        output.write('\n'.join(lines) + '\n')
    print('Telegram settings saved privately on this Mac.')
    print('Your chat ID is ' + chat_id + '. You will need it for the GitHub secret.')
    os.environ['TELEGRAM_BOT_TOKEN'] = token
    os.environ['TELEGRAM_CHAT_ID'] = chat_id
    import telegram_test
    return telegram_test.main()


if __name__ == '__main__':
    raise SystemExit(main())
