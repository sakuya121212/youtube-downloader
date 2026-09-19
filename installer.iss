#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif

[Setup]
AppId={{5918B153-67A0-4832-A0F6-C6E2A490024A}
AppName=YouTube Music Downloader
AppVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\YouTubeMusicDownloader
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=dist
OutputBaseFilename=YouTubeMusicDownloader-{#AppVersion}-windows-x64-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\YouTubeMusicDownloader.exe
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "japanese"; MessagesFile: "compiler:Languages\Japanese.isl"

[Files]
Source: "dist\YouTubeMusicDownloader\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

; Remove obsolete bundled runtimes during upgrades; user data lives elsewhere.
[InstallDelete]
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{userprograms}\YouTube Music Downloader"; Filename: "{app}\YouTubeMusicDownloader.exe"

[Run]
Filename: "{app}\YouTubeMusicDownloader.exe"; Description: "Launch YouTube Music Downloader"; Flags: nowait postinstall skipifsilent
