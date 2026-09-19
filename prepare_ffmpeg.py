"""Fetch the pinned Windows x64 FFmpeg build; verify before extracting."""
import hashlib
import shutil
import urllib.request
import zipfile
from pathlib import Path

VERSION = '9.0.1'
ARCHIVE = f'ffmpeg-{VERSION}-essentials_build.zip'
URL = f'https://github.com/GyanD/codexffmpeg/releases/download/{VERSION}/{ARCHIVE}'
SHA256 = 'fec81ae03971d9dd4be3ebe02e263bd2ec1d789483f931bdba5f5715e65da2e9'
DIRECTORY = Path(__file__).resolve().parent / 'tools'


def install_archive(archive, destination):
    with archive.open('rb') as stream:
        if hashlib.file_digest(stream, 'sha256').hexdigest() != SHA256:
            raise ValueError('FFmpeg archive SHA-256 mismatch; nothing was extracted.')
    with zipfile.ZipFile(archive) as bundle:
        for member in ('bin/ffmpeg.exe', 'bin/ffprobe.exe', 'LICENSE'):
            with bundle.open(f'ffmpeg-{VERSION}-essentials_build/{member}') as source:
                with (destination / Path(member).name).open('wb') as output:
                    shutil.copyfileobj(source, output)


if __name__ == '__main__':
    DIRECTORY.mkdir(exist_ok=True)
    archive = DIRECTORY / ARCHIVE
    if not archive.exists():
        partial = archive.with_suffix('.download')
        with urllib.request.urlopen(URL, timeout=60) as source, partial.open('wb') as output:
            shutil.copyfileobj(source, output)
        partial.replace(archive)
    install_archive(archive, DIRECTORY)
    print(f'FFmpeg {VERSION}: verified and installed in {DIRECTORY}')
