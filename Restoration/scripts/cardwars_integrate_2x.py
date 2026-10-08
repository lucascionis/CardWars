"""Stage and verify Card Wars's local 2x restoration; never run the game.

Original files remain untouched. Texture streams are split below 2 GiB for
Unity 2017's 32-bit streaming offsets. All unrelated object payloads are
verified byte-for-byte after serialization, including scripts and meshes.
"""
import copy
import gc
import hashlib
import json
import math
import os
import struct
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import UnityPy
from PIL import Image
from UnityPy.export.Texture2DConverter import image_to_texture2d, parse_image_data
from UnityPy.helpers import TypeTreeHelper
from UnityPy.helpers.TypeTreeGenerator import TypeTreeGenerator

ROOT = Path(__file__).resolve().parents[1]
GAME = Path('/Users/luca/Games/CardWars/game')
STAGE = GAME.with_name('game-restored-2x-staging')
OUT = ROOT / 'outputs/cardwars-integrazione-2x'
LIMIT = 1536 * 1024 * 1024


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda: f.read(4 * 1024 * 1024), b''):
            h.update(b)
    return h.hexdigest()


def save(data):
    p = OUT / 'manifest.json'
    temp = p.with_suffix('.tmp')
    temp.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    temp.replace(p)


def key(ptr, af):
    if not ptr['m_PathID']:
        return None
    name = af.name
    if ptr['m_FileID']:
        name = af.externals[ptr['m_FileID'] - 1].path.replace('\\', '/').rsplit('/', 1)[-1]
    return f"{name}:{ptr['m_PathID']}"


def times2(d):
    for k in d:
        d[k] *= 2


def sprite_2x(d):
    times2(d['m_Rect'])
    times2(d['m_Offset'])
    times2(d['m_Border'])
    d['m_PixelsToUnits'] *= 2
    d['m_Extrude'] *= 2
    rd = d['m_RD']
    for k in ['textureRect', 'textureRectOffset', 'uvTransform']:
        times2(rd[k])
    if rd['atlasRectOffset'] != {'x': -1.0, 'y': -1.0}:
        times2(rd['atlasRectOffset'])
    # Mesh positions, normalized UVs, pivot and physics shapes are in world
    # or normalized units; preserving them keeps geometry and hitboxes intact.


def main():
    os.nice(10)
    OUT.mkdir(parents=True, exist_ok=True)
    inv = json.loads((ROOT / 'outputs/cardwars-inventario/inventario.json').read_text())
    queue = json.loads((ROOT / 'outputs/cardwars-altri-asset-2x/queue.json').read_text())
    records = {}
    for folder, name, items in [('cardwars-carte-2x', 'manifest.json', 'cards'),
                                ('cardwars-altri-asset-2x', 'queue.json', 'assets')]:
        base = ROOT / 'outputs' / folder
        d = json.loads((base / name).read_text())
        assert d['status'] == 'complete'
        for a in d[items]:
            assert a['validated'] and a['id'] not in records
            p = base / a['output']
            assert sha(p) == a['output_sha256'], a['id']
            records[a['id']] = dict(a, png=str(p))
    expected = {t['id'] for t in inv['textures'] if t['width'] and t['height']}
    assert set(records) == expected and len(records) == 2059
    # Also confirm source streams and metadata still match the validated batch.
    for p, info in queue['source_files'].items():
        assert sha(p) == info['sha256'], p
    for f in inv['source_files']:
        assert sha(GAME / 'CardWars_Data' / f['file']) == f['sha256'], f['file']
    if not STAGE.exists():
        subprocess.run(['/bin/cp', '-cR', str(GAME), str(STAGE)], check=True)
    data_dir = STAGE / 'CardWars_Data'
    generator = TypeTreeGenerator('2017.4.40f1')
    generator.load_local_dll_folder(str(GAME / 'CardWars_Data/Managed'))
    atlas_node = generator.get_nodes_up('Assembly-CSharp.dll', 'UIAtlas')
    next(c for c in atlas_node.m_Children if c.m_Name == 'm_Enabled').m_MetaFlag = 0x4000
    # UnityPyBoost ignores UInt8 alignment for this generated MonoBehaviour
    # header. The Python reader respects it; roundtrips below assert every byte.
    TypeTreeHelper.read_typetree_boost = None
    manifest_path = OUT / 'manifest.json'
    report = json.loads(manifest_path.read_text()) if manifest_path.exists() else {
        'status': 'staging', 'started_at_utc': datetime.now(timezone.utc).isoformat(),
        'original_game': str(GAME), 'staging_game': str(STAGE), 'scale': 2,
        'unity': '2017.4.40f1', 'game_launched': False, 'unity_editor_used': False,
        'texture_count': 2059, 'excluded_runtime_fonts': 3, 'files': [],
        'note': 'Lossless RGB/RGBA streams, full mip chains, source IDs retained; no game execution.'}
    done = {f['file']: f for f in report['files']}
    texture_files = sorted({a['source'] for a in records.values()})
    for name in texture_files:
        if name in done:
            assert sha(data_dir / name) == done[name]['sha256']
            for s in done[name]['streams']:
                assert sha(data_dir / s['file']) == s['sha256']
            print('Already verified:', name, flush=True)
            continue
        print('Packing:', name, flush=True)
        env = UnityPy.load(str(GAME / 'CardWars_Data' / name))
        af = next(o.assets_file for o in env.objects)
        original_hashes = {o.path_id: hashlib.sha256(o.get_raw_data()).hexdigest() for o in env.objects}
        scripts = {o.path_id: o.read().m_ClassName for o in env.objects if o.type.name == 'MonoScript'}
        materials = {}
        for o in env.objects:
            if o.type.name == 'Material':
                d = o.read_typetree()
                for slot, tex in d['m_SavedProperties']['m_TexEnvs']:
                    if slot == '_MainTex':
                        materials[f'{name}:{o.path_id}'] = key(tex['m_Texture'], af)
        stream = None
        streams = []
        textures = []
        changed = {}
        sprites = []
        atlases = []
        for o in env.objects:
            oid = f'{name}:{o.path_id}'
            if o.type.name == 'Texture2D' and oid in records:
                a = records[oid]
                t = o.read()
                original_raw = o.get_raw_data()
                t.save()
                assert o.data == original_raw, ('Texture roundtrip', oid)
                assert [t.m_Width, t.m_Height] == a['input_size'] and t.m_Name == a['name']
                old_format, old_mips = t.m_TextureFormat, t.m_MipCount
                # Four DXT originals use lossless storage to retain restored
                # pixels and original alpha without a second lossy compression.
                fmt = {10: 3, 12: 4}.get(old_format, old_format)
                assert fmt in (3, 4), (oid, fmt)
                mode = 'RGB' if fmt == 3 else 'RGBA'
                with Image.open(a['png']) as image:
                    im = image.convert(mode)
                width, height = im.size
                assert [width, height] == [x * 2 for x in a['input_size']]
                mip_count = 1 if old_mips == 1 else int(math.log2(max(width, height))) + 1
                encoded = bytearray()
                sizes = []
                mip = im
                for level in range(mip_count):
                    b, actual = image_to_texture2d(mip, fmt, af.target_platform, t.m_PlatformBlob)
                    assert int(actual) == fmt
                    encoded.extend(b)
                    sizes.append([mip.width, mip.height, len(b)])
                    if level + 1 < mip_count:
                        mip = mip.resize((max(1, mip.width // 2), max(1, mip.height // 2)), Image.Resampling.LANCZOS)
                if stream is None or stream.tell() + len(encoded) + 16 > LIMIT:
                    if stream:
                        stream.close()
                    sn = f'GameToMac_Restored2x_{Path(name).stem}_{len(streams):03d}.resS'
                    stream = (data_dir / sn).open('wb')
                    streams.append({'file': sn})
                stream.write(b'\0' * ((-stream.tell()) % 16))
                offset = stream.tell()
                stream.write(encoded)
                t.m_Width, t.m_Height = width, height
                t.m_TextureFormat = fmt
                t.m_MipCount = mip_count
                t.m_CompleteImageSize = len(encoded)
                t.image_data = b''
                t.m_StreamData.path = streams[-1]['file']
                t.m_StreamData.offset = offset
                t.m_StreamData.size = len(encoded)
                t.save()
                changed[o.path_id] = hashlib.sha256(o.data).hexdigest()
                textures.append({'id': oid, 'path_id': o.path_id, 'name': a['name'],
                    'png_sha256': a['output_sha256'], 'pixel_sha256': hashlib.sha256(im.tobytes()).hexdigest(),
                    'mode': mode, 'size': [width, height], 'original_format': old_format, 'format': fmt,
                    'original_mips': old_mips, 'mips': sizes, 'stream': t.m_StreamData.path,
                    'offset': offset, 'bytes': len(encoded), 'encoded_sha256': hashlib.sha256(encoded).hexdigest()})
                if len(textures) % 100 == 0:
                    print(name, 'textures', len(textures), flush=True)
                del encoded, b, im, mip
            elif o.type.name == 'Sprite':
                d = o.read_typetree()
                if key(d['m_RD']['texture'], af) not in records:
                    continue
                raw = o.get_raw_data()
                o.save_typetree(d)
                assert o.data == raw
                before = copy.deepcopy(d)
                sprite_2x(d)
                assert d['m_Rect']['width'] / d['m_PixelsToUnits'] == before['m_Rect']['width'] / before['m_PixelsToUnits']
                assert d['m_RD']['m_VertexData'] == before['m_RD']['m_VertexData']
                assert d['m_PhysicsShape'] == before['m_PhysicsShape']
                o.save_typetree(d)
                changed[o.path_id] = hashlib.sha256(o.data).hexdigest()
                sprites.append(o.path_id)
            elif o.type.name == 'MonoBehaviour':
                raw = o.get_raw_data()
                fid, sid = struct.unpack_from('<iq', raw, 16)
                if fid != 0 or scripts.get(sid) != 'UIAtlas':
                    continue
                d = o.read_typetree(atlas_node)
                assert d['m_Script']['m_PathID'] == sid
                o.save_typetree(d, atlas_node)
                assert o.data == raw
                tex = materials.get(key(d['material'], af))
                if tex not in records:
                    continue
                if d['mCoordinates'] == 0:
                    for sprite in d['sprites']:
                        times2(sprite['inner'])
                        times2(sprite['outer'])
                else:
                    assert d['mCoordinates'] == 1
                old_pixel = d['mPixelSize']
                d['mPixelSize'] /= 2
                o.save_typetree(d, atlas_node)
                changed[o.path_id] = hashlib.sha256(o.data).hexdigest()
                atlases.append({'path_id': o.path_id, 'texture': tex, 'sprites': len(d['sprites']),
                               'coordinates': d['mCoordinates'], 'old_pixel_size': old_pixel, 'pixel_size': d['mPixelSize']})
        if stream:
            stream.close()
        assert len(textures) == sum(a['source'] == name for a in records.values())
        target = data_dir / name
        temp = target.with_suffix('.restoration-tmp')
        temp.write_bytes(af.save())
        temp.replace(target)
        del env, af
        gc.collect()
        print('Verifying:', name, flush=True)
        check = UnityPy.load(str(target))
        assert set(original_hashes) == {o.path_id for o in check.objects}
        checked_textures = {a['path_id']: a for a in textures}
        for o in check.objects:
            digest = hashlib.sha256(o.get_raw_data()).hexdigest()
            assert digest == changed.get(o.path_id, original_hashes[o.path_id]), (name, o.path_id)
            if o.path_id not in checked_textures:
                continue
            a = checked_textures[o.path_id]
            t = o.read()
            assert [t.m_Width, t.m_Height] == a['size']
            assert t.m_MipCount == len(a['mips']) and t.m_TextureFormat == a['format']
            assert t.m_CompleteImageSize == a['bytes'] and t.m_StreamData.size == a['bytes']
            assert t.m_StreamData.path == a['stream'] and t.m_StreamData.offset == a['offset']
            assert not t.image_data
            with (data_dir / a['stream']).open('rb') as f:
                f.seek(a['offset'])
                encoded = f.read(a['bytes'])
            assert hashlib.sha256(encoded).hexdigest() == a['encoded_sha256']
            image = parse_image_data(encoded, *a['size'], a['format'], o.assets_file.version,
                                     o.assets_file.target_platform, t.m_PlatformBlob).convert(a['mode'])
            assert hashlib.sha256(image.tobytes()).hexdigest() == a['pixel_sha256'], a['id']
            assert sum(m[2] for m in a['mips']) == len(encoded)
            del encoded, image
        for s in streams:
            s.update(bytes=(data_dir / s['file']).stat().st_size, sha256=sha(data_dir / s['file']))
            assert s['bytes'] < LIMIT
        report['files'].append({'file': name, 'original_sha256': sha(GAME / 'CardWars_Data' / name),
            'sha256': sha(target), 'textures': textures, 'sprites': sprites, 'ngui_atlases': atlases,
            'streams': streams, 'object_count': len(original_hashes),
            'unchanged_object_payloads_verified': len(original_hashes) - len(changed),
            'changed_object_payloads_verified': len(changed), 'roundtrip_verified': True})
        save(report)
        del check
        gc.collect()
        print('Verified:', name, len(textures), 'textures,', len(sprites), 'sprites,', len(atlases), 'NGUI atlases', flush=True)
    assert sum(len(f['textures']) for f in report['files']) == 2059
    # Inventory all installation bytes, including untouched executable, DLLs,
    # levels, streams, scripts and audio. A completed manifest is the marker
    # used by GameToMac to advertise the installed restoration.
    originals = []
    patched = {f['file'] for f in report['files']}
    for original in sorted(GAME.rglob('*')):
        if not original.is_file():
            continue
        rel = original.relative_to(GAME)
        source_hash = sha(original)
        staged = STAGE / rel
        if not (rel.parent == Path('CardWars_Data') and rel.name in patched):
            assert sha(staged) == source_hash, str(rel)
        originals.append({'path': str(rel), 'sha256': source_hash, 'bytes': original.stat().st_size})
    report.update(status='verified', finished_at_utc=datetime.now(timezone.utc).isoformat(),
                  original_files=originals, original_installation_preserved=True,
                  restored_texture_bytes=sum(s['bytes'] for f in report['files'] for s in f['streams']))
    save(report)
    (STAGE / 'GameToMac-restoration-2x.json').write_text(json.dumps({
        'status': 'verified', 'scale': 2, 'texture_count': 2059,
        'manifest': str(OUT / 'manifest.json'), 'manifest_sha256': sha(OUT / 'manifest.json'),
        'game_launched': False, 'installed_at_utc': datetime.now(timezone.utc).isoformat()
    }, indent=2))
    print('RESTORATION VERIFIED — staging ready; original game has not been replaced.', flush=True)


if __name__ == '__main__':
    main()
