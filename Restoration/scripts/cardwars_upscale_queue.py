"""Prepare and run the remaining Card Wars graphic assets as a local queue.

Only writes under outputs/. One GPU process at a time, tile 128, 2:1:2
load/process/save threads. Reuses only pixel-identical source images.
Run --prepare first, then --run. The runner is resumable and process-locked.
"""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import fcntl
import gc
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
import traceback

import UnityPy
from PIL import Image, ImageChops

from cardwars_upscale_cards import sha, write_json


ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "outputs/cardwars-altri-asset-2x"
INVENTORY = ROOT / "outputs/cardwars-inventario/inventario.json"
BINARY = ROOT / "work/upscale-tools/realesrgan-ncnn-vulkan-v0.2.0-macos/realesrgan-ncnn-vulkan"
MODELS = ROOT / "work/upscale-tools/models"
LABELS = {"screens": "Schermate e loghi", "maps": "Mappe e percorsi", "ui": "Interfaccia e atlanti", "scenery": "Scenari e ambienti", "characters": "Personaggi e oggetti", "effects": "Effetti e animazioni", "card_variants": "Varianti delle carte"}


def now():
    return datetime.now(timezone.utc).isoformat()


def save(queue):
    queue["updated_at_utc"] = now()
    write_json(OUT / "queue.json", queue)
    write_json(OUT / "progress.json", {"status": queue["status"], "stage": queue.get("stage"), "pid": os.getpid(), "total": len(queue["assets"]), "completed": sum(r.get("validated", False) for r in queue["assets"]), "jobs": [{k: j[k] for k in ("key", "label", "count", "status")}|{k: j[k] for k in ("gpu_written", "gpu_total") if k in j} for j in queue["jobs"]], "updated_at_utc": queue["updated_at_utc"], "error": queue.get("error")})


def prepare():
    if (OUT / "queue.json").exists():
        print("Existing queue preserved:", OUT / "queue.json")
        return
    inventory = json.loads(INVENTORY.read_text())
    completed = json.loads((ROOT / "outputs/cardwars-carte-2x/manifest.json").read_text())
    assert completed["status"] == "complete"
    completed_ids = {r["id"] for r in completed["cards"]}
    selected = [r for r in inventory["textures"] if r["id"] not in completed_ids and not r.get("runtime_generated") and r["category"] != "technical"]
    for directory in ["originals", "upscaled", "cache", "inputs", "logs", "miniature"]:
        (OUT / directory).mkdir(parents=True, exist_ok=True)
    records = []
    for row in selected:
        job = row["category"] if row["category"] not in ("creatures", "buildings", "spells") else "card_variants"
        assert job in LABELS
        stem = re.sub(r"[^A-Za-z0-9_.-]", "_", row["name"]).strip("_.") or "texture"
        filename = f"{Path(row['file']).stem}_{row['path_id']}_{stem}.png"
        records.append({"id": row["id"], "name": row["name"], "source": row["file"], "path_id": row["path_id"], "category": row["category"], "job": job, "family_primary": row["family_primary"], "low_variant": row["low_variant"], "input_size": [row["width"], row["height"]], "pixel_sha256": row["pixel_sha256"], "original": f"originals/{filename}", "output": f"upscaled/{job}/{filename}", "review_note": row["review_note"], "status": "queued"})
    assert len(records) == 1771 and len({r["output"] for r in records}) == 1771
    queue = {"status": "queued", "stage": "prepared", "created_at_utc": now(), "installation": inventory["installation"], "scale": 2, "model": "realesr-animevideov3-x2", "tile_size": 128, "threads": "2:1:2", "validation_threads": 2, "game_modified": False, "game_launched": False, "applied_to_game": False, "completed_card_assets": len(completed_ids), "excluded_runtime_fonts": inventory["summary"]["runtime_generated"], "remaining_primary_families": sum(r["family_primary"] for r in records), "jobs": [{"key": k, "label": label, "count": sum(r["job"] == k for r in records), "status": "queued"} for k, label in LABELS.items()], "assets": records, "note": "PNG extraction and upscale only. Preserve original alpha. Same names do not establish image identity. Atlas metadata, UVs, mipmaps, animation coherence and in-game rendering need review before integration."}
    save(queue)
    (OUT / "LEGGIMI.txt").write_text("CARD WARS — CODA RESTAURO 2×\n\n1.771 texture grafiche mancanti, incluse varianti ridotte e delle carte.\n766 famiglie principali ulteriori; le 288 carte già elaborate restano separate.\nFont dinamici esclusi: non contengono un'immagine salvata.\nUn solo processo GPU, tile 128, thread 2:1:2, priorità CPU ridotta.\nRiutilizzo esclusivamente per sorgenti con pixel, dimensioni e alpha identici.\nFile omonimi distinti conservano ID e percorsi diversi.\nTrasparenza originale ripristinata per ogni PNG finale.\nNessun file del gioco modificato, nessun gioco avviato.\nqueue.json: piano, stato e hash; progress.json: avanzamento sintetico.\nPer riprendere: eseguire scripts/cardwars_upscale_queue.py --run con il venv locale.\n")
    print(json.dumps({"remaining": len(records), "primary_families": queue["remaining_primary_families"], "jobs": queue["jobs"]}, ensure_ascii=False, indent=2))


def verify_cache(path, size):
    if not path.is_file():
        return False
    try:
        with Image.open(path) as image:
            image.load()
            return image.size == tuple(v * 2 for v in size)
    except Exception:
        return False


def run(queue):
    start = time.monotonic()
    game = Path(queue["installation"])
    # A detached GPU child can survive an interrupted parent. Wait for that
    # exact queue process before resuming; never overlap two GPU jobs.
    previous_gpu = queue.get("gpu_pid")
    if previous_gpu:
        while True:
            command = subprocess.run(["ps", "-p", str(previous_gpu), "-o", "command="], capture_output=True, text=True).stdout
            if str(BINARY) not in command or str(OUT / "cache") not in command:
                break
            print(f"Waiting for existing queue GPU process {previous_gpu}", flush=True)
            time.sleep(10)
        queue.pop("gpu_pid", None)
    if shutil.disk_usage(OUT).free < 15 * 1024**3:
        raise RuntimeError("Insufficient space for the full queue: need at least 15 GiB free")
    queue.update(status="running", stage="checking_sources", pid=os.getpid(), started_at_utc=queue.get("started_at_utc", now()))
    save(queue)
    inventory = json.loads(INVENTORY.read_text())
    expected = {r["file"]: r["sha256"] for r in inventory["source_files"]}
    paths = sorted({game / r["source"] for r in queue["assets"]})
    for p in list(paths):
        stream = p.with_name(p.name + ".resS")
        if stream.exists():
            paths.append(stream)
    fingerprints = {str(p): {"sha256": sha(p), "size": p.stat().st_size, "mtime_ns": p.stat().st_mtime_ns} for p in paths}
    for p in paths:
        if p.suffix == ".assets":
            assert fingerprints[str(p)]["sha256"] == expected[p.name], f"Inventory source changed: {p}"
    if queue.get("source_files"):
        assert fingerprints == queue["source_files"], "Source fingerprint differs from saved queue"
    queue["source_files"] = fingerprints
    # Seed the cache from the verified card batch and the five-image trial.
    for directory, list_key in [(ROOT / "outputs/cardwars-carte-2x", "cards"), (ROOT / "outputs/cardwars-upscale-5", "samples")]:
        previous = json.loads((directory / "manifest.json").read_text())
        for row in previous[list_key]:
            original = directory / row.get("original", f"originals/{row['name']}.png")
            output = directory / row.get("output", f"upscaled/{row['name']}.png")
            if sha(output) != row["output_sha256"]:
                raise RuntimeError(f"Previous output changed: {output}")
            with Image.open(original) as img:
                rgba = img.convert("RGBA")
                digest = hashlib.sha256(f"{rgba.width},{rgba.height},RGBA\0".encode() + rgba.tobytes()).hexdigest()
                cached = OUT / "cache" / f"{digest}.png"
                if not verify_cache(cached, img.size):
                    shutil.copy2(output, cached)
    queue["stage"] = "extracting"
    save(queue)
    for source in sorted({r["source"] for r in queue["assets"]}):
        records = [r for r in queue["assets"] if r["source"] == source]
        missing = [r for r in records if not (r.get("original_sha256") and (OUT / r["original"]).is_file() and sha(OUT / r["original"]) == r["original_sha256"])]
        if not missing:
            continue
        env = UnityPy.load(str(game / source))
        objects = {o.path_id: o for o in env.objects if o.type.name == "Texture2D"}
        for i, record in enumerate(missing):
            data = objects[record["path_id"]].read()
            image = data.image
            if image.mode not in ("RGB", "RGBA"):
                image = image.convert("RGBA")
            rgba = image.convert("RGBA")
            digest = hashlib.sha256(f"{rgba.width},{rgba.height},RGBA\0".encode() + rgba.tobytes()).hexdigest()
            assert digest == record["pixel_sha256"], record["id"]
            original = OUT / record["original"]
            image.save(original)
            record.update(input_mode=image.mode, original_sha256=sha(original), status="extracted")
            # Uniform-color textures have no detail to reconstruct. Double
            # their dimensions exactly, rather than hallucinating variation.
            if all(lo == hi for lo, hi in image.convert("RGB").getextrema()):
                cached = OUT / "cache" / f"{digest}.png"
                image.resize((image.width*2, image.height*2), Image.Resampling.NEAREST).save(cached)
                record["method"] = "uniform-color exact resize 2x"
            if (i + 1) % 75 == 0:
                save(queue)
                print(f"Extracted {source}: {i+1}/{len(missing)}", flush=True)
        del env, objects, data, image, rgba
        gc.collect()
        save(queue)
        print(f"Extracted {source}: {len(missing)}", flush=True)

    def finish(record):
        target = OUT / record["output"]
        if record.get("validated") and target.is_file() and sha(target) == record.get("output_sha256"):
            return record
        with Image.open(OUT / record["original"]) as original, Image.open(OUT / "cache" / f"{record['pixel_sha256']}.png") as raw:
            assert raw.size == (original.width*2, original.height*2)
            if original.mode == "RGBA":
                output = raw.convert("RGBA")
                alpha = original.getchannel("A").resize(output.size, Image.Resampling.BILINEAR)
                output.putalpha(alpha)
            else:
                output = raw.convert("RGB")
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_suffix(".tmp.png")
            output.save(temporary)
            temporary.replace(target)
            with Image.open(target) as saved:
                saved.load()
                assert saved.size == output.size and saved.mode == original.mode
                if original.mode == "RGBA":
                    assert ImageChops.difference(saved.getchannel("A"), alpha).getbbox() is None
                record.update(output_size=list(saved.size), output_mode=saved.mode, output_sha256=sha(target), validated=True, status="complete", alpha_policy="original mask bilinear 2x" if original.mode == "RGBA" else "opaque RGB")
                thumb = saved.convert("RGBA")
                thumb.thumbnail((240, 180), Image.Resampling.LANCZOS)
                bg = Image.new("RGBA", thumb.size, "#e0e3e6")
                bg.alpha_composite(thumb)
                name = hashlib.sha256(record["id"].encode()).hexdigest()[:20] + ".jpg"
                bg.convert("RGB").save(OUT / "miniature" / name, quality=88)
                record["thumbnail"] = "miniature/" + name
        return record

    for job in queue["jobs"]:
        records = [r for r in queue["assets"] if r["job"] == job["key"]]
        if job["status"] == "complete" and all(r.get("validated") and (OUT / r["output"]).is_file() and sha(OUT / r["output"]) == r["output_sha256"] for r in records):
            continue
        if shutil.disk_usage(OUT).free < 8 * 1024**3:
            raise RuntimeError("Free space below 8 GiB; queue stopped and can be resumed")
        job.update(status="running", started_at_utc=now())
        queue.update(stage=f"upscaling:{job['key']}")
        folder = OUT / "inputs" / job["key"] / f"run-{time.time_ns()}"
        folder.mkdir(parents=True, exist_ok=True)
        todo = {}
        for record in records:
            digest = record["pixel_sha256"]
            cached = OUT / "cache" / f"{digest}.png"
            if not verify_cache(cached, record["input_size"]):
                todo[digest] = record
        for digest, record in todo.items():
            destination = folder / f"{digest}.png"
            if not destination.exists():
                os.link(OUT / record["original"], destination)
        job["gpu_total"] = len(todo)
        save(queue)
        if todo:
            command = ["nice", "-n", "10", str(BINARY), "-i", str(folder), "-o", str(OUT / "cache"), "-s", "2", "-n", "realesr-animevideov3", "-m", str(MODELS), "-t", "128", "-j", "2:1:2", "-f", "png"]
            with (OUT / "logs" / f"{job['key']}.log").open("a") as log:
                process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
                queue["gpu_pid"] = process.pid
                previous_count = -1
                while process.poll() is None:
                    count = sum((OUT / "cache" / f"{digest}.png").exists() for digest in todo)
                    job["gpu_written"] = count
                    save(queue)
                    if count != previous_count:
                        print(f"{job['key']}: GPU {count}/{len(todo)}", flush=True)
                        previous_count = count
                    time.sleep(5)
            if process.returncode:
                raise RuntimeError(f"GPU job {job['key']} exited {process.returncode}; see its log")
            queue.pop("gpu_pid", None)
            job["gpu_written"] = len(todo)
        queue["stage"] = f"validating:{job['key']}"
        save(queue)
        with ThreadPoolExecutor(max_workers=2) as pool:
            for i, future in enumerate(as_completed([pool.submit(finish, record) for record in records])):
                future.result()
                if (i+1) % 25 == 0:
                    save(queue)
        job.update(status="complete", completed_at_utc=now())
        save(queue)
        print(f"{job['key']}: COMPLETE, {len(records)} validated PNGs", flush=True)
    queue["stage"] = "verifying_sources"
    save(queue)
    for p in paths:
        assert sha(p) == fingerprints[str(p)]["sha256"], f"Source bytes changed: {p}"
        assert p.stat().st_mtime_ns == fingerprints[str(p)]["mtime_ns"], f"Source mtime changed: {p}"
    assert all(r.get("validated") for r in queue["assets"])
    queue.update(status="complete", stage="complete", source_bytes_and_mtime_unchanged=True, finished_at_utc=now(), elapsed_this_run_seconds=round(time.monotonic()-start, 1))
    save(queue)
    print(f"COMPLETE: {len(queue['assets'])} remaining assets verified", flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--run", action="store_true")
    args = parser.parse_args()
    if args.prepare:
        prepare()
    if args.run:
        with (OUT / "worker.lock").open("w") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                print("Queue already has a worker; no duplicate GPU process started")
                return
            queue = json.loads((OUT / "queue.json").read_text())
            if queue["status"] == "complete":
                print("Queue already complete")
                return
            try:
                run(queue)
            except Exception as exc:
                queue.update(status="failed", stage="attention", error=f"{type(exc).__name__}: {exc}")
                save(queue)
                traceback.print_exc()
                raise


if __name__ == "__main__":
    main()
