import urllib.request, json
data = json.loads(urllib.request.urlopen('https://pypi.org/pypi/spacy/json').read())
versions = [k for k in data['releases'].keys() if k.startswith('3.8')]
print("spaCy 3.8.x versions:", versions)
for v in reversed(versions):
    data_v = json.loads(urllib.request.urlopen(f'https://pypi.org/pypi/spacy/{v}/json').read())
    requires_dist = data_v['info'].get('requires_dist', [])
    if requires_dist:
        weasel_req = [r for r in requires_dist if 'weasel' in r]
        print(f"spaCy {v} requires weasel: {weasel_req}")
