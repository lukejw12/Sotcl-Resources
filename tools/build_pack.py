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
