param([Parameter(Mandatory=$true)][string]$OutputDirectory)
$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$output = [IO.Path]::GetFullPath((Join-Path $repoRoot $OutputDirectory))
if (-not $output.StartsWith(($repoRoot + '\dist\'), [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Fresh build output must be within repository dist.'
}
if (Test-Path -LiteralPath $output) { throw 'Output already exists; no overwrite or retry.' }
$vc = 'C:\Program Files (x86)\Microsoft Visual Studio\18\BuildTools\VC\Tools\MSVC\14.50.35717'
$sdk = 'C:\Program Files (x86)\Windows Kits\10'
$sdkVersion = '10.0.26100.0'
$env:PATH = "$vc\bin\Hostx64\x64;" + $env:PATH
$env:INCLUDE = "$output;$repoRoot\desktop\native-foundation;$vc\include;$sdk\Include\$sdkVersion\ucrt;$sdk\Include\$sdkVersion\shared;$sdk\Include\$sdkVersion\um"
$env:LIB = "$vc\lib\x64;$sdk\Lib\$sdkVersion\ucrt\x64;$sdk\Lib\$sdkVersion\um\x64"
New-Item -ItemType Directory -Path $output | Out-Null
& python -B (Join-Path $PSScriptRoot 'instrument_fixture.py') (Join-Path $repoRoot 'desktop/native-foundation/harness.cpp') (Join-Path $output 'a4-fixture-harness.h')
if ($LASTEXITCODE -ne 0) { throw 'Accepted harness identity/instrumentation failed.' }
foreach ($name in @('handle-probe', 'fixture-host')) {
    & "$vc\bin\Hostx64\x64\cl.exe" /nologo /std:c++17 /W4 /O1 /MT /GS /guard:cf /sdl /EHsc `
        (Join-Path $PSScriptRoot "$name.cpp") "/Fe:$output\$name.exe" "/Fo:$output\$name.obj" `
        /link /DYNAMICBASE /HIGHENTROPYVA /NXCOMPAT /guard:cf /INCREMENTAL:NO
    if ($LASTEXITCODE -ne 0) { throw "Native $name build failed." }
    if ($name -eq 'handle-probe') {
        $hash = (Get-FileHash -LiteralPath "$output\$name.exe").Hash.ToLowerInvariant()
        $size = (Get-Item -LiteralPath "$output\$name.exe").Length
        "#define PROBE_SHA256 `"$hash`"`n#define PROBE_BYTES $size" | Set-Content -LiteralPath "$output\probe-identity.h" -Encoding utf8NoBOM
    }
    & "$vc\bin\Hostx64\x64\dumpbin.exe" /imports /headers /loadconfig "$output\$name.exe" | Set-Content -LiteralPath "$output\$name.inspection.txt" -Encoding utf8NoBOM
    if ($LASTEXITCODE -ne 0) { throw 'Binary inspection failed.' }
    if ($name -eq 'fixture-host' -and (Select-String -LiteralPath "$output\$name.inspection.txt" -Pattern '\bResumeThread\b')) {
        throw 'Fixture must not import ResumeThread.'
    }
}
New-Item -ItemType Directory -Path "$output\source" | Out-Null
foreach ($directory in @('native-prelaunch', 'native-foundation')) {
    Copy-Item -LiteralPath (Join-Path $repoRoot "desktop/$directory") -Destination "$output\source\$directory" -Recurse
}
$files = [ordered]@{}
Get-ChildItem -LiteralPath $output -File -Recurse | Where-Object { $_.FullName -notmatch '__pycache__' } | Sort-Object FullName | ForEach-Object {
    $relative = [IO.Path]::GetRelativePath($output, $_.FullName).Replace('\','/')
    $files[$relative] = @{sha256=(Get-FileHash -LiteralPath $_.FullName).Hash.ToLowerInvariant(); bytes=$_.Length}
}
$windows = Get-ItemProperty -LiteralPath 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion'
[ordered]@{
    schema='daf-a4-fixture-build/v1'; git_parent=(& git -C $repoRoot rev-parse HEAD)
    note='Exact source hashes identify working-tree input. Separate A4 detector-control fixture only, never desktop execution.'
    compiler=@{toolset='14.50.35717'; sdk=$sdkVersion; sha256=(Get-FileHash "$vc\bin\Hostx64\x64\cl.exe").Hash.ToLowerInvariant()}
    flags='/std:c++17 /W4 /O1 /MT /GS /guard:cf /sdl /EHsc /DYNAMICBASE /HIGHENTROPYVA /NXCOMPAT /INCREMENTAL:NO'
    environment=@{build="$($windows.CurrentBuildNumber).$($windows.UBR)"; edition=$windows.EditionID; architecture='x64'; clean_machine=$false}
    files=$files
} | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath "$output\build-manifest.json" -Encoding utf8NoBOM
Write-Output $output
