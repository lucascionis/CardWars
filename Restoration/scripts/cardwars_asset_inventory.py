"""Read installed Card Wars textures and create a local, searchable inventory.

No game files are written. No upscale or game process is started.
Run with the UnityPy/Pillow venv used for the five-image trial.
"""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import html
import json
from pathlib import Path

import UnityPy
from PIL import Image


LABELS = {
    "creatures": "Carte · creature",
    "buildings": "Carte · edifici",
    "spells": "Carte · magie",
    "screens": "Schermate, loghi e promozioni",
    "maps": "Mappe e percorsi",
    "ui": "Interfaccia, cornici e icone",
    "characters": "Personaggi, creature e oggetti 3D",
    "scenery": "Scenari e ambienti",
    "effects": "Effetti e animazioni",
    "technical": "Font e texture tecniche",
    "review": "Da classificare visivamente",
}
WORLD_PREFIXES = ("treefort", "icekingdom", "marshmallow", "donutland", "wildberry", "cave_", "lumpyspace_", "beachparty", "picnic_", "coliseum", "candy_", "sand_", "ice_", "stadium", "dungeon_", "landscape", "plains")


def category(name, paths, slots):
    n = name.removeprefix("low_").lower().strip()
    if n.startswith("creature_"):
        return "creatures"
    if n.startswith("building_"):
        return "buildings"
    if any("/cardart" in p and "/spells/" in p for p in paths):
        return "spells"
    if n == "font texture" or any(k in n for k in ("normalmap", "lightmap", "bumpmap")) or any(s.lower() in ("_bumpmap", "_normalmap") for s in slots):
        return "technical"
    if n.startswith(("loading", "loadscreen", "fc_purchase", "sidequest_01")) or n in ("logo", "kfflogo", "trophyscreen", "lootscreen_background"):
        return "screens"
    if n.startswith(("questmap", "fcquestmap", "fcvalentinequestmap", "fcnis", "nisvd")):
        return "maps"
    if n.startswith(("guiatlas", "charactericon", "cardartatlas", "cardframe", "battle_banners", "rarity_banners", "bannersatlas", "battlering", "sidequest_", "sidequest_hud", "gameboardgrid", "questinfo")) or n in ("uisprite", "card_front", "card_back", "cards_01", "goldcard_overlay", "background"):
        return "ui"
    if n.startswith(("fx_", "spell_", "hitimpact", "glow_", "flare", "ring0", "spark", "trail", "grad", "shockwave", "witchway", "burst", "burningmark", "text_")) or n in ("fxdamagebattle", "hexanim", "floop_red", "floodlight", "flyinglava", "cerebralbloodstorm_rain"):
        return "effects"
    if n.startswith(WORLD_PREFIXES):
        return "scenery"
    if any(p.startswith("Assets/Texture2D/") for p in paths):
        return "characters"
    return "review"


def pointer_key(ptr, file):
    if not ptr.m_PathID:
        return None
    name = file.name
    if ptr.m_FileID:
        try:
            name = ptr.assetsfile.externals[ptr.m_FileID - 1].path.replace("\\", "/").rsplit("/", 1)[-1]
        except (IndexError, AttributeError):
            return None
    return f"{name}:{ptr.m_PathID}"


def build_page(data, destination):
    summary = data["summary"]
    cats = "".join(f'<option value="{key}">{html.escape(label)}</option>' for key, label in LABELS.items())
    overview = "".join(f'<tr><td>{html.escape(LABELS[key])}</td><td>{summary["categories"][key]["textures"]}</td><td>{summary["categories"][key]["families"]}</td></tr>' for key in LABELS if key in summary["categories"])
    payload = json.dumps(data, ensure_ascii=False).replace("<", "\\u003c")
    template = r'''<!doctype html><html lang="it"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Card Wars · indice del restauro</title>
<style>
:root{color-scheme:dark}body{margin:0;background:#111820;color:#eaf0f7;font:16px system-ui,sans-serif;line-height:1.5}main{max-width:1320px;margin:auto;padding:32px 24px}h1{font-size:36px;line-height:1.15;margin:12px 0}h2{font-size:22px}p{max-width:1000px;color:#bdcadd}a{color:#9ed9ec}.stats{display:flex;gap:14px;flex-wrap:wrap;margin:24px 0}.stat{background:#1c2a37;padding:16px 20px;border-radius:12px;min-width:140px}.stat b{display:block;font-size:28px}.stat span{color:#bdcadd;font-size:14px}.layout{display:grid;grid-template-columns:1fr 1fr;gap:24px}.panel{background:#18232e;padding:20px;border-radius:12px}table{border-collapse:collapse;width:100%}td,th{text-align:left;padding:7px 10px;border-bottom:1px solid #354454}th{color:#a7bdce;font-size:13px}li{margin:8px 0}.controls{display:flex;gap:12px;flex-wrap:wrap;margin:22px 0;align-items:center}input,select,button{background:#1c2a37;color:#edf5fc;border:1px solid #4a6073;border-radius:8px;padding:10px;font:inherit}input[type=search]{flex:1;min-width:210px}input[type=checkbox]{accent-color:#89d1ed}button{cursor:pointer}button:disabled{opacity:.35;cursor:default}.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(270px,1fr));gap:16px}.card{background:#1c2935;border:1px solid #354454;border-radius:12px;overflow:hidden}.thumb{height:180px;display:flex;justify-content:center;align-items:center;background:#e0e3e6}.thumb img{max-width:100%;max-height:180px;object-fit:contain}.info{padding:14px}.name{font-size:17px;font-weight:650;overflow-wrap:anywhere}.meta{font-size:13px;color:#bdd0df}.tag{display:inline-block;font-size:12px;padding:3px 7px;margin:6px 4px 6px 0;border-radius:5px;background:#334657}.priority-1{background:#23514c}.priority-2{background:#344d69}.priority-3{background:#625031}.priority-4{background:#58464d}details{margin-top:12px;font-size:13px;color:#c0d1df}summary{cursor:pointer}.pager{display:flex;align-items:center;gap:16px;margin:22px 0}.note{font-size:14px;color:#b8c8d7}code{overflow-wrap:anywhere;font-size:12px}.empty{padding:32px;background:#1c2935;border-radius:12px}@media(max-width:720px){main{padding:22px 12px}.layout{grid-template-columns:1fr}h1{font-size:30px}.stat{min-width:100px}.controls{align-items:stretch;flex-direction:column}}
</style><main>
<p>RESTAURO GRAFICO · INVENTARIO LOCALE</p><h1>Card Wars: cosa possiamo migliorare</h1>
<p>Immagini lette dalla tua installazione, con miniature su sfondo uniforme. Questo indice prepara il lavoro: il gioco resta invariato e non è stato avviato.</p>
<div class="stats"><div class="stat"><b>__TOTAL__</b><span>Texture2D installate</span></div><div class="stat"><b>__UNIQUE__</b><span>immagini pixel-identiche distinte</span></div><div class="stat"><b>__FAMILIES__</b><span>famiglie per nome</span></div><div class="stat"><b>__LOW__</b><span>varianti low_</span></div></div>
<div class="layout"><section class="panel"><h2>Materiale per categoria</h2><table><thead><tr><th>Categoria</th><th>Texture</th><th>Famiglie</th></tr></thead><tbody>__OVERVIEW__</tbody></table><p class="note">Le famiglie riuniscono nomi uguali e varianti low_: possono differire nei pixel. I duplicati esatti sono verificati sui pixel decodificati, includendo la trasparenza.</p></section>
<section class="panel"><h2>Ordine proposto</h2><ol><li><b>Carte:</b> creature, edifici e magie. Partire dalla versione più grande di ogni illustrazione, conservando la trasparenza.</li><li><b>Schermate e mappe:</b> controllare a mano loghi, scritte incorporate e linee sottili.</li><li><b>Interfaccia e ambienti:</b> verificare gli atlanti, i ritagli degli sprite, le cuciture e le proporzioni.</li><li><b>Personaggi ed effetti:</b> controllare le UV e la coerenza dei fotogrammi. Font e texture tecniche richiedono strumenti specifici.</li></ol>
<p class="note">Il 2× quadruplica i pixel. La sola superficie RGBA di base passerebbe da __MEMORY__ MiB a __MEMORY2__ MiB; non è una misura della VRAM effettiva e non include mipmap o compressione. Le varianti minori con una controparte maggiore vanno derivate da quella, evitando un secondo upscale.</p></section></div>
<h2>Esplora le immagini</h2>
<div class="controls"><input id="query" type="search" placeholder="Cerca nome, file o percorso…" aria-label="Cerca immagini"><select id="category" aria-label="Categoria"><option value="">Tutte le categorie</option>__CATS__</select><select id="priority" aria-label="Priorità"><option value="">Tutte le priorità</option><option value="1">1 · Carte</option><option value="2">2 · Schermate e mappe</option><option value="3">3 · Atlanti e ambienti</option><option value="4">4 · Controllo specialistico</option></select><select id="order" aria-label="Ordina"><option value="priority">Priorità</option><option value="name">Nome</option><option value="area">Dimensioni maggiori</option></select><label><input id="families" type="checkbox" checked> Una variante per famiglia</label></div>
<div class="controls"><label><input id="duplicates" type="checkbox" checked> Nascondi copie identiche</label><label><input id="technical" type="checkbox"> Includi font e texture tecniche</label><a href="inventario.json">Dati completi JSON</a><a href="riepilogo.txt">Riepilogo testuale</a></div>
<p id="count" role="status" aria-live="polite"></p><div id="cards" class="grid"></div><div class="pager"><button id="prev">Precedente</button><span id="page"></span><button id="next">Successiva</button></div>
<p class="note">Classificazione preliminare basata su nomi, percorsi della repository e riferimenti dei materiali/sprite. La miniatura serve al controllo visivo. Un elemento candidato non è ancora un asset verificato nel gioco. L'indice comprende i file di scena e gli archivi .assets della build; le risorse interne di Unity sono escluse. Nessuna immagine esterna aggiuntiva è presente in StreamingAssets.</p></main>
<script id="data" type="application/json">__DATA__</script><script>
const data=JSON.parse(document.getElementById('data').textContent), rows=data.textures, labels=data.category_labels, pageSize=48;let page=0, filtered=[];
const $=id=>document.getElementById(id),esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function refresh(){const q=$('query').value.trim().toLowerCase();filtered=rows.filter(r=>(!q||r.search.includes(q))&&(!$('category').value||r.category===$('category').value)&&(!$('priority').value||r.priority===Number($('priority').value))&&(!$('families').checked||r.family_primary)&&(!$('duplicates').checked||!r.duplicate_of)&&($('technical').checked||r.category!=='technical'));const order=$('order').value;filtered.sort((a,b)=>order==='area'?b.width*b.height-a.width*a.height:order==='name'?a.name.localeCompare(b.name):a.priority-b.priority||a.category.localeCompare(b.category)||a.name.localeCompare(b.name));page=0;render();}
function render(){const pages=Math.max(1,Math.ceil(filtered.length/pageSize));$('count').textContent=`${filtered.length} immagini corrispondenti · ${rows.length} texture nell'indice`; $('page').textContent=`Pagina ${page+1} / ${pages}`;$('prev').disabled=page===0;$('next').disabled=page>=pages-1;
$('cards').innerHTML=filtered.slice(page*pageSize,(page+1)*pageSize).map(r=>`<article class="card"><div class="thumb">${r.thumbnail?`<img loading="lazy" src="${esc(r.thumbnail)}" alt="${esc(r.name)}">`:'Miniatura non disponibile'}</div><div class="info"><div class="name">${esc(r.name)}</div><span class="tag priority-${r.priority}">Priorità ${r.priority}</span><span class="tag">${esc(labels[r.category])}</span><div>${r.width} × ${r.height} → ${r.width*2} × ${r.height*2}</div><div class="meta">${esc(r.format)} · ${esc(r.alpha_label)}<br>${r.sprite_count} sprite · ${r.material_count} materiali referenziati</div><p class="note">${esc(r.action)}</p><details><summary>Origine e controlli</summary><p><code>${esc(r.file)} · ID ${r.path_id}</code></p><p>${esc(r.review_note)}</p>${r.duplicate_of?`<p>Copia identica di: <code>${esc(r.duplicate_of)}</code></p>`:''}${r.higher_variant?`<p>Variante maggiore: <code>${esc(r.higher_variant)}</code></p>`:''}<p class="note">Percorsi repository compatibili per nome, senza verifica di identità:</p><p>${r.repo_paths.map(p=>`<code>${esc(p)}</code>`).join('<br>')||'Nessuna corrispondenza per nome'}</p>${r.error?`<p>${esc(r.error)}</p>`:''}</details></div></article>`).join('')||'<div class="empty">Nessuna immagine corrisponde ai filtri.</div>';}
for(const id of ['query','category','priority','order','families','duplicates','technical'])$(id).addEventListener(id==='query'?'input':'change',refresh);$('prev').onclick=()=>{page--;render()};$('next').onclick=()=>{page++;render()};refresh();
</script></html>'''
    replacements = {"TOTAL": summary["texture_count"], "UNIQUE": summary["unique_pixel_images"], "FAMILIES": summary["families"], "LOW": summary["low_variants"], "MEMORY": round(summary["rgba_base_mib"]), "MEMORY2": round(summary["rgba_base_mib"] * 4), "OVERVIEW": overview, "CATS": cats, "DATA": payload}
    for key, value in replacements.items():
        template = template.replace(f"__{key}__", str(value))
    (destination / "index.html").write_text(template)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--game-data", type=Path, required=True)
    parser.add_argument("--repo-tree", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.game_data.resolve()
    out = args.output.resolve()
    if out.is_relative_to(root):
        raise ValueError("Inventory output must be outside the game installation")
    (out / "miniature").mkdir(parents=True, exist_ok=True)
    tree = json.loads(args.repo_tree.read_text())
    repo_paths = defaultdict(list)
    for item in tree["tree"]:
        p = Path(item["path"])
        if item["type"] == "blob" and p.suffix.lower() in (".png", ".jpg", ".jpeg", ".tga", ".psd", ".tif", ".tiff", ".dds", ".bmp", ".exr"):
            repo_paths[p.stem.lower()].append(item["path"])
    files = sorted(p for p in root.iterdir() if p.is_file() and (p.suffix == ".assets" or p.name.startswith("level") or p.name == "globalgamemanagers"))
    tracked = files + sorted(p for p in root.iterdir() if p.suffix in (".resS", ".resource"))
    before = {str(p): (p.stat().st_size, p.stat().st_mtime_ns) for p in tracked}
    rows, sprites, materials, errors, source_files = [], defaultdict(list), defaultdict(list), [], []
    for p in files:
        env = UnityPy.load(str(p))
        objects = list(env.objects)
        counts = Counter(o.type.name for o in objects)
        source_files.append({"file": p.name, "bytes": p.stat().st_size, "object_counts": dict(counts), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()})
        for o in objects:
            if o.type.name == "Sprite":
                d = o.read()
                key = pointer_key(d.m_RD.texture, p)
                if key:
                    sprites[key].append(d.m_Name)
            elif o.type.name == "Material":
                d = o.read()
                for slot, tex in d.m_SavedProperties.m_TexEnvs:
                    key = pointer_key(tex.m_Texture, p)
                    if key:
                        materials[key].append({"name": d.m_Name, "slot": slot})
        for o in objects:
            if o.type.name != "Texture2D":
                continue
            d = o.read()
            key = f"{p.name}:{o.path_id}"
            row = {"id": key, "file": p.name, "path_id": o.path_id, "name": d.m_Name, "width": d.m_Width, "height": d.m_Height, "format": getattr(d.m_TextureFormat, "name", str(d.m_TextureFormat)), "format_id": int(d.m_TextureFormat), "mip_count": d.m_MipCount, "low_variant": d.m_Name.startswith("low_"), "repo_paths": repo_paths[d.m_Name.lower()], "encoded_bytes": d.m_CompleteImageSize}
            if d.m_Width <= 0 or d.m_Height <= 0:
                row.update(runtime_generated=True, alpha_label="generata a runtime, senza immagine salvata")
                rows.append(row)
                continue
            try:
                img = d.image.convert("RGBA")
                row["pixel_sha256"] = hashlib.sha256(f"{img.width},{img.height},RGBA\0".encode() + img.tobytes()).hexdigest()
                lo, hi = img.getchannel("A").getextrema()
                row["alpha_extrema"] = [lo, hi]
                row["alpha_label"] = "opaca" if lo == 255 else "semitrasparente" if lo > 0 else "con trasparenza"
                thumb = img.copy()
                thumb.thumbnail((240, 180), Image.Resampling.LANCZOS)
                bg = Image.new("RGBA", thumb.size, "#e0e3e6")
                bg.alpha_composite(thumb)
                thumb_name = hashlib.sha256(key.encode()).hexdigest()[:20] + ".jpg"
                bg.convert("RGB").save(out / "miniature" / thumb_name, quality=88)
                row["thumbnail"] = "miniature/" + thumb_name
            except Exception as exc:
                row.update(error=f"{type(exc).__name__}: {str(exc)[:200]}", alpha_label="non decodificata")
                errors.append({"id": key, "error": row["error"]})
            rows.append(row)
        print(f"{p.name}: {counts['Texture2D']} texture", flush=True)
        del env, objects
    from UnityPy.enums import TextureFormat
    families, pixels = defaultdict(list), defaultdict(list)
    for row in rows:
        row["format"] = TextureFormat(row["format_id"]).name
        row["sprites"] = sprites[row["id"]]
        row["sprite_count"] = len(row["sprites"])
        row["materials"] = materials[row["id"]]
        row["material_count"] = len({m["name"] for m in row["materials"]})
        row["category"] = category(row["name"], row["repo_paths"], [m["slot"] for m in row["materials"]])
        row["priority"] = 1 if row["category"] in ("creatures", "buildings", "spells") else 2 if row["category"] in ("screens", "maps") else 3 if row["category"] in ("ui", "scenery") else 4
        row["family"] = row["name"].removeprefix("low_").lower().strip()
        row["atlas_hint"] = "atlas" in row["name"].lower() or row["sprite_count"] > 1
        notes = []
        if row["atlas_hint"]:
            notes.append("Atlante o texture condivisa: verificare ritagli, coordinate e metadati prima del reinserimento.")
        if row["category"] in ("characters", "scenery"):
            notes.append("Controllare UV, cuciture, ripetizioni e mipmap.")
        if row["category"] == "effects":
            notes.append("Controllare fotogrammi, trasparenza e coerenza dell'animazione; attenzione a gradienti e bagliori.")
        if row["category"] in ("screens", "maps", "ui"):
            notes.append("Controllare eventuali scritte incorporate, loghi e linee sottili.")
        if row["alpha_label"] != "opaca":
            notes.append("Preservare la maschera alpha originale; nessuna griglia nelle miniature.")
        row["review_note"] = " ".join(notes) or "Confrontare con l'originale e verificare l'aspetto nel gioco prima di applicare."
        row["action"] = "Candidato per prova 2×" if row["priority"] < 4 else "Prova selettiva con controllo manuale"
        if row["category"] == "technical":
            row["action"] = "Escludere dal batch AI; font e dati tecnici richiedono trattamento specifico"
        if row.get("error"):
            row["action"] = "Decodifica da risolvere prima di elaborare"
        families[row["family"]].append(row)
        if row.get("pixel_sha256"):
            pixels[row["pixel_sha256"]].append(row)
    for group in families.values():
        group.sort(key=lambda r: (-r["width"]*r["height"], r["low_variant"], r["file"] != "resources.assets", r["id"]))
        primary = group[0]
        for row in group:
            row["family_primary"] = row is primary
            row["family_size"] = len(group)
            if row["width"]*row["height"] < primary["width"]*primary["height"]:
                row["higher_variant"] = primary["id"]
                row["action"] = "Derivare dalla variante maggiore dopo aver verificato la corrispondenza"
    for group in pixels.values():
        group.sort(key=lambda r: (not r["family_primary"], r["low_variant"], r["id"]))
        for row in group[1:]:
            row["duplicate_of"] = group[0]["id"]
    for row in rows:
        row["search"] = " ".join([row["name"], row["file"], *row["repo_paths"]]).lower()
    categories = {c: {"textures": sum(r["category"] == c for r in rows), "families": len({r["family"] for r in rows if r["category"] == c})} for c in LABELS if any(r["category"] == c for r in rows)}
    unchanged = all((p.stat().st_size, p.stat().st_mtime_ns) == before[str(p)] for p in tracked)
    if not unchanged:
        raise RuntimeError("A source file changed during the inventory")
    summary = {"texture_count": len(rows), "decoded_images": sum(bool(r.get("pixel_sha256")) for r in rows), "runtime_generated": sum(bool(r.get("runtime_generated")) for r in rows), "unique_pixel_images": len(pixels), "families": len(families), "low_variants": sum(r["low_variant"] for r in rows), "exact_duplicate_copies": sum(bool(r.get("duplicate_of")) for r in rows), "smaller_variants": sum(bool(r.get("higher_variant")) for r in rows), "decode_errors": len(errors), "categories": categories, "dimensions": dict(Counter(f"{r['width']}×{r['height']}" for r in rows)), "rgba_base_mib": sum(r["width"]*r["height"]*4 for r in rows) / 1024**2}
    data = {"generated_at_utc": datetime.now(timezone.utc).isoformat(), "installation": str(root), "game_modified": False, "game_launched": False, "upscale_executed": False, "source_size_and_mtime_unchanged": unchanged, "unitypy_version": UnityPy.__version__, "category_labels": LABELS, "classification_method": "Preliminary name/path/material-reference rules; repository paths match names only. Family membership is not pixel identity.", "scope": "Texture2D in installed .assets and level files; Unity built-in resource files excluded; Sprite subregions are references, not extra textures.", "repo_tree_sha": tree["sha"], "repo_tree_truncated": tree["truncated"], "summary": summary, "source_files": source_files, "errors": errors, "textures": rows}
    (out / "inventario.json").write_text(json.dumps(data, ensure_ascii=False, indent=2))
    lines = ["CARD WARS — INDICE DEL MATERIALE GRAFICO", f"Installazione: {root}", f"Texture2D: {len(rows)}", f"Immagini decodificate: {summary['decoded_images']}", f"Texture generate a runtime: {summary['runtime_generated']} (font senza immagine salvata)", f"Immagini distinte per pixel: {len(pixels)}", f"Copie identiche aggiuntive: {summary['exact_duplicate_copies']}", f"Famiglie per nome: {len(families)}", f"Varianti low_: {summary['low_variants']}", f"Errori di decodifica: {len(errors)}", "", "CATEGORIE — TEXTURE / FAMIGLIE"]
    lines.extend(f"{LABELS[c]}: {v['textures']} / {v['families']}" for c, v in categories.items())
    lines.extend(["", "Classificazione preliminare: controllare le miniature prima del batch.", "Per carte e varianti low_, usare prima la sorgente maggiore disponibile.", "Famiglie per nome e duplicati pixel-identici sono due conteggi differenti.", "Preservare alpha; controllare atlanti/sprite, UV, mipmap, scritte e fotogrammi.", "Il 2× quadruplica i pixel; memoria RGBA stimata senza mipmap/compressione.", "File del gioco invariati per dimensione e mtime. Nessun gioco o upscale avviato.", "I file di sistema interni di Unity non sono candidati al restauro."])
    (out / "riepilogo.txt").write_text("\n".join(lines) + "\n")
    build_page(data, out)
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
