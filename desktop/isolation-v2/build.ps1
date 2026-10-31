param([string]$OutputDirectory = 'dist/m21-isolation-v2')
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
if ((Get-FileHash -LiteralPath (Join-Path $runtime 'python.exe')).Hash.ToLowerInvariant() -ne 'd718435b892db4ad5b547d12fec61be7baa7faf7a58d857ea58053be24c7a000') {
    throw 'The approved bundled CPython runtime identity does not match.'
}
Copy-Item -LiteralPath $runtime -Destination (Join-Path $output 'runtime') -Recurse
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'probe.py') -Destination $output
New-Item -ItemType Directory -Path (Join-Path $output 'source') | Out-Null
Get-ChildItem -LiteralPath $PSScriptRoot -File | ForEach-Object {
    Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $output 'source')
}
[IO.File]::WriteAllText((Join-Path $output 'allowed.txt'), 'Explicitly readable synthetic fixture')
[IO.File]::WriteAllText((Join-Path $output 'private.txt'), 'Host-private synthetic fixture')
[IO.File]::WriteAllText((Join-Path $output 'ambient-shared.txt'), 'Synthetic resource shared with all LPACs')
[IO.File]::WriteAllText((Join-Path $output 'dual-grant.txt'), 'Explicitly permitted dual-SID write fixture')
[IO.File]::WriteAllBytes((Join-Path $output 'protected.bin'), [byte[]]@())
[IO.File]::WriteAllText((Join-Path $output 'fixture-root.marker'), 'DAF M2.1 generated standalone restricting-SID fixture')
$identities = [ordered]@{}
Get-ChildItem -LiteralPath $output -File -Recurse | Sort-Object FullName | ForEach-Object {
    $relative = [IO.Path]::GetRelativePath($output, $_.FullName).Replace('\', '/')
    $identities[$relative] = @{sha256=(Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant(); bytes=$_.Length}
}
$windowsVersion = Get-ItemProperty -LiteralPath 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion'
$manifest = [ordered]@{
    schema = 'daf-isolation-feasibility-build/v2'
    source_base = (& git -C $repoRoot rev-parse HEAD)
    original_failed_source = '42a1ca7118d4f56361328e1b8acb4fb843683a70'
    note = 'Source file hashes identify this working-tree build; source_base alone does not.'
    built_utc = [DateTime]::UtcNow.ToString('o')
    environment = @{
        windows_build = "$($windowsVersion.CurrentBuildNumber).$($windowsVersion.UBR)"
        display_version = $windowsVersion.DisplayVersion
        edition = $windowsVersion.EditionID
        architecture = [Runtime.InteropServices.RuntimeInformation]::OSArchitecture.ToString()
        msvc = '14.50.35717'; windows_sdk = $sdkVersion
        compiler_sha256 = (Get-FileHash -LiteralPath "$vc\bin\Hostx64\x64\cl.exe").Hash.ToLowerInvariant()
        bundled_python = '3.14.10'; clean_machine = $false
    }
    files = $identities
}
$manifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $output 'build-manifest.json') -Encoding utf8NoBOM
Write-Output $output
