import urllib.request, json
data = json.loads(urllib.request.urlopen('https://pypi.org/pypi/spacy/json').read())
versions = [k for k in data['releases'].keys() if 'dev' not in k]
versions.sort(key=lambda s: [int(u) for u in s.split('.')])
for v in versions:
    if v.startswith('2.') or v.startswith('1.') or v.startswith('0.'): continue
    data_v = json.loads(urllib.request.urlopen(f'https://pypi.org/pypi/spacy/{v}/json').read())
    requires_dist = data_v['info'].get('requires_dist', [])
    if requires_dist:
        weasel_req = [r for r in requires_dist if 'weasel' in r]
        print(f"spaCy {v} requires weasel: {weasel_req}")
