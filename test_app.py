import queue
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

import app


class AppTest(unittest.TestCase):
    def test_shared_data_location(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old = app.Store(root / 'data' / 'library.sqlite3')
            old.save(app.DEFAULTS | {'template': 'legacy_{title}'})
            old.db.close()
            with patch.dict('os.environ', {'LOCALAPPDATA': str(root / 'profile')}), patch.object(app, 'ROOT', root):
                target = app.database_path()
                migrated = app.Store(target)
                self.assertEqual(migrated.settings()['template'], 'legacy_{title}')
                migrated.save(app.DEFAULTS | {'template': 'updated_{title}'})
                migrated.db.close()
                self.assertEqual(app.database_path(), target)
                with patch.object(app, 'ROOT', root / 'different-install'):
                    self.assertEqual(app.database_path(), target)
                reopened = app.Store(target)
                self.assertEqual(reopened.settings()['template'], 'updated_{title}')
                reopened.db.close()
            self.assertTrue((root / 'data' / 'library.sqlite3').is_file())

    def test_local_workflow(self):
        video_id = 'BaW_jenozKc'
        canonical = f'https://www.youtube.com/watch?v={video_id}'
        for url in (canonical + '&list=PL123&index=2', f'https://youtu.be/{video_id}?si=abc',
                    f'https://music.youtube.com/watch?v={video_id}', f'https://www.youtube.com/shorts/{video_id}'):
            self.assertEqual(app.video_url(url), (video_id, canonical))
        for url in ('https://youtube.com/playlist?list=123', 'file:///tmp/test',
                    f'https://youtube.com.evil.example/watch?v={video_id}', 'https://youtube.com/watch?v=bad'):
            with self.assertRaises(ValueError):
                app.video_url(url)
        info = {'id': video_id, 'title': '音楽:テスト/曲', 'uploader': '投稿者'}
        self.assertEqual(app.filename('{uploader} - {title}', info), '投稿者 - 音楽_テスト_曲')
        self.assertEqual(app.filename('CON', info), '_CON')
        for template in ('', '{other}', '{title.__class__}', '{title!r}'):
            with self.assertRaises(ValueError):
                app.filename(template, info)

        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            settings = app.DEFAULTS | {'folder': str(folder), 'quality': app.QUALITIES[2], 'template': '{uploader} - {title}'}
            database = folder / 'library.sqlite3'
            store = app.Store(database)
            self.assertEqual(store.settings(), app.DEFAULTS)
            self.assertEqual(store.settings()['quality'], 'MP3 / 320 kbps')
            self.assertEqual(app.QUALITIES[-1], app.ORIGINAL_AUDIO)
            store.save({'quality': '最高音質（元の音声・無変換）'})
            self.assertEqual(store.settings()['quality'], app.ORIGINAL_AUDIO)
            store.save(settings)
            store.db.close()
            store = app.Store(database)
            self.assertEqual(store.settings(), settings)

            class LocalYoutubeDL:
                def __init__(self, options):
                    self.options = options
                    self.path = Path(options['outtmpl'].replace('%(ext)s', 'wav'))

                def __enter__(self):
                    return self

                def __exit__(self, *args):
                    pass

                def extract_info(self, url, download):
                    assert url == canonical and download and self.options['noplaylist']
                    assert self.options['format'] == 'bestaudio'
                    with wave.open(str(self.path), 'wb') as audio:
                        audio.setparams((1, 2, 44100, 0, 'NONE', 'not compressed'))
                        audio.writeframes(b'\0\0' * 4410)
                    self.options['progress_hooks'][0]({'status': 'finished'})
                    return info

                def prepare_filename(self, metadata):
                    return str(self.path)

            events = queue.Queue()
            with patch('yt_dlp.YoutubeDL', LocalYoutubeDL):
                for quality in app.QUALITIES:
                    for repeat in range(2):
                        app.download(canonical, settings | {'quality': quality}, events)
                        messages = []
                        while not events.empty():
                            messages.append(events.get_nowait())
                        kind, payload = messages[-1]
                        self.assertEqual(kind, 'complete', payload)
                        metadata, selected, path = payload
                        self.assertGreater(path.stat().st_size, 0)
                        self.assertEqual(path.suffix, '.wav' if quality == app.ORIGINAL_AUDIO else '.mp3')
                        store.record(metadata, selected, path)
            self.assertEqual(len(store.history()), 8)
            self.assertEqual(len({row[4] for row in store.history()}), 8)
            self.assertIsNotNone(store.previous(video_id))
            with patch('yt_dlp.YoutubeDL', side_effect=RuntimeError('network unavailable')):
                app.download(canonical, settings, events)
            self.assertEqual(events.get_nowait(), ('error', 'network unavailable'))
            self.assertFalse(list(folder.glob('.music-*')))
            store.db.close()

            window = app.App(database)
            window.withdraw()
            try:
                window.update()
                self.assertEqual(window.vars['template'].get(), settings['template'])
                self.assertEqual(len(window.tree.get_children()), 8)
                window.url.set(canonical + '&list=test')
                with patch('app.messagebox.askyesno', return_value=False) as confirm, patch('app.threading.Thread') as worker:
                    window.start()
                    confirm.assert_called_once()
                    worker.assert_not_called()
                with patch('app.messagebox.askyesno', return_value=True), patch('app.threading.Thread') as worker:
                    window.start()
                    worker.return_value.start.assert_called_once()
                    self.assertTrue(window.busy)
                window.events.put(('error', 'test error'))
                with patch('app.messagebox.showerror') as error:
                    window.poll()
                    error.assert_called_once()
                self.assertFalse(window.busy)
            finally:
                window.store.db.close()
                window.destroy()


if __name__ == '__main__':
    unittest.main()
