import hashlib
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import prepare_ffmpeg


class ArchiveTest(unittest.TestCase):
    def test_verify_before_extracting_and_ignore_other_members(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            archive = folder / 'test.zip'
            with zipfile.ZipFile(archive, 'w') as bundle:
                for member in ('bin/ffmpeg.exe', 'bin/ffprobe.exe', 'LICENSE'):
                    bundle.writestr(f'ffmpeg-{prepare_ffmpeg.VERSION}-essentials_build/{member}', b'test')
                bundle.writestr('../outside', b'untrusted')
            with self.assertRaises(ValueError):
                prepare_ffmpeg.install_archive(archive, folder)
            self.assertEqual(list(folder.iterdir()), [archive])
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            with patch.object(prepare_ffmpeg, 'SHA256', digest):
                prepare_ffmpeg.install_archive(archive, folder)
            self.assertEqual({p.name for p in folder.iterdir()}, {'test.zip', 'ffmpeg.exe', 'ffprobe.exe', 'LICENSE'})
