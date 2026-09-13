"""Build the shared folder payload for ZIP and installer distributions."""
import shutil
from pathlib import Path

import PyInstaller.__main__


root = Path(__file__).resolve().parent
node = shutil.which('node')
if not node:
    raise SystemExit('Node.js 22+ is required to build the executable.')

PyInstaller.__main__.run([
    str(root / 'app.py'), '--name', 'YouTubeMusicDownloader',
    '--onedir', '--windowed', '--noconfirm',
    '--distpath', str(root / 'dist'), '--workpath', str(root / 'build'),
    '--specpath', str(root / 'build'),
    '--collect-all', 'yt_dlp', '--collect-all', 'yt_dlp_ejs',
    '--collect-all', 'imageio_ffmpeg', '--add-binary', f'{node}:.',
])
shutil.copy2(root / 'README.md', root / 'dist' / 'YouTubeMusicDownloader' / 'README.md')
