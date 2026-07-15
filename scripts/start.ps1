param(
    [int]$Port = 8501
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$pythonCandidates = @(
    (Join-Path $root ".venv311\Scripts\python.exe"),
    (Join-Path $root ".venv\Scripts\python.exe")
) | Where-Object { Test-Path -LiteralPath $_ }
$python = $null
foreach ($candidate in $pythonCandidates) {
    try {
        $candidateVersion = (& $candidate -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null).Trim()
        if ($LASTEXITCODE -eq 0 -and $candidateVersion -eq "3.11") {
            $python = $candidate
            break
        }
    } catch {}
}
if (-not $python) {
    throw "A working Python 3.11 environment is missing. Recreate .venv311 and run pip install -e `".[dev]`"."
}

$runtimeDirs = @(
    "$env:LOCALAPPDATA\Programs\Ollama",
    "C:\Program Files\Tesseract-OCR",
    "$env:LOCALAPPDATA\Programs\Ghostscript\bin"
) | Where-Object { Test-Path -LiteralPath $_ }
$env:Path = ($runtimeDirs + $env:Path) -join [IO.Path]::PathSeparator

$localTessdata = Join-Path $root ".runtime\tessdata"
if (Test-Path -LiteralPath (Join-Path $localTessdata "ukr.traineddata")) {
    $env:TESSDATA_PREFIX = $localTessdata
}

$ollamaCommand = Get-Command ollama -ErrorAction SilentlyContinue
$ollamaPath = if ($ollamaCommand) { $ollamaCommand.Source } else { $null }
if (-not $ollamaPath) {
    $candidate = "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe"
    if (Test-Path -LiteralPath $candidate) {
        $ollamaPath = $candidate
    }
}
if (-not $ollamaPath) {
    throw "Ollama is not installed."
}

try {
    Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:11434/api/tags" -TimeoutSec 2 | Out-Null
} catch {
    Start-Process -FilePath $ollamaPath -ArgumentList "serve" -WindowStyle Hidden | Out-Null
    $ready = $false
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        Start-Sleep -Milliseconds 500
        try {
            Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:11434/api/tags" -TimeoutSec 2 | Out-Null
            $ready = $true
            break
        } catch {}
    }
    if (-not $ready) {
        throw "Ollama did not become ready on 127.0.0.1:11434."
    }
}

Set-Location $root
& $python -m streamlit run app.py --server.address 127.0.0.1 --server.port $Port
