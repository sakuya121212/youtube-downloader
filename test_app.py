import queue
import json
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
import wave
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import app


class AppTest(unittest.TestCase):
    def test_update_release(self):
        self.assertEqual(app.version_tuple('v0.1.2'), (0, 1, 2))
        self.assertIsNone(app.version_tuple('latest'))
        with tempfile.TemporaryDirectory() as directory, patch.object(app, 'RESOURCES', Path(directory)):
            self.assertIsNone(app.application_version())
            (Path(directory) / 'VERSION').write_text('0.1.2', encoding='ascii')
            self.assertEqual(app.application_version(), '0.1.2')
        self.assertEqual(
            app.update_release('0.1.2', {'tag_name': 'v0.1.3'}),
            ('v0.1.3', 'https://github.com/sakuya121212/youtube-downloader/releases/tag/v0.1.3'),
        )
        self.assertIsNone(app.update_release('0.1.3', {'tag_name': 'v0.1.3'}))
        self.assertIsNone(app.update_release('0.1.3', {'tag_name': 'not-a-version'}))

    def test_compact_layout_and_progress_states(self):
        with tempfile.TemporaryDirectory() as directory:
            window = app.App(Path(directory) / 'library.sqlite3')
            try:
                window.geometry('800x600')
                for tab in window.tabs.values():
                    window.notebook.select(tab)
                    window.update()
                    self.assertFalse(tab.details.winfo_ismapped())
                    tab.toggle_settings()
                    window.update()
                    self.assertTrue(tab.details.winfo_ismapped())
                    self.assertGreater(tab.tree.winfo_height(), 64)
                    path_field = next(widget for widget in tab.winfo_children()[0].winfo_children()
                                      if any(child.cget('text') == '保存ファイル' for child in widget.winfo_children()
                                             if isinstance(child, app.ttk.Label)))
                    self.assertLessEqual(path_field.winfo_rooty() + path_field.winfo_height(),
                                         window.winfo_rooty() + window.winfo_height())
                    tab.vars['template'].set('saved_{title}')
                    tab.toggle_settings()
                    self.assertEqual(tab.save()['template'], 'saved_{title}')
                    window.update()
                    self.assertEqual(tab.tree.xview(), (0.0, 1.0))
                    path = str(Path(directory) / 'long filename.mp3')
                    tab.refresh([('2026-09-23', 'title', 'uploader', 'MP3', path)])
                    tab.tree.selection_set(tab.tree.get_children()[0])
                    window.update()
                    self.assertEqual(tab.history_path.get(), path)
                    tab.refresh([])
                    window.update()
                    self.assertEqual(tab.history_path.get(), '')
                    for value in (None, 40, None):
                        tab.events.put(('progress', (value, 'processing')))
                        tab.poll()
                        self.assertEqual(str(tab.progress['mode']), 'indeterminate' if value is None else 'determinate')
                    for kind, payload in (
                        ('complete', ({'id': 'test', 'title': 'title'}, 'MP3', Path(path))),
                        ('cancelled', None), ('error', 'test error'),
                    ):
                        tab.set_progress(None)
                        tab.events.put((kind, payload))
                        with patch('app.messagebox.showerror'):
                            tab.poll()
                        self.assertEqual(str(tab.progress['mode']), 'determinate')
                        self.assertEqual(tab.progress['value'], 100 if kind == 'complete' else 0)
            finally:
                window.store.db.close()
                window.destroy()

    def test_separate_format_and_quality_controls(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / 'library.sqlite3'
            window = app.App(database)
            window.withdraw()
            try:
                for mode, tab in window.tabs.items():
                    original = '無変換' if mode == 'video' else '元の形式'
                    converted = 'AAC' if mode == 'video' else 'MP3'
                    for quality in tab.qualities:
                        tab.vars['quality'].set(quality)
                        tab.load_quality_controls()
                        self.assertEqual(tab.save()['quality'], quality)
                    tab.audio_format.set(converted)
                    tab.bitrate.set('192 kbps')
                    self.assertEqual(tab.save()['quality'], f'{converted} / 192 kbps')
                    tab.audio_format.set(original)
                    self.assertTrue(tab.bitrate_combo.instate(['disabled']))
                    self.assertEqual(tab.save()['quality'], app.VIDEO_AUDIO[0] if mode == 'video' else app.ORIGINAL_AUDIO)
                    tab.audio_format.set(converted)
                    self.assertTrue(tab.bitrate_combo.instate(['readonly', '!disabled']))
                    self.assertEqual(tab.bitrate.get(), '192 kbps')
                    tab.bitrate.set('invalid')
                    with patch('app.messagebox.showerror') as error:
                        self.assertIsNone(tab.save())
                        error.assert_called_once()
                    tab.bitrate.set('128 kbps')
                video = window.tabs['video']
                for resolution in app.VIDEO_QUALITIES:
                    video.vars['resolution'].set(resolution)
                    video.load_quality_controls()
                    self.assertEqual(video.save()['resolution'], resolution)
                video.container.set('MP4')
                video.resolution.set('1080p')
                self.assertTrue(window.close())
                window = app.App(database)
                window.withdraw()
                music, video = window.tabs.values()
                self.assertEqual((music.audio_format.get(), music.bitrate.get()), ('MP3', '128 kbps'))
                self.assertEqual((video.container.get(), video.resolution.get(), video.audio_format.get(), video.bitrate.get()),
                                 ('MP4', '1080p', 'AAC', '128 kbps'))
                for mode, tab in window.tabs.items():
                    with patch('app.messagebox.askyesno', return_value=True):
                        tab.reset_settings()
                    self.assertEqual(tab.save(), tab.defaults)
                    self.assertEqual(tab.bitrate_combo.instate(['disabled']), mode == 'video')
            finally:
                window.store.db.close()
                window.destroy()

    def test_video_workflow_and_tabs(self):
        import yt_dlp

        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            database = folder / 'library.sqlite3'
            # Upgrade a database from before tabs existed.
            with closing(sqlite3.connect(database)) as legacy:
                legacy.execute('CREATE TABLE history (id INTEGER PRIMARY KEY, video_id TEXT NOT NULL, title TEXT NOT NULL, uploader TEXT NOT NULL, saved_at TEXT NOT NULL, quality TEXT NOT NULL, path TEXT NOT NULL)')
                legacy.execute("INSERT INTO history VALUES (1, 'BaW_jenozKc', 'old', '', '2026-01-01', 'MP3', 'old.mp3')")
                legacy.commit()
            with closing(app.Store(database).db) as legacy:
                legacy.execute("INSERT INTO settings VALUES ('video.resolution', '360p')")
                legacy.commit()
            window = app.App(database)
            window.withdraw()
            music, video = window.tabs.values()
            try:
                self.assertEqual(window.title(), 'YouTube Downloader')
                self.assertEqual(video.vars['resolution'].get(), 'MKV / 360p')
                for old_resolution, label in zip(('最高画質', '2160p', '1440p', '1080p', '720p', '480p', '360p'), app.VIDEO_QUALITIES):
                    window.store.save({'resolution': old_resolution}, 'video')
                    self.assertEqual(window.store.settings('video')['resolution'], label)
                self.assertEqual(window.notebook.select(), str(music))
                self.assertEqual(len(music.tree.get_children()), 1)
                self.assertFalse(video.tree.get_children())
                music.vars['template'].set('music_{title}')
                video.vars['template'].set('video_{title}')
                video.vars['folder'].set(str(folder))
                video.container.set('MP4')
                video.resolution.set('360p')
                window.notebook.select(video)
                window.update()
                self.assertEqual(music.vars['template'].get(), 'music_{title}')
                self.assertTrue(window.close())
                window = app.App(database)
                window.withdraw()
                music, video = window.tabs.values()
                self.assertEqual(window.notebook.select(), str(music))
                self.assertEqual(music.vars['template'].get(), 'music_{title}')
                self.assertEqual(video.vars['template'].get(), 'video_{title}')
                self.assertEqual(video.vars['resolution'].get(), 'MP4 / 360p')
                video.resolution.set('invalid')
                with patch('app.messagebox.showerror') as error:
                    self.assertIsNone(video.save())
                    error.assert_called_once()
                with patch('app.messagebox.askyesno', return_value=True):
                    video.reset_settings()
                self.assertEqual(window.store.settings('video'), app.VIDEO_DEFAULTS)
                self.assertEqual(window.store.settings()['template'], 'music_{title}')

                formats = []
                for height in (360, 720):
                    fixture = folder / f'fixture{height}.mp4'
                    subprocess.run([str(app.FFMPEG), '-hide_banner', '-loglevel', 'error',
                                    '-f', 'lavfi', '-i', f'color=size={height * 2}x{height}:rate=10',
                                    '-t', '0.2', '-an', '-c:v', 'libx264', str(fixture)], check=True)
                    formats.append({'format_id': str(height), 'url': fixture.as_uri(), 'ext': 'mp4',
                                    'height': height, 'vcodec': 'h264', 'acodec': 'none'})
                audio = folder / 'fixture.m4a'
                subprocess.run([str(app.FFMPEG), '-hide_banner', '-loglevel', 'error', '-f', 'lavfi',
                                '-i', 'sine=frequency=440', '-t', '0.2', '-c:a', 'aac', str(audio)], check=True)
                formats.append({'format_id': 'audio', 'url': audio.as_uri(), 'ext': 'm4a',
                                'vcodec': 'none', 'acodec': 'aac'})

                class LocalYoutubeDL(yt_dlp.YoutubeDL):
                    def __init__(self, options):
                        super().__init__(options | {'enable_file_urls': True})

                    def extract_info(self, url, download=True):
                        return self.process_ie_result({'id': 'BaW_jenozKc', 'title': 'video',
                                                       'extractor': 'local', 'formats': formats}, download=download)

                with patch('yt_dlp.YoutubeDL', LocalYoutubeDL):
                    cases = [(f'{container} / {resolution}', quality) for container in ('MKV', 'MP4')
                             for resolution, quality in [('360p', quality) for quality in app.VIDEO_AUDIO]
                             + [('720p', app.VIDEO_AUDIO[0]), ('最高画質', app.VIDEO_AUDIO[0])]]
                    for resolution, quality in cases:
                        settings = app.VIDEO_DEFAULTS | {'folder': str(folder), 'resolution': resolution, 'quality': quality}
                        app.download('https://www.youtube.com/watch?v=BaW_jenozKc', settings, video.events, mode='video')
                        messages = []
                        while not video.events.empty():
                            messages.append(video.events.get_nowait())
                        kind, payload = messages[-1]
                        self.assertEqual(kind, 'complete', payload)
                        self.assertTrue(any(event == 'progress' and value[0] is None for event, value in messages))
                        info, selected, path = payload
                        self.assertEqual(path.suffix, '.' + resolution.split(' / ')[0].lower())
                        probe = subprocess.run([str(app.FFMPEG.with_name('ffprobe.exe')), '-v', 'error',
                                                '-show_streams', '-of', 'json', str(path)], check=True, capture_output=True, text=True)
                        streams = json.loads(probe.stdout)['streams']
                        self.assertEqual([stream['codec_type'] for stream in streams], ['video', 'audio'])
                        self.assertEqual(streams[0]['height'], 360 if resolution.endswith(' / 360p') else 720)
                        self.assertEqual(streams[1]['codec_name'], 'aac')
                        video.events.put((kind, payload))
                        video.poll()
                self.assertEqual(len(window.store.history('video')), len(cases))
                self.assertEqual(len(window.store.history()), 1)
                self.assertEqual(len({row[4] for row in window.store.history('video')}), len(cases))
                self.assertFalse(list(folder.glob('.video-*')))
                video.url.set('https://youtu.be/BaW_jenozKc')
                with patch('app.messagebox.askyesno', return_value=False), patch('app.threading.Thread') as worker:
                    video.start()
                    worker.assert_not_called()
                music.busy = video.busy = True
                with patch('app.messagebox.askyesno', return_value=True):
                    window.close()
                self.assertTrue(music.cancel_event.is_set() and video.cancel_event.is_set())
                music.events.put(('cancelled', None))
                music.poll()
                self.assertTrue(window.close_pending)
                video.events.put(('cancelled', None))
                with patch.object(window, 'close') as close:
                    video.poll()
                    close.assert_called_once()
            finally:
                window.store.db.close()
                window.destroy()

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
                window.tabs['music'].vars['folder'].set('')
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
            window.tabs['music'].busy = True
            with patch('app.messagebox.askyesno', return_value=True):
                window.close()
            window.tabs['music'].events.put(('cancelled', None))
            with patch.object(window, 'destroy', wraps=window.destroy) as destroy:
                window.tabs['music'].poll()
                destroy.assert_called_once()
            window = app.App(Path(directory) / 'finished.sqlite3')
            window.withdraw()
            window.tabs['music'].busy = True

            def finish_while_confirming(*args, **kwargs):
                window.tabs['music'].busy = False
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
                self.assertEqual(window.tabs['music'].vars['template'].get(), settings['template'])
                self.assertEqual(len(window.tabs['music'].tree.get_children()), 8)
                window.tabs['music'].url.set(canonical + '&list=test')
                with patch('app.messagebox.askyesno', return_value=False) as confirm, patch('app.threading.Thread') as worker:
                    window.tabs['music'].start()
                    confirm.assert_called_once()
                    worker.assert_not_called()
                with patch('app.messagebox.askyesno', return_value=True), patch('app.threading.Thread') as worker:
                    window.tabs['music'].start()
                    worker.return_value.start.assert_called_once()
                    self.assertTrue(window.tabs['music'].busy)
                window.tabs['music'].events.put(('error', 'test error'))
                with patch('app.messagebox.showerror') as error:
                    window.tabs['music'].poll()
                    error.assert_called_once()
                self.assertFalse(window.tabs['music'].busy)
                window.tabs['music'].busy = True
                with patch('app.messagebox.askyesno', return_value=False):
                    window.close()
                self.assertFalse(window.tabs['music'].cancel_event.is_set())
                with patch('app.messagebox.askyesno', return_value=True):
                    window.close()
                self.assertTrue(window.tabs['music'].cancel_event.is_set())
                self.assertTrue(window.close_pending)
                with patch.object(window, 'close') as close:
                    window.tabs['music'].events.put(('cancelled', None))
                    window.tabs['music'].poll()
                    close.assert_called_once()
                self.assertFalse(window.tabs['music'].busy)
                before = {key: var.get() for key, var in window.tabs['music'].vars.items()}
                with patch('app.messagebox.askyesno', return_value=False) as confirm:
                    window.tabs['music'].reset_settings()
                    self.assertEqual(confirm.call_args.kwargs['icon'], 'warning')
                    self.assertEqual(confirm.call_args.kwargs['default'], 'no')
                self.assertEqual({key: var.get() for key, var in window.tabs['music'].vars.items()}, before)
                self.assertEqual(window.store.settings(), before)
                with patch('app.messagebox.askyesno', return_value=True):
                    window.tabs['music'].reset_settings()
                self.assertEqual({key: var.get() for key, var in window.tabs['music'].vars.items()}, app.DEFAULTS)
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
