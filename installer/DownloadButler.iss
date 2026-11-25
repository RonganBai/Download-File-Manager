; 自动整理文件管理器（原名“下载管家”）安装包脚本（Inno Setup 6）——由 build.ps1 调用
#define AppName "自动整理文件管理器"
; 旧名称：开机启动项的名字沿用它（程序内也用它读写），旧版的快捷方式在升级时删除
#define OldName "下载管家"
#define AppVersion "2.10.0"
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
; 改名后开始菜单文件夹也用新名称（旧的“下载管家”文件夹在 [InstallDelete] 中删除）
UsePreviousGroup=no
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
; 程序常驻托盘，关闭窗口不会退出：安装 / 卸载前由 [Code] 先结束它（并等它真正退出）。
; 之后再用 Windows 重启管理器检查其他占用安装目录文件的程序（如资源管理器扩展、同步盘、杀毒软件），
; 交互安装时列出来让用户选择关闭，静默更新时自动关闭；装完不重启它们。
CloseApplications=yes
CloseApplicationsFilter=*.exe,*.dll,*.pyd
RestartApplications=no
VersionInfoVersion={#AppVersion}
VersionInfoProductName=Download Butler
VersionInfoDescription={#AppName}

[Languages]
Name: "default"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
default.TaskDesktop=创建桌面快捷方式 / Create a desktop shortcut
default.TaskAutostart=开机自动在后台运行（自动整理下载文件夹）/ Start with Windows
default.GroupExtra=附加选项 / Additional options:
default.LaunchApp=立即运行 {#AppName} / Launch Download Butler

[Tasks]
Name: "desktopicon"; Description: "{cm:TaskDesktop}"; GroupDescription: "{cm:GroupExtra}"
Name: "autostart"; Description: "{cm:TaskAutostart}"; GroupDescription: "{cm:GroupExtra}"

[Files]
Source: "{#DistDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; 覆盖安装时清掉旧版本残留的运行库
Type: filesandordirs; Name: "{app}\_internal"
; 改名前（下载管家）创建的快捷方式
Type: filesandordirs; Name: "{autoprograms}\{#OldName}"
Type: files; Name: "{autodesktop}\{#OldName}.lnk"
Type: files; Name: "{userdesktop}\{#OldName}.lnk"

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"; IconFilename: "{app}\_internal\assets\icon.ico"
Name: "{group}\卸载 {#AppName}"; Filename: "{uninstallexe}"
; 桌面快捷方式已存在且指向本程序时不重写：重写会让资源管理器当成新图标，挪到桌面第一个空位
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; IconFilename: "{app}\_internal\assets\icon.ico"; Tasks: desktopicon; \
    Check: NeedDesktopIcon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "{#OldName}"; \
    ValueData: """{app}\{#AppExe}"" --min"; Flags: uninsdeletevalue; Tasks: autostart

[Run]
; 新建了桌面快捷方式时才刷新图标缓存：每次都刷新会让桌面重新载入布局，图标可能跳回旧位置
Filename: "{sys}\ie4uinit.exe"; Parameters: "-show"; Flags: runhidden nowait; Check: NeedIconRefresh
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchApp}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; 缩略图缓存（设置与背景图保存在 %APPDATA%\下载管家，卸载时保留）
Type: filesandordirs; Name: "{localappdata}\DownloadButler\thumbs"

[Code]
var
  WasRunning: Boolean;
  DesktopCreated: Boolean;

{ 快捷方式是否存在并且指向安装目录里的程序 }
function LinkPointsToApp(Lnk: String): Boolean;
var
  Shell, Link: Variant;
  Target: String;
begin
  Result := False;
  if not FileExists(Lnk) then Exit;
  try
    Shell := CreateOleObject('WScript.Shell');
    Link := Shell.CreateShortcut(Lnk);
    Target := Link.TargetPath;
    Result := CompareText(Target, ExpandConstant('{app}\{#AppExe}')) = 0;
  except
    Result := True;   { 读不了就保留原样，宁可不动也不打乱桌面 }
  end;
end;

{ 升级时桌面上已有可用的快捷方式就保留原文件（位置不变）；没有或已失效才新建 }
function NeedDesktopIcon(): Boolean;
begin
  Result := not LinkPointsToApp(ExpandConstant('{autodesktop}\{#AppName}.lnk'));
  if Result then DesktopCreated := True;
end;

function NeedIconRefresh(): Boolean;
begin
  Result := DesktopCreated;
end;

{ 安装目录里的 DownloadButler.exe 是否在运行：
  先看互斥体（当前登录会话），再用 WMI 按进程路径查（也能发现以管理员身份运行的实例） }
function AppRunning(): Boolean;
var
  Locator, Svc, Procs, P: Variant;
  I: Integer;
  Dir, Path: String;
begin
  Result := CheckForMutexes('DownloadButlerMutex');
  if Result then Exit;
  Dir := Lowercase(AddBackslash(ExpandConstant('{app}')));
  try
    Locator := CreateOleObject('WbemScripting.SWbemLocator');
    Svc := Locator.ConnectServer('.', 'root\CIMV2');
    Procs := Svc.ExecQuery('SELECT ExecutablePath FROM Win32_Process WHERE Name = ''{#AppExe}''');
    for I := 0 to Procs.Count - 1 do
    begin
      P := Procs.ItemIndex(I);
      Path := '';
      if not VarIsNull(P.ExecutablePath) then Path := P.ExecutablePath;
      Path := Lowercase(Path);
      if Pos(Dir, Path) = 1 then
      begin
        Result := True;
        Exit;
      end;
    end;
  except
    { WMI 不可用时只依赖互斥体 }
  end;
end;

{ 结束正在运行的程序，并等它真正退出（最多 10 秒）；返回之前是否在运行 }
function StopApp(): Boolean;
var
  Code, I: Integer;
begin
  Result := AppRunning();
  if not Result then Exit;
  { /T：连同它启动的子进程（如 7-Zip）一起结束；不只看互斥体，旧版本没有互斥体也能关掉 }
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /T /IM {#AppExe}', '', SW_HIDE, ewWaitUntilTerminated, Code);
  for I := 1 to 50 do
  begin
    if not AppRunning() then Break;
    Sleep(200);
  end;
  Sleep(300);   { 进程退出后系统还要一点时间释放文件句柄 }
end;

function NotClosedMsg(): String;
begin
  Result := '无法关闭正在运行的 {#AppName}（可能是以管理员身份运行的）。' + #13#10 +
            '请右键托盘图标选择“退出”，或在任务管理器中结束 {#AppExe}，然后重试。';
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  WasRunning := StopApp();
  if AppRunning() then
    Result := NotClosedMsg()
  else
    Result := '';
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Code: Integer;
  Mode: String;
begin
  if CurStep <> ssPostInstall then Exit;
  { 程序内更新会传 /relaunch=show 或 /relaunch=min；其他静默更新时，原来在运行就在托盘重新启动。
    以原来的用户身份启动：安装程序是管理员身份时，不让程序也带着管理员权限运行 }
  Mode := ExpandConstant('{param:relaunch|}');
  if (Mode = '') and WasRunning and WizardSilent() then Mode := 'min';
  if Mode = 'show' then
    ExecAsOriginalUser(ExpandConstant('{app}\{#AppExe}'), '', '', SW_SHOW, ewNoWait, Code)
  else if Mode = 'min' then
    ExecAsOriginalUser(ExpandConstant('{app}\{#AppExe}'), '--min', '', SW_SHOW, ewNoWait, Code);
end;

function InitializeUninstall(): Boolean;
begin
  StopApp();
  Result := not AppRunning();
  if not Result and not UninstallSilent() then
    MsgBox(NotClosedMsg(), mbError, MB_OK);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  { 程序内开启的开机启动也一并移除 }
  if CurUninstallStep = usUninstall then
    RegDeleteValue(HKEY_CURRENT_USER, 'Software\Microsoft\Windows\CurrentVersion\Run', '{#OldName}');
end;
