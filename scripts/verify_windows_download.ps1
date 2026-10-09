# Test the exact installer already downloadable from the original successful run.
# No app rebuild, dependency installation, CUDA Toolkit or workstation GPU needed.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)] [string] $ArtifactDirectory,
    [Parameter(Mandatory = $true)] [string] $OutputDirectory,
    [Parameter(Mandatory = $true)] [ValidatePattern('^[1-9][0-9]{0,19}$')] [string] $SourceRunId,
    [ValidatePattern('^[0-9]+\.[0-9]+\.[0-9]+$')] [string] $ExpectedVersion = '0.3.0',
    [ValidatePattern('^[a-fA-F0-9]{40}$')] [string] $ExpectedSourceCommit = '893c7274b1932d6496aa2aa509601075a6f66eb0'
)
$ErrorActionPreference = 'Stop'
$expectedSource = $ExpectedSourceCommit.ToLowerInvariant()
$requiresStartupCompilerGate = [version] $ExpectedVersion -ge [version] '0.3.1'
$artifact = (Resolve-Path -LiteralPath $ArtifactDirectory).Path
$output = [IO.Path]::GetFullPath($OutputDirectory)
New-Item -ItemType Directory -Path $output -Force | Out-Null
$checks = [Collections.Generic.List[string]]::new()
$proof = [ordered]@{
    status = 'failed'
    source_run_id = $SourceRunId
    application_version = $expectedVersion
    source_commit = $expectedSource
    installer_sha256 = $null
    installer_bytes = $null
    required_checks = $checks
    scope = 'Existing artifact download, byte integrity and fresh installed Windows engine/CUDA/native desktop checks; no rebuild.'
    gpu_device_execution = 'Not tested; CUDA native imports and offline kernel compilation only.'
    graphics_backend = 'Hosted VM software WebGL; no physical workstation graphics benchmark.'
}

function Require([bool] $Condition, [string] $Message) {
    if (!$Condition) { throw $Message }
}
function Read-Receipt([string] $RelativePath) {
    $receipt = Get-Content -LiteralPath (Join-Path $artifact $RelativePath) -Raw | ConvertFrom-Json
    Require ($receipt.status -eq 'ok') "Archived receipt did not pass: $RelativePath"
    return $receipt
}
function Require-CudaReceipt($Receipt) {
    Require ($Receipt.application_version -eq $expectedVersion) 'CUDA receipt has an unexpected application version.'
    Require ($Receipt.libraries.Count -ge 10) 'CUDA receipt does not contain the required bundled native libraries.'
    Require ($Receipt.compiler.ptx_bytes -gt 0) 'CUDA receipt has no actual offline-compiled PTX.'
    Require (![string]::IsNullOrWhiteSpace($Receipt.headers.cudart)) 'CUDA runtime headers are missing from the receipt.'
    Require (![string]::IsNullOrWhiteSpace($Receipt.headers.nvrtc)) 'NVRTC headers are missing from the receipt.'
    foreach ($header in @('cuda_runtime.h', 'cupy/carray.cuh', 'cuda/std/limits')) {
        Require ($Receipt.compiler.compiled_headers -contains $header) "CUDA offline compiler did not report the required header: $header"
    }
    # Preserve verification of historical 0.3.0 receipts. New releases must
    # prove normal-startup CuPy compilation without smoke-test DLL preloads.
    if ($requiresStartupCompilerGate) {
        Require ($Receipt.compiler.startup_path_verified -is [bool] -and $Receipt.compiler.startup_path_verified -eq $true) 'CUDA compiler did not verify normal application startup.'
        Require ($Receipt.compiler.test_only_preloads_before_compilation -is [bool] -and $Receipt.compiler.test_only_preloads_before_compilation -eq $false) 'CUDA compiler used test-only library preloads or omitted the preload evidence.'
        foreach ($target in @('compute_75', 'compute_89')) {
            Require ($Receipt.compiler.targets -contains $target) "CUDA offline compiler did not verify the required target: $target"
        }
    }
}
function Notice([string] $Message, [string] $Level = 'notice') {
    $bounded = $Message.Substring(0, [Math]::Min(1200, $Message.Length))
    $escaped = $bounded.Replace('%', '%25').Replace("`r", '%0D').Replace("`n", '%0A')
    Write-Host "::${Level} title=Existing installer download verification::$escaped"
}

try {
    $installerFilename = "RocketWorkbench-$ExpectedVersion-windows-x64-setup.exe"
    $installer = Join-Path $artifact (Join-Path 'release' $installerFilename)
    $installerInfo = Get-Item -LiteralPath $installer
    $checksum = (Get-Content -LiteralPath ($installer + '.sha256') -Raw).Trim()
    $checksumPattern = '^([a-fA-F0-9]{64})\s+' + [regex]::Escape($installerFilename) + '$'
    Require ($checksum -match $checksumPattern) 'The shipped checksum file has an unexpected format or filename.'
    $expectedHash = $Matches[1].ToLowerInvariant()
    $actualHash = (Get-FileHash -LiteralPath $installer -Algorithm SHA256).Hash.ToLowerInvariant()
    Require ($actualHash -eq $expectedHash) 'Downloaded installer SHA-256 does not match its shipped checksum.'
    $proof.installer_sha256 = $actualHash
    $proof.installer_bytes = $installerInfo.Length
    $checks.Add('downloaded_installer_sha256_matches_shipped_checksum')

    # Inno Setup's executable bootstrap can be PE32 even for an x64 app payload.
    $stream = [IO.File]::OpenRead($installer)
    $reader = [IO.BinaryReader]::new($stream)
    try {
        Require ($stream.Length -gt 1048576) 'Downloaded installer is unexpectedly small.'
        Require ($reader.ReadUInt16() -eq 0x5A4D) 'Downloaded installer has no MZ executable header.'
        $stream.Position = 0x3C
        $peOffset = $reader.ReadUInt32()
        Require ($peOffset -ge 0x40 -and $peOffset -le $stream.Length - 26) 'Downloaded installer has an invalid PE header offset.'
        $stream.Position = $peOffset
        Require ($reader.ReadUInt32() -eq 0x00004550) 'Downloaded installer has no Windows PE signature.'
        $machine = $reader.ReadUInt16()
        Require ($machine -in @(0x014c, 0x8664)) 'Downloaded installer has an unsupported PE bootstrap architecture.'
        $stream.Position = $peOffset + 24
        Require ($reader.ReadUInt16() -in @(0x010b, 0x020b)) 'Downloaded installer has no valid PE optional header.'
        $proof.installer_pe_machine = ('0x{0:X4}' -f $machine)
    } finally {
        $reader.Dispose()
        $stream.Dispose()
    }
    $checks.Add('downloaded_installer_is_valid_windows_pe')

    $manifest = Get-Content -LiteralPath (Join-Path $artifact 'build/bundle_manifest.json') -Raw | ConvertFrom-Json
    Require ($manifest.application_version -eq $expectedVersion) "Downloaded manifest is not version $ExpectedVersion."
    Require ($manifest.source_commit -eq $expectedSource) 'Downloaded manifest does not identify the expected released source commit.'
    Require ($manifest.source_dirty -is [bool] -and !$manifest.source_dirty) 'Downloaded manifest does not describe a clean source build.'
    Require ($manifest.gpu_runtime_requested -eq $true) 'Downloaded bundle does not include the requested CUDA runtime.'
    $checks.Add('archived_manifest_version_source_and_clean_build_match')

    foreach ($relativePath in @('build/frozen-smoke.json', 'build/installed-engine-smoke.json')) {
        $archived = Read-Receipt $relativePath
        Require ($archived.application_version -eq $expectedVersion -and $archived.fea_elements -gt 0 -and $archived.flight_samples -gt 0) "Archived engineering receipt is incomplete: $relativePath"
    }
    foreach ($relativePath in @('build/frozen-cuda-bundle-smoke.json', 'build/installed-cuda-bundle-smoke.json')) {
        Require-CudaReceipt (Read-Receipt $relativePath)
    }
    $preferences = Read-Receipt 'build/installed-preferences-smoke.json'
    Require ($preferences.fresh_processes -eq 2 -and $preferences.different_loopback_origins -eq $true) 'Archived preference receipt did not verify two fresh desktop sessions.'
    $checks.Add('archived_engine_cuda_and_preference_receipts_pass')

    $installed = Join-Path $env:RUNNER_TEMP ('RocketWorkbench-download-check-' + [Guid]::NewGuid().ToString('N'))
    $installLog = Join-Path $output 'install.log'
    $processCheck = Join-Path $PSScriptRoot 'windows_process_check.ps1'
    & $processCheck -FilePath $installer -ProcessArguments @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', ('/DIR="' + $installed + '"'), ('/LOG="' + $installLog + '"')) -TimeoutSeconds 600
    $executable = Join-Path $installed 'RocketWorkbench.exe'
    $fileVersion = (Get-Item -LiteralPath $executable).VersionInfo.ProductVersion
    Require ($fileVersion -eq $expectedVersion) "Freshly installed executable ProductVersion is not $ExpectedVersion."
    $proof.installed_product_version = $fileVersion
    $checks.Add('downloaded_installer_silently_installs_version_' + $ExpectedVersion.Replace('.', '_'))

    $enginePath = Join-Path $output 'installed-engine-smoke.json'
    & $processCheck -FilePath $executable -ProcessArguments @('--smoke-test', '--smoke-output', ('"' + $enginePath + '"')) -TimeoutSeconds 360
    $engine = Get-Content -LiteralPath $enginePath -Raw | ConvertFrom-Json
    Require ($engine.status -eq 'ok' -and $engine.application_version -eq $expectedVersion -and $engine.fea_elements -gt 0 -and $engine.flight_samples -gt 0) 'Freshly installed engine did not return actual flight/FEA evidence.'
    $proof.flight_samples = $engine.flight_samples
    $proof.fea_elements = $engine.fea_elements
    $checks.Add('fresh_installed_flight_and_solid_fea_smoke_pass')

    $cudaPath = Join-Path $output 'installed-cuda-bundle-smoke.json'
    & $processCheck -FilePath $executable -ProcessArguments @('--cuda-bundle-smoke-test', '--smoke-output', ('"' + $cudaPath + '"')) -TimeoutSeconds 180
    $cuda = Get-Content -LiteralPath $cudaPath -Raw | ConvertFrom-Json
    Require ($cuda.status -eq 'ok') 'Freshly installed CUDA bundle check failed.'
    Require-CudaReceipt $cuda
    $proof.cuda_native_libraries = $cuda.libraries.Count
    $proof.cuda_compiled_ptx_bytes = $cuda.compiler.ptx_bytes
    if ($requiresStartupCompilerGate) {
        $proof.cuda_startup_path_verified = $cuda.compiler.startup_path_verified
        $proof.cuda_test_only_preloads_before_compilation = $cuda.compiler.test_only_preloads_before_compilation
        $proof.cuda_compilation_targets = @($cuda.compiler.targets)
        $checks.Add('fresh_installed_cuda_normal_startup_compiles_compute_75_and_compute_89_without_test_preloads')
    }
    $checks.Add('fresh_installed_cuda_native_imports_headers_and_offline_compilation_pass')

    $desktopData = Join-Path $env:RUNNER_TEMP ('RocketWorkbench-download-desktop-' + [Guid]::NewGuid().ToString('N'))
    try {
        & $processCheck -FilePath $executable -ProcessArguments @('--desktop-smoke-test', '--data-dir', ('"' + $desktopData + '"')) -TimeoutSeconds 90
    } finally {
        $desktopLog = Join-Path $desktopData 'application.log'
        if (Test-Path -LiteralPath $desktopLog) {
            Copy-Item -LiteralPath $desktopLog -Destination (Join-Path $output 'installed-desktop-smoke.log')
        }
    }
    $desktopLogText = Get-Content -LiteralPath (Join-Path $output 'installed-desktop-smoke.log') -Raw
    Require ($desktopLogText -match 'Desktop smoke passed:') 'Fresh native desktop did not log its actual UI/WebGL/API success.'
    foreach ($key in @('shell', 'webgl', 'api', 'project')) {
        Require ($desktopLogText -match ("'" + $key + "': True")) "Fresh native desktop check is missing: $key"
    }
    $checks.Add('fresh_installed_native_ui_authenticated_api_project_and_webgl_pass')
    $proof.status = 'ok'
    Notice "Downloaded original $ExpectedVersion installer from run $SourceRunId; SHA-256 $actualHash matches shipped checksum. Fresh installation, real flight/FEA engine, bundled CUDA imports/offline compiler and native UI/API/WebGL passed. Physical NVIDIA device execution is not tested."
} catch {
    $proof.error = $_.Exception.Message
    Notice $proof.error 'error'
    throw
} finally {
    $proof.completed_at_utc = [DateTime]::UtcNow.ToString('o')
    $proof | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $output 'verification.json') -Encoding utf8
}
