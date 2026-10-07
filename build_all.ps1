$ErrorActionPreference = "Stop"
Write-Host "Starting PyInstaller..."
pyinstaller --noconfirm cleaveshell.spec
if ($LASTEXITCODE -ne 0) {
    Write-Host "PyInstaller failed with code $LASTEXITCODE"
    exit $LASTEXITCODE
}
Write-Host "PyInstaller finished successfully."
Write-Host "Starting Inno Setup Compiler..."
& "C:\Users\Administrator\AppData\Local\Programs\Inno Setup 6\iscc.exe" CleaveDB_Installer.iss
if ($LASTEXITCODE -ne 0) {
    Write-Host "Inno Setup failed with code $LASTEXITCODE"
    exit $LASTEXITCODE
}
Write-Host "Inno Setup finished successfully. Final installer is ready."
