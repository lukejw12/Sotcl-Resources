import json, os, sys, copy, zipfile, io, shutil, tempfile, struct, zlib


PILLAR_MATCH_ENDS = True

TARGET_PACK_FORMAT = 97
TARGET_SUPPORTED_FORMATS = {"min_inclusive": 46, "max_inclusive": 9999}

CROSS_MODEL_IDS = set()

PILLAR_SIDE_MODE = "custom"
PILLAR_FACES = {
    "x": {"up": (90, "H"), "down": (90, "H"), "north": (90, "H"), "south": (90, "H")},
    "z": {"up": (0, None), "down": (0, None), "west": (90, "H"), "east": (90, "H")},
}

PILLAR_DEBUG = False
import tkinter as tk
from tkinter import scrolledtext, filedialog

T = {
    "bg":  "#0c0c14",  "bg2": "#111119",  "sf":  "#181824",  "sf2": "#1e1e2c",
    "sf3": "#262638",  "bd":  "#2a2a42",  "bd2": "#3a3a54",
    "tx":  "#e0e0f0",  "sub": "#8888a8",  "mt":  "#505068",
    "ac":  "#b07af0",  "ac2": "#9460d8",  "bl":  "#5a9cf8",  "gn":  "#46d87a",
    "rd":  "#f06868",  "og":  "#f89838",  "yl":  "#f0b830",  "tl":  "#30c8b0",
}

BLOCKSTATE_FILES = [
    "assets/minecraft/blockstates/brown_mushroom_block.json",
    "assets/minecraft/blockstates/red_mushroom_block.json",
    "assets/minecraft/blockstates/mushroom_stem.json",
    "assets/minecraft/blockstates/note_block.json",
    "assets/minecraft/blockstates/chorus_plant.json",
    "assets/minecraft/blockstates/tripwire.json",
    "assets/minecraft/blockstates/farmland.json",
]

DEFAULT_MODELS = {
    "minecraft:block/note_block", "block/note_block",
    "minecraft:block/brown_mushroom_block", "block/original/brown_mushroom_block",
    "minecraft:block/red_mushroom_block", "block/original/red_mushroom_block",
    "minecraft:block/mushroom_stem", "block/original/mushroom_stem",
    "minecraft:block/chorus_plant", "block/original/chorus_plant",
    "minecraft:block/blackstone",
}

# Format ranges ItemsAdder itself gives its overlays (taken from a clean ItemsAdder 26.3 pack). Used to register an
# ia_overlay_* folder that has files but is missing from pack.mcmeta, e.g. when a custom pack.mcmeta replaced
# ItemsAdder's own overlay list.
KNOWN_IA_OVERLAYS = {
    "ia_overlay_1_20_5_plus": (32, 9999),
    "ia_overlay_1_21_2_plus": (42, 9999),
    "ia_overlay_1_21_4_to_5": (46, 55),
    "ia_overlay_1_21_4_plus": (46, 9999),
    "ia_overlay_1_21_5": (55, 55),
    "ia_overlay_1_21_6_to_11": (63, 75),
    "ia_overlay_1_21_6_plus": (63, 9999),
    "ia_overlay_26_1_plus": (84, 9999),
    "ia_overlay_modern_atlas": (75, 9999),
    "ia_overlay_legacy_atlas": (1, 69),
}

PAPER_OVERLAYS = [
    "ia_overlay_1_21_6_plus/assets/minecraft/items/paper.json",
    "ia_overlay_1_21_4_to_5/assets/minecraft/items/paper.json",
    "ia_overlay_1_21_6_to_11/assets/minecraft/items/paper.json",
]

def _load_json_from_zip(zf, path):
    try:
        return json.loads(zf.read(path))
    except (KeyError, json.JSONDecodeError):
        return None

def _is_jank_path(path):
    parts = path.split("/")
    return len(parts) > 4 and parts[0] == "assets" and parts[2] in ("items", "models") and parts[3] == "jank"


def _merge_jank(merged, gen_files, changes, log):
    """IACopperBlockInjector 1.7.0 Jank blocks: baked models in assets/<ns>/models/jank/<id>/ and the item
    definitions their displays use in assets/<ns>/items/jank/<id>/. Copy them over, bring in the textures the
    models use, and drop files of Jank blocks that are gone (the plugin wipes each block's folders too)."""
    log("\n═══ JANK BLOCKS (IACopperBlockInjector) ═══", "header")
    gen_jank = {p: d for p, d in gen_files.items() if _is_jank_path(p)}
    fixed_refs = 0
    for path in list(gen_jank):
        if "/models/" not in path:
            continue
        try:
            model = json.loads(gen_jank[path].decode("utf-8-sig") if isinstance(gen_jank[path], bytes) else gen_jank[path])
        except Exception:
            continue
        texs = model.get("textures") or {}
        changed = False
        for key, ref in list(texs.items()):
            sprite = ref.get("sprite") if isinstance(ref, dict) else ref
            if not isinstance(sprite, str) or not sprite.startswith("_") or ":" not in sprite:
                continue
            bad = _resource_to_tex_path(sprite)
            good = _resource_to_tex_path(sprite[1:])
            if bad in gen_files or bad in merged:
                continue
            if good in gen_files or good in merged:
                if isinstance(ref, dict):
                    ref["sprite"] = sprite[1:]
                else:
                    texs[key] = sprite[1:]
                changed = True
                fixed_refs += 1
        if changed:
            gen_jank[path] = json.dumps(model, indent=2).encode("utf-8")
    if fixed_refs:
        log(f"  Fixed {fixed_refs} texture reference(s) written as _<namespace>:... (the namespace had no such texture)", "warn")
    copied = 0
    for path, data in gen_jank.items():
        if merged.get(path) != data:
            merged[path] = data
            copied += 1
    textures = 0
    for path, data in gen_jank.items():
        if "/models/" not in path:
            continue
        try:
            model = json.loads(data.decode("utf-8-sig") if isinstance(data, bytes) else data)
        except Exception:
            continue
        for ref in (model.get("textures") or {}).values():
            if isinstance(ref, dict):
                ref = ref.get("sprite", "")
            if not isinstance(ref, str) or not ref or ref.startswith("#"):
                continue
            tex = _resource_to_tex_path(ref)
            for p in (tex, tex + ".mcmeta"):
                if p in gen_files and p not in merged:
                    merged[p] = gen_files[p]
                    if p == tex:
                        changes["textures"].append(p)
                        textures += 1
    stale = [p for p in merged if _is_jank_path(p) and p not in gen_jank]
    for p in stale:
        del merged[p]
        changes["removed"].append(p)
    blocks = {p.split("/jank/", 1)[1].split("/", 1)[0] for p in gen_jank}
    if gen_jank or stale:
        log(f"  {len(blocks)} Jank block(s): {copied} file(s) copied or refreshed, {textures} texture(s) added, "
            f"{len(stale)} stale file(s) removed", "ok")
    else:
        log("  No Jank blocks in the generated pack", "sub")


def _resource_to_tex_path(resource):
    if ":" in resource:
        ns, path = resource.split(":", 1)
    else:
        ns, path = "minecraft", resource
    return f"assets/{ns}/textures/{path}.png"

def _model_ref_to_path(ref):
    if ":" in ref:
        ns, path = ref.split(":", 1)
    else:
        ns, path = "minecraft", ref
    return f"assets/{ns}/models/{path}.json"

# ----------------------------------------------------------------------
# v14: ModelEngine merge settings
# ----------------------------------------------------------------------
ME_NAMESPACE_PREFIX = "assets/modelengine/"
ME_OVERLAY_PREFIX = "modelengine_"
# items whose custom_model_data entries ModelEngine owns (merged by threshold / predicate, not replaced)
ME_ITEM_DEFS = ["assets/minecraft/items/leather_horse_armor.json"]
ME_LEGACY_ITEM_MODELS = ["assets/minecraft/models/item/leather_horse_armor.json"]


def _read_pack(path):
    """Read a resource pack from a .zip or an unzipped folder into {relative_path: bytes}."""
    files = {}
    if os.path.isdir(path):
        for dirpath, _dirs, names in os.walk(path):
            for n in names:
                full = os.path.join(dirpath, n)
                rel = os.path.relpath(full, path).replace(os.sep, "/")
                with open(full, "rb") as f:
                    files[rel] = f.read()
    else:
        files = _read_zip_lenient(path)
    # packs zipped as a single top folder (e.g. "resource pack/pack.mcmeta") -> strip that folder
    if files and "pack.mcmeta" not in files:
        tops = {p.split("/", 1)[0] for p in files}
        if len(tops) == 1:
            top = next(iter(tops)) + "/"
            if top + "pack.mcmeta" in files:
                files = {p[len(top):]: d for p, d in files.items() if p.startswith(top)}
    return files


def _read_zip_lenient(path):
    """Read every entry by its central-directory name, like Minecraft does. ItemsAdder's pack protection writes local
    headers whose names don't match the central directory, which zipfile refuses; those entries are read raw instead."""
    files = {}
    with open(path, "rb") as fh:
        zf = zipfile.ZipFile(fh)
        for info in zf.infolist():
            name = info.filename
            if name.endswith("/"):
                continue
            try:
                files[name] = zf.read(info)
                continue
            except Exception:
                pass
            try:
                fh.seek(info.header_offset)
                hdr = fh.read(30)
                if len(hdr) < 30 or hdr[:4] != b"PK\x03\x04":
                    continue
                n, m = struct.unpack("<HH", hdr[26:30])
                fh.seek(info.header_offset + 30 + n + m)
                raw = fh.read(info.compress_size)
                if info.compress_type == zipfile.ZIP_STORED:
                    files[name] = raw
                elif info.compress_type == zipfile.ZIP_DEFLATED:
                    files[name] = zlib.decompress(raw, -15)
            except Exception:
                continue
    return files


def _is_shader_path(path):
    return "/shaders/" in path or path.startswith("shaders/")


def _normalise_pack_format(merged, log):
    """Set the merged pack to a 26.3-era pack_format with a wide supported_formats range.

    The working pack is often still on a 1.21.x pack_format (e.g. 75) with an old supported_formats
    (e.g. [32, 64]); on 26.3 the client would drop it as incompatible. We keep every overlay and asset
    untouched and only rewrite the top-level pack version fields."""
    log("\n═══ PACK FORMAT (26.3) ═══", "header")
    raw = merged.get("pack.mcmeta")
    meta = None
    if raw:
        try:
            meta = json.loads(raw)
        except (ValueError, TypeError):
            meta = None
    if not isinstance(meta, dict):
        meta = {"pack": {"description": "Merged pack"}}
    pack = meta.setdefault("pack", {})
    old_fmt = pack.get("pack_format")
    old_sup = pack.get("supported_formats")
    lo = TARGET_SUPPORTED_FORMATS["min_inclusive"]
    hi = TARGET_SUPPORTED_FORMATS["max_inclusive"]
    pack["pack_format"] = TARGET_PACK_FORMAT
    pack["supported_formats"] = dict(TARGET_SUPPORTED_FORMATS)
    # 26.3 rejects packs above format 64 unless min_format and max_format are present as top-level ints
    pack["min_format"] = lo
    pack["max_format"] = hi
    merged["pack.mcmeta"] = json.dumps(meta, indent=2).encode()
    log(f"  pack_format {old_fmt} -> {TARGET_PACK_FORMAT}", "ok")
    log(f"  supported_formats {old_sup} -> [{TARGET_SUPPORTED_FORMATS['min_inclusive']}, {TARGET_SUPPORTED_FORMATS['max_inclusive']}]", "ok")


def run_merge(work_path, gen_path, me_path, out_path, log, me_shaders=False):
    """Main merge. gen_path (ItemsAdder) and me_path (ModelEngine) are each optional, but at least one is needed.
    log(msg, tag) writes to the UI. Returns the number of changes, or None on a fatal error."""
    log("Reading working pack...", "info")
    work_files = _read_pack(work_path)
    log(f"  {len(work_files)} files", "sub")

    merged = dict(work_files)
    changes = {"atlas": [], "models": [], "textures": [], "blockstates": [],
               "paper": [], "painting": [], "other": [], "modelengine": [], "removed": []}
    next_ia = None

    if gen_path:
        log("\n████ ITEMSADDER ████", "header")
        next_ia = _merge_itemsadder(work_files, merged, gen_path, changes, log)
        if next_ia is None:
            log("\nItemsAdder merge failed — nothing written.", "err")
            return None
    else:
        log("\n(ItemsAdder skipped — no generated pack given)", "sub")

    if me_path:
        log("\n████ MODELENGINE ████", "header")
        if not _merge_modelengine(merged, me_path, changes, log, me_shaders):
            log("\nModelEngine merge failed — nothing written.", "err")
            return None
    else:
        log("\n(ModelEngine skipped — no ModelEngine pack given)", "sub")

    # v17: normalise pack.mcmeta so Minecraft 26.3 accepts the merged pack
    _normalise_pack_format(merged, log)

    log(f"\n═══ WRITING OUTPUT ═══", "header")
    log(f"  {out_path}", "info")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zout:
        for path in sorted(merged.keys()):
            zout.writestr(path, merged[path])
    with open(out_path, "wb") as f:
        f.write(buf.getvalue())

    total = sum(len(v) for v in changes.values())
    log(f"\n{'═' * 50}", "header")
    log("  DONE!", "ok")
    if gen_path:
        log(f"  Atlas entries added:    {len(changes['atlas'])}", "info")
        log(f"  Models written:         {len(changes['models'])}", "info")
        log(f"  Textures copied:        {len(changes['textures'])}", "info")
        log(f"  Blockstates updated:    {len(changes['blockstates'])}", "info")
        log(f"  Paper entries added:    {len(changes['paper'])}", "info")
        log(f"  Painting entries added: {len(changes['painting'])}", "info")
        log(f"  Other files:            {len(changes['other'])}", "info")
        log(f"  Stale files removed:    {len(changes['removed'])}", "info")
        log(f"  Next available ia:    ia:{next_ia}", "info")
    if me_path:
        log(f"  ModelEngine changes:    {len(changes['modelengine'])}", "info")
    log(f"  Total files in pack:  {len(merged)}", "sub")
    if total == 0:
        log("\n  Nothing new to merge — packs are already in sync!", "warn")
    log(f"{'═' * 50}", "header")
    return total


def _merge_itemsadder(work_files, merged, gen_path, changes, log):
    """Ports new blocks/items from the IA-generated pack into `merged` (in place). Returns next free ia:N, or None on error."""
    log("Reading generated pack...", "info")
    gen_files = _read_pack(gen_path)
    log(f"  {len(gen_files)} files", "sub")
    _unnest_raw_files(gen_files, log)


    log("\n═══ BLOCKS ATLAS ═══", "header")

    work_atlas_path = "assets/minecraft/atlases/blocks.json"
    gen_atlas_path = None
    for p in ["assets/minecraft/atlases/blocks.json",
              "ia_overlay_modern_atlas/assets/minecraft/atlases/blocks.json"]:
        if p in gen_files:
            gen_atlas_path = p
            break

    if work_atlas_path not in work_files:
        log("  ERROR: No blocks atlas in working pack!", "err")
        return None
    if not gen_atlas_path:
        log("  ERROR: No blocks atlas in generated pack!", "err")
        return None

    work_atlas = json.loads(work_files[work_atlas_path])
    gen_atlas = json.loads(gen_files[gen_atlas_path])

    existing_resources = set()
    max_ia = 0
    for entry in work_atlas.get("sources", []):
        if entry.get("type") == "single":
            existing_resources.add(entry["resource"])
            sprite = entry.get("sprite", entry["resource"])
            if sprite.startswith("ia:"):
                try:
                    max_ia = max(max_ia, int(sprite.split(":")[1]))
                except ValueError:
                    pass

    next_ia = max_ia + 1
    log(f"  Working atlas: {len(existing_resources)} resources, max ia:{max_ia}", "sub")

    gen_sprite_to_resource = {}
    for entry in gen_atlas.get("sources", []):
        if entry.get("type") == "single":
            sprite = entry.get("sprite", entry["resource"])
            resource = entry["resource"]
            if not resource.startswith("ia:"):
                gen_sprite_to_resource[sprite] = resource

    log("\n═══ BLOCKSTATES ═══", "header")

    new_block_models = {}  # model_ref -> needs processing
    cross_placed_refs = {}  # model_ref -> model_ref_placed (plants: blockstates must use the cross model)
    wire_model_ids = set()  # model ids referenced by the tripwire blockstate = plants

    for bs_rel in BLOCKSTATE_FILES:
        if bs_rel not in gen_files:
            continue
        gen_bs = json.loads(gen_files[bs_rel])
        work_bs = json.loads(work_files[bs_rel]) if bs_rel in work_files else None

        gen_variants = gen_bs.get("variants", {})
        work_variants = work_bs.get("variants", {}) if work_bs else {}

        new_variants = {}
        for state, vdata in gen_variants.items():
            if not isinstance(vdata, dict):
                continue
            model = vdata.get("model", "")
            if bs_rel.endswith("/tripwire.json") and model:
                wire_model_ids.add(model.rsplit("/", 1)[-1])
            if model in DEFAULT_MODELS:
                continue
            if state not in work_variants:
                new_variants[state] = vdata
            else:
                # v12: the generated pack is the authority for every state it defines. ItemsAdder re-assigns slot
                # numbers when blocks are removed and added, so an old og variant (e.g. 140 -> backrooms_carpet)
                # must be replaced by the current one (140 -> abyssalite_block), not kept.
                old = work_variants[state] if isinstance(work_variants[state], dict) else {}
                if old.get("model") != model or old.get("x", 0) != vdata.get("x", 0) or old.get("y", 0) != vdata.get("y", 0):
                    new_variants[state] = vdata

        if new_variants:
            log(f"  {os.path.basename(bs_rel)}: +{len(new_variants)} variant(s)", "ok")
            for state, vdata in new_variants.items():
                model_ref = vdata.get("model", "")
                new_block_models[model_ref] = True
                log(f"    {model_ref}", "sub")

            if work_bs:
                work_variants.update(new_variants)
                work_bs["variants"] = work_variants
            else:
                work_bs = gen_bs
            merged[bs_rel] = json.dumps(work_bs, indent=2).encode()
            changes["blockstates"].append(bs_rel)

    if not new_block_models:
        log("  No new blockstate entries found.", "sub")

    log("\n═══ BLOCK MODELS & TEXTURES ═══", "header")

    for model_ref in new_block_models:
        model_path = _model_ref_to_path(model_ref)

        if model_path not in gen_files:
            log(f"  WARNING: Model not found: {model_path}", "warn")
            continue

        gen_model = json.loads(gen_files[model_path])

        if "ia_auto" in model_ref:
            textures = gen_model.get("textures", {})
            old_refs = set()
            for v in textures.values():
                if isinstance(v, str) and (v.startswith("ia:") or v.startswith("_b_")):
                    old_refs.add(v)

            ref_mapping = {}  # old_ref -> new ia:XX sprite
            for old_ref in sorted(old_refs):
                if old_ref.startswith("ia:"):
                    resource = gen_sprite_to_resource.get(old_ref)
                    if not resource:
                        log(f"  WARNING: Can't resolve {old_ref} for {model_ref}", "warn")
                        continue
                else:
                    resource = old_ref[3:]  # strip "_b_"

                if resource in existing_resources:
                    for entry in work_atlas["sources"]:
                        if entry.get("type") == "single" and entry["resource"] == resource:
                            ref_mapping[old_ref] = entry.get("sprite", entry["resource"])
                            break
                else:
                    new_sprite = f"ia:{next_ia}"
                    work_atlas["sources"].append({
                        "type": "single",
                        "resource": resource,
                        "sprite": new_sprite,
                    })
                    existing_resources.add(resource)
                    ref_mapping[old_ref] = new_sprite
                    log(f"  Atlas: {new_sprite} <- {resource}", "ok")
                    changes["atlas"].append((new_sprite, resource))
                    next_ia += 1

                    tex_path = _resource_to_tex_path(resource)
                    if tex_path in gen_files and tex_path not in merged:
                        merged[tex_path] = gen_files[tex_path]
                        log(f"  Texture: {tex_path}", "sub")
                        changes["textures"].append(tex_path)
                    elif tex_path not in gen_files:
                        log(f"  WARNING: Texture not found in gen pack: {tex_path}", "warn")

            new_model = copy.deepcopy(gen_model)
            for key, val in new_model.get("textures", {}).items():
                if val in ref_mapping:
                    new_model["textures"][key] = ref_mapping[val]

            model_id = model_path.rsplit("/", 1)[-1][:-5]
            if model_id in CROSS_MODEL_IDS or model_id in wire_model_ids:
                tex = new_model.get("textures", {})
                sprite = tex.get("all") or tex.get("particle") or next(iter(tex.values()), None)
                if sprite:
                    # item (gui / hand / frame): flat sprite; placed block: separate cross model
                    placed_path = model_path[:-5] + "_placed.json"
                    merged[placed_path] = json.dumps({"parent": "minecraft:block/cross",
                                                      "textures": {"cross": sprite, "particle": sprite}}).encode()
                    new_model = {"parent": "minecraft:item/generated", "textures": {"layer0": sprite}}
                    cross_placed_refs[model_ref] = model_ref + "_placed"
                    log(f"  Plant: {model_id} -> 2D item + _placed cross model", "ok")

            merged[model_path] = json.dumps(new_model).encode()
            log(f"  Model: {model_path}", "ok")
            changes["models"].append(model_path)

        else:
            if model_path not in merged:
                merged[model_path] = gen_files[model_path]
                log(f"  Model (direct): {model_path}", "ok")
                changes["models"].append(model_path)

                for tex_ref in gen_model.get("textures", {}).values():
                    if isinstance(tex_ref, str) and not tex_ref.startswith("#"):
                        tex_path = _resource_to_tex_path(tex_ref)
                        if tex_path in gen_files and tex_path not in merged:
                            merged[tex_path] = gen_files[tex_path]
                            log(f"  Texture: {tex_path}", "sub")
                            changes["textures"].append(tex_path)


    # ------------------------------------------------------------------
    # Generic model porter (v2): remaps IA's "_b_<resource>" / "ia:N" sprite refs to this
    # pack's atlas, copies textures, follows non-vanilla parents. Used for override
    # blockstates (waxed copper blocks from IACopperBlockInjector) and paper item models.
    # ------------------------------------------------------------------
    ported_models = set()

    def _atlas_sprite_for(resource):
        nonlocal next_ia
        if resource in existing_resources:
            for entry in work_atlas["sources"]:
                if entry.get("type") == "single" and entry["resource"] == resource:
                    return entry.get("sprite", entry["resource"])
        new_sprite = f"ia:{next_ia}"
        work_atlas["sources"].append({"type": "single", "resource": resource, "sprite": new_sprite})
        existing_resources.add(resource)
        log(f"  Atlas: {new_sprite} <- {resource}", "ok")
        changes["atlas"].append((new_sprite, resource))
        next_ia += 1
        tex_path = _resource_to_tex_path(resource)
        if tex_path in gen_files and tex_path not in merged:
            merged[tex_path] = gen_files[tex_path]
            log(f"  Texture: {tex_path}", "sub")
            changes["textures"].append(tex_path)
        elif tex_path not in gen_files and tex_path not in merged:
            log(f"  WARNING: Texture not found in gen pack: {tex_path}", "warn")
        return new_sprite

    def port_model(model_ref, force=False):
        """Copy a model from the generated pack into the merged pack, fixing texture refs."""
        if not model_ref or model_ref in ported_models:
            return
        ported_models.add(model_ref)
        model_path = _model_ref_to_path(model_ref)
        if model_path not in gen_files:
            if model_path not in merged and not model_ref.startswith("minecraft:") and not model_ref.startswith("block/") and not model_ref.startswith("item/"):
                log(f"  WARNING: Model not found: {model_path}", "warn")
            return
        if model_path in merged and not force:
            return
        try:
            model_data = json.loads(gen_files[model_path])
        except json.JSONDecodeError:
            merged[model_path] = gen_files[model_path]
            return
        textures = model_data.get("textures", {})
        for key, val in list(textures.items()):
            if not isinstance(val, str) or val.startswith("#"):
                continue
            if val.startswith("_b_"):
                textures[key] = _atlas_sprite_for(val[3:])
            elif val.startswith("ia:"):
                res = gen_sprite_to_resource.get(val)
                if res:
                    textures[key] = _atlas_sprite_for(res)
            else:
                # plain texture reference: copy the png so it resolves
                tex_path = _resource_to_tex_path(val)
                if tex_path in gen_files and tex_path not in merged:
                    merged[tex_path] = gen_files[tex_path]
                    log(f"  Texture: {tex_path}", "sub")
                    changes["textures"].append(tex_path)
        model_data["textures"] = textures
        merged[model_path] = json.dumps(model_data).encode()
        log(f"  Model: {model_path}", "ok")
        changes["models"].append(model_path)
        parent = model_data.get("parent")
        if isinstance(parent, str) and not parent.startswith("minecraft:") and ":" in parent:
            port_model(parent)

    def _models_in_blockstate(bs):
        out = []
        for v in bs.get("variants", {}).values():
            for item in (v if isinstance(v, list) else [v]):
                if isinstance(item, dict) and item.get("model"):
                    out.append(item["model"])
        for part in bs.get("multipart", []):
            apply = part.get("apply")
            for item in (apply if isinstance(apply, list) else [apply]):
                if isinstance(item, dict) and item.get("model"):
                    out.append(item["model"])
        return out

    # ------------------------------------------------------------------
    # v15: ItemsAdder custom fires (placed_model.type: FIRE) live in assets/minecraft/blockstates/fire.json,
    # a multipart file. IA's generated copy already contains vanilla fire for every age it doesn't use, so it
    # is taken whole; every non-vanilla model it applies is ported (textures + animation .mcmeta included).
    # ------------------------------------------------------------------
    fire_rel = "assets/minecraft/blockstates/fire.json"
    if fire_rel in gen_files:
        log("\n═══ CUSTOM FIRE ═══", "header")
        try:
            fire_bs = json.loads(gen_files[fire_rel])
            fire_models = []
            fixed_ids = 0
            for part in fire_bs.get("multipart", []):
                apply = part.get("apply")
                for item in (apply if isinstance(apply, list) else [apply]):
                    if isinstance(item, dict):
                        m = item.get("model", "")
                        # ItemsAdder 4.0.x bug: fire model ids come out double-namespaced ("sotcl:sotcl:block/x"),
                        # which the client rejects -> missing model. Collapse "ns:ns:path" to "ns:path".
                        parts = m.split(":")
                        if len(parts) == 3 and parts[0] == parts[1]:
                            m = parts[0] + ":" + parts[2]
                            item["model"] = m
                            fixed_ids += 1
                        if m and ":" in m and not m.startswith("minecraft:") and m not in fire_models:
                            fire_models.append(m)
            if fixed_ids:
                log(f"  fixed {fixed_ids} double-namespaced fire model id(s) (ItemsAdder bug)", "ok")
            if fire_models:
                merged[fire_rel] = json.dumps(fire_bs, indent=2).encode()
                changes["other"].append(fire_rel)
                log(f"  fire.json: taken from generated ({len(fire_models)} custom fire model(s))", "ok")
                for m in fire_models:
                    mpath = _model_ref_to_path(m)
                    if mpath not in gen_files and mpath not in merged and mpath not in work_files:
                        log(f"  MISSING fire model {m}: expected {mpath} in the generated pack "
                            f"(put it in contents/<ns>/models/... next to the fire's model_path)", "err")
                        continue
                    if mpath not in gen_files:
                        continue                      # already in the working pack: keep it
                    port_model(m)
                    # animated fire textures need their .mcmeta next to the png
                    gm = json.loads(gen_files.get(_model_ref_to_path(m), b"{}") or b"{}")
                    for val in gm.get("textures", {}).values():
                        if not isinstance(val, str) or val.startswith("#"):
                            continue
                        res = val[3:] if val.startswith("_b_") else gen_sprite_to_resource.get(val, val)
                        meta = _resource_to_tex_path(res) + ".mcmeta"
                        if meta in gen_files and meta not in merged:
                            merged[meta] = gen_files[meta]
                            log(f"  Animation: {meta}", "sub")
                            changes["textures"].append(meta)
            else:
                log("  fire.json has no custom fires - left as is", "sub")
        except Exception as ex:
            log(f"  fire.json: skipped ({ex})", "warn")

    if cross_placed_refs:
        for bs_rel in BLOCKSTATE_FILES:
            if bs_rel not in merged:
                continue
            bs = json.loads(merged[bs_rel]); changed = False
            for state, vdata in bs.get("variants", {}).items():
                if isinstance(vdata, dict) and vdata.get("model") in cross_placed_refs:
                    vdata["model"] = cross_placed_refs[vdata["model"]]; changed = True
            if changed:
                merged[bs_rel] = json.dumps(bs, indent=2).encode()
                log(f"  {os.path.basename(bs_rel)}: plant variants now use _placed cross models", "ok")

    log("\n═══ OVERRIDE BLOCKSTATES (waxed copper / IACopperBlockInjector) ═══", "header")
    override_count = 0
    for path in sorted(gen_files):
        if not _is_override_blockstate(path):
            continue
        try:
            bs = json.loads(gen_files[path])
        except json.JSONDecodeError:
            log(f"  WARNING: bad json {path}", "warn")
            continue
        models = _models_in_blockstate(bs)
        if not any(":" in m and not m.startswith("minecraft:") for m in models):
            continue  # not a custom override
        merged[path] = gen_files[path]  # whole file replaces the working one: these are full overrides
        changes["blockstates"].append(path)
        override_count += 1
        custom = sorted({m for m in models if ":" in m and not m.startswith("minecraft:")})
        log(f"  {os.path.basename(path)}: {len(custom)} custom model(s)", "ok")
        for m in custom:
            port_model(m, force=True)
    if override_count == 0:
        log("  No override blockstates found.", "sub")


    # ------------------------------------------------------------------
    # v3: IACopperBlockInjector sounds patch. The injector emits
    # assets/<ns>/iacopper_sounds_patch.json in the IA pack; merge it into the working
    # pack's assets/minecraft/sounds.json (silenced copper events + iacopper.* copies).
    # ------------------------------------------------------------------
    log("\n═══ SOUNDS PATCH (IACopperBlockInjector) ═══", "header")
    sounds_path = "assets/minecraft/sounds.json"
    frag_paths = [p for p in gen_files if p.startswith("assets/") and p.endswith("/iacopper_sounds_patch.json")]
    if frag_paths:
        try:
            work_sounds = json.loads(merged[sounds_path]) if sounds_path in merged else {}
        except json.JSONDecodeError:
            work_sounds = {}
        added = 0
        for fp in frag_paths:
            try:
                frag = json.loads(gen_files[fp])
            except json.JSONDecodeError:
                log(f"  WARNING: bad json {fp}", "warn")
                continue
            for key, val in frag.items():
                if work_sounds.get(key) != val:
                    work_sounds[key] = val
                    added += 1
            merged[fp] = gen_files[fp]
        merged[sounds_path] = json.dumps(work_sounds, indent=2).encode()
        log(f"  Merged {added} sound event(s) into {sounds_path}", "ok")
    else:
        log("  No sounds patch fragment in gen pack.", "sub")


    # ------------------------------------------------------------------
    # v4: PILLAR / LOG FIX. ItemsAdder rotates one cube model in the blockstate for
    # horizontal LOG placements (x:90 / x:90,y:90), which turns the end faces and mirrors
    # the side grain. Vanilla (bamboo) uses dedicated cube_column_uv_locked_x/_z models
    # with no blockstate rotation. Do the same for every pillar-like IA model.
    # ------------------------------------------------------------------
    log("\n═══ PILLAR FIX (uv-locked horizontal models) ═══", "header")
    pillar_models_made = 0
    pillar_variants_fixed = 0

    def _pillar_textures(model_ref):
        """(end, side) texture refs if the model is pillar-like, else None."""
        path = _model_ref_to_path(model_ref)
        if path not in merged:
            return None
        try:
            m = json.loads(merged[path])
        except json.JSONDecodeError:
            return None
        t = m.get("textures", {})
        if "end" in t and "side" in t:
            return (t["end"], t["side"])
        faces = [t.get(k) for k in ("down", "up", "north", "east", "south", "west")]
        if any(f is None for f in faces):
            return None
        down, up, north, east, south, west = faces
        if down == up and north == east == south == west and down != north:
            return (down, north)
        return None

    def _write_pillar_models(model_ref, end, side):
        nonlocal pillar_models_made
        base_path = _model_ref_to_path(model_ref)
        out = {}
        # Explicit face rotations (clockwise, as seen from outside each face) so an asymmetric side texture chains
        # around the log axis: every face's right edge meets the next face's left edge, like the upright pillar.
        # Vanilla's cube_column_uv_locked_* only align the grain and put highlight against highlight on one edge.
        presets = {
            "chain": {"x": {"down": (90, None), "up": (90, None), "north": (270, None), "south": (90, None)},
                      "z": {"up": (0, None), "east": (90, None), "down": (180, None), "west": (270, None)}},
            "lighting": {"x": {"down": (270, None), "up": (90, None), "north": (90, None), "south": (90, None)},
                         "z": {"up": (0, None), "east": (90, None), "down": (180, None), "west": (90, None)}},
        }
        face_spec = PILLAR_FACES if PILLAR_SIDE_MODE == "custom" else presets[PILLAR_SIDE_MODE]
        ends = {"x": ("west", "east"), "z": ("north", "south")}
        if PILLAR_DEBUG:
            # debug texture: red bar = texture top, green bar = texture left, blue dot = top-left corner
            import struct, zlib
            def _png(w, h, px):
                raw = b"".join(b"\x00" + b"".join(struct.pack("BBBB", *px(x, y)) for x in range(w)) for y in range(h))
                def chunk(t, d): return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
                return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")
            def px(x, y):
                if x < 3 and y < 3: return (40, 80, 255, 255)      # blue corner = top-left
                if y < 3: return (230, 40, 40, 255)                # red = top edge
                if x < 3: return (40, 200, 40, 255)                # green = left edge
                return (235, 235, 235, 255)
            merged["assets/minecraft/textures/block/iacopper_pillar_debug.png"] = _png(16, 16, px)
            log("  PILLAR DEBUG: all pillar faces use the red/green orientation texture", "warn")
            face_spec = {"x": {f: (0, None) for f in ("up", "down", "north", "south")},
                         "z": {f: (90, "H") for f in ("up", "down", "west", "east")}}

        def _face(face, rot, flip):
            # screen flip after rotation -> Minecraft uv mirror before rotation:
            #   flipH after rot90/270 == uv flipV;  flipV after rot90/270 == uv flipH;  after rot0/180 same axis
            f = {"texture": "#side", "cullface": face}
            if flip:
                uv_flip = flip if rot % 180 == 0 else ("V" if flip == "H" else "H")
                f["uv"] = [16, 0, 0, 16] if uv_flip == "H" else [0, 16, 16, 0]
            if rot:
                f["rotation"] = rot
            return f
        for axis in ("x", "z"):
            ref = model_ref + "_" + axis
            path = base_path[:-5] + "_" + axis + ".json"
            faces = {}
            for face, (rot, flip) in face_spec[axis].items():
                faces[face] = _face(face, rot, flip)
            for face in ends[axis]:
                faces[face] = {"texture": "#end", "cullface": face}
            if PILLAR_DEBUG:
                for f in faces.values(): f["texture"] = "#side"
                end = side = "minecraft:block/iacopper_pillar_debug"
            model = {"parent": "minecraft:block/block",
                     "textures": {"particle": side, "end": end, "side": side},
                     "elements": [{"from": [0, 0, 0], "to": [16, 16, 16], "faces": faces}]}
            merged[path] = json.dumps(model).encode()   # always rewrite: v4 wrote vanilla-parent versions
            pillar_models_made += 1
            log(f"  Model: {path}", "sub")
            out[axis] = ref
        if PILLAR_MATCH_ENDS:
            # upright model: both ends unrotated so the bottom reads like the top (vanilla rotates 'up' 180)
            merged[base_path] = json.dumps({
                "parent": "minecraft:block/block",
                "textures": {"particle": side, "end": end, "side": side},
                "elements": [{"from": [0, 0, 0], "to": [16, 16, 16], "faces": {
                    "down": {"texture": "#end", "cullface": "down"},
                    "up": {"texture": "#end", "cullface": "up"},
                    "north": {"texture": "#side", "cullface": "north"},
                    "south": {"texture": "#side", "cullface": "south"},
                    "west": {"texture": "#side", "cullface": "west"},
                    "east": {"texture": "#side", "cullface": "east"}}}]
            }).encode()
        return out

    pillar_cache = {}
    for bs_path in [p for p in merged if p.startswith("assets/minecraft/blockstates/") and p.endswith(".json")]:
        try:
            bs = json.loads(merged[bs_path])
        except json.JSONDecodeError:
            continue
        variants = bs.get("variants")
        if not isinstance(variants, dict):
            continue
        changed = False
        for key, val in variants.items():
            if not isinstance(val, dict):
                continue
            model_ref = val.get("model")
            if not model_ref or ":" not in model_ref or model_ref.startswith("minecraft:"):
                continue
            x, y = val.get("x", 0), val.get("y", 0)
            if x != 90 or y not in (0, 90):
                continue
            if model_ref not in pillar_cache:
                tex = _pillar_textures(model_ref)
                pillar_cache[model_ref] = _write_pillar_models(model_ref, *tex) if tex else None
            axes = pillar_cache[model_ref]
            if not axes:
                continue
            variants[key] = {"model": axes["x"] if y == 90 else axes["z"]}
            changed = True
            pillar_variants_fixed += 1
        if changed:
            merged[bs_path] = json.dumps(bs, indent=2).encode()
            changes["blockstates"].append(bs_path)
    log(f"  {pillar_variants_fixed} horizontal variant(s) fixed, {pillar_models_made} model(s) written", "ok" if pillar_variants_fixed else "sub")

    log("\n═══ CLEANUP: stale _b_ refs in existing models ═══", "header")
    fixed_count = 0
    for path in list(merged.keys()):
        if not (path.endswith(".json") and "/models/item/ia_auto/" in path):
            continue
        try:
            model_data = json.loads(merged[path])
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        textures = model_data.get("textures", {})
        if not any(isinstance(v, str) and v.startswith("_b_") for v in textures.values()):
            continue

        ref_mapping = {}
        for v in set(textures.values()):
            if not (isinstance(v, str) and v.startswith("_b_")):
                continue
            resource = v[3:]  # strip "_b_"

            if resource in existing_resources:
                for entry in work_atlas["sources"]:
                    if entry.get("type") == "single" and entry["resource"] == resource:
                        ref_mapping[v] = entry.get("sprite", entry["resource"])
                        break
            else:
                new_sprite = f"ia:{next_ia}"
                work_atlas["sources"].append({
                    "type": "single",
                    "resource": resource,
                    "sprite": new_sprite,
                })
                existing_resources.add(resource)
                ref_mapping[v] = new_sprite
                log(f"  Atlas: {new_sprite} <- {resource}", "ok")
                changes["atlas"].append((new_sprite, resource))
                next_ia += 1

                tex_path = _resource_to_tex_path(resource)
                if tex_path in gen_files and tex_path not in merged:
                    merged[tex_path] = gen_files[tex_path]
                    log(f"  Texture: {tex_path}", "sub")
                    changes["textures"].append(tex_path)

        for key, val in textures.items():
            if val in ref_mapping:
                textures[key] = ref_mapping[val]
        model_data["textures"] = textures
        merged[path] = json.dumps(model_data).encode()
        log(f"  Fixed: {path}", "ok")
        fixed_count += 1

    if fixed_count == 0:
        log("  No stale _b_ refs found.", "sub")

    log("\n═══ PAPER ITEM MODEL ═══", "header")

    for paper_rel in PAPER_OVERLAYS:
        if paper_rel not in gen_files:
            continue
        if paper_rel not in work_files:
            log(f"  Overlay not in working pack: {paper_rel}", "sub")
            continue

        gen_paper = json.loads(gen_files[paper_rel])
        work_paper = json.loads(work_files[paper_rel])

        gen_entries = gen_paper.get("model", {}).get("entries", [])
        work_entries = work_paper.get("model", {}).get("entries", [])

        work_thresholds = {e["threshold"]: e for e in work_entries}
        gen_thresholds = {e["threshold"]: e for e in gen_entries}

        added = 0
        for threshold, entry in gen_thresholds.items():
            model = entry.get("model", {}).get("model", "")
            if threshold not in work_thresholds:
                work_entries.append(entry)
                log(f"  +threshold {threshold} -> {model}", "ok")
                changes["paper"].append((threshold, model))
                port_model(model)
                added += 1
            elif model != work_thresholds[threshold].get("model", {}).get("model", ""):
                old_model = work_thresholds[threshold].get("model", {}).get("model", "")
                if old_model in ("item/paper", "minecraft:item/paper"):
                    work_thresholds[threshold]["model"] = entry["model"]
                    log(f"  ~threshold {threshold}: {old_model} -> {model}", "ok")
                    changes["paper"].append((threshold, model))
                    port_model(model)
                    added += 1

        if added:
            work_entries.sort(key=lambda e: e["threshold"])
            work_paper["model"]["entries"] = work_entries
            merged[paper_rel] = json.dumps(work_paper, indent=2).encode()
            log(f"  Updated {paper_rel} (+{added} entries)", "ok")
        else:
            log(f"  {os.path.basename(paper_rel)}: no changes needed", "sub")

    merged[work_atlas_path] = json.dumps(work_atlas, indent=2).encode()

    log("\n═══ PAINTING ITEM MODEL ═══", "header")

    painting_rel = "assets/minecraft/items/painting.json"
    if painting_rel in gen_files and painting_rel in work_files:
        gen_painting = json.loads(gen_files[painting_rel])
        work_painting = json.loads(work_files[painting_rel])

        gen_cases = gen_painting.get("model", {}).get("cases", [])
        work_cases = work_painting.get("model", {}).get("cases", [])

        work_whens = {str(c["when"]): c for c in work_cases}

        added_p = 0
        for case in gen_cases:
            when_key = str(case.get("when", ""))
            if when_key and when_key not in work_whens:
                work_cases.append(case)
                model = case.get("model", {}).get("model", "?")
                log(f"  +variant {when_key} -> {model}", "ok")
                changes["painting"].append((when_key, model))
                added_p += 1

        if added_p:
            work_painting["model"]["cases"] = work_cases
            merged[painting_rel] = json.dumps(work_painting, indent=2).encode()
            log(f"  Updated painting.json (+{added_p} variants)", "ok")
        else:
            log("  No changes needed", "sub")
    elif painting_rel in gen_files and painting_rel not in work_files:
        merged[painting_rel] = gen_files[painting_rel]
        log("  Copied painting.json from generated pack (didn't exist in working)", "ok")
        changes["painting"].append(("*", "full copy"))
    else:
        log("  No painting.json found in generated pack", "sub")

    log("\n═══ NEW NAMESPACE FILES ═══", "header")

    new_ns_count = 0
    for path, data in gen_files.items():
        if path.startswith("assets/itemsadder_additions/"):
            if path not in merged:
                merged[path] = data
                log(f"  + {path}", "ok")
                changes["other"].append(path)
                new_ns_count += 1
        elif path.startswith("ia_overlay_") and not path.endswith("/"):
            if "atlases/" in path or path in PAPER_OVERLAYS:
                continue
            if merged.get(path) != data:
                merged[path] = data
                new_ns_count += 1

    if new_ns_count:
        log(f"  {new_ns_count} overlay/namespace file(s) copied or refreshed", "ok")
    else:
        log("  No new namespace files", "sub")

    _merge_jank(merged, gen_files, changes, log)

    _remove_stale_itemsadder(merged, gen_files, changes, log)
    return next_ia


def _unnest_raw_files(gen_files, log):
    """ItemsAdder sometimes copies a content folder's resource_pack/ folder in as plain namespace assets, producing
    assets/<ns>/resource_pack/assets/... instead of assets/... . Put those files back where they belong."""
    moved = 0
    for path in sorted(gen_files):
        parts = path.split("/", 3)
        if len(parts) == 4 and parts[0] == "assets" and parts[2] in ("resource_pack", "resourcepack") and parts[3].startswith("assets/"):
            target = parts[3]
            data = gen_files.pop(path)
            if target not in gen_files:
                gen_files[target] = data
                moved += 1
    if moved:
        log(f"  Moved {moved} file(s) ItemsAdder had nested under assets/<namespace>/resource_pack/ back to the pack root", "ok")


def _is_override_blockstate(path):
    """Whole-file blockstate overrides written by IACopperBlockInjector: waxed copper carriers, leaf slots and shelf slots."""
    if not (path.startswith("assets/minecraft/blockstates/") and path.endswith(".json")):
        return False
    name = path.rsplit("/", 1)[-1]
    return name.startswith("waxed_") or name.endswith("_leaves.json") or name.endswith("_shelf.json")


def _remove_stale_itemsadder(merged, gen_files, changes, log):
    """Deletes ItemsAdder-owned files the working pack still has but the current generated pack no longer contains,
    and keeps the ia_overlay_* entries in pack.mcmeta in step with the generated pack."""
    log("\n═══ STALE FILES (ItemsAdder) ═══", "header")
    removed = []
    gen_has_overrides = any(_is_override_blockstate(p) for p in gen_files)
    gen_has_overlays = any(p.startswith("ia_overlay_") for p in gen_files)
    if not gen_has_overrides:
        log("  The generated pack has no copper/leaf blockstates, so none are removed (is it the full ItemsAdder zip?)", "warn")
    if not gen_has_overlays:
        log("  The generated pack has no ia_overlay files, so none are removed", "warn")
    for path in sorted(merged):
        if path in gen_files:
            continue
        if _is_override_blockstate(path) and gen_has_overrides:
            try:
                bs = json.loads(merged[path])
            except (ValueError, TypeError):
                continue
            models = []
            for v in (bs.get("variants") or {}).values():
                for one in (v if isinstance(v, list) else [v]):
                    if isinstance(one, dict) and one.get("model"):
                        models.append(one["model"])
            for part in bs.get("multipart") or []:
                apply = part.get("apply")
                for one in (apply if isinstance(apply, list) else [apply]):
                    if isinstance(one, dict) and one.get("model"):
                        models.append(one["model"])
            if any(":" in m and not m.startswith("minecraft:") for m in models):
                removed.append(path)
        elif path.startswith("ia_overlay_") and not path.endswith("/") and gen_has_overlays:
            removed.append(path)
    for path in removed:
        del merged[path]
        changes["removed"].append(path)
        log(f"  - {path}", "ok")

    try:
        gen_meta = json.loads(gen_files.get("pack.mcmeta", b"") or b"{}")
        work_meta = json.loads(merged.get("pack.mcmeta", b"") or b"{}")
    except (ValueError, TypeError):
        gen_meta, work_meta = None, None
    gen_entries = (gen_meta or {}).get("overlays", {}).get("entries", []) if isinstance(gen_meta, dict) else []
    gen_ia = [e for e in gen_entries if str(e.get("directory", "")).startswith("ia_overlay_")]
    if isinstance(work_meta, dict):
        gen_by_dir = {e["directory"]: e for e in gen_ia}
        with_files = sorted({p.split("/", 1)[0] for p in merged if p.startswith("ia_overlay_") and "/" in p})
        entries = work_meta.setdefault("overlays", {}).setdefault("entries", [])
        before = json.dumps(entries)
        dropped = []
        if gen_ia:
            dropped = [e.get("directory") for e in entries
                       if str(e.get("directory", "")).startswith("ia_overlay_")
                       and e.get("directory") not in gen_by_dir and e.get("directory") not in with_files]
            entries[:] = [gen_by_dir.get(e.get("directory"), e) for e in entries if e.get("directory") not in dropped]
        present = {e.get("directory") for e in entries}
        ia_positions = [i for i, e in enumerate(entries) if str(e.get("directory", "")).startswith("ia_overlay_")]
        at = (ia_positions[-1] + 1) if ia_positions else 0
        added = []
        wanted = [e["directory"] for e in gen_ia] + [d for d in with_files if d not in gen_by_dir]
        for d in wanted:
            if d in present:
                continue
            if d in gen_by_dir:
                e = gen_by_dir[d]
            elif d in KNOWN_IA_OVERLAYS:
                lo, hi = KNOWN_IA_OVERLAYS[d]
                e = {"directory": d, "formats": [lo, hi], "min_format": lo, "max_format": hi}
            else:
                log(f"  WARNING: {d} has files but an unknown version range; not registered", "warn")
                continue
            entries.insert(at, e)
            at += 1
            present.add(d)
            added.append(d)
        if json.dumps(entries) != before:
            merged["pack.mcmeta"] = json.dumps(work_meta, indent=2).encode()
        for d in dropped:
            log(f"  - overlay entry {d}", "ok")
            changes["removed"].append(f"pack.mcmeta overlay {d}")
        for d in added:
            log(f"  + overlay entry {d}", "ok")
            changes["other"].append(f"pack.mcmeta overlay {d}")
        if not entries:
            work_meta.pop("overlays", None)
            merged["pack.mcmeta"] = json.dumps(work_meta, indent=2).encode()
    if not removed and not changes["removed"]:
        log("  No stale files", "sub")


def _merge_modelengine(merged, me_path, changes, log, include_shaders):
    """Merges ModelEngine's generated resource pack into `merged` (in place). Returns True on success."""
    before = dict(merged)  # to count only real changes at the end
    log("Reading ModelEngine pack...", "info")
    me_files = _read_pack(me_path)
    log(f"  {len(me_files)} files", "sub")
    if not any(p.startswith(ME_NAMESPACE_PREFIX) for p in me_files):
        log("  ERROR: no assets/modelengine/ folder found — is this ModelEngine's resource pack?", "err")
        return False

    def _json(data):
        try:
            return json.loads(data)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None

    # ---- modelengine namespace: ModelEngine owns it, so replace it wholesale (drops models you deleted) ----
    log("\n═══ MODELENGINE NAMESPACE ═══", "header")
    stale = [p for p in merged if p.startswith(ME_NAMESPACE_PREFIX) and p not in me_files]
    for p in stale:
        del merged[p]
    added = updated = 0
    for p, d in me_files.items():
        if not p.startswith(ME_NAMESPACE_PREFIX):
            continue
        if p not in merged:
            added += 1
        elif merged[p] != d:
            updated += 1
        else:
            continue
        merged[p] = d
        changes["modelengine"].append(p)
    changes["modelengine"].extend(stale)
    models = sorted({p.split("/")[3] for p in me_files
                     if p.startswith("assets/modelengine/models/") and p.count("/") >= 4})
    log(f"  +{added} new, ~{updated} updated, -{len(stale)} removed", "ok" if (added or updated or stale) else "sub")
    if models:
        log(f"  Models: {', '.join(models)}", "sub")

    # ---- blocks atlas: add ModelEngine's sources (texture directory) without touching IA's entries ----
    log("\n═══ BLOCKS ATLAS ═══", "header")
    atlas_path = "assets/minecraft/atlases/blocks.json"
    me_atlas = _json(me_files[atlas_path]) if atlas_path in me_files else None
    if me_atlas:
        work_atlas = _json(merged[atlas_path]) if atlas_path in merged else None
        if work_atlas is None:
            merged[atlas_path] = me_files[atlas_path]
            log("  Copied ModelEngine's atlas (working pack had none)", "ok")
            changes["modelengine"].append(atlas_path)
        else:
            sources = work_atlas.setdefault("sources", [])
            n = 0
            for src in me_atlas.get("sources", []):
                if src not in sources:
                    sources.append(src)
                    n += 1
                    log(f"  + {src.get('type')} source {src.get('source') or src.get('resource') or ''}", "ok")
            if n:
                merged[atlas_path] = json.dumps(work_atlas, indent=2).encode()
                changes["modelengine"].append(atlas_path)
            else:
                log("  Already contains ModelEngine's sources", "sub")
    else:
        log("  No atlas in ModelEngine pack", "sub")

    # ---- item definitions (1.21.4+): merge range_dispatch entries by threshold ----
    log("\n═══ ITEM DEFINITIONS ═══", "header")
    for p in ME_ITEM_DEFS:
        if p not in me_files:
            continue
        me_def = _json(me_files[p])
        work_def = _json(merged[p]) if p in merged else None
        if work_def is None or work_def.get("model", {}).get("type") != "minecraft:range_dispatch":
            if p in merged and merged[p] != me_files[p]:
                log(f"  {os.path.basename(p)}: working version isn't a range_dispatch — replaced with ModelEngine's", "warn")
            merged[p] = me_files[p]
            changes["modelengine"].append(p)
            log(f"  {os.path.basename(p)}: copied", "ok")
            continue
        me_entries = me_def.get("model", {}).get("entries", [])
        me_models = {e.get("model", {}).get("model") for e in me_entries}
        me_thresholds = {e.get("threshold") for e in me_entries}
        kept = []
        for e in work_def["model"].get("entries", []):
            mdl = e.get("model", {}).get("model", "")
            if str(mdl).startswith("modelengine:"):
                continue  # old ModelEngine entry, replaced below
            if e.get("threshold") in me_thresholds:
                log(f"  CONFLICT {os.path.basename(p)} threshold {e.get('threshold')}: '{mdl}' "
                    f"overwritten by ModelEngine", "warn")
                continue
            kept.append(e)
        work_def["model"]["entries"] = sorted(kept + me_entries, key=lambda e: e.get("threshold", 0))
        if work_def != _json(merged[p]):
            merged[p] = json.dumps(work_def, indent=2).encode()
        changes["modelengine"].append(p)
        log(f"  {os.path.basename(p)}: {len(me_entries)} ModelEngine entr(ies), {len(kept)} other kept", "ok")

    # ---- legacy item models (pre-1.21.4 overrides): merge by custom_model_data ----
    for p in ME_LEGACY_ITEM_MODELS:
        if p not in me_files:
            continue
        me_m = _json(me_files[p])
        work_m = _json(merged[p]) if p in merged else None
        if work_m is None:
            merged[p] = me_files[p]
            changes["modelengine"].append(p)
            log(f"  {os.path.basename(p)} (legacy): copied", "ok")
            continue
        me_ov = me_m.get("overrides", [])
        me_cmd = {o.get("predicate", {}).get("custom_model_data") for o in me_ov}
        kept = []
        for o in work_m.get("overrides", []):
            if str(o.get("model", "")).startswith("modelengine:"):
                continue
            if o.get("predicate", {}).get("custom_model_data") in me_cmd:
                log(f"  CONFLICT {os.path.basename(p)} (legacy) cmd "
                    f"{o['predicate']['custom_model_data']}: '{o.get('model')}' overwritten", "warn")
                continue
            kept.append(o)
        work_m["overrides"] = sorted(kept + me_ov,
                                     key=lambda o: o.get("predicate", {}).get("custom_model_data", 0))
        if work_m != _json(merged[p]):
            merged[p] = json.dumps(work_m, indent=2).encode()
        changes["modelengine"].append(p)
        log(f"  {os.path.basename(p)} (legacy): {len(me_ov)} ModelEngine override(s), {len(kept)} other kept", "ok")

    # ---- shaders (root) ----
    log("\n═══ SHADERS ═══", "header")
    root_shaders = [p for p in me_files if p.startswith("assets/") and _is_shader_path(p)]
    if include_shaders:
        clashes = [p for p in root_shaders if p in merged and merged[p] != me_files[p]]
        for p in root_shaders:
            merged[p] = me_files[p]
            changes["modelengine"].append(p)
        log(f"  Copied {len(root_shaders)} ModelEngine shader file(s)", "ok")
        for p in clashes:
            log(f"  WARNING: replaced your pack's {p}", "warn")
        own_entity = [p for p in merged if p.endswith("shaders/core/entity.fsh") and not p.startswith(ME_OVERLAY_PREFIX)
                      and p not in me_files]
        if own_entity:
            log("  WARNING: your pack has its own entity shaders in overlays "
                f"({', '.join(sorted({x.split('/')[0] for x in own_entity}))}). Mixed with ModelEngine's they can make "
                "entities black/invisible — test in-game.", "warn")
    else:
        log(f"  Skipped {len(root_shaders)} ModelEngine shader file(s) (keeps your pack's own shaders)", "sub")
        log("  ModelEngine mobs still render; only ModelEngine's player-model features need these.", "sub")

    # ---- overlays: copy modelengine_* folders and register them in pack.mcmeta ----
    log("\n═══ OVERLAYS ═══", "header")
    for p in [p for p in merged if p.startswith(ME_OVERLAY_PREFIX)]:
        del merged[p]  # clear stale copies
    overlay_dirs_with_files = set()
    skipped_ov = 0
    for p, d in me_files.items():
        if not p.startswith(ME_OVERLAY_PREFIX):
            continue
        if _is_shader_path(p) and not include_shaders:
            skipped_ov += 1
            continue
        merged[p] = d
        overlay_dirs_with_files.add(p.split("/", 1)[0])
    if skipped_ov:
        log(f"  Skipped {skipped_ov} overlay shader file(s)", "sub")

    me_meta = _json(me_files.get("pack.mcmeta", b"")) or {}
    work_meta = _json(merged.get("pack.mcmeta", b"")) or {"pack": {"pack_format": 46, "description": "Merged pack"}}
    entries = work_meta.setdefault("overlays", {}).setdefault("entries", [])
    entries[:] = [e for e in entries if not str(e.get("directory", "")).startswith(ME_OVERLAY_PREFIX)]
    n_ov = 0
    for e in me_meta.get("overlays", {}).get("entries", []):
        if e.get("directory") in overlay_dirs_with_files:
            entries.append(e)
            n_ov += 1
            log(f"  + overlay {e['directory']}", "ok")
    if not entries:
        work_meta.pop("overlays", None)
    if include_shaders and "sodium" in me_meta:
        work_meta["sodium"] = me_meta["sodium"]
    if work_meta != _json(merged.get("pack.mcmeta", b"")):
        merged["pack.mcmeta"] = json.dumps(work_meta, indent=2).encode()
    changes["modelengine"].append("pack.mcmeta")
    if not n_ov:
        log("  No ModelEngine overlays needed", "sub")

    changes["modelengine"] = sorted(p for p in set(before) | set(merged) if before.get(p) != merged.get(p))
    log(f"\n  ModelEngine merge complete ({len(changes['modelengine'])} file(s) changed).", "ok")
    return True

class App:
    def __init__(self, root):
        self.root = root
        self.root.title("IA Block Porter v20")
        self.root.geometry("820x740")
        self.root.configure(bg=T["bg"])
        self.root.minsize(640, 560)
        self._build()

    def _build(self):
        hdr = tk.Frame(self.root, bg=T["bg"])
        hdr.pack(fill="x", padx=24, pady=(18, 0))
        tk.Label(hdr, text="IA Block Porter", font=("Segoe UI", 18, "bold"),
                 fg=T["ac"], bg=T["bg"]).pack(side="left")
        tk.Label(hdr, text="v20", font=("Segoe UI", 9, "bold"),
                 fg=T["mt"], bg=T["bg"]).pack(side="left", padx=(8, 0), pady=(6, 0))

        tk.Label(self.root, text="Merges an ItemsAdder pack, a ModelEngine pack, or both into your working pack. "
                                 "Leave a field empty to skip it.",
                 font=("Segoe UI", 9), fg=T["sub"], bg=T["bg"]).pack(padx=24, pady=(4, 12))

        picks = tk.Frame(self.root, bg=T["sf2"], padx=14, pady=14)
        picks.pack(fill="x", padx=24, pady=(0, 10))

        self.work_var = tk.StringVar()
        self.gen_var = tk.StringVar()
        self.me_var = tk.StringVar()
        self.out_var = tk.StringVar()
        self.me_shaders_var = tk.BooleanVar(value=False)

        # (label, var, mode, optional)  mode: open | save | open_or_folder
        rows = [
            ("Working pack (your good one):", self.work_var, "open", False),
            ("ItemsAdder pack (optional):", self.gen_var, "open", True),
            ("ModelEngine pack (optional):", self.me_var, "open_or_folder", True),
            ("Output (merged pack):", self.out_var, "save", False),
        ]
        for label, var, mode, optional in rows:
            row = tk.Frame(picks, bg=T["sf2"])
            row.pack(fill="x", pady=3)
            tk.Label(row, text=label, font=("Segoe UI", 9, "bold"),
                     fg=T["sub"] if optional else T["tx"], bg=T["sf2"], width=28, anchor="w").pack(side="left")
            entry = tk.Entry(row, textvariable=var, font=("Consolas", 9),
                             bg=T["sf"], fg=T["tx"], insertbackground=T["ac"],
                             relief="flat", bd=5)
            entry.pack(side="left", fill="x", expand=True, padx=(0, 8))

            def _browse(v=var, m=mode):
                if m == "save":
                    p = filedialog.asksaveasfilename(
                        defaultextension=".zip", filetypes=[("Zip files", "*.zip")],
                        initialfile="sotcl.zip", parent=self.root)
                else:
                    p = filedialog.askopenfilename(filetypes=[("Zip files", "*.zip")], parent=self.root)
                if p:
                    v.set(p)
                    if m != "save" and not self.out_var.get():
                        self.out_var.set(os.path.join(os.path.dirname(p), "sotcl.zip"))

            def _browse_dir(v=var):
                p = filedialog.askdirectory(parent=self.root,
                                            title="ModelEngine's 'resource pack' folder")
                if p:
                    v.set(p)

            def _btn(text, cmd):
                tk.Button(row, text=text, font=("Segoe UI", 8), bg=T["sf3"],
                          fg=T["tx"], activebackground=T["ac"], activeforeground="#fff",
                          relief="flat", cursor="hand2", padx=10, pady=3,
                          command=cmd).pack(side="left", padx=(0, 4))

            _btn("Browse", _browse)
            if mode == "open_or_folder":
                _btn("Folder", _browse_dir)
            if optional:
                _btn("✕", lambda v=var: v.set(""))

        opt = tk.Frame(picks, bg=T["sf2"])
        opt.pack(fill="x", pady=(8, 0))
        tk.Checkbutton(opt, text="Include ModelEngine shaders (only if you need ModelEngine player models — "
                                 "can clash with your pack's own entity shaders)",
                       variable=self.me_shaders_var, font=("Segoe UI", 8),
                       fg=T["sub"], bg=T["sf2"], selectcolor=T["sf"],
                       activebackground=T["sf2"], activeforeground=T["tx"]).pack(anchor="w")

        btn_frame = tk.Frame(self.root, bg=T["bg"])
        btn_frame.pack(fill="x", padx=24, pady=(0, 8))

        self.merge_btn = tk.Button(
            btn_frame, text="  Merge  ", font=("Segoe UI", 13, "bold"),
            bg=T["gn"], fg="#fff", activebackground=T["tl"], activeforeground="#fff",
            relief="flat", cursor="hand2", padx=24, pady=8,
            command=self._run_merge)
        self.merge_btn.pack(side="left")

        self.status = tk.Label(btn_frame, text="", font=("Segoe UI", 10),
                               fg=T["gn"], bg=T["bg"])
        self.status.pack(side="left", padx=(16, 0))

        tk.Label(self.root, text="LOG", font=("Segoe UI", 7, "bold"),
                 fg=T["mt"], bg=T["bg"]).pack(anchor="w", padx=26, pady=(4, 0))

        log_border = tk.Frame(self.root, bg=T["bd"], padx=1, pady=1)
        log_border.pack(fill="both", expand=True, padx=24, pady=(2, 16))

        self.log = scrolledtext.ScrolledText(
            log_border, font=("Consolas", 9), bg=T["sf"], fg=T["tx"],
            insertbackground=T["ac"], selectbackground=T["sf3"],
            relief="flat", wrap="word", bd=8, state="disabled")
        self.log.pack(fill="both", expand=True)

        self.log.tag_configure("header", foreground=T["ac"], font=("Consolas", 9, "bold"))
        self.log.tag_configure("ok", foreground=T["gn"])
        self.log.tag_configure("info", foreground=T["bl"])
        self.log.tag_configure("sub", foreground=T["sub"])
        self.log.tag_configure("warn", foreground=T["og"])
        self.log.tag_configure("err", foreground=T["rd"], font=("Consolas", 9, "bold"))

    def _log(self, msg, tag=""):
        self.log.configure(state="normal")
        self.log.insert("end", msg + "\n", tag)
        self.log.see("end")
        self.log.configure(state="disabled")
        self.root.update_idletasks()

    def _run_merge(self):
        work = self.work_var.get().strip()
        gen = self.gen_var.get().strip()
        me = self.me_var.get().strip()
        out = self.out_var.get().strip()

        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")
        self.status.configure(text="", fg=T["gn"])

        if not work or not out:
            self._log("ERROR: Working pack and output are required.", "err")
            return
        if not gen and not me:
            self._log("ERROR: Pick an ItemsAdder pack, a ModelEngine pack, or both.", "err")
            return
        if not os.path.isfile(work) and not os.path.isdir(work):
            self._log(f"ERROR: Working pack not found: {work}", "err")
            return
        if gen and not os.path.isfile(gen) and not os.path.isdir(gen):
            self._log(f"ERROR: ItemsAdder pack not found: {gen}", "err")
            return
        if me and not os.path.isfile(me) and not os.path.isdir(me):
            self._log(f"ERROR: ModelEngine pack not found: {me}", "err")
            return
        if os.path.abspath(out) == os.path.abspath(work):
            self._log("WARNING: output is the same file as the working pack — it will be overwritten.", "warn")

        self.merge_btn.configure(state="disabled", text="  Merging...  ",
                                 bg=T["yl"], fg=T["bg"])
        self.root.update()

        try:
            total = run_merge(work, gen or None, me or None, out, self._log,
                              me_shaders=self.me_shaders_var.get())
            if total is None:
                self.status.configure(text="Failed — check log", fg=T["rd"])
            elif total > 0:
                self.status.configure(text=f"Done! {total} changes merged.", fg=T["gn"])
            else:
                self.status.configure(text="Nothing new to merge.", fg=T["og"])
        except Exception as e:
            import traceback
            self._log(f"\nERROR: {e}", "err")
            self._log(traceback.format_exc(), "err")
            self.status.configure(text="Failed — check log", fg=T["rd"])
        finally:
            self.merge_btn.configure(state="normal", text="  Merge  ",
                                     bg=T["gn"], fg="#fff")

if __name__ == "__main__":
    try:
        root = tk.Tk()
        App(root)
        root.mainloop()
    except Exception as e:
        print(f"\nFATAL ERROR: {e}")
        import traceback; traceback.print_exc()
        print("\nPress Enter to close...")
        try:
            input()
        except:
            pass
