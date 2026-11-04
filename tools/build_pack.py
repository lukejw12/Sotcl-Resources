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
