# Setup reproducible (Windows): verifica Python 3.12, crea .venv, instala dependencias pineadas
# y corre chequeos de sanity.
# Uso:  powershell -ExecutionPolicy Bypass -File .\setup.ps1
#       (opcional) $env:PYTHON = "C:\ruta\python.exe"; .\setup.ps1
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

$Requerida = "3.12"

function Get-PyVersion([string]$Exe, [string[]]$ExtraArgs) {
    try {
        $v = & $Exe @ExtraArgs -c "import sys; print(f'{sys.version_info[0]}.{sys.version_info[1]}')" 2>$null
        if ($LASTEXITCODE -eq 0) { return "$v".Trim() }
    } catch { }
    return ""
}

function Invoke-Checked([string]$Exe, [string[]]$Arguments) {
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Falló: $Exe $($Arguments -join ' ') (código $LASTEXITCODE)" }
}

Write-Host "==> Verificando Python $Requerida"
$candidatos = @()
if ($env:PYTHON) { $candidatos += ,@($env:PYTHON) }
$candidatos += ,@("py", "-$Requerida")
$candidatos += ,@("python3.12")
$candidatos += ,@("python")
$candidatos += ,@("python3")

$PyExe = $null; $PyArgs = @()
foreach ($c in $candidatos) {
    $exe = $c[0]
    $extra = @($c | Select-Object -Skip 1)
    if (-not (Get-Command $exe -ErrorAction SilentlyContinue)) { continue }
    if ((Get-PyVersion $exe $extra) -eq $Requerida) { $PyExe = $exe; $PyArgs = $extra; break }
}

if (-not $PyExe) {
    Write-Error @"
No se encontró Python $Requerida.
Instalalo y volvé a correr este script:
  winget install -e --id Python.Python.3.12
  (o descargalo de https://www.python.org/downloads/windows/ y marcá 'Add python.exe to PATH')
O indicá el intérprete:  `$env:PYTHON = 'C:\ruta\python.exe'; .\setup.ps1
"@
    exit 1
}
$ver = & $PyExe @PyArgs --version
Write-Host "    Usando $ver ($PyExe $($PyArgs -join ' '))"

$VenvPy = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if ((Test-Path $VenvPy) -and ((Get-PyVersion $VenvPy @()) -ne $Requerida)) {
    Write-Host "==> .venv existente usa otra versión de Python: se recrea"
    Remove-Item -Recurse -Force (Join-Path $PSScriptRoot ".venv")
}
if (-not (Test-Path $VenvPy)) {
    Write-Host "==> Creando entorno virtual .venv"
    Invoke-Checked $PyExe ($PyArgs + @("-m", "venv", ".venv"))
}

# Activación para esta sesión (si la ExecutionPolicy lo impide, se usa el python del venv directamente)
try { . (Join-Path $PSScriptRoot ".venv\Scripts\Activate.ps1") } catch { Write-Host "    (no se pudo activar el venv en esta sesión; se usa $VenvPy)" }

Write-Host "==> Instalando dependencias (pyproject.toml, versiones exactas)"
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
