# Exercise the actual installed API and solvers, without Python or test fixtures.
# Timeouts below bound this verification process, never the numerical solver.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)] [string] $Executable,
    [Parameter(Mandatory = $true)] [string] $OutputPath,
    [Parameter(Mandatory = $true)] [ValidatePattern('^[0-9]+\.[0-9]+\.[0-9]+$')] [string] $ExpectedVersion
)
$ErrorActionPreference = 'Stop'
$output = [IO.Path]::GetFullPath($OutputPath)
New-Item -ItemType Directory -Path ([IO.Path]::GetDirectoryName($output)) -Force | Out-Null
$temporaryRoot = if ($env:RUNNER_TEMP) { $env:RUNNER_TEMP } else { [IO.Path]::GetTempPath() }
$data = Join-Path $temporaryRoot ('RocketWorkbench-installed-launch-cfd-' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $data -Force | Out-Null
$process = $null
$proof = [ordered]@{
    status = 'failed'; application_version = $ExpectedVersion
    scope = 'Actual installed application API; solved launch drives real CPU transient Euler fields.'
    fidelity = 'Adaptive point-mass flight and experimental inviscid Euler; no hardware GPU or validated CFD claim.'
    independent_boundary_check = 'Linear interpolation of saved vehicle velocity minus saved wind vectors; not the reported air-relative speed.'
    solver_time_limits_added = $false
}
function Require([bool] $Condition, [string] $Message) {
    if (!$Condition) { throw $Message }
}
function Api([string] $Path, [string] $Method = 'GET', $Body = $null) {
    $arguments = @{ Uri = $script:base + $Path; Method = $Method; TimeoutSec = 10; NoProxy = $true }
    if ($null -ne $Body) { $arguments.Body = $Body | ConvertTo-Json -Depth 20 -Compress; $arguments.ContentType = 'application/json' }
    Invoke-RestMethod @arguments
}
function Wait-JobResult([string] $Identity, [int] $TimeoutSeconds) {
    $timer = [Diagnostics.Stopwatch]::StartNew()
    while ($timer.Elapsed.TotalSeconds -lt $TimeoutSeconds) {
        Require (!$process.HasExited) 'Installed headless application exited during a solver job.'
        $job = Api ('/api/jobs/' + $Identity)
        if ($job.status -notin @('queued', 'running')) {
            Require ($job.status -eq 'completed') ('Actual installed job failed: ' + $job.status + ' ' + $job.error)
            Require ($null -ne $job.result) 'Completed installed job returned no result.'
            return $job
        }
        Start-Sleep -Milliseconds 100
    }
    throw "Verification timeout waiting for installed job $Identity; no solver time limit was configured."
}
function Assert-FiniteField($Values, [string] $Name) {
    Require ($null -ne $Values -and @($Values).Count -gt 0) "Actual field is missing: $Name"
    foreach ($value in $Values) {
        if ($value -is [array]) { Assert-FiniteField $value $Name; continue }
        Require ($null -ne $value -and $value -isnot [string] -and $value -isnot [bool]) "Field contains a nonnumeric value: $Name"
        Require ([double]::IsFinite([double] $value)) "Field contains a nonfinite value: $Name"
    }
}
function Relative-Speed($Rows, [double] $Time) {
    $index = 0
    while ($index -lt $Rows.Count - 2 -and [double] $Rows[$index + 1].time -le $Time) { $index++ }
    $left = $Rows[$index]; $right = $Rows[$index + 1]
    $span = [double] $right.time - [double] $left.time
    Require ($span -gt 0 -and $Time -ge [double] $left.time -and $Time -le [double] $right.time) 'Saved flight samples do not bracket a CFD timestamp.'
    $fraction = ($Time - [double] $left.time) / $span
    $squared = 0.0
    for ($axis = 0; $axis -lt 3; $axis++) {
        $a = [double] $left.velocity_vector[$axis] - [double] $left.wind_vector[$axis]
        $b = [double] $right.velocity_vector[$axis] - [double] $right.wind_vector[$axis]
        $component = $a + $fraction * ($b - $a)
        $squared += $component * $component
    }
    return [Math]::Sqrt($squared)
}
try {
    Require ([version] $ExpectedVersion -ge [version] '0.3.1') 'Installed launch-driven CFD verification requires release 0.3.1 or later.'
    $listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, 0)
    try { $listener.Start(); $port = $listener.LocalEndpoint.Port } finally { $listener.Stop() }
    $script:base = 'http://127.0.0.1:' + $port
    $start = [Diagnostics.ProcessStartInfo]::new()
    $start.FileName = (Resolve-Path -LiteralPath $Executable).Path
    $start.UseShellExecute = $false; $start.CreateNoWindow = $true
    foreach ($argument in @('--headless', '--host', '127.0.0.1', '--port', [string] $port, '--data-dir', $data)) { $start.ArgumentList.Add($argument) }
    $process = [Diagnostics.Process]::Start($start)
    $ready = [Diagnostics.Stopwatch]::StartNew()
    $health = $null
    while ($ready.Elapsed.TotalSeconds -lt 90) {
        Require (!$process.HasExited) 'Installed headless application exited before readiness.'
        try { $health = Api '/api/health'; break } catch { Start-Sleep -Milliseconds 200 }
    }
    Require ($null -ne $health -and $health.status -eq 'ok' -and $health.version -eq $ExpectedVersion) 'Installed API readiness/version check failed.'
    $project = Api '/api/project'
    Require (![string]::IsNullOrWhiteSpace($project.id) -and $project.components.Count -gt 0) 'Installed API returned no real demo project.'
    $conditions = @{ dt = 0.05; wind_speed = 3; turbulence = 0.1; seed = 19 }
    $flightStart = Api '/api/jobs' 'POST' @{ kind = 'flight'; conditions = $conditions; configuration_id = $project.active_configuration_id }
    $flight = Wait-JobResult $flightStart.id 90
    $trajectory = @($flight.result.trajectory)
    Require ($trajectory.Count -gt 2 -and $flight.result.summary.complete -eq $true -and $flight.result.summary.apogee_m -gt 0) 'Installed flight did not calculate a complete launch/recovery.'
    Require ($flight.result.inputs.application_version -eq $ExpectedVersion) 'Solved launch provenance has an unexpected application version.'
    $options = @{ mode = 'transient'; transient_source = 'launch'; flight_job_id = $flight.id; flight_start_s = 1.0; flight_end_s = 1.0001; backend = 'cpu'; grid_resolution = 12; transverse_resolution = 12; max_cells = 50000; sample_limit = 30; surface_limit = 30; snapshot_count = 4 }
    $cfdStart = Api '/api/jobs' 'POST' @{ kind = 'cfd'; conditions = $conditions; configuration_id = $project.active_configuration_id; options = $options }
    $cfd = Wait-JobResult $cfdStart.id 120
    $result = $cfd.result; $frames = @($result.transient.frames)
    Require ($cfd.progress_basis -eq 'physical_time' -and $result.summary.mode -eq 'transient' -and $result.summary.status -eq 'transient_complete') 'Installed CFD did not complete a real transient physical-time solve.'
    Require ($result.summary.converged -is [bool] -and !$result.summary.converged -and $result.summary.pressure_force_steady -is [bool] -and !$result.summary.pressure_force_steady) 'Transient CFD incorrectly claims converged steady pressure forces.'
    Require ([Math]::Abs([double] $result.summary.physical_time_s - 0.0001) -lt 1e-12 -and $frames.Count -ge 2 -and $frames.Count -le 4) 'Installed CFD returned incomplete time/frame evidence.'
    Require ([Math]::Abs([double] $frames[0].time_s) -lt 1e-12 -and [Math]::Abs([double] $frames[-1].time_s - 0.0001) -lt 1e-12) 'Actual initial/final CFD physical timestamps are incorrect.'
    Require ([Math]::Abs([double] $frames[0].flight_time_s - 1.0) -lt 1e-12 -and [Math]::Abs([double] $frames[-1].flight_time_s - 1.0001) -lt 1e-12) 'CFD snapshots do not identify the requested saved launch interval.'
    $source = $result.inputs.flight_source
    Require ($source.job_id -eq $flight.id -and $source.generated_for_cfd -is [bool] -and !$source.generated_for_cfd) 'Installed CFD did not use the selected completed launch.'
    Require ($source.inputs.project_sha256 -eq $flight.result.inputs.project_sha256 -and $source.inputs.project_sha256 -match '^[a-f0-9]{64}$') 'Installed CFD launch provenance does not match the solved input project.'
    $boundaryMatches = [Collections.Generic.List[object]]::new()
    $previousTime = -1.0
    foreach ($frame in $frames) {
        Require ([double] $frame.time_s -gt $previousTime) 'CFD frames are not distinct increasing accepted-state timestamps.'
        $previousTime = [double] $frame.time_s
        foreach ($field in @('flow_velocity_m_s', 'sample_pressure_pa', 'sample_velocity_m_s', 'sample_density_kg_m3', 'sample_mach', 'surface_pressure_pa', 'force_n', 'moment_about_origin_nm', 'freestream_velocity_m_s')) { Assert-FiniteField $frame.$field $field }
        $expected = Relative-Speed $trajectory ([double] $frame.flight_time_s)
        $actual = [Math]::Sqrt([double] $frame.freestream_velocity_m_s[0] * [double] $frame.freestream_velocity_m_s[0] + [double] $frame.freestream_velocity_m_s[1] * [double] $frame.freestream_velocity_m_s[1] + [double] $frame.freestream_velocity_m_s[2] * [double] $frame.freestream_velocity_m_s[2])
        $speedError = [Math]::Abs($actual - $expected)
        Require ($speedError -le [Math]::Max(1e-10, 1e-12 * $expected)) 'CFD frame boundary speed disagrees with independently interpolated saved vehicle/wind vectors.'
        $boundaryMatches.Add([ordered]@{ time_s = $frame.time_s; flight_time_s = $frame.flight_time_s; expected_speed_m_s = $expected; actual_speed_m_s = $actual; absolute_error_m_s = $speedError; flow_velocity_scalars = @($frame.flow_velocity_m_s).Count; pressure_samples = @($frame.sample_pressure_pa).Count; surface_pressures = @($frame.surface_pressure_pa).Count })
    }
    Require ([Math]::Abs($boundaryMatches[-1].actual_speed_m_s - $boundaryMatches[0].actual_speed_m_s) -gt 1e-8) 'Launch-driven CFD boundary speed did not change over the real saved flight interval.'
    $proof.status = 'ok'; $proof.flight_job_id = $flight.id; $proof.cfd_job_id = $cfd.id
    $proof.source_project_sha256 = $source.inputs.project_sha256; $proof.source_matches = $true
    $proof.apogee_m = $flight.result.summary.apogee_m; $proof.flight_samples = $trajectory.Count
    $proof.frame_count = $frames.Count; $proof.physical_time_s = $result.summary.physical_time_s
    $proof.boundary_speed_matches = $boundaryMatches; $proof.backend = $result.backend
    $proof.converged = $result.summary.converged; $proof.pressure_force_steady = $result.summary.pressure_force_steady
    Write-Output "Installed $ExpectedVersion launch-driven transient CFD passed: $($frames.Count) actual frames, saved-flight provenance, finite fields and independently matched changing boundary speeds."
} catch {
    $proof.error = $_.Exception.Message
    throw
} finally {
    if ($null -ne $process) {
        if (!$process.HasExited) { $process.Kill($true); $process.WaitForExit(10000) | Out-Null }
        $process.Dispose()
    }
    $proof.completed_at_utc = [DateTime]::UtcNow.ToString('o')
    $proof | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $output -Encoding utf8
}
