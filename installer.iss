#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif

[Setup]
AppId={{5918B153-67A0-4832-A0F6-C6E2A490024A}
AppName=YouTube Downloader
AppVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\YouTubeDownloader
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=dist
OutputBaseFilename=YouTubeDownloader-{#AppVersion}-windows-x64-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\YouTubeDownloader.exe
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "japanese"; MessagesFile: "compiler:Languages\Japanese.isl"

[Files]
Source: "dist\YouTubeDownloader\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

; Remove obsolete bundled runtimes during upgrades; user data lives elsewhere.
[InstallDelete]
Type: filesandordirs; Name: "{app}\_internal"
Type: files; Name: "{app}\YouTubeMusicDownloader.exe"
Type: files; Name: "{userprograms}\YouTube Music Downloader.lnk"

[Icons]
Name: "{userprograms}\YouTube Downloader"; Filename: "{app}\YouTubeDownloader.exe"

[Run]
Filename: "{app}\YouTubeDownloader.exe"; Description: "Launch YouTube Downloader"; Flags: nowait postinstall skipifsilent
