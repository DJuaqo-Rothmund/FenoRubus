; Instalador de PhenoRubus para Windows (Inno Setup 6).
;   iscc /DAppVersion=1.1.90 tools\windows\installer.iss
#ifndef AppVersion
  #define AppVersion "dev"
#endif

[Setup]
AppId={{7C1B9E52-3E1A-4C55-9F1E-6A3B2D9F0E11}
AppName=PhenoRubus
AppVersion={#AppVersion}
AppPublisher=PhenoRubus
DefaultDirName={localappdata}\Programs\PhenoRubus
DefaultGroupName=PhenoRubus
PrivilegesRequired=lowest
OutputDir=..\..\dist
OutputBaseFilename=PhenoRubus-{#AppVersion}-Windows
SetupIconFile=phenorubus.ico
UninstallDisplayIcon={app}\PhenoRubus.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "es"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "desktopicon"; Description: "Crear un acceso directo en el escritorio"; GroupDescription: "Accesos directos:"

[Files]
Source: "..\..\dist\PhenoRubus\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\PhenoRubus"; Filename: "{app}\PhenoRubus.exe"
Name: "{autodesktop}\PhenoRubus"; Filename: "{app}\PhenoRubus.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\PhenoRubus.exe"; Description: "Abrir PhenoRubus"; Flags: nowait postinstall skipifsilent
