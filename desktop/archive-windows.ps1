$ErrorActionPreference = 'Stop'
$root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$folder = Join-Path $root 'dist\desktop\DAF-win32-x64'
$archive = Join-Path $root 'dist\desktop\DAF-0.2.1-windows-x64.zip'
if (-not (Test-Path -LiteralPath (Join-Path $folder 'DAF.exe'))) { throw 'Run npm run build in desktop first.' }
Compress-Archive -LiteralPath $folder -DestinationPath $archive -Force
$bytes = (Get-Item -LiteralPath $archive).Length
$expanded = (Get-ChildItem -LiteralPath $folder -File -Recurse | Measure-Object -Property Length -Sum).Sum
$hash = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
"$hash  DAF-0.2.1-windows-x64.zip" | Set-Content -LiteralPath "$archive.sha256" -Encoding ascii
@{ archiveBytes = $bytes; expandedBytes = $expanded; sha256 = $hash } |
    ConvertTo-Json | Set-Content -LiteralPath "$archive.metrics.json" -Encoding utf8
Get-Content -LiteralPath "$archive.metrics.json"
