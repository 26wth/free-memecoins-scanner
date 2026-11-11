"""Find early on-chain momentum using public feeds. Sends alerts only."""
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import logging
import math
import re
import time
from urllib.parse import urlsplit

import requests

LOG = logging.getLogger(__name__)
GT = 'https://api.geckoterminal.com/api/v2'
DEX = 'https://api.dexscreener.com'
GO = 'https://api.gopluslabs.io/api/v1'
# GeckoTerminal ID: (display name, DEX Screener ID, GoPlus security ID).
CHAINS = {
    'solana': ('Solana', 'solana', 'solana'),
    'robinhood': ('Robinhood', 'robinhood', '4663'),
    'hyperevm': ('HyperEVM', 'hyperevm', None),
    'base': ('Base', 'base', '8453'),
    'bsc': ('BNB Chain', 'bsc', '56'),
    'eth': ('Ethereum', 'ethereum', '1'),
    'arc': ('Arc', 'arc', '5042'),
    'megaeth': ('MegaETH', 'megaeth', None),
    'x-layer': ('X Layer', 'xlayer', '196'),
    'monad': ('Monad', 'monad', '143'),
    'polygon_pos': ('Polygon', 'polygon', '137'),
    'arbitrum': ('Arbitrum', 'arbitrum', '42161'),
    'optimism': ('Optimism', 'optimism', '10'),
    'avax': ('Avalanche', 'avalanche', '43114'),
    'sei-network': ('Sei', 'sei', None),
    'elysium': ('Elysium', 'elysium', None),
    'near': ('NEAR', 'near', None),
    'ton': ('TON', 'ton', None),
    'ink': ('Ink', 'ink', None),
}
VENUES = {
    'pump-fun': 'Pump.fun', 'pumpfun': 'Pump.fun', 'pumpswap': 'Pump.fun (PumpSwap)',
    'pump-swap': 'Pump.fun (PumpSwap)', 'stonkfun': 'Stonkfun',
    'raydium-launchlab': 'Raydium LaunchLab', 'launchlab': 'Raydium LaunchLab',
    'pons-dot-family': 'Pons', 'pons-v2': 'Pons V2', 'pons-v2-dex': 'Pons V2', 'long-xyz': 'Long.xyz',
    'noxafun': 'Noxafun', 'noxa-fun': 'Noxafun', 'four-meme': 'Four.meme',
}
VENUE_FEEDS = [
    ('solana', 'pump-fun'), ('solana', 'pumpswap'), ('solana', 'raydium-launchlab'),
    ('solana', 'stonkfun'), ('robinhood', 'pons-dot-family'),
    ('robinhood', 'pons-v2-dex'), ('robinhood', 'long-xyz'),
]
MIN_AGE = 15 * 60
MAX_WINDOW = 25 * 60
MAX_POOL_AGE = 90 * 60
MIN_LIQUIDITY = 10_000
MAX_VALUATION = 500_000
MAX_WATCH = 80
MAX_ALERTS = 2
MAX_ALERTS_PER_DAY = 5
DAY = 86400
HARD_SOL_FLAGS = ('mintable', 'freezable', 'closable', 'non_transferable',
                  'transfer_fee_upgradable', 'balance_mutable_authority')
HARD_EVM_FLAGS = (
    'is_honeypot', 'cannot_sell_all', 'is_blacklisted', 'hidden_owner',
    'is_mintable', 'owner_change_balance', 'slippage_modifiable', 'is_proxy',
)
SOCIAL_DOMAINS = {'twitter': 'x.com', 'x': 'x.com', 'telegram': 't.me',
                  'discord': 'discord.gg', 'github': 'github.com'}


def number(value, default=None):
    try:
        result = float(value)
        return result if math.isfinite(result) else default
    except (TypeError, ValueError, OverflowError):
        return default


def get(url, **params):
    response = requests.get(url, params=params, timeout=(3, 5),
                            headers={'Accept': 'application/json'})
    response.raise_for_status()
    return response.json()


def address(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-zA-Z0-9_.:-]{12,130}', value):
        return ''
    return value.lower() if re.fullmatch(r'0x[0-9a-fA-F]{40,64}', value) else value


def clean(value, limit=160):
    return ' '.join(str(value or '').split())[:limit]


def valid_link(value):
    if not isinstance(value, str) or len(value) > 1800 or any(c.isspace() for c in value):
        return ''
    try:
        parsed = urlsplit(value)
        if parsed.scheme in ('https', 'http') and parsed.hostname and not parsed.username:
            return value
    except ValueError:
        pass
    return ''


def project_links(rows):
    links = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        url = row.get('url')
        platform = str(row.get('platform', row.get('type', ''))).lower()
        handle = str(row.get('handle') or '').lstrip('@')
        if not url and platform in SOCIAL_DOMAINS and re.fullmatch(r'[a-zA-Z0-9_/-]{1,100}', handle):
            url = f'https://{SOCIAL_DOMAINS[platform]}/{handle}'
        if url := valid_link(url):
            links.append(url)
    return links


def market_links(info):
    return project_links((info.get('websites') or []) + (info.get('socials') or []))


def relation(row, name):
    return ((row.get('relationships') or {}).get(name, {}).get('data') or {}).get('id', '')


def parse_gecko(payload, path):
    tokens = {row['id']: row['attributes'] for row in payload.get('included', [])
              if row.get('type') == 'token' and 'id' in row and 'attributes' in row}
    for row in payload.get('data') or []:
        try:
            attrs = row['attributes']
            chain = next((network for network in CHAINS if row['id'].startswith(network + '_')), '')
            token_id = relation(row, 'base_token')
            token = tokens.get(token_id, {})
            mint = address(token.get('address') or token_id.removeprefix(chain + '_'))
            pool = address(attrs.get('address'))
            if chain not in CHAINS or not mint or not pool:
                continue
            title = str(attrs.get('name', '')).split(' / ', 1)[0]
            yield {
                'chain': chain, 'mint': mint, 'pool': pool,
                'name': clean(token.get('name') or title),
                'symbol': clean(token.get('symbol') or title, 48),
                'venue': relation(row, 'dex'),
                'created': datetime.fromisoformat(attrs['pool_created_at'].replace('Z', '+00:00')).timestamp(),
                'cap': number(attrs.get('market_cap_usd')),
                'fdv': number(attrs.get('fdv_usd')),
                'liquidity': number(attrs.get('reserve_in_usd'), 0),
                'price': number(attrs.get('base_token_price_usd'), 0),
                'volume': attrs.get('volume_usd') or {},
                'tx': attrs.get('transactions') or {},
                'change': attrs.get('price_change_percentage') or {},
                'url': f'https://www.geckoterminal.com/{chain}/pools/{pool}',
                'links': [], 'source': path,
            }
        except (KeyError, TypeError, ValueError, AttributeError):
            continue


def discovery(started):
    # One shared pool of candidates. Pace requests across all networks because
    # the public provider limits calls per minute for the entire runner.
    chain_ids = list(CHAINS)
    slot = int(started // 300)
    offset = slot * 7 % len(chain_ids)
    chain_ids = chain_ids[offset:] + chain_ids[:offset]
    chain_paths = [f'networks/{chain}/new_pools' for chain in chain_ids]
    venue_paths = [f'networks/{chain}/dexes/{venue}/pools' for chain, venue in VENUE_FEEDS]
    venue_offset = slot % len(venue_paths)
    venue_paths = venue_paths[venue_offset:] + venue_paths[:venue_offset]
    paths = ['networks/new_pools', 'networks/trending_pools']
    # Alternate network and venue requests, then collect every result before ranking.
    for index, path in enumerate(chain_paths):
        paths.append(path)
        if index < len(venue_paths):
            paths.append(venue_paths[index])
    rows = []
    completed = 0
    next_request = time.monotonic()
    for path in paths:
        delay = max(0, next_request - time.monotonic())
        if time.time() - started + delay >= 175:
            break
        time.sleep(delay)
        # Public limits fluctuate. A 12.5s interval avoids exceeding even
        # five calls per minute on a single runner.
        next_request = time.monotonic() + 12.5
        try:
            rows.extend(parse_gecko(get(f'{GT}/{path}', include='base_token,dex'), path))
            completed += 1
        except requests.HTTPError as error:
            status = error.response.status_code if error.response is not None else 'unknown'
            LOG.warning('Discovery %s returned HTTP %s', path, status)
            if status == 429:
                retry_after = number(error.response.headers.get('Retry-After'), 62)
                next_request = time.monotonic() + max(12.5, retry_after)
        except (requests.RequestException, ValueError, TypeError, AttributeError):
            LOG.warning('Discovery failed for %s', path)
    LOG.info('Discovery completed %s/%s feeds, %s pool rows', completed, len(paths), len(rows))
    return rows


def parse_dex(row, chain, fallback_venue=''):
    base = row.get('baseToken') or {}
    mint, pool = address(base.get('address')), address(row.get('pairAddress'))
    created = number(row.get('pairCreatedAt'), 0) / 1000
    if not mint or not pool or not created:
        return None
    venue = next((label for label in row.get('labels') or [] if label in VENUES), '')
    return {
        'chain': chain, 'mint': mint, 'pool': pool, 'created': created,
        'name': clean(base.get('name')), 'symbol': clean(base.get('symbol'), 48),
        'venue': venue or fallback_venue or str(row.get('dexId') or ''),
        'cap': number(row.get('marketCap')), 'fdv': number(row.get('fdv')),
        'liquidity': number((row.get('liquidity') or {}).get('usd'), 0),
        'price': number(row.get('priceUsd'), 0), 'volume': row.get('volume') or {},
        'tx': row.get('txns') or {}, 'change': row.get('priceChange') or {},
        'url': valid_link(row.get('url')), 'links': market_links(row.get('info') or {}),
        'source': 'DEX Screener',
    }


def key_for(coin):
    return f"{coin['chain']}:{coin['mint']}"


def recent(coin, now):
    return 0 <= now - coin['created'] <= MAX_POOL_AGE


def enrich(rows, tracked, profiles, now):
    by_key = defaultdict(list)
    by_chain = defaultdict(set)
    for coin in rows:
        by_key[key_for(coin)].append(coin)
        if recent(coin, now) and coin['liquidity'] >= MIN_LIQUIDITY / 2:
            by_chain[coin['chain']].add(coin['mint'])
    for key in tracked:
        chain, mint = key.split(':', 1)
        if chain in CHAINS and address(mint):
            by_chain[chain].add(mint)
    for chain, (_, dex_chain, _) in CHAINS.items():
        by_chain[chain].update(
            mint for source_chain, mint in profiles if source_chain == dex_chain and mint
        )
    requests_to_make = []
    for chain, mints in by_chain.items():
        # Prioritize addresses already being observed, then the most liquid discoveries.
        ordered = sorted(mints, key=lambda mint: (
            f'{chain}:{mint}' not in tracked,
            -max((c['liquidity'] for c in by_key[f'{chain}:{mint}']), default=0), mint))
        if ordered:
            requests_to_make.append((chain, ordered[:30]))

    def fetch(batch):
        chain, mints = batch
        try:
            dex_chain = CHAINS[chain][1]
            data = get(f"{DEX}/tokens/v1/{dex_chain}/{','.join(mints)}")
            return chain, data if isinstance(data, list) else []
        except (requests.RequestException, ValueError):
            LOG.warning('DEX Screener enrichment unavailable on %s', chain)
            return chain, []

    with ThreadPoolExecutor(max_workers=8) as pool:
        for chain, response in pool.map(fetch, requests_to_make):
            for row in response:
                if row.get('chainId') != CHAINS[chain][1]:
                    continue
                base = row.get('baseToken') or {}
                mint = address(base.get('address'))
                known = by_key.get(f'{chain}:{mint}', [])
                pool_id = address(row.get('pairAddress'))
                gecko = next((c for c in known if c['pool'] == pool_id), {})
                if coin := parse_dex(row, chain, gecko.get('venue', '')):
                    by_key[key_for(coin)].append(coin)
    return by_key


def num_field(coin, group, key, default=0):
    return number((coin.get(group) or {}).get(key), default)


def valuation(coin):
    cap = coin.get('cap')
    return cap if cap and cap > 0 else coin.get('fdv')


def watchable(coin, now):
    tx = (coin['tx'].get('m5') or {})
    return (
        recent(coin, now) and coin['liquidity'] >= MIN_LIQUIDITY and coin['price'] > 0
        and 0 < (valuation(coin) or 0) <= MAX_VALUATION
        and num_field(coin, 'volume', 'm5') >= 350
        and number(tx.get('buys'), 0) >= 4 and number(tx.get('sells'), 0) >= 1
        and num_field(coin, 'change', 'h1') <= 250
    )


def sample(coin, now, holders):
    tx = coin['tx'].get('m5') or {}
    return {
        't': now, 'pool': coin['pool'], 'price': coin['price'], 'liq': coin['liquidity'],
        'vol': num_field(coin, 'volume', 'm5'), 'buys': number(tx.get('buys'), 0),
        'sells': number(tx.get('sells'), 0), 'holders': holders,
    }


def momentum(samples):
    if len(samples) < 3:
        return False
    first, last = samples[0], samples[-1]
    if not MIN_AGE <= last['t'] - first['t'] <= MAX_WINDOW:
        return False
    if any(b['t'] - a['t'] > 10 * 60 for a, b in zip(samples, samples[1:])):
        return False
    if any(s['pool'] != first['pool'] or s['liq'] < 0.8 * first['liq'] for s in samples):
        return False
    peak = max(s['price'] for s in samples)
    return (
        1.03 <= last['price'] / first['price'] <= 2.5 and last['price'] >= peak * .82
        and last['vol'] >= max(800, first['vol'] * 1.15)
        and last['buys'] >= max(8, first['buys'] + 2, last['sells'] * 1.15)
        and sum(s['buys'] > s['sells'] for s in samples) >= 2
    )


def flag(data, key):
    value = data.get(key)
    if isinstance(value, dict):
        value = value.get('status')
    return None if str(value) not in ('0', '1') else str(value) == '1'


def security(coin):
    chain, mint = coin['chain'], coin['mint']
    chain_id = CHAINS[chain][2]
    if chain_id is None:
        return None
    sol = chain == 'solana'
    path = 'solana/token_security' if sol else f'token_security/{chain_id}'
    try:
        result = get(f'{GO}/{path}', contract_addresses=mint).get('result') or {}
        data = result.get(mint) or result.get(mint.lower())
        if not isinstance(data, dict) or not data:
            return None
        count = number(data.get('holder_count'))
        holders = data.get('holders') or []
        # GoPlus percentages are fractions of supply. Keep unverified wallets
        # in the total; exclude only a known pool address or standard burn sink.
        excluded = {coin['pool'], '0x000000000000000000000000000000000000dead',
                    '0x0000000000000000000000000000000000000000'}
        shares = [number(row.get('percent')) for row in holders
                  if address(row.get('address') or row.get('account') or row.get('token_account')) not in excluded]
        if (count is None and not sol) or len(holders) < 10 or not shares or any(
            share is None or not 0 <= share <= 1 for share in shares
        ):
            return None
        if sum(shares) > 1.001:
            return None
        checks = HARD_SOL_FLAGS if sol else HARD_EVM_FLAGS
        observed = {field: flag(data, field) for field in checks}
        required = ('mintable', 'freezable') if sol else ('is_honeypot', 'cannot_sell_all', 'is_mintable')
        risky = any(value is True for value in observed.values())
        if sol:
            risky |= any(flag(creator, 'malicious_address') is True
                         for creator in data.get('creator') or [])
        if not sol:
            risky |= any(number(data.get(field), 1) > .10 for field in ('buy_tax', 'sell_tax'))
        return {'count': int(count) if count is not None else None,
                'top': max(shares), 'top10': sum(shares),
                'risky': risky or any(observed[field] is None for field in required)}
    except (requests.RequestException, ValueError, AttributeError, TypeError):
        return None


def wallet_clusters(coin):
    # Bubbles is a separate free Solana provider. An incomplete map is not a pass.
    if coin['chain'] != 'solana':
        return None
    try:
        data = get(f"https://bubblemaps.dev/api/map/{coin['mint']}")
        result = data.get('summary') or data.get('map') or {}
        launch = result.get('launch') or result
        share = number(launch.get('topClusterShare'))
        holders = number(result.get('holders'))
        generated = number(result.get('generatedAt'), 0)
        if generated > 1e12:
            generated /= 1000
        if (result.get('phase') == 'deep' and result.get('partial') is not True
                and 0 <= time.time() - generated <= 30 * 60
                and share is not None and 0 <= share <= 100 and holders and holders >= 40):
            return {'share': share, 'count': int(holders)}
    except (requests.RequestException, ValueError, AttributeError):
        pass
    return None


def slug(value):
    return ''.join(re.findall(r'[a-z0-9]', value.lower()))


def leader(coin, candidates):
    labels = {slug(coin['name']), slug(coin['symbol'])} - {''}
    for other in candidates:
        if key_for(other) == key_for(coin):
            continue
        if not labels.intersection({slug(other['name']), slug(other['symbol'])}):
            continue
        if (coin['liquidity'] < 2 * other['liquidity']
                or num_field(coin, 'volume', 'm5') < 2 * num_field(other, 'volume', 'm5')):
            return False
    return bool(labels)


def search_lookalikes(coin):
    by_dex_chain = {details[1]: chain for chain, details in CHAINS.items()}
    try:
        result = get(f'{DEX}/latest/dex/search', q=coin['name'])
        for row in result.get('pairs') or []:
            chain = by_dex_chain.get(row.get('chainId'))
            if chain and (match := parse_dex(row, chain)):
                yield match
    except (requests.RequestException, ValueError, AttributeError, TypeError):
        # Do not treat a failed comparison as evidence that there are no copies.
        raise RuntimeError('Copy comparison unavailable') from None


def current_news(fetch_news, now):
    try:
        return list(fetch_news(now))
    except Exception:
        LOG.warning('Headline sources unavailable')
        return []


def related_news(coin, news):
    # Require the whole coin name in an independent headline. Names alone are
    # still not proof of a connection, so the alert calls this a possible match.
    parts = re.findall(r'[a-z0-9]+', coin['name'].lower())
    if len(parts) < 2 or sum(map(len, parts)) < 8:
        return None
    phrase = ' '.join(parts)
    for item in news:
        title = ' '.join(re.findall(r'[a-z0-9]+', item['title'].lower()))
        if f' {phrase} ' in f' {title} ' and valid_link(item['link']):
            return item
    return None


def launchpad(coin, pools):
    if coin['chain'] == 'solana' and coin['mint'].endswith('pump'):
        if any(VENUES.get(row['venue'], '').startswith('Pump.fun') for row in pools):
            return 'Pump.fun'
    venues = sorted(pools, key=lambda row: row['created'])
    return next((VENUES[row['venue']] for row in venues if row['venue'] in VENUES), 'Unknown')


def metadata(coin, pools, profile):
    links = [url for row in pools for url in row['links']]
    links.extend(project_links(profile.get('links') or []))
    description = clean(profile.get('description'), 280)
    # GeckoTerminal token info lists websites and platform handles in addition
    # to pair metadata. Read metadata only for candidates that pass the checks.
    try:
        data = get(f"{GT}/networks/{coin['chain']}/tokens/{coin['mint']}/info")
        info = (data.get('data') or {}).get('attributes') or {}
        links.extend(url for url in map(valid_link, info.get('websites') or []) if url)
        socials = [
            {'platform': name, 'handle': info.get(field)}
            for name, field in [('twitter', 'twitter_handle'), ('telegram', 'telegram_handle'),
                                ('discord', 'discord_url')]
            if info.get(field)
        ]
        for row in socials:
            if valid_link(row['handle']):
                row['url'] = row['handle']
        links.extend(project_links(socials))
        description = description or clean(info.get('description'), 280)
    except (requests.RequestException, ValueError, AttributeError, TypeError):
        pass
    return list(dict.fromkeys(links)), description


def cash(value):
    return f'${value:,.0f}' if value is not None and value >= 0 else 'Unavailable'


def alert_message(coin, pools, samples, risk, cluster, story, links, description):
    minutes = (samples[-1]['t'] - samples[0]['t']) / 60
    tx = samples[-1]
    narrative = ('Possible headline match: ' + clean(story['title'], 280) if story else
                 'Project description: ' + description if description else 'No clear narrative')
    mcap = cash(coin['cap']) if coin['cap'] and coin['cap'] > 0 else 'Unavailable'
    if mcap == 'Unavailable' and coin['fdv'] and coin['fdv'] > 0:
        mcap += f" (FDV {cash(coin['fdv'])})"
    report = [
        f"Early momentum watch | {coin['name']} ({coin['symbol']})",
        f'Narrative: {narrative}',
        f"Network: {CHAINS[coin['chain']][0]} | Launchpad: {launchpad(coin, pools)}",
        f"Contract: {coin['mint']}",
        f"Market cap: {mcap} | Pool liquidity: {cash(coin['liquidity'])}",
        f"Volume: {cash(num_field(coin, 'volume', 'm5'))} (5m), "
        f"{cash(num_field(coin, 'volume', 'h1', None))} (1h)",
        f"Observed {minutes:.0f} min | {int(tx['buys'])} buys / {int(tx['sells'])} sells (5m)",
        f"Holders: {risk['count']:,} | Top tracked wallets: {risk['top10']:.1%} combined",
        f"Wallet map: {'Bubbles largest linked cluster ' + format(cluster, '.1f') + '%' if cluster is not None else 'unavailable on this network'}",
        f"Chart: {coin['url'] or 'https://www.geckoterminal.com/' + coin['chain'] + '/pools/' + coin['pool']}",
    ]
    if story:
        report.append(f"Headline source: {story['link']}")
    if links:
        report.append('Project links (as listed):')
        report.extend(link for link in links if not story or link != story['link'])
    return report


def send_report(lines, send):
    # Keep URLs whole while fitting Telegram's message size limit.
    parts = []
    text = ''
    for line in lines:
        if len((text + '\n' + line).encode('utf-16-le')) // 2 > 3900:
            parts.append(text)
            text = lines[0] + ' | links continued'
        text = text + '\n' + line if text else line
    if text:
        parts.append(text)
    for part in parts:
        send(part)


def run(state, fetch_news, save_state, send):
    started = time.time()
    tracked = state.setdefault('runner_watch', {})
    sent = state.setdefault('runner_alerts', {})
    sent = {key: timestamp for key, timestamp in sent.items() if started - timestamp < 30 * DAY}
    state['runner_alerts'] = sent
    # Import the old alert keys so a token previously sent by the news scanner
    # will not be sent again merely because the implementation changed.
    for old_key, timestamp in state.get('alerts', {}).items():
        mint = address(old_key.rsplit(':', 1)[-1])
        if mint and started - timestamp < 30 * DAY:
            sent.setdefault(f'solana:{mint}', timestamp)
    tracked = {key: obs for key, obs in tracked.items()
               if obs and started - obs[-1]['t'] <= MAX_WINDOW and key not in sent}
    with ThreadPoolExecutor(max_workers=2) as executor:
        news_future = executor.submit(current_news, fetch_news, started)
        rows = discovery(started)
        headlines = news_future.result()
    saved_news = state.get('runner_news', {})
    for item in headlines:
        if valid_link(item['link']):
            saved_news[item['link']] = item
    news = sorted(
        (item for item in saved_news.values() if started - item['published'] < 2 * 3600),
        key=lambda item: -item['published'],
    )[:160]
    state['runner_news'] = {item['link']: item for item in news}
    try:
        raw_profiles = get(f'{DEX}/token-profiles/latest/v1')
        profiles = {(row.get('chainId'), address(row.get('tokenAddress'))): row
                    for row in raw_profiles if isinstance(row, dict)}
    except (requests.RequestException, ValueError, TypeError):
        profiles = {}
    by_key = enrich(rows, tracked, profiles, time.time())
    now = time.time()
    leaders = [max(pools, key=lambda coin: coin['liquidity']) for pools in by_key.values() if pools]
    eligible = []
    for key, pools in by_key.items():
        if key in sent:
            continue
        previous = tracked.get(key, [])
        young = [coin for coin in pools if watchable(coin, now)]
        if not young:
            tracked.pop(key, None)
            continue
        # One older, liquid pool for the same address is evidence this may be a
        # relisting rather than an early launch.
        if any(now - coin['created'] > MAX_POOL_AGE and coin['liquidity'] >= MIN_LIQUIDITY for coin in pools):
            tracked.pop(key, None)
            continue
        same_pool = [coin for coin in young if previous and coin['pool'] == previous[-1]['pool']]
        coin = max(same_pool or young, key=lambda c: (c['liquidity'], c['source'] == 'DEX Screener'))
        if previous and (coin['pool'] != previous[-1]['pool'] or now - previous[0]['t'] > MAX_WINDOW
                         or now - previous[-1]['t'] > 10 * 60):
            previous = []
        if previous and now - previous[-1]['t'] < 180:
            continue  # A manual rerun does not create a fresh five-minute sample.
        eligible.append((coin, previous))
    eligible.sort(key=lambda item: (
        not bool(item[1]), -num_field(item[0], 'volume', 'm5'), -item[0]['liquidity']))
    # Bound risk queries. Existing watches get checked first, then fresh movers
    # compete in one ranking across chains and launchpads.
    selected = [(coin, previous) for coin, previous in eligible if CHAINS[coin['chain']][2]][:16]
    alerts = 0
    risk_rejections = defaultdict(int)
    remaining = min(MAX_ALERTS, max(0, MAX_ALERTS_PER_DAY - sum(
        started - timestamp < DAY for timestamp in sent.values()
    )))
    map_calls = 0
    last_map_call = 0
    with ThreadPoolExecutor(max_workers=8) as executor:
        for (coin, previous), risk in zip(selected, executor.map(security, (c for c, _ in selected))):
            key = key_for(coin)
            sol = coin['chain'] == 'solana'
            if (risk is None or risk['risky'] or (risk['count'] is not None and risk['count'] < 40)
                    or risk['top'] > (.12 if sol else .08)
                    or risk['top10'] > (.45 if sol else .35)):
                reason = 'missing holder data' if risk is None else 'risk flags or holder thresholds'
                risk_rejections[reason] += 1
                tracked.pop(key, None)
                continue
            samples = previous + [sample(coin, now, risk['count'])]
            tracked[key] = samples
            if alerts >= remaining or not previous or time.time() - started >= 215:
                continue
            moving = momentum(samples)
            if not leader(coin, leaders):
                continue
            cluster = None
            if sol:
                # Start preparing maps before the minimum observation time.
                if map_calls >= 3 or (not moving and now - samples[0]['t'] < 8 * 60):
                    continue
                time.sleep(max(0, 1.1 - (time.monotonic() - last_map_call)))
                last_map_call = time.monotonic()
                map_calls += 1
                wallet_map = wallet_clusters(coin)
                if wallet_map is None or wallet_map['share'] > 25:
                    continue
                cluster = wallet_map['share']
                risk['count'] = wallet_map['count']
                samples[-1]['holders'] = wallet_map['count']
            holder_samples = [item['holders'] for item in samples if item['holders'] is not None]
            if not moving or (len(holder_samples) >= 2 and holder_samples[-1] < holder_samples[0]):
                continue
            try:
                if not leader(coin, search_lookalikes(coin)):
                    continue
            except RuntimeError:
                LOG.warning('Copy comparison unavailable; holding alert')
                continue
            pools = by_key[key]
            profile = profiles.get((CHAINS[coin['chain']][1], coin['mint']), {})
            links, description = metadata(coin, pools, profile)
            story = related_news(coin, news)
            try:
                send_report(alert_message(coin, pools, samples, risk, cluster, story, links, description), send)
            except Exception:
                LOG.warning('Telegram delivery failed; no alert recorded')
                continue
            sent[key] = now
            tracked.pop(key, None)
            state['runner_watch'] = tracked
            save_state(state)
            alerts += 1
    state['runner_watch'] = dict(sorted(tracked.items(), key=lambda item: -item[1][-1]['t'])[:MAX_WATCH])
    save_state(state)
    LOG.info('Pools: %s | watchable: %s | watched: %s | alerts sent: %s',
             len(by_key), len(eligible), len(state['runner_watch']), alerts)
    LOG.info('Risk checks attempted: %s | withheld: %s', len(selected), dict(risk_rejections))
