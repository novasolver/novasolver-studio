; Windows installer for NovaSolver Studio (Inno Setup 6). Built by build_release.ps1 when ISCC.exe is available
; (GitHub Actions windows runners have it), from the same PyInstaller folder as the portable zip:
;   ISCC.exe /DAppVersion=0.7.0 /DAppDir=<build\dist\NovaSolverStudio> /DOutDir=<release> installer\NovaSolverStudio.iss
; Per-user by default: no administrator rights, installs to %LOCALAPPDATA%\Programs, so the built-in updater can
; replace the program folder later. Cases stay in Documents\NovaSolverStudio and are never removed by uninstall.

#ifndef AppVersion
  #error Pass /DAppVersion=x.y.z
#endif
#ifndef AppDir
  #error Pass /DAppDir=<PyInstaller output folder>
#endif
#ifndef OutDir
  #define OutDir "..\release"
#endif

[Setup]
AppId={{6F3C2B9A-7D4E-4E1B-9C55-2A8F0E6B1D37}
AppName=NovaSolver Studio
AppVersion={#AppVersion}
AppVerName=NovaSolver Studio {#AppVersion}
AppPublisher=NovaSolver
AppPublisherURL=https://novasolver.jp/studio/
AppSupportURL=https://github.com/novasolver/novasolver-studio/issues
AppUpdatesURL=https://github.com/novasolver/novasolver-studio/releases
DefaultDirName={autopf}\NovaSolverStudio
DefaultGroupName=NovaSolver Studio
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#OutDir}
OutputBaseFilename=NovaSolverStudio-{#AppVersion}-win64-setup
SetupIconFile=..\assets\NovaSolverStudio.ico
UninstallDisplayIcon={app}\NovaSolverStudio.exe
LicenseFile=..\LICENSE
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ChangesAssociations=yes
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "ja"; MessagesFile: "compiler:Languages\Japanese.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
ja.AssocTask=.nscase ファイルを NovaSolver Studio で開く
en.AssocTask=Open .nscase files with NovaSolver Studio
ja.CaseFile=NovaSolver Studio ケース
en.CaseFile=NovaSolver Studio case

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "assoc"; Description: "{cm:AssocTask}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "{#AppDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\NovaSolver Studio"; Filename: "{app}\NovaSolverStudio.exe"
Name: "{group}\{cm:UninstallProgram,NovaSolver Studio}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\NovaSolver Studio"; Filename: "{app}\NovaSolverStudio.exe"; Tasks: desktopicon

[Registry]
; HKA = current user for a per-user install, all users for an administrator install
Root: HKA; Subkey: "Software\Classes\.nscase"; ValueType: string; ValueName: ""; ValueData: "NovaSolverStudio.Case"; Flags: uninsdeletevalue; Tasks: assoc
Root: HKA; Subkey: "Software\Classes\.nscase\OpenWithProgids"; ValueType: string; ValueName: "NovaSolverStudio.Case"; ValueData: ""; Flags: uninsdeletevalue; Tasks: assoc
Root: HKA; Subkey: "Software\Classes\NovaSolverStudio.Case"; ValueType: string; ValueName: ""; ValueData: "{cm:CaseFile}"; Flags: uninsdeletekey; Tasks: assoc
Root: HKA; Subkey: "Software\Classes\NovaSolverStudio.Case\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\NovaSolverStudio.exe,0"; Tasks: assoc
Root: HKA; Subkey: "Software\Classes\NovaSolverStudio.Case\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\NovaSolverStudio.exe"" ""%1"""; Tasks: assoc

[Run]
Filename: "{app}\NovaSolverStudio.exe"; Description: "{cm:LaunchProgram,NovaSolver Studio}"; Flags: nowait postinstall skipifsilent
