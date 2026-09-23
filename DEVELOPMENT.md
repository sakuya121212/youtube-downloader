# 開発・配布手順

利用者向けの案内は [README.md](README.md) を参照してください。

## ソースからの起動とビルド

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

成果物は `dist/YouTubeDownloader/` です。このフォルダー全体を ZIP 化します。
インストーラーは [Inno Setup 6](https://jrsoftware.org/isinfo.php) で作成します。

```powershell
Compress-Archive -Path dist/YouTubeDownloader -DestinationPath dist/YouTubeDownloader-0.1.0-windows-x64.zip
& "${env:ProgramFiles(x86)}/Inno Setup 6/ISCC.exe" /DAppVersion=0.1.0 installer.iss
```

## GitHub Actions と依存の更新

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

## 旧ソース版からの移行

旧版の `data/library.sqlite3` は、新しい保存先がまだない場合に起動元フォルダーからコピーして引き継ぎます。元ファイルは残します。
ソース版から配布版へ移行する場合は、更新後の `start.bat` を一度起動してください。

## 検証

```powershell
.venv\Scripts\python.exe -m unittest -v
```

ネットワーク取得をローカル音声に置き換え、URL 判定、設定の永続化、実際の MP3 変換、同名ファイル保護、履歴、再取得確認、エラー復帰を検証します。
動画はローカルの映像・音声を実際の yt-dlp／FFmpeg で取得・結合し、画質選択と各音質設定で保存した MKV・MP4 を FFprobe で検証します。タブごとの設定・履歴、旧DB移行、起動タブ、両タブのキャンセルも確認します。

2026-09-13 に上記テストの成功と、公開動画「Me at the zoo」の音声を YouTube から WebM で取得できることを確認しました。
