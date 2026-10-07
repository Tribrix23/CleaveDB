[Setup]
AppName=CleaveDB
AppVersion=3.9.0
DefaultDirName={autopf}\CleaveDB
DefaultGroupName=CleaveDB
OutputDir=dist
OutputBaseFilename=CleaveDB-v3.9.0-Setup
SetupIconFile=cleavedb.ico
Compression=lzma
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64
ChangesEnvironment=yes
PrivilegesRequired=admin

[Files]
Source: "dist\cleaveshell.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "edge_gateway.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "README.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\CleaveDB Shell"; Filename: "{app}\cleaveshell.exe"
Name: "{group}\Uninstall CleaveDB"; Filename: "{uninstallexe}"

[Registry]
; Add to PATH
Root: HKLM; Subkey: "SYSTEM\CurrentControlSet\Control\Session Manager\Environment"; \
    ValueType: expandsz; ValueName: "Path"; ValueData: "{olddata};{app}"; \
    Check: NeedsAddPath(ExpandConstant('{app}'))

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
