import urllib.request, json
r = urllib.request.urlopen('http://127.0.0.1:8002/api/health', timeout=30)
d = json.loads(r.read())
feeds = d.get('feeds', {})
fresh = stale = warn = error = 0
if isinstance(feeds, dict):
    for name, info in feeds.items():
        status = info.get('status', '?')
        if status == 'fresh': fresh += 1
        elif status == 'stale': stale += 1
        elif status == 'warn': warn += 1
        elif status == 'error': error += 1
        ts = info.get('last_fetch', info.get('updated', '?'))
        print(f'{name}: {status} last={ts}')
print(f'\nSummary: {fresh} fresh, {stale} stale, {warn} warn, {error} error, {len(feeds)} total')
fa = d.get('feed_autopilot', d.get('autopilot', 'not in response'))
print(f'Feed autopilot: {fa}')
