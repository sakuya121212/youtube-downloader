import os
import queue
import re
import sqlite3
import string
import subprocess
import sys
import tempfile
import threading
import time
import json
import webbrowser
from contextlib import closing
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen
import tkinter as tk
from tkinter import filedialog, messagebox, ttk


ROOT = Path(sys.executable if getattr(sys, 'frozen', False) else __file__).resolve().parent
RESOURCES = Path(__file__).resolve().parent
FFMPEG = (RESOURCES if getattr(sys, 'frozen', False) else ROOT / 'tools') / 'ffmpeg.exe'
ORIGINAL_AUDIO = 'WebM / M4A / 無変換'
QUALITIES = ('MP3 / 320 kbps', 'MP3 / 192 kbps', 'MP3 / 128 kbps', ORIGINAL_AUDIO)
DEFAULTS = {'folder': str(Path.home() / 'Downloads'), 'quality': QUALITIES[0], 'template': '{title}'}
VIDEO_QUALITIES = tuple(f'{container} / {resolution}' for container in ('MKV', 'MP4')
                        for resolution in ('最高画質', '2160p', '1440p', '1080p', '720p', '480p', '360p'))
VIDEO_AUDIO = ('音声無変換', 'AAC / 320 kbps', 'AAC / 192 kbps', 'AAC / 128 kbps')
VIDEO_DEFAULTS = DEFAULTS | {'quality': VIDEO_AUDIO[0], 'resolution': VIDEO_QUALITIES[0]}
CONVERSION_TIMEOUT = 30 * 60
RELEASE_API = 'https://api.github.com/repos/sakuya121212/youtube-downloader/releases/latest'
RELEASE_PAGE = 'https://github.com/sakuya121212/youtube-downloader/releases/tag/'


class Cancelled(Exception):
    pass


def version_tuple(value):
    match = re.fullmatch(r'v?(\d+)\.(\d+)\.(\d+)', value)
    return tuple(map(int, match.groups())) if match else None


def application_version():
    try:
        version = (RESOURCES / 'VERSION').read_text(encoding='ascii').strip()
    except OSError:
        return None
    return version if version_tuple(version) else None


def update_release(current, release):
    tag = release.get('tag_name') if isinstance(release, dict) else None
    latest, installed = version_tuple(tag) if isinstance(tag, str) else None, version_tuple(current)
    if latest and installed and latest > installed:
        return tag, RELEASE_PAGE + tag


def fetch_update(current):
    try:
        request = Request(RELEASE_API, headers={'Accept': 'application/vnd.github+json', 'User-Agent': 'YouTubeDownloader'})
        with urlopen(request, timeout=5) as response:
            return update_release(current, json.load(response))
    except (OSError, TypeError, ValueError):
        return None


def check_cancel(cancel):
    if cancel is not None and cancel.is_set():
        raise Cancelled()


def database_path():
    base = Path(os.environ.get('LOCALAPPDATA') or Path.home() / 'AppData' / 'Local')
    target = base / 'YouTubeMusicDownloader' / 'library.sqlite3'
    legacy = ROOT / 'data' / 'library.sqlite3'
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists() and legacy.is_file():
        # SQLite backup includes committed changes even when the old DB uses WAL.
        with tempfile.TemporaryDirectory(dir=target.parent) as temporary:
            backup = Path(temporary) / 'library.sqlite3'
            with closing(sqlite3.connect(legacy.as_uri() + '?mode=ro', uri=True)) as source:
                with closing(sqlite3.connect(backup)) as destination:
                    source.backup(destination)
            # On Windows rename refuses to overwrite a concurrently created DB.
            try:
                backup.rename(target)
            except FileExistsError:
                pass
    return target


def video_url(value):
    parsed = urlparse(value.strip())
    host = (parsed.hostname or '').lower()
    if parsed.scheme not in ('http', 'https') or parsed.username or parsed.password:
        raise ValueError('YouTube の動画 URL を入力してください。')
    parts = parsed.path.strip('/').split('/')
    video_id = None
    if host == 'youtu.be' and len(parts) == 1:
        video_id = parts[0]
    elif host in ('youtube.com', 'www.youtube.com', 'm.youtube.com', 'music.youtube.com'):
        if parsed.path == '/watch':
            video_id = parse_qs(parsed.query).get('v', [None])[0]
        elif len(parts) == 2 and parts[0] in ('shorts', 'live', 'embed'):
            video_id = parts[1]
    if not video_id or not re.fullmatch(r'[A-Za-z0-9_-]{11}', video_id):
        raise ValueError('動画を特定できません。プレイリストの場合も、動画の v= がある URL を入力してください。')
    return video_id, f'https://www.youtube.com/watch?v={video_id}'


def filename(template, info):
    if not template.strip():
        raise ValueError('ファイル名の設定を入力してください。')
    for _, field, spec, conversion in string.Formatter().parse(template):
        if field is not None and (field not in ('title', 'uploader', 'id') or spec or conversion):
            raise ValueError('使える差し込みは {title}、{uploader}、{id} です。')
    result = template.format(**{k: str(info.get(k) or '不明') for k in ('title', 'uploader', 'id')})
    result = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', result).strip().rstrip('.')
    result = result[:160].rstrip(' .')
    if not result:
        raise ValueError('有効なファイル名を設定してください。')
    if re.match(r'^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)', result, re.I):
        result = '_' + result
    return result


class Store:
    def __init__(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        try:
            self.db.executescript('''
            CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS history (
                id INTEGER PRIMARY KEY, video_id TEXT NOT NULL, title TEXT NOT NULL,
                uploader TEXT NOT NULL, saved_at TEXT NOT NULL, quality TEXT NOT NULL, path TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS history_video ON history(video_id);
            ''')
            if 'mode' not in {row[1] for row in self.db.execute('PRAGMA table_info(history)')}:
                self.db.execute("ALTER TABLE history ADD COLUMN mode TEXT NOT NULL DEFAULT 'music'")
                self.db.commit()
        except sqlite3.Error:
            self.db.close()
            raise

    def settings(self, mode='music'):
        defaults = VIDEO_DEFAULTS if mode == 'video' else DEFAULTS
        prefix = 'video.' if mode == 'video' else ''
        saved = dict(self.db.execute('SELECT key, value FROM settings'))
        settings = {key: saved.get(prefix + key, value) for key, value in defaults.items()}
        if settings['quality'] == '最高音質（元の音声・無変換）':
            settings['quality'] = ORIGINAL_AUDIO
        if mode == 'video' and 'MKV / ' + settings['resolution'] in VIDEO_QUALITIES:
            settings['resolution'] = 'MKV / ' + settings['resolution']
        return settings

    def save(self, settings, mode='music'):
        prefix = 'video.' if mode == 'video' else ''
        with self.db:
            self.db.executemany('INSERT OR REPLACE INTO settings VALUES (?, ?)',
                                ((prefix + key, value) for key, value in settings.items()))

    def previous(self, video_id, mode='music'):
        return self.db.execute('SELECT saved_at, path FROM history WHERE video_id=? AND mode=? ORDER BY id DESC LIMIT 1', (video_id, mode)).fetchone()

    def record(self, info, quality, path, mode='music'):
        with self.db:
            self.db.execute('INSERT INTO history(video_id,title,uploader,saved_at,quality,path,mode) VALUES (?,?,?,?,?,?,?)',
                            (info['id'], info['title'], info.get('uploader') or '', datetime.now().isoformat(timespec='seconds'), quality, str(path), mode))

    def history(self, mode='music'):
        return self.db.execute('SELECT saved_at,title,uploader,quality,path FROM history WHERE mode=? ORDER BY id DESC', (mode,)).fetchall()



def publish(source, folder, name, cancel=None):
    # Exclusive creation also protects files created by another running instance.
    for number in range(1, 10000):
        check_cancel(cancel)
        target = folder / f'{name}{"" if number == 1 else f" ({number})"}{source.suffix}'
        try:
            output = target.open('xb')
        except FileExistsError:
            continue
        try:
            with output, source.open('rb') as incoming:
                while chunk := incoming.read(1024 * 1024):
                    check_cancel(cancel)
                    output.write(chunk)
                check_cancel(cancel)
        except BaseException:
            target.unlink(missing_ok=True)
            raise
        return target
    raise OSError('同じ名前のファイルが多すぎます。ファイル名を変更してください。')


def download(url, settings, events, cancel=None, mode='music'):
    try:
        check_cancel(cancel)
        is_video = mode == 'video'
        import yt_dlp

        def progress(data):
            check_cancel(cancel)
            if data['status'] == 'downloading':
                total = data.get('total_bytes') or data.get('total_bytes_estimate')
                percent = min(100, data.get('downloaded_bytes', 0) / total * 100) if total else None
                events.put(('progress', (percent, f'ダウンロード中… {percent:.0f}%' if total else 'ダウンロード中…')))
            elif data['status'] == 'finished':
                events.put(('progress', (None, 'ファイルを準備中…')))

        folder = Path(settings['folder']).expanduser().resolve()
        folder.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=f'.{mode}-', dir=folder) as temp:
            options = {
                'format': 'bestaudio', 'noplaylist': True, 'quiet': True, 'noprogress': True,
                'outtmpl': str(Path(temp) / 'audio.%(ext)s'), 'windowsfilenames': True,
                'progress_hooks': [progress], 'socket_timeout': 30, 'retries': 3,
                'ffmpeg_location': str(FFMPEG.parent),
                'js_runtimes': {'node': {'path': str(RESOURCES / 'node.exe')} if (RESOURCES / 'node.exe').is_file() else {}, 'deno': {}},
            }
            if is_video:
                container, resolution = settings['resolution'].split(' / ')
                limit = '' if resolution == '最高画質' else f'[height<={int(resolution[:-1])}]'
                options['format'] = f'bestvideo{limit}+bestaudio/best{limit}'
                if container == 'MP4':
                    options['format'] = f'bestvideo[ext=mp4]{limit}+bestaudio[ext=m4a]/best[ext=mp4]{limit}'
                options['merge_output_format'] = 'mkv'
            with yt_dlp.YoutubeDL(options) as ydl:
                info = ydl.extract_info(url, download=True)
                source = Path(info.get('filepath') or ydl.prepare_filename(info))
            check_cancel(cancel)
            if is_video or settings['quality'] != ORIGINAL_AUDIO:
                events.put(('progress', (None, '動画を処理中…' if is_video else 'MP3 に変換中…')))
                converted = Path(temp) / (f'converted.{container.lower()}' if is_video else 'converted.mp3')
                if is_video:
                    codec = ['-map', '0:v:0', '-map', '0:a:0?', '-c:v', 'copy']
                    codec += ['-c:a', 'copy'] if settings['quality'] == VIDEO_AUDIO[0] else [
                        '-c:a', 'aac', '-b:a', settings['quality'].split(' / ')[1].split()[0] + 'k']
                else:
                    codec = ['-vn', '-c:a', 'libmp3lame', '-b:a', settings['quality'].split(' / ')[1].split()[0] + 'k']
                with subprocess.Popen(
                    [str(FFMPEG), '-nostdin', '-hide_banner', '-loglevel', 'error',
                     '-i', str(source), *codec, str(converted)],
                    stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='replace',
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0) as process:
                    deadline = time.monotonic() + CONVERSION_TIMEOUT
                    try:
                        while True:
                            check_cancel(cancel)
                            if time.monotonic() >= deadline:
                                raise RuntimeError('変換が制限時間（30分）を超えました。')
                            try:
                                _, stderr = process.communicate(timeout=0.2)
                                break
                            except subprocess.TimeoutExpired:
                                continue
                    finally:
                        if process.poll() is None:
                            process.kill()
                        process.communicate()
                    if process.returncode:
                        raise RuntimeError(f'変換に失敗しました。\n{stderr[-2000:]}')
                source = converted
            if not source.is_file() or source.stat().st_size == 0:
                raise RuntimeError('ファイルが生成されませんでした。')
            events.put(('progress', (None, 'ファイルを保存中…')))
            target = publish(source, folder, filename(settings['template'], info), cancel)
        quality = f"{settings['resolution']} / {settings['quality']}" if is_video else settings['quality']
        events.put(('complete', (info, quality, target)))
    except Exception as error:
        if isinstance(error, Cancelled) or (cancel is not None and cancel.is_set()):
            events.put(('cancelled', None))
        else:
            events.put(('error', str(error)))


class App(tk.Tk):
    def __init__(self, database=None):
        super().__init__()
        self.title('YouTube Downloader')
        self.geometry('960x720')
        self.minsize(800, 700)
        self.withdraw()
        data_path = database if database is not None else Path(os.environ.get('LOCALAPPDATA') or Path.home() / 'AppData' / 'Local') / 'YouTubeMusicDownloader' / 'library.sqlite3'
        try:
            self.store = Store(database if database is not None else database_path())
            saved = {mode: (self.store.settings(mode), self.store.history(mode)) for mode in ('music', 'video')}
        except (OSError, sqlite3.Error) as error:
            if hasattr(self, 'store'):
                self.store.db.close()
            messagebox.showerror('起動できません',
                                 f'設定・履歴を読み込めませんでした。\n保存場所: {data_path}\n\n{error}\n\n'
                                 'フォルダーのアクセス権と空き容量を確認してください。\n'
                                 'DBが破損している場合は、アプリを終了した状態でこのフォルダーをバックアップし、'
                                 '正常なバックアップから復元してください。音楽ファイルは削除されません。', parent=self)
            self.destroy()
            raise SystemExit(1)
        style = ttk.Style(self)
        style.theme_use('clam')
        style.configure('.', font=('Yu Gothic UI', 10), background='white', foreground='#172b40')
        style.configure('TFrame', background='white')
        style.configure('TLabel', background='white')
        style.configure('TButton', padding=(12, 4), background='#f1f5f9', bordercolor='#d4dee8',
                        lightcolor='#f1f5f9', darkcolor='#f1f5f9', relief='flat')
        style.map('TButton', background=[('disabled', '#f1f5f9'), ('pressed', '#dce5ee'), ('active', '#e5edf5')],
                  foreground=[('disabled', '#738396')])
        style.configure('TEntry', padding=4, fieldbackground='white', bordercolor='#cbd5e1')
        style.configure('TCombobox', padding=3, fieldbackground='white', background='#f1f5f9', bordercolor='#cbd5e1')
        style.map('TCombobox', fieldbackground=[('readonly', 'white')], foreground=[('readonly', '#172b40')])
        style.configure('TLabelframe', background='white', bordercolor='#dbe4ee', relief='solid', borderwidth=1)
        style.configure('TLabelframe.Label', background='white', foreground='#40536b', font=('Yu Gothic UI', 10, 'bold'))
        style.configure('TNotebook', background='#eaf0f6', borderwidth=0, tabmargins=(20, 10, 20, 0))
        style.configure('TNotebook.Tab', padding=(22, 8), background='#eaf0f6', font=('Yu Gothic UI', 10, 'bold'))
        style.map('TNotebook.Tab', background=[('selected', 'white'), ('active', '#f8fafc')],
                  foreground=[('selected', '#172b40'), ('!selected', '#52657b')])
        style.configure('Treeview', rowheight=32, background='white', fieldbackground='white', bordercolor='#dbe4ee')
        style.configure('Treeview.Heading', padding=(8, 7), background='#f1f5f9', foreground='#40536b',
                        font=('Yu Gothic UI', 10, 'bold'), relief='flat')
        for mode, accent, hover, tint in (
            ('music', '#2458bd', '#19469d', '#eff5ff'),
            ('video', '#147d52', '#0d6140', '#edf8f1'),
        ):
            style.configure(f'{mode}.TFrame', background=tint)
            style.configure(f'{mode}.TLabel', background=tint, foreground='#52657b')
            style.configure(f'{mode}.Title.TLabel', background=tint, foreground=accent, font=('Yu Gothic UI', 24, 'bold'))
            style.configure(f'{mode}.Section.TLabel', background=tint, foreground='#172b40', font=('Yu Gothic UI', 11, 'bold'))
            style.configure(f'{mode}.Accent.TButton', padding=(22, 12), background=accent, foreground='white',
                            bordercolor=accent, lightcolor=accent, darkcolor=accent, font=('Yu Gothic UI', 10, 'bold'))
            style.map(f'{mode}.Accent.TButton', background=[('disabled', '#dbe4ee'), ('pressed', hover), ('active', hover)],
                      foreground=[('disabled', '#52657b'), ('!disabled', 'white')],
                      bordercolor=[('disabled', '#dbe4ee'), ('focus', hover)])
            style.configure(f'{mode}.Horizontal.TProgressbar', background=accent, troughcolor='#dfe8ef',
                            borderwidth=0, lightcolor=accent, darkcolor=accent, thickness=6)
            style.map(f'{mode}.Treeview', background=[('selected', accent)], foreground=[('selected', 'white')])
        self.close_pending = False
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill='both', expand=True)
        self.tabs = {}
        for mode, label in (('music', 'Music Download'), ('video', 'Video Download')):
            panel = DownloadTab(self.notebook, self, mode, *saved[mode])
            self.tabs[mode] = panel
            self.notebook.add(panel, text=label)
        self.notebook.select(self.tabs['music'])
        self.protocol('WM_DELETE_WINDOW', self.close)
        self.deiconify()
        if getattr(sys, 'frozen', False):
            self.after(1000, self.check_for_update)

    def check_for_update(self):
        current = application_version()
        if current:
            threading.Thread(target=self.find_update, args=(current,), daemon=True).start()

    def find_update(self, current):
        update = fetch_update(current)
        if update:
            try:
                self.after(0, self.show_update, *update)
            except (RuntimeError, tk.TclError):
                pass

    def show_update(self, version, url):
        if messagebox.askyesno('更新があります', f'YouTube Downloader {version} を利用できます。\n\nダウンロードページを開きますか？', parent=self):
            webbrowser.open(url)

    def close(self):
        if any(tab.busy for tab in self.tabs.values()):
            if self.close_pending or not messagebox.askyesno('終了の確認', '処理をキャンセルして終了しますか？', default='no', parent=self):
                return
            if any(tab.busy for tab in self.tabs.values()):
                self.close_pending = True
                for tab in self.tabs.values():
                    tab.cancel()
                return
        saved = [tab.save() for tab in self.tabs.values()]
        if all(value is not None for value in saved) or messagebox.askyesno(
                '保存せず終了', '設定を保存できませんでした。未保存の設定変更を破棄して終了しますか？', default='no', parent=self):
            self.store.db.close()
            self.destroy()
            return True


class DownloadTab(ttk.Frame):
    def __init__(self, parent, app, mode, saved_settings, saved_history):
        super().__init__(parent)
        self.app = app
        self.store = app.store
        self.mode = mode
        self.defaults = VIDEO_DEFAULTS if mode == 'video' else DEFAULTS
        self.qualities = VIDEO_AUDIO if mode == 'video' else QUALITIES
        self.events = queue.Queue()
        self.busy = False
        self.cancel_event = threading.Event()
        self.vars = {key: tk.StringVar(value=value) for key, value in saved_settings.items()}
        self.url = tk.StringVar()
        self.status = tk.StringVar(value='動画の URL を貼り付けてください。')
        outer = ttk.Frame(self, padding=(24, 8), style=f'{mode}.TFrame')
        outer.pack(fill='both', expand=True)
        ttk.Label(outer, text='Video Download' if mode == 'video' else 'Music Download', style=f'{mode}.Title.TLabel').pack(anchor='w')
        ttk.Label(outer, text='動画 URL', style=f'{mode}.Section.TLabel').pack(anchor='w')
        row = ttk.Frame(outer, style=f'{mode}.TFrame')
        row.pack(fill='x', pady=(6, 14))
        entry = ttk.Entry(row, textvariable=self.url, font=('Segoe UI', 12))
        entry.pack(side='left', fill='x', expand=True, ipady=5, padx=(0, 12))
        entry.bind('<Return>', lambda event: self.start())
        self.button = ttk.Button(row, text='Download', style=f'{mode}.Accent.TButton', command=self.start)
        self.button.pack(side='right')
        self.cancel_button = ttk.Button(row, text='キャンセル', command=self.cancel, state='disabled')
        self.cancel_button.pack(side='right', padx=(0, 8))
        settings = ttk.LabelFrame(outer, text=' 保存設定 ', padding=(14, 8))
        settings.pack(fill='x')
        settings.columnconfigure(1, weight=1)
        settings.columnconfigure(3, weight=1)
        ttk.Label(settings, text='保存先').grid(row=0, column=0, sticky='w', padx=(0, 15))
        ttk.Entry(settings, textvariable=self.vars['folder']).grid(row=0, column=1, columnspan=3, sticky='ew', pady=3)
        ttk.Button(settings, text='参照…', command=self.browse).grid(row=0, column=4, padx=(8, 0))
        self.audio_format = tk.StringVar()
        self.bitrate = tk.StringVar()
        self.container = tk.StringVar()
        self.resolution = tk.StringVar()
        self.load_quality_controls()
        audio_row = [
            ('音声処理' if mode == 'video' else '保存形式', self.audio_format,
             ('無変換', 'AAC') if mode == 'video' else ('MP3', '元の形式')),
            ('音質', self.bitrate, ('320 kbps', '192 kbps', '128 kbps')),
        ]
        rows = [audio_row]
        if mode == 'video':
            rows.insert(0, [('保存形式', self.container, ('MP4', 'MKV')),
                            ('画質', self.resolution, tuple(value.split(' / ')[1] for value in VIDEO_QUALITIES[:7]))])
        for row_number, fields in enumerate(rows, 1):
            for column, (label, variable, values) in enumerate(fields):
                ttk.Label(settings, text=label).grid(row=row_number, column=column * 2, sticky='w', padx=(8 if column else 0, 15))
                combo = ttk.Combobox(settings, textvariable=variable, values=values, state='readonly', width=14)
                combo.grid(row=row_number, column=column * 2 + 1, sticky='ew', pady=3)
                if variable is self.bitrate:
                    self.bitrate_combo = combo
        for variable in (self.audio_format, self.bitrate, self.container, self.resolution):
            variable.trace_add('write', self.sync_quality_controls)
        self.sync_quality_controls()
        self.details_button = ttk.Button(settings, text='詳細設定を開く', command=self.toggle_settings)
        self.details_button.grid(row=3, column=0, columnspan=5, sticky='w', pady=(6, 0))
        self.details = ttk.Frame(settings)
        self.details.grid(row=4, column=0, columnspan=5, sticky='ew', pady=(4, 0))
        self.details.columnconfigure(1, weight=1)
        ttk.Label(self.details, text='ファイル名').grid(row=0, column=0, sticky='w', padx=(0, 15))
        ttk.Entry(self.details, textvariable=self.vars['template']).grid(row=0, column=1, columnspan=2, sticky='ew', pady=3)
        ttk.Label(self.details, text='例: {uploader} - {title}  ·  拡張子は自動で付きます。').grid(row=1, column=1, columnspan=2, sticky='w', pady=2)
        ttk.Button(self.details, text='設定を保存', command=self.save).grid(row=2, column=2, sticky='e')
        ttk.Button(self.details, text='初期設定にリセット', command=self.reset_settings).grid(row=2, column=1, sticky='w')
        self.details.grid_remove()
        status = ttk.Label(outer, textvariable=self.status, style=f'{mode}.TLabel')
        status.pack(fill='x', pady=(12, 5))
        status.bind('<Configure>', lambda event: status.configure(wraplength=max(1, event.width)))
        self.progress = ttk.Progressbar(outer, maximum=100, style=f'{mode}.Horizontal.TProgressbar')
        self.progress.pack(fill='x', pady=(0, 12))
        history_heading = ttk.Frame(outer, style=f'{mode}.TFrame')
        history_heading.pack(fill='x', pady=(0, 8))
        ttk.Label(history_heading, text='ダウンロード履歴', style=f'{mode}.Section.TLabel').pack(side='left')
        ttk.Label(history_heading, text='ダブルクリックで保存フォルダーを開く', style=f'{mode}.TLabel').pack(side='right')
        history = ttk.Frame(outer)
        history.pack(fill='both', expand=True)
        columns = ('date', 'title', 'uploader', 'quality', 'path')
        self.tree = ttk.Treeview(history, columns=columns, displaycolumns=columns[:4], show='headings', height=6, selectmode='browse', style=f'{mode}.Treeview')
        for col, label, width in zip(columns[:4], ('日時', '動画名', '投稿者', '画質 / 音質' if mode == 'video' else '音質'), (150, 230, 110, 190)):
            self.tree.heading(col, text=label)
            self.tree.column(col, width=width, minwidth=80, stretch=col == 'title')
        vertical = ttk.Scrollbar(history, orient='vertical', command=self.tree.yview)
        horizontal = ttk.Scrollbar(history, orient='horizontal', command=self.tree.xview)
        self.tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        history.columnconfigure(0, weight=1)
        history.rowconfigure(0, weight=1)
        self.tree.grid(row=0, column=0, sticky='nsew')
        vertical.grid(row=0, column=1, sticky='ns')
        horizontal.grid(row=1, column=0, sticky='ew')
        self.history_path = tk.StringVar()
        detail = ttk.Frame(outer, style=f'{mode}.TFrame')
        detail.pack(side='bottom', fill='x', pady=(8, 0), before=history)
        ttk.Label(detail, text='保存ファイル', style=f'{mode}.TLabel').pack(side='left', padx=(0, 8))
        ttk.Entry(detail, textvariable=self.history_path, state='readonly').pack(side='left', fill='x', expand=True)
        self.tree.bind('<<TreeviewSelect>>', self.select_history)
        self.tree.bind('<Double-1>', self.open_folder)
        self.refresh(saved_history)
        self.poll_id = self.after(100, self.poll)
        entry.focus_set()

    def destroy(self):
        self.after_cancel(self.poll_id)
        self.progress.stop()
        super().destroy()

    def load_quality_controls(self):
        # Keep the stored/download settings compatible with earlier versions.
        quality = self.vars['quality'].get()
        resolution = self.vars['resolution'].get() if self.mode == 'video' else ''
        original = quality in (ORIGINAL_AUDIO, VIDEO_AUDIO[0])
        audio_format, _, bitrate = quality.partition(' / ')
        self.audio_format.set(('無変換' if self.mode == 'video' else '元の形式') if original else audio_format)
        self.bitrate.set('320 kbps' if original else bitrate)
        container, _, height = resolution.partition(' / ')
        self.container.set(container)
        self.resolution.set(height)

    def sync_quality_controls(self, *args):
        audio_format = self.audio_format.get()
        original = audio_format == ('無変換' if self.mode == 'video' else '元の形式')
        self.bitrate_combo.configure(state='disabled' if original else 'readonly')
        quality = (VIDEO_AUDIO[0] if self.mode == 'video' else ORIGINAL_AUDIO) if original else f'{audio_format} / {self.bitrate.get()}'
        self.vars['quality'].set(quality)
        if self.mode == 'video':
            self.vars['resolution'].set(f'{self.container.get()} / {self.resolution.get()}')

    def toggle_settings(self):
        if self.details.winfo_manager():
            self.details.grid_remove()
            self.details_button.configure(text='詳細設定を開く')
        else:
            self.details.grid()
            self.details_button.configure(text='詳細設定を閉じる')

    def select_history(self, event=None):
        selection = self.tree.selection()
        self.history_path.set(self.tree.item(selection[0], 'values')[4] if selection else '')

    def set_progress(self, value):
        if value is None:
            if str(self.progress['mode']) != 'indeterminate':
                self.progress.configure(mode='indeterminate', value=0)
                self.progress.start()
        else:
            self.progress.stop()
            self.progress.configure(mode='determinate', value=value)

    def browse(self):
        folder = filedialog.askdirectory(initialdir=self.vars['folder'].get(), mustexist=True)
        if folder:
            self.vars['folder'].set(folder)

    def reset_settings(self):
        if not messagebox.askyesno(
                '設定のリセット',
                'このタブの設定を初期設定に戻して保存しますか？\n現在の設定は失われます。ダウンロード履歴と保存済みファイルは削除しません。',
                icon='warning', default='no', parent=self):
            return
        try:
            self.store.save(self.defaults, self.mode)
        except sqlite3.Error as error:
            messagebox.showerror('設定をリセットできません', str(error), parent=self)
            return
        for key, value in self.defaults.items():
            self.vars[key].set(value)
        self.load_quality_controls()
        if not self.busy:
            self.status.set('設定を初期値にリセットしました。')

    def save(self):
        try:
            settings = {key: var.get().strip() for key, var in self.vars.items()}
            if not settings['folder'] or not Path(settings['folder']).is_absolute():
                raise ValueError('保存先を絶対パスで指定してください。例: E:\\MUSIC')
            if settings['quality'] not in self.qualities:
                raise ValueError('音質を選択してください。')
            if self.mode == 'video' and settings['resolution'] not in VIDEO_QUALITIES:
                raise ValueError('画質を選択してください。')
            filename(settings['template'], {'title': '動画名', 'uploader': '投稿者', 'id': 'sample'})
            self.store.save(settings, self.mode)
            if not self.busy:
                self.status.set('設定を保存しました。')
            return settings
        except (ValueError, OSError, sqlite3.Error) as error:
            messagebox.showerror('設定を保存できません', str(error), parent=self)

    def start(self):
        if self.busy:
            return
        try:
            video_id, url = video_url(self.url.get())
            previous = self.store.previous(video_id, self.mode)
        except (ValueError, sqlite3.Error) as error:
            messagebox.showerror('開始できません', str(error), parent=self)
            return
        settings = self.save()
        if not settings:
            return
        if previous and not messagebox.askyesno('ダウンロード済み', f'過去にダウンロードしています。もう一度ダウンロードしますか？\n\n日時: {previous[0]}\n保存先: {previous[1]}', parent=self):
            self.status.set('再ダウンロードをキャンセルしました。')
            return
        self.busy = True
        self.cancel_event.clear()
        self.cancel_button.state(['!disabled'])
        self.button.state(['disabled'])
        self.set_progress(None)
        self.status.set('動画情報を取得中…')
        threading.Thread(target=download, args=(url, settings, self.events, self.cancel_event, self.mode), daemon=True).start()

    def cancel(self):
        if self.busy:
            self.cancel_event.set()
            self.cancel_button.state(['disabled'])
            self.status.set('キャンセル中… 通信の応答待ちには時間がかかる場合があります。')

    def poll(self):
        self.after_cancel(self.poll_id)
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == 'progress':
                    if self.cancel_event.is_set():
                        continue
                    value, text = payload
                    self.set_progress(value)
                    self.status.set(text)
                    continue
                self.busy = False
                self.set_progress(100 if kind == 'complete' else 0)
                self.button.state(['!disabled'])
                self.cancel_button.state(['disabled'])
                if kind == 'complete':
                    info, quality, path = payload
                    try:
                        self.store.record(info, quality, path, self.mode)
                        self.refresh()
                        self.status.set(f'完了 · 保存しました: {path}')
                    except sqlite3.Error as error:
                        self.status.set(f'ファイルは保存済み: {path}')
                        messagebox.showerror('履歴保存エラー', f'ファイルは保存しましたが履歴を保存できませんでした。\n{path}\n{error}', parent=self)
                elif kind == 'cancelled':
                    self.progress['value'] = 0
                    self.status.set('キャンセルしました。')
                else:
                    self.status.set('ダウンロードに失敗しました。URL とネットワークを確認してください。')
                    messagebox.showerror('ダウンロードエラー', payload, parent=self)
                if self.app.close_pending and not any(tab.busy for tab in self.app.tabs.values()):
                    self.app.close_pending = False
                    if self.app.close():
                        return
        except queue.Empty:
            pass
        self.poll_id = self.after(100, self.poll)

    def refresh(self, rows=None):
        self.history_path.set('')
        for item in self.tree.get_children():
            self.tree.delete(item)
        for row in self.store.history(self.mode) if rows is None else rows:
            self.tree.insert('', 'end', values=row)

    def open_folder(self, event):
        item = self.tree.identify_row(event.y)
        if item:
            try:
                os.startfile(str(Path(self.tree.item(item, 'values')[4]).parent))
            except OSError as error:
                messagebox.showerror('フォルダーを開けません', str(error), parent=self)



if __name__ == '__main__':
    App().mainloop()
