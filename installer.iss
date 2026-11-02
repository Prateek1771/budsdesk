; Windows installer (Inno Setup 6):  iscc /DVersion=1.0.0 installer.iss  ->  dist\BudsDesk-Setup.exe
#ifndef Version
  #define Version "0.0.0"
#endif

[Setup]
AppId={{6F1B7C2E-4B1D-4C55-9A3E-B0D5D35C1771}
AppName=BudsDesk
AppVersion={#Version}
AppPublisher=Prateek1771
AppPublisherURL=https://github.com/Prateek1771/budsdesk
DefaultDirName={localappdata}\Programs\BudsDesk
DefaultGroupName=BudsDesk
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=dist
OutputBaseFilename=BudsDesk-Setup
SetupIconFile=ui\icon.ico
UninstallDisplayIcon={app}\BudsDesk.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes

[Tasks]
Name: desktopicon; Description: "Create a &desktop shortcut"; Flags: unchecked

[Files]
Source: "dist\BudsDesk.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\BudsDesk"; Filename: "{app}\BudsDesk.exe"
Name: "{autodesktop}\BudsDesk"; Filename: "{app}\BudsDesk.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\BudsDesk.exe"; Description: "Launch BudsDesk"; Flags: nowait postinstall skipifsilent
