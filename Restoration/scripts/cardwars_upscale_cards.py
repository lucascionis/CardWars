"""Upscale the inventoried card illustrations locally, outside the game.

One tiled GPU worker; loading/saving use two threads each. Identical input
pixels share one inference result. A completed batch can be resumed safely.
"""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import gc
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import time

import UnityPy
from PIL import Image, ImageChops


def sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path, data):
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    temp.replace(path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--models", type=Path, required=True)
    args = parser.parse_args()
    inventory = json.loads(args.inventory.read_text())
    game = Path(inventory["installation"])
    out = args.output.resolve()
    if out.is_relative_to(game):
        raise ValueError("Output must be outside the game installation")
    for dirname in ["originals", "upscaled", "gpu-inputs", "gpu-results", "miniature"]:
        (out / dirname).mkdir(parents=True, exist_ok=True)
    selected = [r for r in inventory["textures"] if r["category"] in ("creatures", "buildings", "spells") and r["family_primary"]]
    assert len(selected) == 288, "Inventory changed: review selected batch size"
    manifest_path = out / "manifest.json"
    if manifest_path.exists():
        previous = json.loads(manifest_path.read_text())
        if previous.get("status") == "complete":
            assert len(previous["cards"]) == len(selected)
            for card in previous["cards"]:
                assert sha(out / card["output"]) == card["output_sha256"]
            print("Completed batch already verified; no second inference needed", flush=True)
            return
    source_files = sorted({game / r["file"] for r in selected})
    for p in list(source_files):
        stream = p.with_name(p.name + ".resS")
        if stream.exists():
            source_files.append(stream)
    baseline = {str(p): {"sha256": sha(p), "size": p.stat().st_size, "mtime_ns": p.stat().st_mtime_ns} for p in source_files}
    started = time.monotonic()
    manifest = {"status": "extracting", "started_at_utc": datetime.now(timezone.utc).isoformat(), "model": "realesr-animevideov3-x2", "backend": "Real-ESRGAN NCNN Vulkan v0.2.0, local Apple M3", "scale": 2, "tile_size": 128, "threads": {"load": 2, "gpu": 1, "save": 2, "validation": 2}, "game_modified": False, "game_launched": False, "applied_to_game": False, "source_files": baseline, "cards": [], "note": "Largest named variant per card family. This batch produces PNGs only; atlas metadata, mipmaps and in-game rendering are not yet validated."}
    write_json(manifest_path, manifest)
    canonical = {}
    for source in sorted({r["file"] for r in selected}):
        env = UnityPy.load(str(game / source))
        objects = {obj.path_id: obj for obj in env.objects if obj.type.name == "Texture2D"}
        for row in selected:
            if row["file"] != source:
                continue
            obj = objects[row["path_id"]]
            data = obj.read()
            image = data.image
            if image.mode not in ("RGB", "RGBA"):
                image = image.convert("RGBA")
            rgba = image.convert("RGBA")
            pixel_hash = hashlib.sha256(f"{rgba.width},{rgba.height},RGBA\0".encode() + rgba.tobytes()).hexdigest()
            assert pixel_hash == row["pixel_sha256"], f"Installed texture differs from inventory: {row['name']}"
            name = row["name"]
            assert Path(name).name == name and name not in (".", ".."), "Invalid image filename"
            original = out / "originals" / f"{name}.png"
            image.save(original)
            card = {"id": row["id"], "name": name, "category": row["category"], "source": source, "path_id": row["path_id"], "input_size": list(image.size), "input_mode": image.mode, "pixel_sha256": pixel_hash, "original": str(original.relative_to(out)), "original_sha256": sha(original), "output": f"upscaled/{name}.png", "alpha_policy": "original mask resized bilinear 2x" if image.mode == "RGBA" else "opaque RGB"}
            if pixel_hash not in canonical:
                canonical[pixel_hash] = card
                shutil.copy2(original, out / "gpu-inputs" / original.name)
            else:
                card["shared_inference_with"] = canonical[pixel_hash]["name"]
            manifest["cards"].append(card)
        del env, objects, obj, data, image, rgba
        gc.collect()
    manifest.update(status="upscaling", unique_inference_images=len(canonical), category_counts=dict(Counter(r["category"] for r in selected)))
    write_json(manifest_path, manifest)
    command = ["nice", "-n", "10", str(args.binary.resolve()), "-i", str(out / "gpu-inputs"), "-o", str(out / "gpu-results"), "-s", "2", "-n", "realesr-animevideov3", "-m", str(args.models.resolve()), "-t", "128", "-j", "2:1:2", "-f", "png"]
    manifest["command"] = command
    write_json(manifest_path, manifest)
    print(f"GPU batch: {len(selected)} cards, {len(canonical)} distinct images, threads 2:1:2, tile 128", flush=True)
    with (out / "gpu.log").open("w") as log:
        process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
        manifest["gpu_pid"] = process.pid
        write_json(manifest_path, manifest)
        previous_count = -1
        while process.poll() is None:
            completed = len(list((out / "gpu-results").glob("*.png")))
            status = {"stage": "upscaling", "completed_inference_files": completed, "total_inference_files": len(canonical), "total_cards": len(selected), "elapsed_seconds": round(time.monotonic() - started), "gpu_pid": process.pid}
            write_json(out / "progress.json", status)
            if completed != previous_count:
                print(f"GPU images written: {completed}/{len(canonical)}", flush=True)
                previous_count = completed
            time.sleep(5)
    if process.returncode:
        manifest.update(status="failed", gpu_exit_code=process.returncode)
        write_json(manifest_path, manifest)
        raise RuntimeError(f"Upscaler exited with {process.returncode}; inspect gpu.log")
    manifest["status"] = "validating"
    write_json(manifest_path, manifest)

    def finish(card):
        source = canonical[card["pixel_sha256"]]
        with Image.open(out / card["original"]) as original, Image.open(out / "gpu-results" / f"{source['name']}.png") as raw:
            assert raw.size == (original.width * 2, original.height * 2), card["name"]
            if original.mode == "RGBA":
                output = raw.convert("RGBA")
                alpha = original.getchannel("A").resize(output.size, Image.Resampling.BILINEAR)
                output.putalpha(alpha)
            else:
                output = raw.convert("RGB")
            target = out / card["output"]
            output.save(target)
            # Re-open the saved result, so checks validate delivered files.
            with Image.open(target) as saved:
                assert saved.size == output.size and saved.mode == original.mode
                if original.mode == "RGBA":
                    assert ImageChops.difference(saved.getchannel("A"), alpha).getbbox() is None
                card.update(output_size=list(saved.size), output_mode=saved.mode, output_sha256=sha(target), validated=True)
                thumb = saved.convert("RGBA")
                thumb.thumbnail((240, 240), Image.Resampling.LANCZOS)
                bg = Image.new("RGBA", thumb.size, "#e0e3e6")
                bg.alpha_composite(thumb)
                bg.convert("RGB").save(out / "miniature" / f"{card['name']}.jpg", quality=90)
            return card

    with ThreadPoolExecutor(max_workers=2) as pool:
        manifest["cards"] = list(pool.map(finish, manifest["cards"]))
    for p in source_files:
        assert sha(p) == baseline[str(p)]["sha256"], f"Source bytes changed: {p}"
        assert p.stat().st_mtime_ns == baseline[str(p)]["mtime_ns"], f"Source mtime changed: {p}"
    manifest.update(status="complete", source_bytes_and_mtime_unchanged=True, finished_at_utc=datetime.now(timezone.utc).isoformat(), elapsed_seconds=round(time.monotonic() - started, 1))
    write_json(manifest_path, manifest)
    write_json(out / "progress.json", {"stage": "complete", "validated_cards": len(manifest["cards"]), "total_cards": len(selected), "elapsed_seconds": manifest["elapsed_seconds"]})
    (out / "LEGGIMI.txt").write_text(f"CARD WARS — ILLUSTRAZIONI CARTE 2×\n\n288 PNG: 194 creature, 27 edifici, 67 magie.\n286 elaborazioni distinte; 2 copie pixel-identiche riutilizzano l'inferenza.\nModello locale: realesr-animevideov3-x2, tile 128, thread 2:1:2.\nTrasparenza originale preservata con interpolazione bilineare 2×.\nTutte le dimensioni, maschere alpha e PNG salvati sono verificati.\nFile sorgenti del gioco invariati, verificati con SHA256 e mtime.\nNessun gioco avviato. Queste immagini non sono applicate al gioco.\nPer il reinserimento occorre verificare atlanti/sprite, mipmap e rendering.\nDurata elaborazione e verifica: {manifest['elapsed_seconds']} secondi.\n\noriginals/: sorgenti estratte\nupscaled/: PNG finali\nmanifest.json: provenienza, hash, configurazione e verifiche\n")
    print(f"COMPLETE: {len(manifest['cards'])} cards validated in {manifest['elapsed_seconds']} seconds", flush=True)


if __name__ == "__main__":
    main()
