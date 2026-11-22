param([string]$BrowserPath = 'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe', [string]$Pattern = '*.mmd')
$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path -LiteralPath $BrowserPath)) { throw 'Indique -BrowserPath con Chrome o Edge instalado.' }
$ConfigFile = Join-Path $ProjectRoot 'runtime\puppeteer.json'
New-Item -ItemType Directory -Path (Split-Path -Parent $ConfigFile) -Force | Out-Null
$ConfigText = @{executablePath=$BrowserPath;args=@('--no-first-run')} | ConvertTo-Json
[IO.File]::WriteAllText($ConfigFile, $ConfigText, (New-Object Text.UTF8Encoding($false)))
$env:PUPPETEER_SKIP_DOWNLOAD = 'true'
Get-ChildItem -LiteralPath (Join-Path $ProjectRoot 'docs\diagramas') -Filter $Pattern | ForEach-Object {
    foreach ($Format in @('svg','png','pdf')) {
        $TargetPath = [IO.Path]::ChangeExtension($_.FullName,$Format)
        & npm.cmd exec --yes --package=@mermaid-js/mermaid-cli@12.2.0 -- mmdc -i $_.FullName -o $TargetPath -p $ConfigFile -b white --size 1800 -s 2
        if ($LASTEXITCODE -ne 0) { throw "No se pudo exportar $($_.Name) a $Format" }
    }
}
