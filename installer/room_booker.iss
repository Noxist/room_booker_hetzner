#define AppName "RoomBooker"
#define AppVersion "2.8"
#define AppPublisher "RoomBooker"
#define AppExeName "RoomBooker.exe"

[Setup]
AppId={{7C8B58B9-6A9A-4E30-9A91-2F63E4B9331C}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\\{#AppName}
DisableProgramGroupPage=yes
OutputDir=..\\dist
OutputBaseFilename=RoomBooker-Setup
Compression=lzma
SolidCompression=yes
WizardStyle=modern

[Files]
Source: "..\\dist\\RoomBooker\\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\\{#AppName}"; Filename: "{app}\\{#AppExeName}"

[Run]
Filename: "{app}\\{#AppExeName}"; Description: "Start RoomBooker"; Flags: nowait postinstall skipifsilent
Filename: "{app}\\{#AppExeName}"; Parameters: "--install-browsers"; Description: "Install Playwright Browser"; Flags: nowait postinstall skipifsilent runhidden
