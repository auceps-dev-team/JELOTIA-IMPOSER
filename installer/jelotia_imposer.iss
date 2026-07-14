; Inno Setup Script — JELOTIA IMPOSER
; Génère un installeur Windows standalone
; Usage : ouvrir dans Inno Setup Compiler et cliquer "Compile"

#define AppName      "Jelotia Imposer"
#define AppVersion   "1.17.1"
#define AppPublisher "Jelotia"
#define AppURL       "https://www.jelotia.com"
#define AppExeName   "JelotiaImposer.exe"
#define BuildDir     "..\dist\JelotiaImposer"

[Setup]
AppId={{A3F7B241-EC2D-4C6A-B9F1-2D0E8A3C5F71}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}
AppUpdatesURL={#AppURL}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
AllowNoIcons=yes
; Require admin rights for installation
PrivilegesRequired=admin
OutputDir=.\output
OutputBaseFilename=JelotiaImposer_v{#AppVersion}_Setup
SetupIconFile=jelotia.ico
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
; Minimum Windows 10
MinVersion=10.0
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64

[Languages]
Name: "french";    MessagesFile: "compiler:Languages\French.isl"
Name: "english";   MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon";  Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "startmenu";    Description: "Créer un raccourci dans le menu Démarrer"; GroupDescription: "Raccourcis"

[Files]
; Main application files (built by PyInstaller)
Source: "{#BuildDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}";         Filename: "{app}\{#AppExeName}"; IconFilename: "{app}\_internal\jelotia.ico"
Name: "{group}\Désinstaller {#AppName}"; Filename: "{uninstallexe}"
Name: "{commondesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; IconFilename: "{app}\_internal\jelotia.ico"; Tasks: desktopicon

[Dirs]
; Créer les dossiers de travail au niveau utilisateur
Name: "{commonappdata}\Jelotia\HotFolder\Input"
Name: "{commonappdata}\Jelotia\HotFolder\Processing"
Name: "{commonappdata}\Jelotia\HotFolder\Output"
Name: "{commonappdata}\Jelotia\HotFolder\Error"
Name: "{commonappdata}\Jelotia\HotFolder\Archive"
Name: "{commonappdata}\Jelotia\Logs"

[Registry]
; Enregistrer les chemins par défaut dans le registre
Root: HKLM; Subkey: "SOFTWARE\Jelotia\Imposer"; ValueType: string; ValueName: "InstallPath"; ValueData: "{app}"; Flags: createvalueifdoesntexist
Root: HKLM; Subkey: "SOFTWARE\Jelotia\Imposer"; ValueType: string; ValueName: "DataPath";    ValueData: "{commonappdata}\Jelotia"; Flags: createvalueifdoesntexist
Root: HKLM; Subkey: "SOFTWARE\Jelotia\Imposer"; ValueType: string; ValueName: "Version";     ValueData: "{#AppVersion}"; Flags: createvalueifdoesntexist

[Run]
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(AppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Supprimer la config locale à la désinstallation (optionnel)
Type: filesandordirs; Name: "{userappdata}\JelotiaImposer"

[Code]
// Vérifier que .NET / Visual C++ Runtime est présent si nécessaire
procedure InitializeWizard;
begin
  WizardForm.WelcomeLabel2.Caption :=
    'Ce programme va installer {#AppName} version {#AppVersion} sur votre ordinateur.'
    + #13#10#13#10
    + 'Assurez-vous que Windows 10 ou supérieur est installé.'
    + #13#10#13#10
    + 'Cliquez sur Suivant pour continuer.';
end;
