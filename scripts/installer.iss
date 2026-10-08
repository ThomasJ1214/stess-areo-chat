; Inno Setup 6. Build through scripts/build_windows.py.
#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif
#ifndef BuildRoot
  #define BuildRoot ".."
#endif

[Setup]
AppId={{F5D77257-B891-4273-9278-8F524629B532}
AppName=Rocket Workbench
AppVersion={#AppVersion}
AppPublisher=Rocket Workbench contributors
DefaultDirName={localappdata}\Programs\Rocket Workbench
DefaultGroupName=Rocket Workbench
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
DisableProgramGroupPage=yes
OutputDir={#BuildRoot}\release
OutputBaseFilename=RocketWorkbench-{#AppVersion}-windows-x64-setup
Compression=lzma2/normal
SolidCompression=yes
DiskSpanning=no
WizardStyle=modern
UninstallDisplayIcon={app}\RocketWorkbench.exe
LicenseFile={#BuildRoot}\LICENSE
SetupLogging=yes
CloseApplications=yes

[Files]
Source: "{#BuildRoot}\dist\RocketWorkbench\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: unchecked

[Icons]
Name: "{group}\Rocket Workbench"; Filename: "{app}\RocketWorkbench.exe"
Name: "{autodesktop}\Rocket Workbench"; Filename: "{app}\RocketWorkbench.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\RocketWorkbench.exe"; Description: "Launch Rocket Workbench"; Flags: nowait postinstall skipifsilent
