[Setup]
AppName=CleaveDB
AppVersion=4.0.1
DefaultDirName={autopf}\CleaveDB
DefaultGroupName=CleaveDB
OutputDir=dist
OutputBaseFilename=CleaveDB-v4.0.1-Setup
SetupIconFile=cleavedb.ico
Compression=lzma
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64
ChangesEnvironment=yes
PrivilegesRequired=admin

[Files]
Source: "dist\cleaveshell\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "edge_gateway.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "coordinator.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "README.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\CleaveDB Shell"; Filename: "{app}\cleaveshell.exe"
Name: "{group}\Uninstall CleaveDB"; Filename: "{uninstallexe}"

[Registry]
; Add to PATH
Root: HKLM; Subkey: "SYSTEM\CurrentControlSet\Control\Session Manager\Environment"; \
    ValueType: expandsz; ValueName: "Path"; ValueData: "{olddata};{app}"; \
    Check: NeedsAddPath(ExpandConstant('{app}'))

[UninstallRun]
Filename: "{cmd}"; Parameters: "/c taskkill /f /im cleaveshell.exe /t"; RunOnceId: "KillCleaveShell"; Flags: runhidden
Filename: "{cmd}"; Parameters: "/c taskkill /f /im edge_gateway.exe /t"; RunOnceId: "KillEdgeGateway"; Flags: runhidden
Filename: "{cmd}"; Parameters: "/c taskkill /f /im coordinator.exe /t"; RunOnceId: "KillCoordinator"; Flags: runhidden

[Code]
function NeedsAddPath(Param: string): boolean;
var
  OrigPath: string;
begin
  if not RegQueryStringValue(HKEY_LOCAL_MACHINE,
    'SYSTEM\CurrentControlSet\Control\Session Manager\Environment',
    'Path', OrigPath)
  then begin
    Result := True;
    exit;
  end;
  Result := Pos(';' + Param + ';', ';' + OrigPath + ';') = 0;
end;
