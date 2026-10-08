# Card Wars restoration snapshot — 2026-10-08

This fork preserves the local Card Wars restoration developed for GameToMac.

## Delivered work

- 2,059 restored textures at 2×: 288 main card illustrations and 1,771 additional textures across seven batches. Three runtime-generated font textures were excluded.
- Local Real-ESRGAN NCNN Vulkan, `realesr-animevideov3-x2`, tile 128, threads 2:1:2, one GPU process, original alpha restored. Reuse only for pixel-identical sources.
- Windows Unity 2017.4.40f1 release integration: 1,087 Sprite metadata records and 44 NGUI atlases adjusted while preserving geometry and normalized UVs; streamed RGB24/RGBA32 textures split into 1,536 MiB chunks.
- Sampling patch: 212 new mip chains, 1,907 filter changes, 53 cameras with MSAA permitted. Existing quality settings request four samples; actual hardware MSAA has not been measured. Atlas regions are reduced separately with premultiplied-alpha BOX filtering. 38 unidentified atlases remain deferred.
- GameToMac launcher cover restored from 192×192 to 768×768.

## Downloads

[Restoration release](https://github.com/lucascionis/CardWars/releases/tag/restoration-2026-10-08) contains eight ZIP packages with original/restored images, comparison galleries, ID manifests, plus SHA256SUMS.txt. Large outputs are release assets rather than Git history. Cache, intermediate inference files, installed game binaries, backups and unrelated GameToMac projects are excluded.

`textures.json` maps all 2,059 verified outputs to serialized Unity file/path IDs and SHA-256 hashes. `reports/` preserves the integration, inventory and sampling evidence; personal filesystem prefixes have been replaced with placeholders in reports and delivery metadata. Reports describe the historical installation, not a fresh test of this repository.

## Current platform and integration status

The tested local installation is the Windows release running through Wine/D3DMetal on Apple Silicon. This fork does **not yet provide a macOS ARM64 build**. The original `Assets/` project has not yet received the restored images: release texture IDs must first be mapped to source textures/GUIDs by decoded pixel identity, then importer/atlas settings adjusted before rebuilding. Name equality alone is insufficient.

The archived scripts in `scripts/` are the actual local workflow, with original local paths and macOS-specific operations retained. They are not a general-purpose installer. Read and adapt their game/workspace/tool paths before running; use a fresh original 1.12.8 installation and regenerate inventory/queue rather than treating historical reports as runnable state. Integration stages a separate copy; the antialiasing script can replace an installation only with its explicit `--install` flag. Do not rerun against an already patched installation as though it were the original baseline.

Python dependencies are pinned in `requirements.txt`; Real-ESRGAN executable/models are separate dependencies. All image inference performed for this snapshot was local; Unity Editor was not used. `verify_delivery.py` verifies delivered PNG hashes without modifying game files.

## Verification and remaining review

All published restored PNGs were checked against their recorded output hashes, and ZIP CRC checks passed. Integration reports record byte-preservation checks for unrelated serialized objects. Runtime evidence confirms launch and a title-screen capture; it is not a complete gameplay/animation or 16:9 regression test. `finn-sampling-preview.png` is a sampling simulation, not an in-game screenshot.

Before source integration/release, review atlas gutters, UVs, coarse mip overlaps, embedded lettering, animation coherence, memory use, small icons and all gameplay screens. Native Apple Silicon support requires a compatible Unity upgrade and a separate build/test effort.

## Credits and rights

Original PC port: shishkabob27/CardWars. Card Wars/Adventure Time assets remain the property of their respective rights holders. This snapshot does not grant a new license over upstream code or game artwork and does not replace their original notices.
