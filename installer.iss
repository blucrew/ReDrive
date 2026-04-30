[Setup]
AppName=ReDrive Rider
AppVersion=0.1.0
AppPublisher=eStimStation
AppPublisherURL=https://www.estimstation.com
AppSupportURL=https://www.estimstation.com
AppUpdatesURL=https://www.estimstation.com
DefaultDirName={autopf}\ReDrive Rider
DefaultGroupName=ReDrive Rider
DisableProgramGroupPage=yes
OutputDir=dist\installer
OutputBaseFilename=ReDriveRider-Setup
SetupIconFile=rider_icon.ico
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
UninstallDisplayIcon={app}\ReDriveRider.exe
; Minimum Windows 10
MinVersion=10.0

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional icons:"; Flags: checked

[Files]
Source: "dist\ReDriveRider.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\ReDrive Rider"; Filename: "{app}\ReDriveRider.exe"
Name: "{group}\Uninstall ReDrive Rider"; Filename: "{uninstallexe}"
Name: "{commondesktop}\ReDrive Rider"; Filename: "{app}\ReDriveRider.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\ReDriveRider.exe"; Description: "Launch ReDrive Rider now"; Flags: postinstall nowait skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}"
