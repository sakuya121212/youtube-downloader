"""Build the shared folder payload for ZIP and installer distributions."""
import shutil
import json
import subprocess
import sys
import re
from importlib.metadata import distributions
from pathlib import Path

import PyInstaller.__main__
import prepare_ffmpeg


root = Path(__file__).resolve().parent
version = sys.argv[1] if len(sys.argv) == 2 else '0.0.0'
if not re.fullmatch(r'\d+\.\d+\.\d+', version):
    raise SystemExit('Version must be major.minor.patch.')
if sys.version_info < (3, 14, 7):
    raise SystemExit('Python 3.14.7+ is required to build the executable.')
prepare_ffmpeg.install_archive(prepare_ffmpeg.DIRECTORY / prepare_ffmpeg.ARCHIVE, prepare_ffmpeg.DIRECTORY)
node = shutil.which('node')
if not node:
    raise SystemExit('Node.js 22+ is required to build the executable.')
version_file = root / 'build' / 'VERSION'
version_file.parent.mkdir(exist_ok=True)
version_file.write_text(version, encoding='ascii')

PyInstaller.__main__.run([
    str(root / 'app.py'), '--name', 'YouTubeDownloader',
    '--onedir', '--windowed', '--noconfirm',
    '--distpath', str(root / 'dist'), '--workpath', str(root / 'build'),
    '--specpath', str(root / 'build'),
    '--collect-all', 'yt_dlp', '--collect-all', 'yt_dlp_ejs',
    '--add-binary', f'{node}:.',
    '--add-binary', f'{root / "tools" / "ffmpeg.exe"}:.',
    '--add-binary', f'{root / "tools" / "ffprobe.exe"}:.',
    '--add-data', f'{root / "tools" / "LICENSE"}:ffmpeg-license',
    '--add-data', f'{version_file}:.',
])
shutil.copy2(root / 'README.md', root / 'dist' / 'YouTubeDownloader' / 'README.md')
manifest = {
    'python': sys.version,
    'node': subprocess.check_output([node, '--version'], text=True).strip(),
    'ffmpeg': {'version': prepare_ffmpeg.VERSION, 'url': prepare_ffmpeg.URL, 'sha256': prepare_ffmpeg.SHA256},
    'packages': dict(sorted((d.metadata['Name'], d.version) for d in distributions())),
}
(root / 'dist' / 'YouTubeDownloader' / 'DEPENDENCIES.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
