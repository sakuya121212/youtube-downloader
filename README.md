# YouTube Music Downloader

Windows 用のローカルデスクトップアプリです。`YouTubeMusicDownloader.exe` をダブルクリックして起動します。
配布フォルダーに Python・Node.js・FFmpeg を同梱しているため、別途インストールは不要です。
exe の隣の `_internal` フォルダーも必要です。移動するときは配布フォルダー全体を移してください。
従来の `start.bat` でも起動できます。同じ Windows ユーザーなら設定と履歴を共有します。

## 使い方

1. 動画の URL を貼り付けます。
2. 必要なら保存先・音質・ファイル名を変更します。
3. **Download** を押します。

プレイリスト情報が付いた動画 URL でも、その動画だけを保存します。
プレイリスト単体の URL は対象動画が決まらないため受け付けません。
通常の動画、短縮 URL、Shorts、ライブの動画 URL、YouTube Music の動画 URL に対応します。

- 保存先の初期値: `E:\MUSIC`
- 音質の初期値: MP3 / 320 kbps。保存済みの音質設定がある場合は、その設定を引き継ぎます。
- 音質の選択肢: MP3 320 / 192 / 128 kbps、WebM / M4A / 無変換（一覧の最後）。無変換では取得可能な最高音質の元音声を保存し、拡張子は動画によって異なります。元音源以上の音質にはなりません。
- ファイル名の初期値: `{title}`。`{uploader}` と `{id}`、好きな文字を組み合わせられます。
- 例: `{uploader} - {title}`、`お気に入り_{title}`。拡張子は自動付与します。
- Windows で使用できない文字は `_` に置換し、長い名前は短縮します。同名ファイルには `(2)` などを付けます。
- 設定は「設定を保存」、Download、正常終了時に保存し、次の起動で復元します。
- 成功したダウンロードを履歴に記録し、同じ動画の再取得時には確認を表示します。履歴をダブルクリックすると保存フォルダーを開きます。

設定と履歴は `%LOCALAPPDATA%\YouTubeMusicDownloader\library.sqlite3` に保存します。
ZIP 版とインストーラー版で共有し、アプリ本体を入れ替えても保持されます。音楽の保存先とは別です。
旧版の `data/library.sqlite3` は、新しい保存先がまだない場合に起動元フォルダーからコピーして引き継ぎます（元ファイルは残します）。
現在のソース版から引き継ぐ場合は、更新後の `start.bat` を一度起動してから exe 版を使ってください。
ダウンロード中も画面は操作できます。変更した設定は次のダウンロードから適用されます。保存完了後に終了してください。

## 別の PC での起動・更新

ZIP 版は展開後の `YouTubeMusicDownloader` フォルダー内にある exe を起動します。
アプリの配置先への書き込みは不要です。ZIP 版も設定をユーザープロファイルに保存するため、完全なポータブル版ではありません。
以下はソース版の起動・更新手順です。exe に更新を反映するには再ビルドしてください。

Python 3.12 以降（Tkinter を含む）と Node.js 22 以降を用意して `start.bat` を実行します。
初回はインターネットから依存パッケージを取得します。FFmpeg は Python パッケージに同梱されます。
YouTube の仕様変更で失敗する場合は以下で更新してください。

```powershell
.venv\Scripts\python.exe -m pip install --upgrade -r requirements.txt
```

exe の再ビルド（[PyInstaller](https://www.pyinstaller.org/en/stable/usage.html) を使用）:

```powershell
.venv\Scripts\python.exe -m pip install pyinstaller
.venv\Scripts\python.exe build_exe.py
```

成果物は `dist/YouTubeMusicDownloader/` です。このフォルダー全体を ZIP 化するか、今後作成するインストーラーの配置対象にしてください。
インストーラーではこのフォルダーの exe へのショートカットを作成し、更新時はアプリを終了して配布ファイルを入れ替えます。
ユーザーデータのフォルダーはインストール・更新・通常のアンインストールで削除しない構成にしてください。
インストーラー本体と自動更新機能はまだ含みません。

YouTube の取得処理には [yt-dlp](https://github.com/yt-dlp/yt-dlp) を使用しています。
JavaScript 実行環境と EJS の設定は [公式ガイド](https://github.com/yt-dlp/yt-dlp/wiki/EJS) に従っています。
非公開・ログイン必須・地域制限などの動画は取得できない場合があります。

## 検証

```powershell
.venv\Scripts\python.exe -m unittest -v
```

ネットワーク取得をローカル音声に置き換え、URL 判定、設定の永続化、実際の MP3 変換、同名ファイル保護、履歴、再取得確認、エラー復帰を検証します。

2026-09-13 に上記テストの成功と、公開動画「Me at the zoo」の音声を YouTube から WebM で取得できることを確認しました。
