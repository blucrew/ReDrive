; ReDrive Rider — Inno Setup script
#define AppName    "ReDrive Rider"
#define AppVersion "0.1.0"
#define AppURL     "https://redrive.estimstation.com"
#define ExeName    "ReDriveRider.exe"

[Setup]
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=EstimStation
AppPublisherURL={#AppURL}
DefaultDirName={autopf}\ReDrive Rider
DefaultGroupName=ReDrive Rider
OutputDir=dist
OutputBaseFilename=ReDriveRider-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
DisableWelcomePage=no
LicenseFile=

[Files]
Source: "dist\{#ExeName}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\ReDrive Rider"; Filename: "{app}\{#ExeName}"
Name: "{commondesktop}\ReDrive Rider"; Filename: "{app}\{#ExeName}"; Tasks: desktopicon

[Tasks]
Name: desktopicon; Description: "Create a &desktop shortcut"; GroupDescription: "Additional icons:"

[Run]
Filename: "{app}\{#ExeName}"; Description: "Launch ReDrive Rider"; Flags: nowait postinstall skipifsilent
