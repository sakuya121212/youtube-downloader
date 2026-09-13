import os
import queue
import re
import shutil
import sqlite3
import string
import subprocess
import sys
import tempfile
import threading
from contextlib import closing
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse
import tkinter as tk
from tkinter import filedialog, messagebox, ttk


ROOT = Path(sys.executable if getattr(sys, 'frozen', False) else __file__).resolve().parent
RESOURCES = Path(__file__).resolve().parent
ORIGINAL_AUDIO = 'WebM / M4A / 無変換'
QUALITIES = ('MP3 / 320 kbps', 'MP3 / 192 kbps', 'MP3 / 128 kbps', ORIGINAL_AUDIO)
DEFAULTS = {'folder': r'E:\MUSIC', 'quality': QUALITIES[0], 'template': '{title}'}


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
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS history (
                id INTEGER PRIMARY KEY, video_id TEXT NOT NULL, title TEXT NOT NULL,
                uploader TEXT NOT NULL, saved_at TEXT NOT NULL, quality TEXT NOT NULL, path TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS history_video ON history(video_id);
        ''')

    def settings(self):
        settings = DEFAULTS | dict(self.db.execute('SELECT key, value FROM settings'))
        if settings['quality'] == '最高音質（元の音声・無変換）':
            settings['quality'] = ORIGINAL_AUDIO
        return settings

    def save(self, settings):
        with self.db:
            self.db.executemany('INSERT OR REPLACE INTO settings VALUES (?, ?)', settings.items())

    def previous(self, video_id):
        return self.db.execute('SELECT saved_at, path FROM history WHERE video_id=? ORDER BY id DESC LIMIT 1', (video_id,)).fetchone()

    def record(self, info, quality, path):
        with self.db:
            self.db.execute('INSERT INTO history(video_id,title,uploader,saved_at,quality,path) VALUES (?,?,?,?,?,?)',
                            (info['id'], info['title'], info.get('uploader') or '', datetime.now().isoformat(timespec='seconds'), quality, str(path)))

    def history(self):
        return self.db.execute('SELECT saved_at,title,uploader,quality,path FROM history ORDER BY id DESC').fetchall()


def publish(source, folder, name):
    # Exclusive creation also protects files created by another running instance.
    for number in range(1, 10000):
        target = folder / f'{name}{"" if number == 1 else f" ({number})"}{source.suffix}'
        try:
            output = target.open('xb')
        except FileExistsError:
            continue
        try:
            with output, source.open('rb') as incoming:
                shutil.copyfileobj(incoming, output)
        except BaseException:
            target.unlink(missing_ok=True)
            raise
        return target
    raise OSError('同じ名前のファイルが多すぎます。ファイル名を変更してください。')


def download(url, settings, events):
    try:
        import imageio_ffmpeg
        import yt_dlp

        def progress(data):
            if data['status'] == 'downloading':
                total = data.get('total_bytes') or data.get('total_bytes_estimate')
                percent = min(100, data.get('downloaded_bytes', 0) / total * 100) if total else 0
                events.put(('progress', (percent, f'ダウンロード中… {percent:.0f}%' if total else 'ダウンロード中…')))
            elif data['status'] == 'finished':
                events.put(('progress', (100, '音声ファイルを準備中…')))

        folder = Path(settings['folder']).expanduser().resolve()
        folder.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='.music-', dir=folder) as temp:
            options = {
                'format': 'bestaudio', 'noplaylist': True, 'quiet': True, 'noprogress': True,
                'outtmpl': str(Path(temp) / 'audio.%(ext)s'), 'windowsfilenames': True,
                'progress_hooks': [progress], 'socket_timeout': 30, 'retries': 3,
                'js_runtimes': {'node': {'path': str(RESOURCES / 'node.exe')} if (RESOURCES / 'node.exe').is_file() else {}, 'deno': {}},
            }
            with yt_dlp.YoutubeDL(options) as ydl:
                info = ydl.extract_info(url, download=True)
                source = Path(ydl.prepare_filename(info))
            if settings['quality'] != ORIGINAL_AUDIO:
                events.put(('progress', (100, 'MP3 に変換中…')))
                converted = Path(temp) / 'converted.mp3'
                bitrate = settings['quality'].split(' / ')[1].split()[0] + 'k'
                result = subprocess.run(
                    [imageio_ffmpeg.get_ffmpeg_exe(), '-nostdin', '-hide_banner', '-loglevel', 'error',
                     '-i', str(source), '-vn', '-c:a', 'libmp3lame', '-b:a', bitrate, str(converted)],
                    capture_output=True, text=True, encoding='utf-8', errors='replace',
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
                if result.returncode:
                    raise RuntimeError(f'MP3 変換に失敗しました。\n{result.stderr[-2000:]}')
                source = converted
            if not source.is_file() or source.stat().st_size == 0:
                raise RuntimeError('音声ファイルが生成されませんでした。')
            target = publish(source, folder, filename(settings['template'], info))
        events.put(('complete', (info, settings['quality'], target)))
    except Exception as error:
        events.put(('error', str(error)))


class App(tk.Tk):
    def __init__(self, database=None):
        super().__init__()
        self.title('YouTube Music Downloader')
        self.geometry('960x720')
        self.minsize(800, 600)
        self.store = Store(database if database is not None else database_path())
        self.events = queue.Queue()
        self.busy = False
        self.vars = {key: tk.StringVar(value=value) for key, value in self.store.settings().items()}
        self.url = tk.StringVar()
        self.status = tk.StringVar(value='動画の URL を貼り付けてください。')
        style = ttk.Style(self)
        style.theme_use('clam')
        style.configure('.', font=('Yu Gothic UI', 10))
        style.configure('Title.TLabel', font=('Yu Gothic UI', 22, 'bold'))
        style.configure('Accent.TButton', padding=(22, 12), background='#2458bd', foreground='white')
        style.configure('Treeview', rowheight=30)
        outer = ttk.Frame(self, padding=24)
        outer.pack(fill='both', expand=True)
        ttk.Label(outer, text='YouTube Music Downloader', style='Title.TLabel').pack(anchor='w')
        ttk.Label(outer, text='動画 URL').pack(anchor='w')
        row = ttk.Frame(outer)
        row.pack(fill='x', pady=(6, 16))
        entry = ttk.Entry(row, textvariable=self.url, font=('Segoe UI', 12))
        entry.pack(side='left', fill='x', expand=True, ipady=9, padx=(0, 12))
        entry.bind('<Return>', lambda event: self.start())
        self.button = ttk.Button(row, text='Download', style='Accent.TButton', command=self.start)
        self.button.pack(side='right')
        settings = ttk.LabelFrame(outer, text='保存設定', padding=14)
        settings.pack(fill='x')
        settings.columnconfigure(1, weight=1)
        ttk.Label(settings, text='保存先').grid(row=0, column=0, sticky='w', padx=(0, 15))
        ttk.Entry(settings, textvariable=self.vars['folder']).grid(row=0, column=1, sticky='ew', pady=5)
        ttk.Button(settings, text='参照…', command=self.browse).grid(row=0, column=2, padx=(8, 0))
        ttk.Label(settings, text='音質').grid(row=1, column=0, sticky='w')
        ttk.Combobox(settings, textvariable=self.vars['quality'], values=QUALITIES, state='readonly').grid(row=1, column=1, sticky='ew', pady=5)
        ttk.Label(settings, text='ファイル名').grid(row=2, column=0, sticky='w')
        ttk.Entry(settings, textvariable=self.vars['template']).grid(row=2, column=1, columnspan=2, sticky='ew', pady=5)
        ttk.Label(settings, text='例: {title}  /  {uploader} - {title}  /  お気に入り_{title}\n拡張子は自動で付きます。設定は終了時・Download 時にも保存します。').grid(row=3, column=1, sticky='w', pady=4)
        ttk.Button(settings, text='設定を保存', command=self.save).grid(row=4, column=2, sticky='e')
        ttk.Label(outer, textvariable=self.status, wraplength=880).pack(anchor='w', pady=(14, 5))
        self.progress = ttk.Progressbar(outer, maximum=100)
        self.progress.pack(fill='x', pady=(0, 16))
        ttk.Label(outer, text='ダウンロード履歴 · ダブルクリックで保存フォルダーを開く').pack(anchor='w', pady=(0, 8))
        history = ttk.Frame(outer)
        history.pack(fill='both', expand=True)
        columns = ('date', 'title', 'uploader', 'quality', 'path')
        self.tree = ttk.Treeview(history, columns=columns, show='headings', height=6)
        for col, label, width in zip(columns, ('日時', '動画名', '投稿者', '音質', '保存ファイル'), (155, 230, 140, 190, 270)):
            self.tree.heading(col, text=label)
            self.tree.column(col, width=width, minwidth=80, stretch=False)
        vertical = ttk.Scrollbar(history, orient='vertical', command=self.tree.yview)
        horizontal = ttk.Scrollbar(history, orient='horizontal', command=self.tree.xview)
        self.tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        history.columnconfigure(0, weight=1)
        history.rowconfigure(0, weight=1)
        self.tree.grid(row=0, column=0, sticky='nsew')
        vertical.grid(row=0, column=1, sticky='ns')
        horizontal.grid(row=1, column=0, sticky='ew')
        self.tree.bind('<Double-1>', self.open_folder)
        self.refresh()
        self.protocol('WM_DELETE_WINDOW', self.close)
        self.after(100, self.poll)
        entry.focus_set()

    def browse(self):
        folder = filedialog.askdirectory(initialdir=self.vars['folder'].get(), mustexist=True)
        if folder:
            self.vars['folder'].set(folder)

    def save(self):
        try:
            settings = {key: var.get().strip() for key, var in self.vars.items()}
            if not settings['folder'] or not Path(settings['folder']).is_absolute():
                raise ValueError('保存先を絶対パスで指定してください。例: E:\\MUSIC')
            if settings['quality'] not in QUALITIES:
                raise ValueError('音質を選択してください。')
            filename(settings['template'], {'title': '動画名', 'uploader': '投稿者', 'id': 'sample'})
            self.store.save(settings)
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
            previous = self.store.previous(video_id)
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
        self.button.state(['disabled'])
        self.progress['value'] = 0
        self.status.set('動画情報を取得中…')
        threading.Thread(target=download, args=(url, settings, self.events), daemon=True).start()

    def poll(self):
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == 'progress':
                    self.progress['value'], text = payload
                    self.status.set(text)
                    continue
                self.busy = False
                self.button.state(['!disabled'])
                if kind == 'complete':
                    info, quality, path = payload
                    try:
                        self.store.record(info, quality, path)
                        self.refresh()
                        self.status.set(f'保存しました: {path}')
                    except sqlite3.Error as error:
                        self.status.set(f'音声は保存済み: {path}')
                        messagebox.showerror('履歴保存エラー', f'音声は保存しましたが履歴を保存できませんでした。\n{path}\n{error}', parent=self)
                else:
                    self.status.set('ダウンロードに失敗しました。URL とネットワークを確認してください。')
                    messagebox.showerror('ダウンロードエラー', payload, parent=self)
        except queue.Empty:
            pass
        self.after(100, self.poll)

    def refresh(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        for row in self.store.history():
            self.tree.insert('', 'end', values=row)

    def open_folder(self, event):
        item = self.tree.identify_row(event.y)
        if item:
            try:
                os.startfile(str(Path(self.tree.item(item, 'values')[4]).parent))
            except OSError as error:
                messagebox.showerror('フォルダーを開けません', str(error), parent=self)

    def close(self):
        if self.busy:
            messagebox.showinfo('ダウンロード中', 'ファイルの保存が完了してから終了してください。', parent=self)
            return
        if self.save() is not None:
            self.store.db.close()
            self.destroy()


if __name__ == '__main__':
    App().mainloop()
