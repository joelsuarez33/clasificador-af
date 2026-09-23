# Setup reproducible (Windows): verifica Python >= 3.12, crea .venv, instala dependencias
# y corre chequeos de sanity.
# Uso:  powershell -ExecutionPolicy Bypass -File .\setup.ps1
#       (opcional) $env:PYTHON = "C:\ruta\python.exe"; .\setup.ps1
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

$MinRequerida = "3.12"

function Get-PyVersion([string]$Exe, [string[]]$ExtraArgs) {
    try {
        $v = & $Exe @ExtraArgs -c "import sys; print(f'{sys.version_info[0]}.{sys.version_info[1]}')" 2>$null
        if ($LASTEXITCODE -eq 0) { return "$v".Trim() }
    } catch { }
    return ""
}

# True si el interprete es >= $MinRequerida (3.12, 3.13, 3.14, ...).
function Test-PyMinimo([string]$Exe, [string[]]$ExtraArgs) {
    $v = Get-PyVersion $Exe $ExtraArgs
    if (-not $v) { return $false }
    try { return ([version]$v -ge [version]$MinRequerida) } catch { return $false }
}

function Invoke-Checked([string]$Exe, [string[]]$Arguments) {
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Falló: $Exe $($Arguments -join ' ') (código $LASTEXITCODE)" }
}

Write-Host "==> Verificando Python >= $MinRequerida"
$candidatos = @()
if ($env:PYTHON) { $candidatos += ,@($env:PYTHON) }
$candidatos += ,@("py", "-3")
$candidatos += ,@("python")
$candidatos += ,@("python3")

$PyExe = $null; $PyArgs = @()
foreach ($c in $candidatos) {
    $exe = $c[0]
    $extra = @($c | Select-Object -Skip 1)
    if (-not (Get-Command $exe -ErrorAction SilentlyContinue)) { continue }
    if (Test-PyMinimo $exe $extra) { $PyExe = $exe; $PyArgs = $extra; break }
}

if (-not $PyExe) {
    Write-Error @"
No se encontró Python >= $MinRequerida.
Instalalo y volvé a correr este script:
  winget install -e --id Python.Python.3.12   # o una versión superior
  (o descargalo de https://www.python.org/downloads/windows/ y marcá 'Add python.exe to PATH')
O indicá el intérprete:  `$env:PYTHON = 'C:\ruta\python.exe'; .\setup.ps1
"@
    exit 1
}
$ver = & $PyExe @PyArgs --version
Write-Host "    Usando $ver ($PyExe $($PyArgs -join ' '))"

$VenvPy = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if ((Test-Path $VenvPy) -and (-not (Test-PyMinimo $VenvPy @()))) {
    Write-Host "==> .venv existente usa un Python anterior a $MinRequerida: se recrea"
    Remove-Item -Recurse -Force (Join-Path $PSScriptRoot ".venv")
}
if (-not (Test-Path $VenvPy)) {
    Write-Host "==> Creando entorno virtual .venv"
    Invoke-Checked $PyExe ($PyArgs + @("-m", "venv", ".venv"))
}

# Activación para esta sesión (si la ExecutionPolicy lo impide, se usa el python del venv directamente)
try { . (Join-Path $PSScriptRoot ".venv\Scripts\Activate.ps1") } catch { Write-Host "    (no se pudo activar el venv en esta sesión; se usa $VenvPy)" }

Write-Host "==> Instalando dependencias (pyproject.toml)"
Invoke-Checked $VenvPy @("-m", "pip", "install", "--upgrade", "pip")
Invoke-Checked $VenvPy @("-m", "pip", "install", "-e", ".[dev]")

Write-Host "==> Sanity check de imports"
Invoke-Checked $VenvPy @("-c", "import google.genai, google.cloud.bigquery, fastapi; print('    imports OK')")

Write-Host "==> Tests (sin llamadas a GCP)"
Invoke-Checked $VenvPy @("-m", "pytest")

Write-Host "==> Configuración"
if (Test-Path (Join-Path $PSScriptRoot ".env")) {
    & $VenvPy -m app.config
    if ($LASTEXITCODE -ne 0) { Write-Warning "Revisá .env y la ruta del JSON de Service Account (ver README)." }
} else {
    Write-Warning "No existe .env. Copiá .env.example a .env y completá los valores."
}

Write-Host @"

Listo. Para trabajar:
  .\.venv\Scripts\Activate.ps1
  python -m preprocess.load_catalogo
  python -m preprocess.build_index
  python -m app.main
"@
