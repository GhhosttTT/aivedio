param(
    [string]$PythonExe = "F:\study\localmodel\.venv\Scripts\python.exe",
    [string]$ComfyUIDir = "F:\study\aishortmovie\aivedio\ComfyUI",
    [int]$Port = 8188,
    [string]$HostAddress = "127.0.0.1",
    [switch]$Foreground
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $PythonExe)) {
    throw "Python runtime not found: $PythonExe"
}

if (-not (Test-Path -LiteralPath (Join-Path $ComfyUIDir "main.py"))) {
    throw "ComfyUI main.py not found under: $ComfyUIDir"
}

$logDir = Join-Path (Split-Path $ComfyUIDir -Parent) "storage\logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

$stdoutLog = Join-Path $logDir "comfyui.out.log"
$stderrLog = Join-Path $logDir "comfyui.err.log"

$alreadyOpen = Test-NetConnection $HostAddress -Port $Port -InformationLevel Quiet
if ($alreadyOpen) {
    Write-Host "ComfyUI is already running at http://${HostAddress}:${Port}"
    Write-Host "stdout: $stdoutLog"
    Write-Host "stderr: $stderrLog"
    exit 0
}

$argsList = @(
    "main.py",
    "--listen", $HostAddress,
    "--port", "$Port",
    "--normalvram",
    "--log-stdout"
)

if ($Foreground) {
    Push-Location $ComfyUIDir
    try {
        & $PythonExe @argsList
    }
    finally {
        Pop-Location
    }
    exit $LASTEXITCODE
}

& cmd /c start "ComfyUI" /D "$ComfyUIDir" /MIN "$PythonExe" @argsList

Start-Sleep -Seconds 8
$isOpen = Test-NetConnection $HostAddress -Port $Port -InformationLevel Quiet

if (-not $isOpen) {
    Write-Host "ComfyUI did not become ready on ${HostAddress}:${Port}."
    Write-Host "stdout: $stdoutLog"
    Write-Host "stderr: $stderrLog"
    exit 1
}

Write-Host "ComfyUI is running at http://${HostAddress}:${Port}"
Write-Host "stdout: $stdoutLog"
Write-Host "stderr: $stderrLog"
