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

- 保存先の初期値: 現在のユーザーの `Downloads` フォルダー（通常 `C:\Users\<ユーザー名>\Downloads`）。保存済みの設定は引き継ぎます。
- 音質の初期値: MP3 / 320 kbps。保存済みの音質設定がある場合は、その設定を引き継ぎます。
- 音質の選択肢: MP3 320 / 192 / 128 kbps、WebM / M4A / 無変換（一覧の最後）。無変換では取得可能な最高音質の元音声を保存し、拡張子は動画によって異なります。元音源以上の音質にはなりません。
- ファイル名の初期値: `{title}`。`{uploader}` と `{id}`、好きな文字を組み合わせられます。
- 例: `{uploader} - {title}`、`お気に入り_{title}`。拡張子は自動付与します。
- Windows で使用できない文字は `_` に置換し、長い名前は短縮します。同名ファイルには `(2)` などを付けます。
- 設定は「設定を保存」、Download、正常終了時に保存し、次の起動で復元します。
- 「初期設定にリセット」は警告で確認後、保存先・音質・ファイル名を初期値に戻して保存します。履歴と保存済みファイルは保持します。
- 成功したダウンロードを履歴に記録し、同じ動画の再取得時には確認を表示します。履歴をダブルクリックすると保存フォルダーを開きます。

設定と履歴は `%LOCALAPPDATA%\YouTubeMusicDownloader\library.sqlite3` に保存します。
ZIP 版とインストーラー版で共有し、アプリ本体を入れ替えても保持されます。音楽の保存先とは別です。
旧版の `data/library.sqlite3` は、新しい保存先がまだない場合に起動元フォルダーからコピーして引き継ぎます（元ファイルは残します）。
現在のソース版から引き継ぐ場合は、更新後の `start.bat` を一度起動してから exe 版を使ってください。
ダウンロード中も画面は操作できます。変更した設定は次のダウンロードから適用されます。
「キャンセル」で取得・変換を中止できます。通信の応答待ちでは中止まで時間がかかる場合があります。
処理中に閉じると、中止して終了するか確認します。一時ファイルの片付けが終わってから終了します。
MP3 変換は30分でタイムアウトします。長い音声で制限に達する場合は無変換を選んでください。
終了時に設定を保存できない場合は、未保存の変更を破棄して終了できます。
設定・履歴の読み込みに失敗した場合は、保存場所と復旧の案内を表示します。DBを自動で削除・初期化することはありません。

## 別の PC での起動・更新

ZIP 版は展開後の `YouTubeMusicDownloader` フォルダー内にある exe を起動します。
アプリの配置先への書き込みは不要です。ZIP 版も設定をユーザープロファイルに保存するため、完全なポータブル版ではありません。
以下はソース版の起動・更新手順です。exe に更新を反映するには再ビルドしてください。

Python 3.14.7（64bit、Tkinter を含む）と Node.js 22.23.2 を用意して `start.bat` を実行します。
旧Pythonで作成した `.venv` は名前を変更してから実行し、3.14で作り直してください。
依存パッケージは Windows x64 / Python 3.14 用にバージョンと SHA-256 を固定しています。
FFmpeg 9.0.1 / FFprobe は `prepare_ffmpeg.py` が公式サイトから案内される Gyan のビルドを取得し、
固定した SHA-256 を検証して `tools/` に配置します。ハッシュ不一致は展開前に停止します。
リポジトリ更新後に手動で依存を反映する場合:

```powershell
.venv\Scripts\python.exe -m pip install --require-hashes --only-binary=:all: -r requirements.txt
.venv\Scripts\python.exe prepare_ffmpeg.py
```

exe の再ビルド（[PyInstaller](https://www.pyinstaller.org/en/stable/usage.html) を使用）:

```powershell
.venv\Scripts\python.exe -m pip install --require-hashes --only-binary=:all: -r requirements-build.txt
.venv\Scripts\python.exe prepare_ffmpeg.py
.venv\Scripts\python.exe build_exe.py
```

成果物は `dist/YouTubeMusicDownloader/` です。このフォルダー全体を ZIP 化します。
インストーラーは [Inno Setup 6](https://jrsoftware.org/isinfo.php) で作成します。

```powershell
Compress-Archive -Path dist/YouTubeMusicDownloader -DestinationPath dist/YouTubeMusicDownloader-0.1.0-windows-x64.zip
& "${env:ProgramFiles(x86)}/Inno Setup 6/ISCC.exe" /DAppVersion=0.1.0 installer.iss
```

Windows 10 以降の x64 向けです。インストーラーは管理者権限不要で、
`%LOCALAPPDATA%\Programs\YouTubeMusicDownloader` に配置し、スタートメニューにショートカットを作成します。
更新時はアプリを終了して新しいインストーラーを実行してください。
インストーラー更新時はアプリ管理下の `_internal` を入れ替え、古いランタイムも削除します。
アンインストールしても設定・履歴・保存した音楽は削除しません。アプリ内の自動更新機能は含みません。

## GitHub Release

[Releases](https://github.com/sakuya121212/youtube-downloader/releases/latest) から ZIP または `-setup.exe` を取得できます。
`main` への push（PR マージを含む）で `.github/workflows/release.yml` が起動します。
テスト、exe ビルド、ZIP・インストーラー作成、起動・インストール・アンインストールの検証が成功した場合に Release を登録します。
バージョンは `0.1.<github.run_number>`、タグは `v0.1.<github.run_number>` です。失敗した実行の番号は欠番になります。
Actions の「Run workflow」から main を指定して手動リリースもできます。
ビルドは読み取り権限のみで実行し、認証情報を checkout に保存しません。
公開専用ジョブだけに Release 書き込み権限を与え、配布物を実行せずアップロードします。
Actions はコミット SHA 固定です。各 Release の `DEPENDENCIES.json` に Python・Node・FFmpeg とパッケージの実バージョンを記録します。
署名は設定していません。

Dependabot が Python 依存と Actions の更新 PR を毎週確認します。マージ前にバージョン・ハッシュと変更内容を確認してください。
Python・Node の固定バージョンと FFmpeg の URL・SHA-256 はセキュリティ更新時に明示的に更新します。
依存を手動更新するときは Python 3.14 / Windows x64 で `pip download --only-binary=:all:` により対象 wheel を取得し、
`pip hash <wheel>` の結果と全推移依存のバージョンを requirements ファイルへ反映してください。
固定したまま放置せず、少なくとも月次およびセキュリティ修正の公開時にランタイムも確認してください。

YouTube の取得処理には [yt-dlp](https://github.com/yt-dlp/yt-dlp) を使用しています。
JavaScript 実行環境と EJS の設定は [公式ガイド](https://github.com/yt-dlp/yt-dlp/wiki/EJS) に従っています。
非公開・ログイン必須・地域制限などの動画は取得できない場合があります。

## 検証

```powershell
.venv\Scripts\python.exe -m unittest -v
```

ネットワーク取得をローカル音声に置き換え、URL 判定、設定の永続化、実際の MP3 変換、同名ファイル保護、履歴、再取得確認、エラー復帰を検証します。

2026-09-13 に上記テストの成功と、公開動画「Me at the zoo」の音声を YouTube から WebM で取得できることを確認しました。
