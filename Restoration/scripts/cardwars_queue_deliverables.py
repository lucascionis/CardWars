"""Verify the remaining queue and build offline galleries/category ZIPs."""
import argparse
from collections import Counter
import html
import json
from pathlib import Path
import zipfile

from PIL import Image, ImageChops, ImageDraw, ImageFont

from cardwars_upscale_cards import sha, write_json


def page(records, title, intro, downloads=""):
    rows = sorted(records, key=lambda r: (r["job"], r["name"], r["id"]))
    payload = json.dumps(rows, ensure_ascii=False).replace("<", "\\u003c")
    counts = Counter(r["job"] for r in rows)
    labels = {"screens": "Schermate e loghi", "maps": "Mappe e percorsi", "ui": "Interfaccia e atlanti", "scenery": "Scenari e ambienti", "characters": "Personaggi e oggetti", "effects": "Effetti e animazioni", "card_variants": "Varianti delle carte"}
    options = "".join(f'<option value="{key}">{html.escape(labels[key])} · {count}</option>' for key, count in counts.items())
    template = r'''<!doctype html><html lang="it"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>__TITLE__</title>
<style>:root{color-scheme:dark}body{margin:0;background:#111820;color:#edf3f8;font:16px system-ui,sans-serif;line-height:1.5}main{max-width:1200px;margin:auto;padding:30px 24px}h1{font-size:34px;margin:8px 0}p{color:#bdcddd}a{color:#a9dced}input,select,button{font:inherit;background:#203342;color:#f0f6fc;border:1px solid #4d687b;padding:9px 12px;border-radius:8px}button{cursor:pointer}button:disabled{opacity:.4;cursor:default}.tools{display:flex;gap:12px;margin:22px 0;flex-wrap:wrap;align-items:center}input[type=search]{flex:1;min-width:190px}section{padding:20px;background:#1b2935;border-radius:14px}.compare{position:relative;max-width:700px;margin:auto;background:#e0e3e6;border-radius:8px;overflow:hidden;--split:50%}.compare img{display:block;width:100%;height:auto}.compare .original{position:absolute;inset:0;clip-path:inset(0 calc(100% - var(--split)) 0 0)}.line{position:absolute;top:0;bottom:0;left:var(--split);width:2px;background:white;box-shadow:0 0 5px #000}.slider{display:flex;align-items:center;gap:15px;max-width:700px;margin:18px auto}.slider input{flex:1;min-width:50px;accent-color:#a9dced}.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(185px,1fr));gap:16px}.card{padding:0;overflow:hidden;text-align:left;border-radius:10px}.card img{display:block;width:100%;height:180px;object-fit:contain;background:#e0e3e6}.card span{display:block;padding:10px;font-size:13px;overflow-wrap:anywhere}.pager{display:flex;gap:14px;align-items:center;margin:22px 0}.links{display:flex;gap:20px;flex-wrap:wrap}.note{font-size:14px}#title{margin:0 0 14px;overflow-wrap:anywhere;font-size:21px}.download-list{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px;margin:22px 0}.download-list a{display:block;padding:14px;background:#223340;border-radius:8px;text-decoration:none}.download-list small{display:block;color:#bdd0df}code{overflow-wrap:anywhere}@media(max-width:600px){main{padding:20px 12px}h1{font-size:28px}.grid{grid-template-columns:repeat(2,1fr)}.card img{height:150px}.tools{align-items:stretch;flex-direction:column}.slider{font-size:13px;gap:8px}}</style>
<main><h1>__TITLE__</h1><p>__INTRO__</p>__DOWNLOADS__
<section id="comparison"><h2 id="title"></h2><div class="compare" id="viewer"><img id="upscaled" alt="Versione upscale 2×"><img id="original" class="original" alt="Originale ingrandito"><div class="line"></div></div><label class="slider">Originale <input id="split" type="range" min="0" max="100" value="50" aria-label="Confronto prima e dopo"> Upscale 2×</label><p id="dimensions"></p><p id="review" class="note"></p><div class="links"><a id="original-link">Originale PNG</a><a id="upscaled-link">Upscale PNG</a></div></section>
<h2>Esplora gli asset</h2><div class="tools"><input id="query" type="search" placeholder="Cerca nome o ID…" aria-label="Cerca asset"><select id="category" aria-label="Categoria"><option value="">Tutte le categorie</option>__OPTIONS__</select><label><input id="primary" type="checkbox"> Solo varianti principali</label><a href="manifest.json">Dati e verifiche</a><a href="LEGGIMI.txt">Note del lotto</a></div><p id="count" role="status" aria-live="polite"></p><div id="cards" class="grid"></div><div class="pager"><button id="prev">Precedente</button><span id="page"></span><button id="next">Successiva</button></div><p class="note">File distinti mantengono ID e percorsi separati. La griglia non è incorporata nei PNG: il confronto usa uno sfondo uniforme. Le immagini non sono applicate al gioco. Atlanti/sprite, UV, mipmap, scritte e coerenza delle animazioni richiedono revisione prima del reinserimento.</p></main>
<script id="data" type="application/json">__DATA__</script><script>
const rows=JSON.parse(document.getElementById('data').textContent),$=id=>document.getElementById(id),size=30;let page=0,filtered=[];
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function chooseAsset(index,scroll=false){const r=rows[index];$('title').textContent=r.name;$('original').src=r.original;$('upscaled').src=r.output;$('original-link').href=r.original;$('upscaled-link').href=r.output;$('dimensions').textContent=`${r.input_size.join(' × ')} → ${r.output_size.join(' × ')} · ${r.id} · ${r.input_mode==='RGBA'?'Trasparenza preservata':'Immagine opaca'}`;$('review').textContent=r.review_note;$('split').value=50;$('viewer').style.setProperty('--split','50%');if(scroll)$('comparison').scrollIntoView({behavior:'smooth',block:'start'});}
function render(){const pages=Math.max(1,Math.ceil(filtered.length/size));$('count').textContent=`${filtered.length} asset corrispondenti su ${rows.length}`;$('page').textContent=`Pagina ${page+1} / ${pages}`;$('prev').disabled=page===0;$('next').disabled=page>=pages-1;$('cards').innerHTML=filtered.slice(page*size,(page+1)*size).map(r=>`<button class="card" data-index="${r.index}" aria-label="Confronta ${esc(r.name)} · ${esc(r.id)}"><img src="${esc(r.thumbnail)}" alt="${esc(r.name)}" loading="lazy"><span>${esc(r.name)}<br><small>${esc(r.input_size.join(' × '))} → ${esc(r.output_size.join(' × '))}</small></span></button>`).join('');for(const b of $('cards').querySelectorAll('button'))b.onclick=()=>chooseAsset(Number(b.dataset.index),true);}
function filter(){const q=$('query').value.toLowerCase().trim();filtered=rows.map((r,index)=>({...r,index})).filter(r=>(!q||(r.name+' '+r.id).toLowerCase().includes(q))&&(!$('category').value||r.job===$('category').value)&&(!$('primary').checked||r.family_primary));page=0;render();}
$('split').oninput=()=>{$('viewer').style.setProperty('--split',$('split').value+'%')};$('query').oninput=filter;$('category').onchange=filter;$('primary').onchange=filter;$('prev').onclick=()=>{page--;render()};$('next').onclick=()=>{page++;render()};chooseAsset(Math.max(0,rows.findIndex(r=>r.name==='Loading_Main_16_9')));filter();
</script></html>'''
    for key, value in {"TITLE": html.escape(title), "INTRO": intro, "DOWNLOADS": downloads, "OPTIONS": options, "DATA": payload}.items():
        template = template.replace(f"__{key}__", value)
    return template


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    root = args.directory.resolve()
    queue = json.loads((root / "queue.json").read_text())
    assert queue["status"] == "complete" and queue["source_bytes_and_mtime_unchanged"]
    records = queue["assets"]
    assert len(records) == 1771 and all(r["validated"] for r in records)
    for i, row in enumerate(records):
        target = root / row["output"]
        assert sha(target) == row["output_sha256"], row["id"]
        with Image.open(root / row["original"]) as original, Image.open(target) as output:
            output.load()
            assert output.size == tuple(v*2 for v in original.size)
            if original.mode == "RGBA":
                alpha = original.getchannel("A").resize(output.size, Image.Resampling.BILINEAR)
                assert ImageChops.difference(alpha, output.getchannel("A")).getbbox() is None
        assert (root / row["thumbnail"]).is_file()
        if (i+1) % 300 == 0:
            print(f"Delivery verification: {i+1}/{len(records)}", flush=True)
    for filename, fingerprint in queue["source_files"].items():
        source = Path(filename)
        assert sha(source) == fingerprint["sha256"] and source.stat().st_mtime_ns == fingerprint["mtime_ns"], filename
    common = {key: queue[key] for key in ["model", "scale", "tile_size", "threads", "source_files", "game_modified", "game_launched", "applied_to_game", "source_bytes_and_mtime_unchanged", "note"]}
    write_json(root / "manifest.json", common | {"total_assets": len(records), "assets": records})
    intro = "1.771 file grafici completati in locale, comprese le varianti ridotte. Le 288 illustrazioni principali delle carte sono già state consegnate separatamente.<br>Dimensioni 2× e trasparenza verificate. File del gioco invariati e gioco non avviato."
    packages = []
    (root / "pacchetti").mkdir(exist_ok=True)
    for job in queue["jobs"]:
        items = [r for r in records if r["job"] == job["key"]]
        assert len(items) == job["count"]
        target = root / "pacchetti" / f"CardWars-{job['key']}-2x.zip"
        prefix = Path(f"CardWars-{job['key']}-2x")
        category_manifest = common | {"category": job["key"], "label": job["label"], "total_assets": len(items), "assets": items}
        category_page = page(items, f"Card Wars · {job['label']} 2×", f"{len(items)} PNG verificati, con originali e miniature. Elaborazione locale; gioco invariato.")
        readme = f"CARD WARS — {job['label'].upper()} 2×\n\n{len(items)} PNG finali con originali e miniature.\nAprire index.html per il confronto su sfondo uniforme.\nDimensioni doppie, trasparenza originale preservata e PNG verificati.\nGioco invariato e non avviato. Asset non reinseriti nel gioco.\nAtlanti, sprite, UV, mipmap, scritte e animazioni richiedono revisione.\nmanifest.json contiene identificativi, provenienza e hash.\n"
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=1, allowZip64=True) as archive:
            archive.writestr(str(prefix / "index.html"), category_page)
            archive.writestr(str(prefix / "manifest.json"), json.dumps(category_manifest, ensure_ascii=False, indent=2))
            archive.writestr(str(prefix / "LEGGIMI.txt"), readme)
            for row in items:
                for key in ["original", "output", "thumbnail"]:
                    path = root / row[key]
                    archive.write(path, prefix / row[key])
        with zipfile.ZipFile(target) as archive:
            assert archive.testzip() is None, target
            assert len([n for n in archive.namelist() if "/upscaled/" in n]) == len(items)
            assert not any("/cache/" in n or "/inputs/" in n for n in archive.namelist())
        info = {"category": job["key"], "label": job["label"], "count": len(items), "path": str(target.relative_to(root)), "bytes": target.stat().st_size, "sha256": sha(target), "zip_integrity_verified": True}
        packages.append(info)
        print(f"Package verified: {job['key']}, {len(items)} PNGs, {target.stat().st_size/1024**2:.1f} MiB", flush=True)
    download_links = '<div class="download-list">' + "".join(f'<a href="{p["path"]}" download>{html.escape(p["label"])}<small>{p["count"]} asset · {p["bytes"]/1024**2:.1f} MiB</small></a>' for p in packages) + '</div>'
    (root / "index.html").write_text(page(records, "Card Wars · tutti gli altri asset in 2×", intro, download_links))
    names = ["Loading_Main_16_9", "Loading_Halloween_16_9", "FcNis01_01", "GUIAtlas", "TreeFort_Atlas", "Picnic_Background", "Finn_Face", "FX_QuestStar_PNG", "Creature_GhostBull"]
    sheet = Image.new("RGB", (960, 1100), "#111820")
    draw = ImageDraw.Draw(sheet)
    font_path = "/System/Library/Fonts/Supplemental/Arial.ttf"
    font = ImageFont.truetype(font_path, 17)
    title = ImageFont.truetype(font_path, 28)
    draw.text((20, 15), "Card Wars — tutti gli altri asset in 2x", fill="#edf3f8", font=title)
    draw.text((20, 53), "1.771 file · 7 lotti · campioni su sfondo uniforme", fill="#bdcddd", font=font)
    for i, name in enumerate(names):
        candidates = [r for r in records if r["name"] == name]
        row = max(candidates, key=lambda r: r["input_size"][0]*r["input_size"][1])
        x, y = 20 + (i%3)*320, 95 + (i//3)*330
        with Image.open(root / row["output"]) as image:
            tile = image.convert("RGBA")
            tile.thumbnail((285,285), Image.Resampling.LANCZOS)
            bg = Image.new("RGBA", (285,285), "#e0e3e6")
            bg.alpha_composite(tile, ((285-tile.width)//2, (285-tile.height)//2))
            sheet.paste(bg.convert("RGB"), (x,y))
        draw.text((x,y+291), name[:28], fill="#edf3f8", font=font)
    sheet.save(root / "campioni.png")
    write_json(root / "delivery.json", {"status": "complete", "total_assets": len(records), "original_card_assets_preserved": 288, "total_graphic_textures_delivered": 2059, "excluded_runtime_fonts": 3, "all_png_dimensions_and_alpha_verified": True, "source_bytes_and_mtime_unchanged": True, "gallery": "index.html", "packages": packages})
    print("DELIVERY COMPLETE: 1,771 assets, 7 verified ZIPs, gallery and manifest", flush=True)


if __name__ == "__main__":
    main()
