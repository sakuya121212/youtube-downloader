import queue
import subprocess
import sys
import tempfile
import threading
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

import app


class AppTest(unittest.TestCase):
    def test_startup_error_and_discard_on_close(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / 'broken.sqlite3'
            database.write_bytes(b'broken database')
            with patch('app.messagebox.showerror') as error, self.assertRaises(SystemExit):
                app.App(database)
            self.assertIn(str(database), error.call_args.args[1])
            self.assertEqual(database.read_bytes(), b'broken database')
            window = app.App(Path(directory) / 'valid.sqlite3')
            window.withdraw()
            closed = False
            try:
                window.vars['folder'].set('')
                with patch('app.messagebox.showerror'), patch('app.messagebox.askyesno', return_value=False):
                    window.close()
                self.assertTrue(window.winfo_exists())
                with patch('app.messagebox.showerror'), patch('app.messagebox.askyesno', return_value=True):
                    closed = window.close()
                self.assertTrue(closed)
            finally:
                if not closed:
                    window.store.db.close()
                    window.destroy()
            window = app.App(Path(directory) / 'close.sqlite3')
            window.withdraw()
            window.busy = True
            with patch('app.messagebox.askyesno', return_value=True):
                window.close()
            window.events.put(('cancelled', None))
            with patch.object(window, 'destroy', wraps=window.destroy) as destroy:
                window.poll()
                destroy.assert_called_once()
            window = app.App(Path(directory) / 'finished.sqlite3')
            window.withdraw()
            window.busy = True

            def finish_while_confirming(*args, **kwargs):
                window.busy = False
                return True

            with patch('app.messagebox.askyesno', side_effect=finish_while_confirming):
                self.assertTrue(window.close())

    def test_cancel_during_publish(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            source = folder / 'source.wav'
            source.write_bytes(b'audio')
            cancel = threading.Event()
            real_check = app.check_cancel
            calls = 0

            def cancel_after_creation(event):
                nonlocal calls
                calls += 1
                if calls == 2:
                    cancel.set()
                real_check(event)

            with patch('app.check_cancel', side_effect=cancel_after_creation), self.assertRaises(app.Cancelled):
                app.publish(source, folder, 'target', cancel)
            self.assertFalse((folder / 'target.wav').exists())
            self.assertEqual(source.read_bytes(), b'audio')

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
                # A real sleeping child verifies that timeout/cancel actually reap the process.
                real_popen = subprocess.Popen
                for cancelled in (False, True):
                    cancel = threading.Event()
                    children = []

                    def stalled_conversion(*args, **kwargs):
                        child = real_popen([sys.executable, '-c', 'import time; time.sleep(60)'], **kwargs)
                        children.append(child)
                        if cancelled:
                            cancel.set()
                        return child

                    with patch('app.subprocess.Popen', side_effect=stalled_conversion), patch.object(app, 'CONVERSION_TIMEOUT', 0):
                        app.download(canonical, settings, events, cancel)
                    messages = []
                    while not events.empty():
                        messages.append(events.get_nowait())
                    self.assertEqual(messages[-1][0], 'cancelled' if cancelled else 'error')
                    if not cancelled:
                        self.assertIn('制限時間', messages[-1][1])
                    self.assertIsNotNone(children[0].poll())
                    self.assertFalse(list(folder.glob('.music-*')))

                cancel = threading.Event()
                cancel.set()
                app.download(canonical, settings, events, cancel)
                self.assertEqual(events.get_nowait(), ('cancelled', None))
                cancel.clear()

                class CancelYoutubeDL(LocalYoutubeDL):
                    def extract_info(self, url, download):
                        cancel.set()
                        return super().extract_info(url, download)

                with patch('yt_dlp.YoutubeDL', CancelYoutubeDL):
                    app.download(canonical, settings, events, cancel)
                self.assertEqual(events.get_nowait(), ('cancelled', None))
                self.assertFalse(list(folder.glob('.music-*')))
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
                window.busy = True
                with patch('app.messagebox.askyesno', return_value=False):
                    window.close()
                self.assertFalse(window.cancel_event.is_set())
                with patch('app.messagebox.askyesno', return_value=True):
                    window.close()
                self.assertTrue(window.cancel_event.is_set())
                self.assertTrue(window.close_pending)
                with patch.object(window, 'close') as close:
                    window.events.put(('cancelled', None))
                    window.poll()
                    close.assert_called_once()
                self.assertFalse(window.busy)
                before = {key: var.get() for key, var in window.vars.items()}
                with patch('app.messagebox.askyesno', return_value=False) as confirm:
                    window.reset_settings()
                    self.assertEqual(confirm.call_args.kwargs['icon'], 'warning')
                    self.assertEqual(confirm.call_args.kwargs['default'], 'no')
                self.assertEqual({key: var.get() for key, var in window.vars.items()}, before)
                self.assertEqual(window.store.settings(), before)
                with patch('app.messagebox.askyesno', return_value=True):
                    window.reset_settings()
                self.assertEqual({key: var.get() for key, var in window.vars.items()}, app.DEFAULTS)
                reopened = app.Store(database)
                self.assertEqual(reopened.settings(), app.DEFAULTS)
                self.assertEqual(len(reopened.history()), 8)
                self.assertTrue(all(Path(row[4]).is_file() for row in reopened.history()))
                reopened.db.close()
            finally:
                window.store.db.close()
                window.destroy()


if __name__ == '__main__':
    unittest.main()
