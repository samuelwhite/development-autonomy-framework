param([string]$OutputDirectory = 'dist/m21-isolation')
$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$output = [IO.Path]::GetFullPath((Join-Path $repoRoot $OutputDirectory))
if (-not $output.StartsWith(($repoRoot + '\dist\'), [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Feasibility output must be a new folder under this repository dist directory.'
}
if (Test-Path -LiteralPath $output) { throw 'Use a fresh output directory.' }
$vc = 'C:\Program Files (x86)\Microsoft Visual Studio\18\BuildTools\VC\Tools\MSVC\14.50.35717'
$sdk = 'C:\Program Files (x86)\Windows Kits\10'
$sdkVersion = '10.0.26100.0'
$env:PATH = "$vc\bin\Hostx64\x64;" + $env:PATH
$env:INCLUDE = "$vc\include;$sdk\Include\$sdkVersion\ucrt;$sdk\Include\$sdkVersion\shared;$sdk\Include\$sdkVersion\um"
$env:LIB = "$vc\lib\x64;$sdk\Lib\$sdkVersion\ucrt\x64;$sdk\Lib\$sdkVersion\um\x64"
New-Item -ItemType Directory -Path $output | Out-Null
& "$vc\bin\Hostx64\x64\cl.exe" /nologo /std:c++17 /W4 /EHsc /MT /guard:cf /sdl `
    (Join-Path $PSScriptRoot 'feasibility.cpp') "/Fe:$output\feasibility.exe" "/Fo:$output\feasibility.obj" /link /DYNAMICBASE /NXCOMPAT
if ($LASTEXITCODE -ne 0) { throw 'Native feasibility build failed.' }
$runtime = Join-Path $repoRoot 'dist/m1.2-desktop/DAF-win32-x64/resources/planning/runtime'
Copy-Item -LiteralPath $runtime -Destination (Join-Path $output 'runtime') -Recurse
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'probe.py') -Destination $output
[IO.File]::WriteAllText((Join-Path $output 'allowed.txt'), 'Explicitly readable synthetic fixture')
[IO.File]::WriteAllText((Join-Path $output 'private.txt'), 'Host-private synthetic fixture')
[IO.File]::WriteAllText((Join-Path $output 'ambient-shared.txt'), 'Synthetic resource shared with all LPACs')
[IO.File]::WriteAllBytes((Join-Path $output 'protected.bin'), [byte[]]@())
Write-Output $output
