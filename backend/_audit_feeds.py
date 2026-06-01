from main import app
from fastapi.testclient import TestClient
client = TestClient(app)

for ep in ['/api/spaceweather', '/api/geopolitics', '/api/markets', '/api/nodes', '/api/military']:
    r = client.get(ep)
    d = r.json()
    print(f'=== {ep} ===')
    print(f'Keys: {list(d.keys())}')
    if isinstance(d, dict) and 'data' in d:
        print(f'Data count: {len(d["data"])}')
        if d['data']:
            print(f'First item keys: {list(d["data"][0].keys())}')
    elif isinstance(d, dict):
        for k, v in d.items():
            t = type(v).__name__
            if isinstance(v, list):
                print(f'  {k}: list[{len(v)}]')
                if v and len(v) < 5:
                    print(f'    {v[0]}')
            elif isinstance(v, dict):
                print(f'  {k}: dict with keys {list(v.keys())}')
            else:
                print(f'  {k}: {t} = {str(v)[:80]}')
    print()
