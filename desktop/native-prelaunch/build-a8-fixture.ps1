param([Parameter(Mandatory=$true)][string]$OutputDirectory)
# COMPILE/INSPECT ONLY. Never launch either output, including smoke tests.
$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$output = [IO.Path]::GetFullPath((Join-Path $repoRoot $OutputDirectory))
if (-not $output.StartsWith(($repoRoot + '\dist\'), [StringComparison]::OrdinalIgnoreCase)) { throw 'A8 output must be within dist.' }
if (Test-Path -LiteralPath $output) { throw 'Fresh output only; never overwrite a failed build.' }
if ($env:CL -or $env:_CL_ -or $env:LINK -or $env:_LINK_) { throw 'Unreviewed inherited compiler/link options.' }
$vc = 'C:\Program Files (x86)\Microsoft Visual Studio\18\BuildTools\VC\Tools\MSVC\14.50.35717'
$sdk = 'C:\Program Files (x86)\Windows Kits\10'
$sdkVersion = '10.0.26100.0'
$compiler = "$vc\bin\Hostx64\x64\cl.exe"
$env:PATH = "$vc\bin\Hostx64\x64;" + $env:PATH
$env:INCLUDE = "$output;$repoRoot\desktop\native-prelaunch;$repoRoot\desktop\native-foundation;$vc\include;$sdk\Include\$sdkVersion\ucrt;$sdk\Include\$sdkVersion\shared;$sdk\Include\$sdkVersion\um"
$env:LIB = "$vc\lib\x64;$sdk\Lib\$sdkVersion\ucrt\x64;$sdk\Lib\$sdkVersion\um\x64"
$flags = @('/nologo','/std:c++17','/W4','/O1','/MT','/GS','/guard:cf','/sdl','/EHsc')
New-Item -ItemType Directory -Path $output | Out-Null
$status = 'FAILED'; $failure = $null
try {
    New-Item -ItemType Directory -Path "$output\source" | Out-Null
    foreach ($directory in @('native-prelaunch', 'native-foundation')) {
        $destination = New-Item -ItemType Directory -Path "$output\source\$directory"
        Get-ChildItem -LiteralPath "$repoRoot\desktop\$directory" -File | ForEach-Object {
            Copy-Item -LiteralPath $_.FullName -Destination $destination.FullName
        }
    }
    & python -B (Join-Path $PSScriptRoot 'instrument_a8.py') $output
    if ($LASTEXITCODE -ne 0) { throw 'A8 exact generation/inverse failed.' }
    # Per-unit real preprocessing/dependencies precede that unit's compilation.
    foreach ($unit in @('handle-probe', 'a8-fixture-host')) {
        & $compiler @flags /P "/Fi$output\$unit.i" /sourceDependencies "$output\$unit.preprocess.json" "$PSScriptRoot\$unit.cpp" 2>&1 | Tee-Object -FilePath "$output\$unit.preprocess.log"
        if ($LASTEXITCODE -ne 0) { throw "A8 $unit preprocessing failed." }
        if ($unit -eq 'a8-fixture-host') {
            & $compiler @flags /P "/Fi$output\a8-preprocess-baseline.i" "$output\a8-preprocess-baseline.cpp" 2>&1 | Tee-Object -FilePath "$output\baseline.preprocess.log"
            if ($LASTEXITCODE -ne 0) { throw 'A8 baseline preprocessing failed.' }
            & python -B "$PSScriptRoot\a8_build_review.py" $output
        } else {
            & python -B "$PSScriptRoot\a8_build_review.py" $output --probe
        }
        if ($LASTEXITCODE -ne 0) { throw "A8 $unit pre-compilation input review failed." }
        & $compiler @flags /sourceDependencies "$output\$unit.compiled.json" "$PSScriptRoot\$unit.cpp" "/Fe:$output\$unit.exe" "/Fo:$output\$unit.obj" /link /DYNAMICBASE /HIGHENTROPYVA /NXCOMPAT /guard:cf /INCREMENTAL:NO 2>&1 | Tee-Object -FilePath "$output\$unit.compile.log"
        if ($LASTEXITCODE -ne 0) { throw "A8 $unit compilation failed." }
        & "$vc\bin\Hostx64\x64\dumpbin.exe" /imports /headers /loadconfig "$output\$unit.exe" | Set-Content -LiteralPath "$output\$unit.inspection.txt" -Encoding utf8NoBOM
        if ($LASTEXITCODE -ne 0) { throw 'A8 binary inspection failed.' }
        if ($unit -eq 'handle-probe') {
            $hash = (Get-FileHash -LiteralPath "$output\$unit.exe").Hash.ToLowerInvariant()
            $size = (Get-Item -LiteralPath "$output\$unit.exe").Length
            "#define PROBE_SHA256 `"$hash`"`n#define PROBE_BYTES $size" | Set-Content -LiteralPath "$output\probe-identity.h" -Encoding utf8NoBOM
        }
    }
    & python -B "$PSScriptRoot\a8_build_review.py" $output --compiled
    if ($LASTEXITCODE -ne 0) { throw 'A8 complete compiled input review failed.' }
    $status = 'COMPILED_NOT_EXECUTED'
} catch {
    $failure = $_.Exception.Message
    throw
} finally {
    $files = [ordered]@{}
    Get-ChildItem -LiteralPath $output -File -Recurse | Sort-Object FullName | ForEach-Object {
        $relative = [IO.Path]::GetRelativePath($output, $_.FullName).Replace('\','/')
        $files[$relative] = @{sha256=(Get-FileHash -LiteralPath $_.FullName).Hash.ToLowerInvariant(); bytes=$_.Length}
    }
    [ordered]@{
        schema='daf-a8-compile-only/v1'; git_parent=(& git -C $repoRoot rev-parse HEAD)
        status=$status; failure=$failure; native_executions=0; cases=@{'A8-C0'='NOT RUN'; 'A8-S1'='NOT RUN'}
        qualified=$false; execution_authority=$false
        compiler=@{toolset='14.50.35717'; sdk=$sdkVersion; sha256=(Get-FileHash -LiteralPath $compiler).Hash.ToLowerInvariant()}
        flags=($flags -join ' '); link_flags='/DYNAMICBASE /HIGHENTROPYVA /NXCOMPAT /guard:cf /INCREMENTAL:NO'; files=$files
    } | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath "$output\build-manifest.json" -Encoding utf8NoBOM
}
Write-Output $output
