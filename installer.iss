[Setup]
AppName=ReDrive Rider
AppVersion=0.1.0
AppPublisher=EstimStation
AppPublisherURL=https://www.estimstation.com
DefaultDirName={autopf}\ReDrive Rider
DefaultGroupName=ReDrive Rider
OutputBaseFilename=ReDriveRider-Setup
Compression=lzma
SolidCompression=yes

[Files]
Source: "dist\ReDriveRider.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\ReDrive Rider"; Filename: "{app}\ReDriveRider.exe"
Name: "{commondesktop}\ReDrive Rider"; Filename: "{app}\ReDriveRider.exe"

[Run]
Filename: "{app}\ReDriveRider.exe"; Description: "Launch ReDrive Rider"; Flags: postinstall nowait
