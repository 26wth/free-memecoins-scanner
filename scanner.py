#!/usr/bin/env python3
"""Free, conservative news-to-Solana-pool alerts. No trading or wallet access."""
import calendar

import hashlib
import json
import logging
import math

import os
import re
import tempfile
import time
from pathlib import Path

import feedparser
import requests

LOG = logging.getLogger('scanner')
STATE_PATH = Path(os.environ.get('STATE_PATH', 'state/state.json'))
FEEDS = [
    'https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en',
    'https://feeds.bbci.co.uk/news/rss.xml',
    'https://www.aljazeera.com/xml/rss/all.xml',
    'https://news.google.com/rss/search?q=gaming+OR+viral+OR+celebrity&hl=en-US&gl=US&ceid=US:en',
]
# These are scoring hints, not an exhaustive allowlist.
EVENT_WORDS = {'breaking','announces','announced','announcement','launches','launched','launch',
    'viral','meme','scandal','arrested','resigns','resigned','wins','won','dies','died',
    'unveils','reveals','revealed','ban','banned','lawsuit','election','elected','explosion',
    'earthquake','crash','outage','shock','shocking','unexpected','trailer','release','released'}
FAMOUS = {'trump','musk','tesla','nvidia','apple','openai','rockstar','gta','biden',
          'youtube','tiktok','instagram','google','microsoft','meta','amazon'}
STOP = {'the','and','for','with','from','that','this','after','about','says','said','news',
        'breaking','world','new','live','what','how','why','watch','video','report','reports',
        'latest','today','first','over','more','than','into','their','will','could','amid',
        'reveals','revealed','announces','announced','launches','launched','release','released',
        'trailer','viral','meme','scandal','wins','loses','trump','musk','tesla','apple',
        'openai','nvidia','rockstar','gta','president','elon','donald','game','games'}
SESSION = requests.Session()
SESSION.headers.update({'User-Agent':'FreeNewsCoinScanner/1.0'})


def norm(text):
    return re.sub(r'[^a-z0-9]+', ' ', text.lower()).strip()


def classify(title):
    """Small transparent heuristic, not an AI or a verification service."""
    words = set(norm(title).split())
    if words & {"earnings", "quarterly", "dividend", "forecast"}: return None

    event = words & EVENT_WORDS
    famous = words & FAMOUS
    # Two uncommon headline words are needed later to prevent celebrity-name-only matches.
    distinctive = [w for w in norm(title).split() if len(w) >= 5 and w not in STOP and w not in EVENT_WORDS]
    distinctive = list(dict.fromkeys(distinctive))
    score = 2 * bool(event) + bool(famous) + (len(distinctive) >= 2)
    if not event or score < 3 or len(distinctive) < 2:
        return None
    return {'score': score, 'terms': distinctive[:4]}


def load_state():
    if not STATE_PATH.exists():
        return {'seen': {}, 'events': {}, 'alerts': {}}
    try:
        data = json.loads(STATE_PATH.read_text())
        if not all(isinstance(data.get(k), dict) for k in ('seen','events','alerts')):
            raise ValueError('invalid state format')
        return data
    except (ValueError, OSError) as e:
        raise RuntimeError('Cannot read state file; refusing to reset deduplication') from e


def save_state(state):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=STATE_PATH.parent, prefix='.state-', suffix='.tmp')
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(state, f, sort_keys=True)
        os.replace(name, STATE_PATH)
    finally:
        if os.path.exists(name): os.unlink(name)


def fetch_news(now):
    for url in FEEDS:
        try:
            response = SESSION.get(url, timeout=15)
            response.raise_for_status()
            for e in feedparser.parse(response.content).entries[:40]:
                stamp = e.get('published_parsed') or e.get('updated_parsed')
                if not stamp: continue
                published = calendar.timegm(stamp)  # feedparser gives UTC
                title = e.get('title', '').split(' - ')[0][:300]
                link = e.get('link', '')
                if title and link and 0 <= now - published <= 900:
                    yield {'title': title, 'link': link, 'published': published}
        except Exception:
            LOG.exception('Feed failed: %s', url)


def evaluate_pair(pair, event, now):
    try:
        if pair.get('chainId') != 'solana': return None
        created = float(pair['pairCreatedAt']) / 1000
        # Pool creation is a proxy only, not proof of token creation.
        if not event['published'] - 600 <= created <= now or now - created > 7200: return None
        liq = float((pair.get('liquidity') or {}).get('usd') or 0)
        vol = float((pair.get('volume') or {}).get('h24') or 0)
        if not math.isfinite(liq) or not math.isfinite(vol) or liq < 10000 or vol < 10000: return None
        base = pair['baseToken']
        if not base.get('address') or not pair.get('url'): return None
        # Require two distinctive full headline terms in the token name or symbol.
        token_words = set(norm(base.get('name','') + ' ' + base.get('symbol','')).split())
        overlap = token_words & set(event['terms'])
        if len(overlap) < 2: return None
        cap = pair.get('marketCap')
        return {'name': base.get('name',''), 'symbol': base.get('symbol',''),
                'address': base['address'], 'url': pair['url'], 'liquidity': liq,
                'volume': vol, 'cap': float(cap) if cap is not None else None,
                'age': (now-created)/60, 'matched': sorted(overlap)}
    except (KeyError, TypeError, ValueError, OverflowError):
        return None


def risk(address):
    try:
        r = SESSION.get('https://api.gopluslabs.io/api/v1/solana/token_security',
                        params={'contract_addresses': address}, timeout=12)
        r.raise_for_status()
        data = (r.json().get('result') or {}).get(address) or {}
        if not data: return 'GoPlus: unavailable or no data; risk unknown.'
        flags = []
        for field in ('mintable','freezable','closable','transfer_fee_upgradable','balance_mutable_authority'):
            value = data.get(field)
            if isinstance(value, dict) and str(value.get('status')) == '1': flags.append(field)
        return ('GoPlus flags: ' + ', '.join(flags) if flags else 'GoPlus: no checked flags found') + '; other and missing risks unknown.'
    except Exception:
        LOG.warning('Risk check unavailable')
        return 'GoPlus unavailable; risk unknown.'


def send(text):
    token = os.environ.get('TELEGRAM_BOT_TOKEN')
    chat = os.environ.get('TELEGRAM_CHAT_ID')
    if not token or not chat: raise RuntimeError('Set both Telegram secrets first')
    # Do not log URL: it contains a secret.
    response = SESSION.post('https://api.telegram.org/bot' + token + '/sendMessage',
                            json={'chat_id':chat, 'text':text, 'disable_web_page_preview':True}, timeout=15)
    if response.status_code != 200 or not response.json().get('ok'):
        raise RuntimeError('Telegram rejected the message (check token and chat ID)')


def scan(state, now):
    for item in fetch_news(now):
        key = hashlib.sha256(norm(item['title']).encode()).hexdigest()
        if key in state['seen']: continue
        state['seen'][key] = now
        classification = classify(item['title'])
        if classification:
            state['events'][key] = dict(item, **classification)
    # Run fewer searches to stay within free limits; older events get another chance next run.
    active = [(k,e) for k,e in state['events'].items() if e['published'] + 3600 > now]
    active.sort(key=lambda row: (-row[1]['score'], row[1]['published']))
    alert_count = 0

    for key, event in active[:12]:
        candidates = {}
        # Search individual distinctive words, then require two-word overlap.
        for term in event['terms'][:2]:
            try:
                r = SESSION.get('https://api.dexscreener.com/latest/dex/search', params={'q':term}, timeout=15)
                r.raise_for_status()
                for pair in (r.json().get('pairs') or []):
                    token = evaluate_pair(pair, event, now)
                    if token and (token['address'] not in candidates or token['liquidity'] > candidates[token['address']]['liquidity']):
                        candidates[token['address']] = token
            except Exception:
                LOG.exception('Token search failed')
        for token in sorted(candidates.values(), key=lambda x:-x['liquidity'])[:5]:
            alert_key = key + ':' + token['address']
            if alert_key in state['alerts']: continue
            if alert_count >= 20: break
            alert_count += 1

            cap = 'unknown' if token['cap'] is None else '${:,.0f}'.format(token['cap'])
            message = (f"Possible news-related Solana token\n{event['title']}\n{event['link']}\n\n"
                       f"{token['name']} ({token['symbol']})\nContract: {token['address']}\n"
                       f"Market cap: {cap} | Liquidity: ${token['liquidity']:,.0f}\n"
                       f"24h volume: ${token['volume']:,.0f} | Pool age: {token['age']:.0f} min\n"
                       f"Matched words: {', '.join(token['matched'])}\n{risk(token['address'])}\n"
                       f"Chart: {token['url']}\nNames can be copied. Verify the story and contract independently.")
            try:
                send(message)
                state['alerts'][alert_key] = now
                save_state(state)  # Minimize repeat alerts if a later operation fails.
                time.sleep(1)
            except Exception:
                LOG.warning('Alert failed; will retry on next run')
    state['events'] = {k:e for k,e in state['events'].items() if e['published'] + 3600 > now}
    state['seen'] = {k:t for k,t in state['seen'].items() if now - t < 7*86400}
    state['alerts'] = {k:t for k,t in state['alerts'].items() if now - t < 7*86400}
    save_state(state)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    scan(load_state(), time.time())
