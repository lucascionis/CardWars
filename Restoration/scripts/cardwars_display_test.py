"""Launch the installed Card Wars runtime with explicit display arguments."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess

BASE = Path('/Users/luca/Library/Application Support/GameToMac Local/CardWars')
ENGINE = BASE / 'engine-wine11-cache-f790fa00f71214bb-audio-input-v1'
FRAMEWORKS = BASE / 'deps/Frameworks'
OUT = Path(__file__).resolve().parents[1] / 'outputs/cardwars-collaudo-fullscreen'


def environment():
    prefixes = ['CX_', 'WINE', 'DYLD_', 'ROSETTA_', 'MTL_', 'D3DM_', 'DXMT_', 'GST_']
    env = {k: v for k, v in os.environ.items() if not any(k.startswith(p) for p in prefixes)}
    env.update(WINEPREFIX=str(BASE / 'prefix'), WINESERVER=str(ENGINE / 'bin/wineserver'),
               WINELOADER=str(ENGINE / 'bin/wine'), WINEDEBUG='-all', ROSETTA_ADVERTISE_AVX='1',
               WINEMSYNC='1', WINEESYNC='0', MTL_HUD_ENABLED='0', D3DM_ENABLE_METALFX='0',
               MVK_CONFIG_LOG_LEVEL='1',
               WINEDLLPATH=str(FRAMEWORKS / 'renderer/d3dmetal/wine') + ':' + str(ENGINE / 'lib/wine'),
               DYLD_FALLBACK_LIBRARY_PATH=str(FRAMEWORKS) + ':' + str(FRAMEWORKS / 'GStreamer.framework/Versions/1.0/lib') + ':/usr/lib',
               GST_PLUGIN_PATH=str(FRAMEWORKS / 'GStreamer.framework/Versions/1.0/lib/gstreamer-1.0'),
               GST_REGISTRY=str(BASE / 'gstreamer-registry.bin'),
               WINEDLLOVERRIDES='winemenubuilder.exe=;mscoree,mshtml=;gameoverlayrenderer,gameoverlayrenderer64=;dxgi,d3d11,d3d12,atidxx64=n,b;nvapi64,nvngx=')
    return env


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--windowed', action='store_true')
    p.add_argument('--no-audio-test', action='store_true')
    p.add_argument('--exe', type=Path, default=Path('/Users/luca/Games/CardWars/game/CardWars.exe'))
    args = p.parse_args()
    OUT.mkdir(exist_ok=True)
    backup = OUT / 'preferences-before-display-test'
    if not backup.exists():
        backup.mkdir()
        shutil.copy2(BASE / 'prefix/user.reg', backup / 'user.reg')
        saved = BASE / 'prefix/drive_c/users/crossover/AppData/LocalLow/shishkabob/Card Wars'
        shutil.copytree(saved, backup / 'saved-game')
    env = environment()
    if args.no_audio_test:
        env['WINEDLLOVERRIDES'] += ';winecoreaudio.drv='
    command = [str(ENGINE / 'bin/wine'), str(args.exe), '-force-d3d11',
               '-screen-fullscreen', '0' if args.windowed else '1',
               '-screen-width', '1920', '-screen-height', '1080', '-window-mode', 'borderless', '-monitor', '1']
    print(command, flush=True)
    with (OUT / ('windowed.log' if args.windowed else 'fullscreen.log')).open('w') as log:
        process = subprocess.Popen(command, env=env, cwd=args.exe.parent, stdout=log, stderr=log)
        (OUT / 'pid.txt').write_text(str(process.pid))
        print('PID', process.pid, flush=True)
        code = process.wait()
    print('Exit', code, flush=True)
