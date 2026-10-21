param(
    [switch]$RunBonanza,
    [switch]$RunAgent
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$bonanzaRoot = Join-Path $projectRoot "BONANZATODO-ULTIMAUPDATE"

if ($RunBonanza) {
    Set-Location -LiteralPath $bonanzaRoot
    Write-Host "Iniciando Bonanza con node Index.js..."
    node Index.js
    exit $LASTEXITCODE
}

if ($RunAgent) {
    Set-Location -LiteralPath $projectRoot
    $venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"

    if (Test-Path -LiteralPath $venvPython) {
        Write-Host "Iniciando el agente con el Python del entorno virtual..."
        & $venvPython -m uvicorn app.main:app --reload --port 8765
    }
    elseif (Get-Command py -ErrorAction SilentlyContinue) {
        Write-Host "Iniciando el agente con py -3..."
        py -3 -m uvicorn app.main:app --reload --port 8765
    }
    elseif (Get-Command python -ErrorAction SilentlyContinue) {
        Write-Host "Iniciando el agente con python..."
        python -m uvicorn app.main:app --reload --port 8765
    }
    else {
        throw "No se encontró Python. Instala Python 3 o crea el entorno .venv."
    }
    exit $LASTEXITCODE
}

if (-not (Test-Path -LiteralPath (Join-Path $bonanzaRoot "Index.js"))) {
    throw "No se encontró BONANZATODO-ULTIMAUPDATE\Index.js."
}
if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    throw "No se encontró Node.js en PATH."
}
if (-not (Test-Path -LiteralPath (Join-Path $bonanzaRoot "node_modules"))) {
    throw "Faltan las dependencias de Bonanza. Ejecuta npm install dentro de BONANZATODO-ULTIMAUPDATE."
}
if (-not (Test-Path -LiteralPath (Join-Path $projectRoot "app\main.py"))) {
    throw "No se encontró app\main.py."
}
if (-not (Test-Path -LiteralPath (Join-Path $projectRoot ".env"))) {
    Write-Warning "No existe .env en la raíz. Configura OPENAI_API_KEY y las credenciales BONANZA_API_* antes de crear boletos."
}
if (-not (Test-Path -LiteralPath (Join-Path $bonanzaRoot ".env"))) {
    Write-Warning "No existe BONANZATODO-ULTIMAUPDATE\.env. Configura JWT_SECRET antes de iniciar Bonanza."
}

$powershellExe = (Get-Process -Id $PID).Path
$scriptPath = $MyInvocation.MyCommand.Path
$bonanzaArgs = @(
    "-NoExit",
    "-ExecutionPolicy", "Bypass",
    "-File", "`"$scriptPath`"",
    "-RunBonanza"
)
$agentArgs = @(
    "-NoExit",
    "-ExecutionPolicy", "Bypass",
    "-File", "`"$scriptPath`"",
    "-RunAgent"
)

Start-Process -FilePath $powershellExe -ArgumentList $bonanzaArgs
Start-Sleep -Seconds 2
Start-Process -FilePath $powershellExe -ArgumentList $agentArgs

Write-Host ""
Write-Host "Bonanza y el agente se iniciaron en ventanas separadas."
Write-Host "Página Bonanza: http://127.0.0.1:3000/login"
Write-Host "Chat del agente: http://127.0.0.1:8765/"
Write-Host "Cierra cada ventana para detener su servidor."
