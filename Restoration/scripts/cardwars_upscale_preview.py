"""Validate the five local Real-ESRGAN samples and build comparison artifacts.

Run after extraction and the native upscale command recorded in manifest.json.
Only writes inside the supplied preview directory; never modifies the game.
"""
import argparse
import hashlib
import html
import json
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFont


DETAILS = {
    "Creature_Pig": ("Il Maiale", (270, 150, 398, 278)),
    "Building_BlueCastle": ("Castello blu", (180, 180, 308, 308)),
    "Spell_FallingStar": ("Stella cadente", (20, 220, 148, 348)),
    "Loading_Main_16_9": ("Schermata principale", (415, 90, 543, 218)),
    "SideQuest_Valentine_Atlas": ("Atlante interfaccia", (140, 650, 268, 778)),
}


def checker(size):
    img = Image.new("RGB", size, "#e4e6e8")
    draw = ImageDraw.Draw(img)
    for y in range(0, size[1], 16):
        for x in range(0, size[0], 16):
            if (x // 16 + y // 16) % 2:
                draw.rectangle((x, y, x + 15, y + 15), fill="#ccd0d4")
    return img


def flattened(img):
    bg = checker(img.size)
    bg.paste(img, (0, 0), img.getchannel("A") if img.mode == "RGBA" else None)
    return bg


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    root = args.directory.resolve()
    manifest = json.loads((root / "manifest.json").read_text())
    canvas = Image.new("RGB", (1200, 2070), "#10141b")
    draw = ImageDraw.Draw(canvas)
    font_path = "/System/Library/Fonts/Supplemental/Arial.ttf"
    title_font = ImageFont.truetype(font_path, 32)
    label_font = ImageFont.truetype(font_path, 21)
    small_font = ImageFont.truetype(font_path, 17)
    draw.text((30, 20), "Card Wars - prova upscale 2x", font=title_font, fill="white")
    draw.text((30, 64), "Campione | Originale interpolato 2x (Lanczos) | Real-ESRGAN 2x", font=label_font, fill="#afbdd0")
    (root / "details").mkdir(exist_ok=True)
    articles = []
    for index, row in enumerate(manifest["samples"]):
        name = row["name"]
        title, box = DETAILS[name]
        original_path = root / "originals" / f"{name}.png"
        output_path = root / "upscaled" / f"{name}.png"
        original = Image.open(original_path)
        output = Image.open(output_path)
        assert output.size == tuple(v * 2 for v in original.size), name
        # NCNN also processes alpha. Restore a deterministic interpolation of
        # the original mask so inference cannot invent/remove transparency.
        if original.mode == "RGBA":
            output = output.convert("RGBA")
            alpha = original.getchannel("A").resize(output.size, Image.Resampling.BILINEAR)
            output.putalpha(alpha)
            output.save(output_path)
            assert ImageChops.difference(output.getchannel("A"), alpha).getbbox() is None
        else:
            output = output.convert("RGB")
            output.save(output_path)
        original_crop = original.crop(box).resize((256, 256), Image.Resampling.LANCZOS).resize((360, 360), Image.Resampling.NEAREST)
        output_crop = output.crop(tuple(v * 2 for v in box)).resize((360, 360), Image.Resampling.NEAREST)
        original_crop.save(root / "details" / f"{name}-original.png")
        output_crop.save(root / "details" / f"{name}-2x.png")
        y = 120 + index * 388
        draw.text((30, y), title, font=label_font, fill="white")
        draw.text((650, y), f"{original.width} x {original.height} -> {output.width} x {output.height}", font=small_font, fill="#afbdd0")
        thumb = flattened(original)
        thumb.thumbnail((220, 300), Image.Resampling.LANCZOS)
        canvas.paste(thumb, (30, y + 42))
        canvas.paste(flattened(original_crop), (300, y + 28))
        canvas.paste(flattened(output_crop), (800, y + 28))
        row.update(original_sha256=hashlib.sha256(original_path.read_bytes()).hexdigest(),
                   output_sha256=hashlib.sha256(output_path.read_bytes()).hexdigest(),
                   output_size=list(output.size), mode=output.mode,
                   alpha_policy="original mask, bilinear 2x" if original.mode == "RGBA" else "opaque RGB",
                   detail_box=list(box))
        row.pop("sha256", None)
        articles.append(f'''<article><div class="heading"><h2>{html.escape(title)}</h2><span>{original.width} × {original.height} → {output.width} × {output.height}</span></div>
<div class="compare"><img src="upscaled/{name}.png" alt="Upscale 2× di {title}"><img class="original" src="originals/{name}.png" alt="Originale di {title}"><div class="line"></div></div>
<label class="slider">Originale <input type="range" min="0" max="100" value="50" aria-label="Confronto {title}" oninput="this.closest('article').style.setProperty('--split',this.value+'%')"> Upscale 2×</label>
<details><summary>Dettaglio a ingrandimento uguale</summary><div class="detail"><figure><img src="details/{name}-original.png" alt="Dettaglio originale"><figcaption>Originale · interpolazione Lanczos 2×</figcaption></figure><figure><img src="details/{name}-2x.png" alt="Dettaglio upscale"><figcaption>Real-ESRGAN 2× · stesso ritaglio</figcaption></figure></div></details>
<p class="links"><a href="originals/{name}.png">Originale PNG</a><a href="upscaled/{name}.png">Upscale PNG</a></p></article>''')
    canvas.save(root / "comparison.png")
    manifest.update(model="realesr-animevideov3-x2", backend="Real-ESRGAN NCNN Vulkan v0.2.0 (arm64, local)",
                    unitypy_version="1.25.4", game_modified=False, game_launched=False,
                    note="Visual proof only. Atlas metadata and in-game rendering have not been tested.",
                    command="realesrgan-ncnn-vulkan -i originals -o upscaled -s 2 -n realesr-animevideov3 -m MODELS -t 128 -j 1:1:1")
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    page = '''<!doctype html><html lang="it"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Card Wars · prova upscale 2×</title>
<style>body{margin:0;background:#10141b;color:#f4f5f7;font:16px system-ui,sans-serif}main{max-width:1050px;margin:auto;padding:40px 24px}h1{font-size:36px;margin:8px 0}header p{color:#afbdd0;line-height:1.6}article{--split:50%;background:#1a222f;padding:22px;border-radius:16px;margin:28px 0}.heading{display:flex;justify-content:space-between;align-items:center;gap:12px}.heading span{color:#afbdd0;font-size:14px}h2{font-size:22px}.compare{position:relative;background:repeating-conic-gradient(#d5d8dc 0% 25%,#f0f1f3 0% 50%) 50%/24px 24px;overflow:hidden;border-radius:8px}.compare img{display:block;width:100%;height:auto}.compare .original{position:absolute;inset:0;clip-path:inset(0 calc(100% - var(--split)) 0 0)}.line{position:absolute;left:var(--split);top:0;bottom:0;width:2px;background:white;box-shadow:0 0 6px #000}.slider{display:flex;gap:18px;align-items:center;margin:18px 0;white-space:nowrap}.slider input{width:100%;accent-color:#b7d9ff}a{color:#b7d9ff}.links{display:flex;gap:22px}summary{cursor:pointer;color:#b7d9ff}.detail{display:flex;gap:18px;margin:18px 0}.detail figure{margin:0;flex:1;min-width:0}.detail img{width:100%;background:#d5d8dc}.detail figcaption{font-size:13px;color:#afbdd0;margin-top:8px}@media(max-width:600px){.heading{display:block}.slider{font-size:13px;gap:8px}.detail{gap:8px}main{padding:24px 12px}}</style>
<main><header><h1>Card Wars · prova upscale 2×</h1><p>Cinque risorse estratte dalla copia installata. Elaborazione locale con Real-ESRGAN.<br>Trascina i cursori: a sinistra l'originale ingrandito, a destra la versione 2×.<br>Trasparenza originale preservata. Il gioco e i suoi salvataggi non sono stati modificati.</p></header>'''
    (root / "index.html").write_text(page + "\n".join(articles) + "</main></html>")
    print(f"Validated {len(manifest['samples'])} samples: {root}")


if __name__ == "__main__":
    main()
