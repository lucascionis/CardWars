"""Build a standalone comparison gallery and portable ZIP for a completed batch."""
import argparse
import json
from pathlib import Path
import zipfile

from PIL import Image, ImageDraw, ImageFont


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    root = args.directory.resolve()
    manifest = json.loads((root / "manifest.json").read_text())
    assert manifest["status"] == "complete"
    cards = sorted(manifest["cards"], key=lambda r: (r["category"], r["name"]))
    payload = json.dumps(cards, ensure_ascii=False).replace("<", "\\u003c")
    template = r'''<!doctype html><html lang="it"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Card Wars · 288 carte in 2×</title>
<style>:root{color-scheme:dark}body{margin:0;background:#111820;color:#edf3f8;font:16px system-ui,sans-serif;line-height:1.5}main{max-width:1180px;margin:auto;padding:30px 24px}h1{font-size:34px;margin:8px 0}p{color:#bdcddd}a{color:#a9dced}input,select,button{font:inherit;background:#203342;color:#f0f6fc;border:1px solid #4d687b;padding:9px 12px;border-radius:8px}button{cursor:pointer}button:disabled{opacity:.4;cursor:default}.tools{display:flex;gap:12px;margin:22px 0;flex-wrap:wrap;align-items:center}input[type=search]{flex:1;min-width:190px}section{padding:20px;background:#1b2935;border-radius:14px}.compare{position:relative;max-width:660px;margin:auto;background:#e0e3e6;border-radius:8px;overflow:hidden;--split:50%}.compare img{display:block;width:100%;height:auto}.compare .original{position:absolute;inset:0;clip-path:inset(0 calc(100% - var(--split)) 0 0)}.line{position:absolute;top:0;bottom:0;left:var(--split);width:2px;background:white;box-shadow:0 0 5px #000}.slider{display:flex;align-items:center;gap:15px;max-width:660px;margin:18px auto}.slider input{flex:1;min-width:50px;accent-color:#a9dced}.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:16px}.card{padding:0;overflow:hidden;text-align:left;border-radius:10px}.card img{display:block;width:100%;height:180px;object-fit:contain;background:#e0e3e6}.card span{display:block;padding:10px;font-size:13px;overflow-wrap:anywhere}.pager{display:flex;gap:14px;align-items:center;margin:22px 0}.links{display:flex;gap:20px;flex-wrap:wrap}.note{font-size:14px}#title{margin:0 0 14px;overflow-wrap:anywhere;font-size:21px}@media(max-width:600px){main{padding:20px 12px}h1{font-size:28px}.grid{grid-template-columns:repeat(2,1fr)}.card img{height:150px}.tools{align-items:stretch;flex-direction:column}.slider{font-size:13px;gap:8px}}</style>
<main><h1>Card Wars · 288 illustrazioni in 2×</h1><p>194 creature · 27 edifici · 67 magie. Elaborazione locale con Real-ESRGAN.<br>Trasparenza originale preservata; sfondo uniforme nel confronto. Il gioco resta invariato.</p>
<section id="comparison"><h2 id="title"></h2><div class="compare" id="viewer"><img id="upscaled" alt="Versione upscale 2×"><img id="original" class="original" alt="Originale ingrandito"><div class="line"></div></div><label class="slider">Originale <input id="split" type="range" min="0" max="100" value="50" aria-label="Confronto prima e dopo"> Upscale 2×</label><p id="dimensions"></p><div class="links"><a id="original-link">Originale PNG</a><a id="upscaled-link">Upscale PNG</a></div></section>
<h2>Scegli una carta</h2><div class="tools"><input id="query" type="search" placeholder="Cerca nome…" aria-label="Cerca carta"><select id="category" aria-label="Categoria"><option value="">Tutte le carte</option><option value="creatures">Creature · 194</option><option value="buildings">Edifici · 27</option><option value="spells">Magie · 67</option></select><a href="manifest.json">Dati e verifiche</a><a href="LEGGIMI.txt">Note del lotto</a></div><p id="count" role="status" aria-live="polite"></p><div id="cards" class="grid"></div><div class="pager"><button id="prev">Precedente</button><span id="page"></span><button id="next">Successiva</button></div><p class="note">PNG pronti per revisione visiva. Il reinserimento nel gioco, gli atlanti e le mipmap restano da verificare. Due carte pixel-identiche condividono la stessa elaborazione; sono consegnati tutti i 288 file.</p></main>
<script id="data" type="application/json">__DATA__</script><script>
const rows=JSON.parse(document.getElementById('data').textContent),$=id=>document.getElementById(id),size=30;let page=0,filtered=[];
const esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function select(index,scroll=false){const r=rows[index];$('title').textContent=r.name;$('original').src=r.original;$('upscaled').src=r.output;$('original-link').href=r.original;$('upscaled-link').href=r.output;$('dimensions').textContent=`${r.input_size.join(' × ')} → ${r.output_size.join(' × ')} · ${r.input_mode==='RGBA'?'Trasparenza preservata':'Immagine opaca'}`;$('split').value=50;$('viewer').style.setProperty('--split','50%');if(scroll)$('comparison').scrollIntoView({behavior:'smooth',block:'start'});}
function render(){const pages=Math.max(1,Math.ceil(filtered.length/size));$('count').textContent=`${filtered.length} carte corrispondenti su 288`;$('page').textContent=`Pagina ${page+1} / ${pages}`;$('prev').disabled=page===0;$('next').disabled=page>=pages-1;$('cards').innerHTML=filtered.slice(page*size,(page+1)*size).map(r=>`<button class="card" data-index="${r.index}" aria-label="Confronta ${esc(r.name)}"><img src="miniature/${encodeURIComponent(r.name)}.jpg" alt="${esc(r.name)}" loading="lazy"><span>${esc(r.name)}</span></button>`).join('');for(const b of $('cards').querySelectorAll('button'))b.onclick=()=>select(Number(b.dataset.index),true);}
function filter(){const q=$('query').value.toLowerCase().trim();filtered=rows.map((r,index)=>({...r,index})).filter(r=>(!q||r.name.toLowerCase().includes(q))&&(!$('category').value||r.category===$('category').value));page=0;render();}
$('split').oninput=()=>{$('viewer').style.setProperty('--split',$('split').value+'%')};$('query').oninput=filter;$('category').onchange=filter;$('prev').onclick=()=>{page--;render()};$('next').onclick=()=>{page++;render()};select(rows.findIndex(r=>r.name==='Creature_Pig'));filter();
</script></html>'''
    (root / "index.html").write_text(template.replace("__DATA__", payload))
    names = ["Creature_Pig", "Creature_DrStuffenstein", "Creature_IceKnight", "Building_BlueCastle", "Building_CandyIgloo", "Building_Windmill_Ghost", "Spell_FallingStar", "Spell_ToiletOfDoom", "Spell_RingOfSnakeEye"]
    sheet = Image.new("RGB", (960, 1100), "#111820")
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 18)
    title = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 28)
    draw.text((20, 15), "Card Wars — 288 illustrazioni in 2x", fill="#edf3f8", font=title)
    draw.text((20, 53), "9 campioni del lotto · sfondo uniforme · alpha preservata", fill="#bdcddd", font=font)
    for i, name in enumerate(names):
        x, y = 20 + (i % 3)*320, 95 + (i // 3)*330
        with Image.open(root / "upscaled" / f"{name}.png") as image:
            tile = image.convert("RGBA")
            tile.thumbnail((285, 285), Image.Resampling.LANCZOS)
            bg = Image.new("RGBA", tile.size, "#e0e3e6")
            bg.alpha_composite(tile)
            sheet.paste(bg.convert("RGB"), (x, y))
        draw.text((x, y+291), name.replace("Creature_", "").replace("Building_", "").replace("Spell_", ""), fill="#edf3f8", font=font)
    sheet.save(root / "campioni.png")
    target = root.parent / "CardWars-carte-2x.zip"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=4) as archive:
        for dirname in ("originals", "upscaled", "miniature"):
            for path in sorted((root / dirname).iterdir()):
                archive.write(path, Path(root.name) / path.relative_to(root))
        for name in ("index.html", "manifest.json", "LEGGIMI.txt", "campioni.png"):
            archive.write(root / name, Path(root.name) / name)
    with zipfile.ZipFile(target) as archive:
        assert archive.testzip() is None
        assert len([n for n in archive.namelist() if "/upscaled/" in n]) == 288
    print(f"Gallery and verified ZIP: {target} ({target.stat().st_size / 1024**2:.1f} MiB)")


if __name__ == "__main__":
    main()
