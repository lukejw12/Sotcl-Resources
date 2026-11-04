"""Runs ia_block_porter without its window, then checks the result."""
import argparse, glob, importlib.util, json, os, re, sys, types, zipfile

ap = argparse.ArgumentParser()
ap.add_argument('--work', required=True)
ap.add_argument('--gen', required=True)
ap.add_argument('--me', default=None)
ap.add_argument('--out', required=True)
a = ap.parse_args()

here = os.path.dirname(os.path.abspath(__file__))
porters = glob.glob(os.path.join(here, 'ia_block_porter*.py'))
if not porters:
    sys.exit('Put your ia_block_porter_vNN.py in the tools folder.')
def ver(p):
    m = re.search(r'v(\d+)', os.path.basename(p))
    return int(m.group(1)) if m else 0
porter = max(porters, key=ver)
print('Using', os.path.basename(porter))

try:
    import tkinter  # noqa: F401
except Exception:
    for name in ('tkinter', 'tkinter.ttk', 'tkinter.filedialog', 'tkinter.messagebox', 'tkinter.scrolledtext', 'tkinter.font'):
        sys.modules[name] = types.ModuleType(name)

spec = importlib.util.spec_from_file_location('porter', porter)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
if not hasattr(mod, 'run_merge'):
    sys.exit('run_merge() not found in ' + os.path.basename(porter))

def log(*parts):
    print(*parts, flush=True)

mod.run_merge(a.work, a.gen, a.me, a.out, log)

if not os.path.exists(a.out):
    sys.exit('The porter did not write ' + a.out)

# Texture edits from Pack Studio: files in overrides/ replace or add pack files,
# and overrides/delete.json lists pack files to drop.
over = os.path.join(os.path.dirname(here), 'overrides')
if os.path.isdir(over):
    adds = {}
    for dirpath, _, files in os.walk(over):
        for f in files:
            full = os.path.join(dirpath, f)
            rel = os.path.relpath(full, over).replace(os.sep, '/')
            if rel.startswith('assets/'):
                adds[rel] = full
    drops = set()
    dj = os.path.join(over, 'delete.json')
    if os.path.exists(dj):
        try:
            drops = set(json.load(open(dj)))
        except Exception as e:
            print('overrides/delete.json is not valid JSON, ignoring it:', e)
    if adds or drops:
        tmp = a.out + '.tmp'
        with zipfile.ZipFile(a.out) as zin, zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                if item.filename in adds or item.filename in drops:
                    continue
                zout.writestr(item, zin.read(item.filename))
            for rel, full in sorted(adds.items()):
                if rel not in drops:
                    zout.write(full, rel)
        os.replace(tmp, a.out)
        print('Applied overrides: %d file(s) replaced or added, %d removed' % (len([r for r in adds if r not in drops]), len(drops)))

size = os.path.getsize(a.out)
print('Output size: %.1f MB' % (size / 1048576))
if size > 99 * 1048576:
    sys.exit('The pack is over GitHub\'s 100 MB file limit.')
# Blocks removed in Pack Studio: drop what's left of them in the pack (ItemsAdder
# blockstate variants, creative menu and item model entries, then unused models).
# Anything the fresh generated pack still refers to is never touched.
CARRIERS = ['note_block', 'brown_mushroom_block', 'red_mushroom_block', 'mushroom_stem', 'tripwire', 'chorus_plant', 'farmland']
REF = re.compile(r'"(?:model|parent)"\s*:\s*"([^"]+)"')
def norm(ref):
    return ref if ':' in ref else 'minecraft:' + ref
rmj = os.path.join(over, 'remove_models.json')
if os.path.exists(rmj):
    try:
        gone = set(json.load(open(rmj)))
    except Exception as e:
        gone = set()
        print('overrides/remove_models.json is not valid JSON, ignoring it:', e)
    if gone:
        live = set()
        with zipfile.ZipFile(a.gen) as g:
            for n in g.namelist():
                if n.endswith('.json'):
                    live.update(norm(r) for r in REF.findall(g.read(n).decode('utf-8', 'ignore')))
        gone = {m for m in gone if norm(m) not in live}
    if gone:
        with zipfile.ZipFile(a.out) as zin:
            files = {i.filename: zin.read(i.filename) for i in zin.infolist()}
        def refs(o):
            out = set()
            if isinstance(o, dict):
                for k, v in o.items():
                    if k in ('model', 'parent') and isinstance(v, str):
                        out.add(norm(v))
                    else:
                        out |= refs(v)
            elif isinstance(o, list):
                for v in o:
                    out |= refs(v)
            return out
        def prune(o):
            n = 0
            if isinstance(o, dict):
                for v in o.values():
                    n += prune(v)
            elif isinstance(o, list):
                keep = []
                for v in o:
                    if isinstance(v, dict) and ('threshold' in v or 'when' in v) and refs(v) and refs(v) <= gone:
                        n += 1
                        continue
                    n += prune(v)
                    keep.append(v)
                o[:] = keep
            return n
        states = entries = 0
        for n in list(files):
            m = re.match(r'^assets/minecraft/blockstates/([a-z_]+)\.json$', n)
            if m and m.group(1) in CARRIERS:
                try:
                    bs = json.loads(files[n])
                except Exception:
                    continue
                vs = bs.get('variants') or {}
                keep = {k: v for k, v in vs.items() if not (refs(v) and refs(v) <= gone)}
                if len(keep) != len(vs):
                    states += len(vs) - len(keep)
                    bs['variants'] = keep
                    files[n] = json.dumps(bs, indent=2).encode()
            elif re.match(r'^(?:[^/]+/)?assets/minecraft/items/[a-z_]+\.json$', n):
                try:
                    d = json.loads(files[n])
                except Exception:
                    continue
                c = prune(d)
                if c:
                    entries += c
                    files[n] = json.dumps(d, indent=2).encode()
        used = set()
        for n, data in files.items():
            if n.endswith('.json') and ('/blockstates/' in n or '/models/' in n or '/items/' in n):
                used.update(norm(r) for r in REF.findall(data.decode('utf-8', 'ignore')))
        models = 0
        for ref in sorted(gone):
            ns, path = ref.split(':', 1)
            mk = 'assets/%s/models/%s.json' % (ns, path)
            if mk in files and ref not in used:
                del files[mk]
                models += 1
        if states or entries or models:
            tmp = a.out + '.tmp'
            with zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED) as zout:
                for n, data in files.items():
                    zout.writestr(n, data)
            os.replace(tmp, a.out)
        print('Removed blocks: %d blockstate variant(s), %d item/creative entr(ies), %d model(s) dropped' % (states, entries, models))

z = zipfile.ZipFile(a.out)
names = z.namelist()
if 'pack.mcmeta' not in names:
    sys.exit('pack.mcmeta is missing from the output.')
json.loads(z.read('pack.mcmeta'))
bad = []
for n in names:
    if n.endswith('.json'):
        try:
            json.loads(z.read(n).decode('utf-8-sig'))
        except Exception:
            bad.append(n)
known = [b for b in bad if b.endswith('dnt/lang/ko_kr.json')]
others = [b for b in bad if b not in known]
print('%d files, %d invalid JSON (%d known)' % (len(names), len(bad), len(known)))
if others:
    print('Invalid JSON:', *others[:20], sep='\n  ')
    if len(others) > 5:
        sys.exit('Too many invalid JSON files, not publishing.')
