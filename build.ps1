# Compila el .exe.  Uso:
#     .\build.ps1              compila
#     .\build.ps1 -Relock      regenera requirements-build.lock (hace falta red)
#
# El lock fija TODO el árbol de dependencias con hashes, no solo PyInstaller: sus
# dependencias transitivas (entre ellas pyinstaller-hooks-contrib, que ejecuta Python
# arbitrario durante el build, y el bootloader precompilado que acaba dentro del .exe) son
# código que no hemos escrito y que entra en el artefacto.

# -Python permite compilar con otro intérprete (lo usa la integración continua, donde no
# existe C:\python39).
param([switch]$Relock, [string]$Python = "C:\python39\python.exe")

$ErrorActionPreference = "Stop"
$raiz = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $raiz

$python = $Python
if (-not (Test-Path $python)) {
    $encontrado = (Get-Command python -ErrorAction SilentlyContinue).Source
    if (-not $encontrado) { throw "No se encuentra Python. Pásalo con -Python <ruta>." }
    Write-Host "No existe $python; se usa $encontrado" -ForegroundColor Yellow
    $python = $encontrado
}
$venv = Join-Path $raiz ".venv"
$py = Join-Path $venv "Scripts\python.exe"
$lock = Join-Path $raiz "requirements-build.lock"

if (-not (Test-Path $py)) {
    Write-Host "Creando entorno de compilación..." -ForegroundColor Cyan
    & $python -m venv $venv
    & $py -m pip install --upgrade pip --quiet
}

if ($Relock -or -not (Test-Path $lock)) {
    Write-Host "Resolviendo dependencias y calculando hashes..." -ForegroundColor Cyan
    $ruedas = Join-Path $raiz ".wheels"
    if (Test-Path $ruedas) { Remove-Item -Recurse -Force $ruedas }
    & $py -m pip download --dest $ruedas --only-binary ":all:" -r requirements-build.txt
    if ($LASTEXITCODE -ne 0) { throw "pip download falló" }
    $lineas = @(
        "# Generado por build.ps1 -Relock. No editar a mano.",
        "# Fija el árbol completo de dependencias de compilación con sus hashes."
    )
    foreach ($f in Get-ChildItem $ruedas -Filter *.whl | Sort-Object Name) {
        $partes = $f.BaseName -split "-"
        $nombre = $partes[0] -replace "_", "-"
        $version = $partes[1]
        $hash = (& $py -m pip hash $f.FullName | Select-String "sha256:").ToString().Trim()
        $lineas += "$nombre==$version \"
        $lineas += "    $hash"
    }
    Set-Content -Path $lock -Value $lineas -Encoding utf8
    Remove-Item -Recurse -Force $ruedas
    Write-Host "Escrito $lock" -ForegroundColor Green
}

Write-Host "Instalando dependencias fijadas..." -ForegroundColor Cyan
& $py -m pip install --require-hashes -r $lock --quiet
if ($LASTEXITCODE -ne 0) { throw "La instalación no coincide con el lock. Revisa antes de seguir." }

Write-Host "Comprobando las pruebas antes de compilar..." -ForegroundColor Cyan
# Sin `2>&1`: unittest escribe por stderr y, redirigido, PowerShell 5.1 lo convierte en un
# NativeCommandError que aborta el script aunque las pruebas hayan pasado.
& $python -m unittest discover -s pruebas -t .
if ($LASTEXITCODE -ne 0) { throw "Las pruebas fallan: no se compila." }

Write-Host "Compilando..." -ForegroundColor Cyan
& $py -m PyInstaller --clean --noconfirm autoclicker.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller falló" }

$salida = Join-Path $raiz "dist\Autoclicker"
$exe = Join-Path $salida "Autoclicker.exe"
if (-not (Test-Path $exe)) { throw "No se generó $exe" }

# PyInstaller deja en build\ una copia del .exe SIN sus DLL al lado. Parece ejecutable, y al
# abrirla siempre falla con "Failed to load Python DLL ... python39.dll". Como compilamos
# siempre con --clean, esa carpeta no sirve de caché para nada: se borra y se acabó la trampa.
$intermedios = Join-Path $raiz "build"
if (Test-Path $intermedios) { Remove-Item -Recurse -Force $intermedios }

$zip = Join-Path $raiz "dist\Autoclicker.zip"
if (Test-Path $zip) { Remove-Item $zip }
Compress-Archive -Path $salida -DestinationPath $zip

$tam = [math]::Round(((Get-ChildItem $salida -Recurse | Measure-Object Length -Sum).Sum / 1MB), 1)
Write-Host ""
Write-Host "Listo. Ejecuta ESTE fichero:" -ForegroundColor Green
Write-Host "    $exe" -ForegroundColor Green
Write-Host "Carpeta: $tam MB   Zip: $([math]::Round((Get-Item $zip).Length / 1MB, 1)) MB"
Write-Host ""
Write-Host "SHA-256 (van en las notas de la release):" -ForegroundColor Cyan
Write-Host ("  Autoclicker.exe  " + (Get-FileHash $exe -Algorithm SHA256).Hash)
Write-Host ("  Autoclicker.zip  " + (Get-FileHash $zip -Algorithm SHA256).Hash)
