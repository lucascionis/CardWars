"""Verify extracted PNGs or release ZIPs without writing to the game.

Usage: python verify_delivery.py EXTRACTED_ROOT
       python verify_delivery.py --archives ZIP_DIRECTORY
"""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    parser.add_argument('--archives', action='store_true')
    args = parser.parse_args()
    manifest = json.loads(Path(__file__).with_name('textures.json').read_text())
    archives = []
    try:
        if args.archives:
            archives = [zipfile.ZipFile(p) for p in sorted(args.root.glob('*.zip'))]
            entries = [(z, name) for z in archives for name in z.namelist() if '/upscaled/' in name]
        for item in manifest['textures']:
            suffix = item['file'].split('/', 1)[1]
            if args.archives:
                candidates = [(z, n) for z, n in entries if n.endswith('/' + suffix)]
                if len(candidates) != 1:
                    raise RuntimeError('Missing or ambiguous output: ' + item['id'])
                z, name = candidates[0]
                data = z.read(name)
            else:
                path = args.root / item['file']
                if not path.is_file():
                    candidates = list(args.root.glob('CardWars-*-2x/' + suffix))
                    if len(candidates) != 1:
                        raise RuntimeError('Missing or ambiguous output: ' + item['id'])
                    path = candidates[0]
                data = path.read_bytes()
            if hashlib.sha256(data).hexdigest() != item['sha256']:
                raise RuntimeError('Hash mismatch: ' + item['id'])
        print('Verified', manifest['total'], 'restored textures')
    finally:
        for z in archives:
            z.close()


if __name__ == '__main__':
    main()
