param([string]$OutputDirectory = 'dist/m21a-native')
$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$output = [IO.Path]::GetFullPath((Join-Path $repoRoot $OutputDirectory))
if (-not $output.StartsWith(($repoRoot + '\dist\'), [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Build output must be a fresh folder within repository dist.'
}
if (Test-Path -LiteralPath $output) { throw 'Fresh output folder required.' }
$vc = 'C:\Program Files (x86)\Microsoft Visual Studio\18\BuildTools\VC\Tools\MSVC\14.50.35717'
$sdk = 'C:\Program Files (x86)\Windows Kits\10'
$sdkVersion = '10.0.26100.0'
$env:PATH = "$vc\bin\Hostx64\x64;" + $env:PATH
$env:INCLUDE = "$vc\include;$sdk\Include\$sdkVersion\ucrt;$sdk\Include\$sdkVersion\shared;$sdk\Include\$sdkVersion\um"
$env:LIB = "$vc\lib\x64;$sdk\Lib\$sdkVersion\ucrt\x64;$sdk\Lib\$sdkVersion\um\x64"
New-Item -ItemType Directory -Path $output | Out-Null
& "$vc\bin\Hostx64\x64\cl.exe" /nologo /std:c++17 /W4 /O1 /MT /GS /guard:cf /sdl /EHsc `
    (Join-Path $PSScriptRoot 'readiness-test.cpp') "/Fe:$output\readiness-test.exe" "/Fo:$output\readiness-test.obj" `
    /link /DYNAMICBASE /HIGHENTROPYVA /NXCOMPAT /guard:cf /INCREMENTAL:NO
if ($LASTEXITCODE -ne 0) { throw 'Readiness test build failed.' }
& "$output\readiness-test.exe"
if ($LASTEXITCODE -ne 0) { throw 'Exact readiness framing tests failed.' }
foreach ($name in @('producer','verifier','harness','probe')) {
    $ext = if ($name -eq 'probe') { 'c' } else { 'cpp' }
    [string[]]$language = if ($ext -eq 'cpp') { '/std:c++17' } else { @() }
    & "$vc\bin\Hostx64\x64\cl.exe" /nologo @language /W4 /O1 /MT /GS /guard:cf /sdl /EHsc `
        (Join-Path $PSScriptRoot "$name.$ext") "/Fe:$output\$name.exe" "/Fo:$output\$name.obj" `
        /link /DYNAMICBASE /HIGHENTROPYVA /NXCOMPAT /guard:cf /INCREMENTAL:NO
    if ($LASTEXITCODE -ne 0) { throw "Native $name build failed." }
    $imports = & "$vc\bin\Hostx64\x64\dumpbin.exe" /imports "$output\$name.exe"
    if ($LASTEXITCODE -ne 0) { throw 'Import inspection failed.' }
    $imports | Set-Content -LiteralPath "$output\$name.imports.txt" -Encoding utf8NoBOM
    $headers = & "$vc\bin\Hostx64\x64\dumpbin.exe" /headers /loadconfig "$output\$name.exe"
    if ($LASTEXITCODE -ne 0) { throw 'Hardening inspection failed.' }
    $headers | Set-Content -LiteralPath "$output\$name.headers.txt" -Encoding utf8NoBOM
    if ($name -in @('producer','verifier')) {
        $dlls = @($imports | Where-Object { $_ -match '^\s+[A-Za-z0-9_.-]+\.dll\s*$' } | ForEach-Object { $_.Trim().ToLowerInvariant() })
        if ($dlls.Count -ne 1 -or $dlls[0] -ne 'kernel32.dll') { throw 'Unexpected worker dependency.' }
        foreach ($flag in @('Dynamic base','NX compatible','Control Flow Guard','High Entropy Virtual Addresses')) {
            if (-not ($headers -match [regex]::Escape($flag))) { throw "Missing $flag" }
        }
    }
}
New-Item -ItemType Directory -Path "$output\source" | Out-Null
Get-ChildItem -LiteralPath $PSScriptRoot -File | ForEach-Object {
    Copy-Item -LiteralPath $_.FullName -Destination "$output\source"
}
$files = [ordered]@{}
Get-ChildItem -LiteralPath $output -File -Recurse | Sort-Object FullName | ForEach-Object {
    $relative = [IO.Path]::GetRelativePath($output, $_.FullName).Replace('\','/')
    $files[$relative] = @{sha256=(Get-FileHash -LiteralPath $_.FullName).Hash.ToLowerInvariant(); bytes=$_.Length}
}
$windows = Get-ItemProperty -LiteralPath 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion'
$manifest = [ordered]@{
    schema='daf-native-build-manifest/v1'
    git_parent=(& git -C $repoRoot rev-parse HEAD)
    note='Exact source hashes, not git_parent, identify working-tree build inputs. Unsigned maintainer build.'
    compiler=@{toolset='14.50.35717'; sdk=$sdkVersion; sha256=(Get-FileHash "$vc\bin\Hostx64\x64\cl.exe").Hash.ToLowerInvariant()}
    flags='/std:c++17 (C++ only) /W4 /O1 /MT /GS /guard:cf /sdl /EHsc /DYNAMICBASE /HIGHENTROPYVA /NXCOMPAT /INCREMENTAL:NO'
    environment=@{build="$($windows.CurrentBuildNumber).$($windows.UBR)"; edition=$windows.EditionID; display_version=$windows.DisplayVersion; architecture='x64'; clean_machine=$false}
    files=$files
}
$manifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath "$output\build-manifest.json" -Encoding utf8NoBOM
Write-Output $output
