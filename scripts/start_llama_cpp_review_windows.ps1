param(
    [string]$PythonExe = "F:\study\localmodel\.venv\Scripts\python.exe",
    [string]$ModelPath = "F:\study\aishortmovie\aivedio\models\qwen\qwen2.5-14b-instruct-q4_k_m.gguf",
    [string]$ModelAlias = "local-vlm",
    [string]$HostAddress = "127.0.0.1",
    [int]$Port = 8080,
    [int]$ContextSize = 4096,
    [int]$GpuLayers = 20
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $PythonExe)) {
    throw "Python runtime not found: $PythonExe"
}

if (-not (Test-Path -LiteralPath $ModelPath)) {
    throw "GGUF model not found: $ModelPath"
}

$ProjectRoot = Split-Path $PSScriptRoot -Parent
$logDir = Join-Path $ProjectRoot "storage\logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

$stdoutLog = Join-Path $logDir "llama_cpp_review.out.log"
$stderrLog = Join-Path $logDir "llama_cpp_review.err.log"

$alreadyOpen = Test-NetConnection $HostAddress -Port $Port -InformationLevel Quiet
if ($alreadyOpen) {
    Write-Host "llama.cpp review service is already running at http://${HostAddress}:${Port}/v1"
    Write-Host "stdout: $stdoutLog"
    Write-Host "stderr: $stderrLog"
    exit 0
}

$argsList = @(
    "-m", "llama_cpp.server",
    "--model", $ModelPath,
    "--model_alias", $ModelAlias,
    "--host", $HostAddress,
    "--port", "$Port",
    "--n_ctx", "$ContextSize",
    "--n_gpu_layers", "$GpuLayers",
    "--chat_format", "chatml",
    "--verbose", "False"
)

& cmd /c start "llama.cpp review" /D "$ProjectRoot" /MIN "$PythonExe" @argsList

Start-Sleep -Seconds 20
$isOpen = Test-NetConnection $HostAddress -Port $Port -InformationLevel Quiet

if (-not $isOpen) {
    Write-Host "llama.cpp review service did not become ready on ${HostAddress}:${Port}."
    Write-Host "stdout: $stdoutLog"
    Write-Host "stderr: $stderrLog"
    exit 1
}

Write-Host "llama.cpp review service is running at http://${HostAddress}:${Port}/v1"
Write-Host "stdout: $stdoutLog"
Write-Host "stderr: $stderrLog"
