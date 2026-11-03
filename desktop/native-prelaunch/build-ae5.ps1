param([Parameter(Mandatory=$true)][string]$OutputDirectory)
# COMPILE/INSPECT ONLY. Never invoke a diagnostic output, including smoke tests.
$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$output = [IO.Path]::GetFullPath((Join-Path $repoRoot $OutputDirectory))
if (-not $output.StartsWith(($repoRoot + '\dist\'), [StringComparison]::OrdinalIgnoreCase)) { throw 'Output must be inside dist.' }
if (Test-Path -LiteralPath $output) { throw 'Fresh build directory required.' }
if ($env:CL -or $env:_CL_ -or $env:LINK -or $env:_LINK_) { throw 'Unreviewed inherited compiler options.' }
$vc = 'C:\Program Files (x86)\Microsoft Visual Studio\18\BuildTools\VC\Tools\MSVC\14.50.35717'
$sdk = 'C:\Program Files (x86)\Windows Kits\10'
$sdkVersion = '10.0.26100.0'
$compiler = "$vc\bin\Hostx64\x64\cl.exe"
$env:PATH = "$vc\bin\Hostx64\x64;" + $env:PATH
$env:INCLUDE = "$output;$output\source\native-prelaunch;$output\source\native-foundation;$vc\include;$sdk\Include\$sdkVersion\ucrt;$sdk\Include\$sdkVersion\shared;$sdk\Include\$sdkVersion\um"
$env:LIB = "$vc\lib\x64;$sdk\Lib\$sdkVersion\ucrt\x64;$sdk\Lib\$sdkVersion\um\x64"
$flags = @('/nologo','/std:c++17','/W4','/O1','/MT','/GS','/guard:cf','/sdl','/EHsc')
New-Item -ItemType Directory -Path "$output\source" | Out-Null
$status = 'FAILED'; $failure = $null
try {
    foreach ($directory in @('native-prelaunch','native-foundation')) {
        $destination = New-Item -ItemType Directory -Path "$output\source\$directory"
        Get-ChildItem -LiteralPath "$repoRoot\desktop\$directory" -File | ForEach-Object {
            Copy-Item -LiteralPath $_.FullName -Destination $destination.FullName
        }
    }
    $frozen = "$output\source\native-prelaunch"
    & python -B "$frozen\instrument_ae5.py" $output
    if ($LASTEXITCODE -ne 0) { throw 'Generation/full inverse failed.' }
    foreach ($unit in @('handle-probe','ae5-fixture-host')) {
        $inputSource = if ($unit -eq 'handle-probe') { "$frozen\handle-probe.cpp" } else { "$output\ae5-fixture-host.cpp" }
        & $compiler @flags /P "/Fi$output\$unit.i" /sourceDependencies "$output\$unit.preprocess.json" $inputSource 2>&1 | Tee-Object -FilePath "$output\$unit.preprocess.log"
        if ($LASTEXITCODE -ne 0) { throw "$unit preprocessing failed." }
        if ($unit -eq 'ae5-fixture-host') {
            foreach ($baseline in @('ae5-baseline','ae5-host-baseline','ae5-transform-tokens')) {
                & $compiler @flags /P "/Fi$output\$baseline.i" "$output\$baseline.cpp" 2>&1 | Tee-Object -FilePath "$output\$baseline.log"
                if ($LASTEXITCODE -ne 0) { throw "$baseline preprocessing failed." }
            }
            & python -B "$frozen\ae5_build_review.py" $output
        } else { & python -B "$frozen\ae5_build_review.py" $output --probe }
        if ($LASTEXITCODE -ne 0) { throw 'Pre-compilation review refused.' }
        & $compiler @flags /sourceDependencies "$output\$unit.compiled.json" $inputSource "/Fe:$output\$unit.exe" "/Fo:$output\$unit.obj" /link /DYNAMICBASE /HIGHENTROPYVA /NXCOMPAT /guard:cf /INCREMENTAL:NO 2>&1 | Tee-Object -FilePath "$output\$unit.compile.log"
        if ($LASTEXITCODE -ne 0) { throw "$unit compile failed." }
        & "$vc\bin\Hostx64\x64\dumpbin.exe" /imports /headers /loadconfig "$output\$unit.exe" | Set-Content -LiteralPath "$output\$unit.inspection.txt" -Encoding utf8NoBOM
        if ($LASTEXITCODE -ne 0) { throw 'Binary inspection failed.' }
        if ($unit -eq 'handle-probe') {
            $hash = (Get-FileHash -LiteralPath "$output\$unit.exe").Hash.ToLowerInvariant()
            $size = (Get-Item -LiteralPath "$output\$unit.exe").Length
            "#define PROBE_SHA256 `"$hash`"`n#define PROBE_BYTES $size" | Set-Content -LiteralPath "$output\probe-identity.h" -Encoding utf8NoBOM
        }
    }
    & python -B "$frozen\ae5_build_review.py" $output --compiled
    if ($LASTEXITCODE -ne 0) { throw 'Final compiler-input/import review refused.' }
    $status = 'COMPILED_NOT_EXECUTED'
} catch { $failure = $_.Exception.Message; throw }
finally {
    $gateReview = $null
    if (Test-Path -LiteralPath "$output\ae5-build-review.json") {
        $gateReview = Get-Content -LiteralPath "$output\ae5-build-review.json" -Raw | ConvertFrom-Json
    }
    $files = [ordered]@{}
    Get-ChildItem -LiteralPath $output -File -Recurse | Sort-Object FullName | ForEach-Object {
        $relative = [IO.Path]::GetRelativePath($output, $_.FullName).Replace('\','/')
        $files[$relative] = @{sha256=(Get-FileHash -LiteralPath $_.FullName).Hash.ToLowerInvariant(); bytes=$_.Length}
    }
    [ordered]@{
        schema='daf-ae5-compile-only/v1'; source_commit=(& git -C $repoRoot rev-parse HEAD)
        source_tree=(& git -C $repoRoot rev-parse 'HEAD^{tree}'); status=$status; failure=$failure
        native_executions=0; native_claims=0; native_gate=$(if ($gateReview) { $gateReview.native_gate } else { 'UNREVIEWED' })
        source_gates=$(if ($gateReview) { $gateReview.source_gates } else { $null }); qualified=$false; execution_authority=$false
        compiler=@{toolset='14.50.35717'; sdk=$sdkVersion; sha256=(Get-FileHash -LiteralPath $compiler).Hash.ToLowerInvariant()}
        flags=($flags -join ' '); link_flags='/DYNAMICBASE /HIGHENTROPYVA /NXCOMPAT /guard:cf /INCREMENTAL:NO'; files=$files
    } | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath "$output\build-manifest.json" -Encoding utf8NoBOM
}
Write-Output $output
