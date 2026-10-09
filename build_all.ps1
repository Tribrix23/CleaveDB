$ErrorActionPreference = "Stop"
Write-Host "Starting PyInstaller..."
pyinstaller --noconfirm cleaveshell.spec
if ($LASTEXITCODE -ne 0) {
    Write-Host "PyInstaller failed with code $LASTEXITCODE"
    exit $LASTEXITCODE
}
Write-Host "PyInstaller finished successfully."

Write-Host "Building Go Coordinator..."
$env:CGO_ENABLED="0"
go build -o coordinator.exe coordinator\src\main.go coordinator\src\merge.go
if ($LASTEXITCODE -ne 0) {
    Write-Host "Go Coordinator build failed with code $LASTEXITCODE"
    exit $LASTEXITCODE
}
Write-Host "Go Coordinator finished successfully."

Write-Host "Starting Inno Setup Compiler..."
& "C:\Users\Administrator\AppData\Local\Programs\Inno Setup 6\iscc.exe" CleaveDB_Installer.iss
if ($LASTEXITCODE -ne 0) {
    Write-Host "Inno Setup failed with code $LASTEXITCODE"
    exit $LASTEXITCODE
}
Write-Host "Inno Setup finished successfully. Final installer is ready."
