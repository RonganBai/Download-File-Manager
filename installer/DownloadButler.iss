; 下载管家 安装包脚本（Inno Setup 6）——由 build.ps1 调用
#define AppName "下载管家"
#define AppVersion "2.2.0"
#define AppPublisher "RonganBai"
#define AppExe "DownloadButler.exe"
#ifndef DistDir
  #define DistDir "..\dist\DownloadButler"
#endif

[Setup]
AppId={{6E2D4B71-93A8-4C5F-B0D2-7F1C8A3E5D94}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
; 按用户安装，无需管理员权限（整理的是当前用户的下载文件夹）
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
DefaultDirName={autopf}\DownloadButler
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=Output
OutputBaseFilename=DownloadButler-Setup-{#AppVersion}
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; 程序运行时持有这个互斥体：安装 / 卸载前提示关闭
AppMutex=DownloadButlerMutex
CloseApplications=yes
VersionInfoVersion={#AppVersion}
VersionInfoProductName=Download Butler

[Languages]
Name: "default"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
default.TaskDesktop=创建桌面快捷方式 / Create a desktop shortcut
default.TaskAutostart=开机自动在后台运行（自动整理下载文件夹）/ Start with Windows
default.GroupExtra=附加选项 / Additional options:
default.LaunchApp=立即运行 下载管家 / Launch Download Butler

[Tasks]
Name: "desktopicon"; Description: "{cm:TaskDesktop}"; GroupDescription: "{cm:GroupExtra}"
Name: "autostart"; Description: "{cm:TaskAutostart}"; GroupDescription: "{cm:GroupExtra}"

[Files]
Source: "{#DistDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; 覆盖安装时清掉旧版本残留的运行库
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"; IconFilename: "{app}\_internal\assets\icon.ico"
Name: "{group}\卸载 {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; IconFilename: "{app}\_internal\assets\icon.ico"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "{#AppName}"; \
    ValueData: """{app}\{#AppExe}"" --min"; Flags: uninsdeletevalue; Tasks: autostart

[Run]
; 刷新 Windows 图标缓存，覆盖安装后桌面 / 开始菜单立即显示新图标
Filename: "{sys}\ie4uinit.exe"; Parameters: "-show"; Flags: runhidden nowait
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchApp}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; 缩略图缓存（设置与背景图保存在 %APPDATA%\下载管家，卸载时保留）
Type: filesandordirs; Name: "{localappdata}\DownloadButler\thumbs"

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  { 程序内开启的开机启动也一并移除 }
  if CurUninstallStep = usUninstall then
    RegDeleteValue(HKEY_CURRENT_USER, 'Software\Microsoft\Windows\CurrentVersion\Run', '{#AppName}');
end;
