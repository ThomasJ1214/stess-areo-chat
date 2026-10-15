# Exercise release physics through the actual installed executable API.
# No development Python, mocked solver result, CUDA Toolkit or GPU is required.
# Verification deadlines below do not configure numerical solver stopping limits.
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
$data = Join-Path $temporaryRoot ('RocketWorkbench-installed-advanced-' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $data -Force | Out-Null
$process = $null
$proof = [ordered]@{
    status = 'failed'; application_version = $ExpectedVersion
    scope = 'Actual installed API: short 6DOF/Dryden trajectories, causal wind/air changes, original-fin dynamic beam FEM and launch-driven laminar transient CFD.'
    limits = 'Short flights intentionally stop at maximum_time. Reference small-angle 6DOF, assumed isotropic fins and unresolved laminar CFD are not validated rocket flight, laminate or turbulent-flow predictions.'
    gpu_device_execution = 'Not tested; actual numerical jobs explicitly use their CPU backends.'
    solver_time_limits_added = $false
}
function Require([bool] $Condition, [string] $Message) {
    if (!$Condition) { throw $Message }
}
function Api([string] $Path, [string] $Method = 'GET', $Body = $null) {
    $arguments = @{ Uri = $script:base + $Path; Method = $Method; TimeoutSec = 10; NoProxy = $true }
    if ($null -ne $Body) { $arguments.Body = $Body | ConvertTo-Json -Depth 24 -Compress; $arguments.ContentType = 'application/json' }
    Invoke-RestMethod @arguments
}
function Wait-JobResult([string] $Identity, [int] $TimeoutSeconds = 120) {
    $timer = [Diagnostics.Stopwatch]::StartNew()
    while ($timer.Elapsed.TotalSeconds -lt $TimeoutSeconds) {
        Require (!$process.HasExited) 'Installed headless application exited during an advanced job.'
        $job = Api ('/api/jobs/' + $Identity)
        if ($job.status -notin @('queued', 'running')) {
            Require ($job.status -eq 'completed') ('Actual installed advanced job failed: ' + $job.status + ' ' + $job.error)
            Require ($null -ne $job.result) 'Completed installed advanced job returned no result.'
            return $job
        }
        Start-Sleep -Milliseconds 100
    }
    throw "Verification timeout waiting for installed advanced job $Identity; no CFD solver deadline was configured."
}
function Assert-FiniteField($Values, [string] $Name) {
    Require ($null -ne $Values -and @($Values).Count -gt 0) "Actual numerical field is missing: $Name"
    foreach ($value in $Values) {
        if ($value -is [array]) { Assert-FiniteField $value $Name; continue }
        Require ($null -ne $value -and $value -isnot [string] -and $value -isnot [bool]) "Field contains a nonnumeric value: $Name"
        Require ([double]::IsFinite([double] $value)) "Field contains a nonfinite value: $Name"
    }
}
function Squared-Norm($Vector) {
    $sum = 0.0
    foreach ($value in $Vector) { $sum += [double] $value * [double] $value }
    return $sum
}
function Max-Difference($Left, $Right) {
    Require (@($Left).Count -eq @($Right).Count) 'Cannot compare numerical vectors of different length.'
    $maximum = 0.0
    for ($index = 0; $index -lt @($Left).Count; $index++) {
        $maximum = [Math]::Max($maximum, [Math]::Abs([double] $Left[$index] - [double] $Right[$index]))
    }
    return $maximum
}
function Assert-RigidFlight($Result) {
    Require ($Result.summary.complete -is [bool] -and !$Result.summary.complete -and $Result.summary.termination_reason -eq 'maximum_time') 'Short 6DOF verification flight must identify its intentional partial-flight limit.'
    Require ([Math]::Abs([double] $Result.summary.flight_time_s - 2.0) -lt 1e-10 -and $Result.summary.rail_exit_time_s -gt 0) '6DOF launch did not reach the requested physical interval and actual rail exit.'
    Require ($Result.wind.model -eq 'dryden' -and $Result.wind.seed -eq 42 -and $Result.wind.dryden.sample_interval_s -eq 0.02) 'Solved flight does not identify the actual seeded Dryden wind model.'
    Require (![string]::IsNullOrWhiteSpace($Result.inertia.basis) -and @($Result.inertia.components).Count -gt 0) 'Rigid-body inertia estimate provenance is missing.'
    Require ($Result.inputs.application_version -eq $ExpectedVersion -and $Result.inputs.conditions.flight_model -eq 'rigid_body') 'Solved rigid-body input provenance is incorrect.'
    $maximumNormError = 0.0; $maximumAxisError = 0.0
    foreach ($row in @($Result.trajectory)) {
        foreach ($field in @('body_quaternion_world', 'body_axis_world', 'angular_velocity_body_rad_s', 'inertia_tensor_body_kg_m2', 'cg_geometry_m', 'wind_vector', 'velocity_vector')) { Assert-FiniteField $row.$field $field }
        $q = $row.body_quaternion_world
        Require (@($q).Count -eq 4) 'Actual rigid-body quaternion is not four-dimensional.'
        $maximumNormError = [Math]::Max($maximumNormError, [Math]::Abs([Math]::Sqrt((Squared-Norm $q)) - 1.0))
        $w = [double] $q[0]; $x = [double] $q[1]; $y = [double] $q[2]; $z = [double] $q[3]
        # Independent Hamilton quaternion first-column rotation check.
        $nose = @((1 - 2 * ($y * $y + $z * $z)), (2 * ($x * $y + $w * $z)), (2 * ($x * $z - $w * $y)))
        $maximumAxisError = [Math]::Max($maximumAxisError, (Max-Difference $nose $row.body_axis_world))
        $tensor = $row.inertia_tensor_body_kg_m2
        Require (@($tensor).Count -eq 3 -and @($tensor[0]).Count -eq 3) 'Actual inertia tensor has an incorrect shape.'
        for ($i = 0; $i -lt 3; $i++) {
            for ($j = 0; $j -lt 3; $j++) { Require ([Math]::Abs([double] $tensor[$i][$j] - [double] $tensor[$j][$i]) -lt 1e-10) 'Actual inertia tensor is not symmetric.' }
        }
        $a = [double] $tensor[0][0]; $b = [double] $tensor[0][1]; $c = [double] $tensor[0][2]
        $d = [double] $tensor[1][1]; $e = [double] $tensor[1][2]; $f = [double] $tensor[2][2]
        $determinant = $a * ($d * $f - $e * $e) - $b * ($b * $f - $c * $e) + $c * ($b * $e - $c * $d)
        Require ($a -gt 0 -and $a * $d - $b * $b -gt 0 -and $determinant -gt 0) 'Actual inertia tensor is not positive definite.'
    }
    Require ($maximumNormError -lt 1e-8 -and $maximumAxisError -lt 1e-8) 'Actual 6DOF quaternion normalization or body-axis rotation check failed.'
    Require ((Max-Difference $Result.trajectory[0].body_quaternion_world $Result.trajectory[-1].body_quaternion_world) -gt 1e-3) 'Actual integrated rigid-body attitude did not evolve after rail exit.'
    Require ([double] $Result.trajectory[-1].inertia_tensor_body_kg_m2[0][0] -lt [double] $Result.trajectory[0].inertia_tensor_body_kg_m2[0][0]) 'Motor propellant consumption did not change the actual rigid-body inertia.'
    return [ordered]@{ samples = @($Result.trajectory).Count; rail_exit_time_s = $Result.summary.rail_exit_time_s; maximum_quaternion_norm_error = $maximumNormError; maximum_body_axis_error = $maximumAxisError; inertia_basis = $Result.inertia.basis; termination_reason = $Result.summary.termination_reason }
}
try {
    $listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, 0)
    try { $listener.Start(); $port = $listener.LocalEndpoint.Port } finally { $listener.Stop() }
    $script:base = 'http://127.0.0.1:' + $port
    $start = [Diagnostics.ProcessStartInfo]::new()
    $start.FileName = (Resolve-Path -LiteralPath $Executable).Path
    $start.UseShellExecute = $false; $start.CreateNoWindow = $true
    foreach ($argument in @('--headless', '--host', '127.0.0.1', '--port', [string] $port, '--data-dir', $data)) { $start.ArgumentList.Add($argument) }
    $process = [Diagnostics.Process]::Start($start)
    $ready = [Diagnostics.Stopwatch]::StartNew(); $health = $null
    while ($ready.Elapsed.TotalSeconds -lt 90) {
        Require (!$process.HasExited) 'Installed headless application exited before advanced API readiness.'
        try { $health = Api '/api/health'; break } catch { Start-Sleep -Milliseconds 200 }
    }
    Require ($null -ne $health -and $health.status -eq 'ok' -and $health.version -eq $ExpectedVersion) 'Installed advanced API readiness/version check failed.'
    $project = Api '/api/project'
    Require (![string]::IsNullOrWhiteSpace($project.id) -and @($project.components).Count -gt 0) 'Installed API returned no actual demo geometry.'
    $conditions = @{ flight_model = 'rigid_body'; wind_model = 'dryden'; wind_speed = 0.2; turbulence = 0.1; seed = 42; launch_angle = 0; max_time = 2; dt = 0.05; initial_angular_velocity_body_rad_s = @(0.1, 0, 0) }
    $baselineStart = Api '/api/jobs' 'POST' @{ kind = 'flight'; conditions = $conditions; configuration_id = $project.active_configuration_id }
    $baseline = Wait-JobResult $baselineStart.id
    $proof.baseline = Assert-RigidFlight $baseline.result
    $proof.baseline_job_id = $baseline.id

    $changedConditions = $conditions.Clone()
    $changedConditions.wind_events = @(@{ time_s = 0.8; wind_speed = 0.8; wind_direction = 180; turbulence = 0.1; transition_s = 0.2; temperature_delta = 3 })
    $structuralOptions = @{ structural_mode = 'dynamic_fins'; elements = 4; steps_per_period = 20; allow_isotropic_surrogate = $true }
    $changedStart = Api '/api/jobs' 'POST' @{ kind = 'flight'; conditions = $changedConditions; configuration_id = $project.active_configuration_id; options = $structuralOptions }
    $changed = Wait-JobResult $changedStart.id
    $proof.changed = Assert-RigidFlight $changed.result
    $proof.changed_job_id = $changed.id
    # Complete project hashes intentionally differ because they include each
    # run's environment/options. Compare the actual geometry identity instead.
    Require ($changed.result.inputs.geometry_signature -eq $baseline.result.inputs.geometry_signature -and $changed.result.inputs.project_id -eq $baseline.result.inputs.project_id -and $changed.result.inputs.configuration_id -eq $baseline.result.inputs.configuration_id) 'Scheduled wind/air change altered the rocket geometry or configuration identity.'
    Require (@($changed.result.wind.events).Count -eq 1 -and $changed.result.inputs.conditions.wind_events[0].time_s -eq 0.8) 'Scheduled actual wind change is missing from solved inputs.'
    $originalRows = @($baseline.result.trajectory); $changedRows = @($changed.result.trajectory)
    $shared = 0; $lastSharedTime = 0.0; $maximumPrefixError = 0.0; $index = 0
    foreach ($row in $changedRows) {
        if ([double] $row.time -gt 0.7) { break }
        while ($index -lt $originalRows.Count - 1 -and [double] $originalRows[$index].time -lt [double] $row.time - 1e-11) { $index++ }
        Require ([Math]::Abs([double] $originalRows[$index].time - [double] $row.time) -lt 1e-11) 'Future wind change unexpectedly altered an earlier accepted physical timestamp.'
        $original = $originalRows[$index]
        foreach ($field in @('velocity_vector', 'body_quaternion_world', 'wind_vector')) {
            $maximumPrefixError = [Math]::Max($maximumPrefixError, (Max-Difference $original.$field $row.$field))
        }
        foreach ($field in @('east', 'north', 'altitude', 'temperature_k', 'mass')) {
            $maximumPrefixError = [Math]::Max($maximumPrefixError, [Math]::Abs([double] $original.$field - [double] $row.$field))
        }
        $shared++; $lastSharedTime = [double] $row.time
    }
    Require ($shared -ge 10 -and $lastSharedTime -ge 0.65 -and $maximumPrefixError -lt 1e-8) 'Causal wind/air change failed the independent unchanged physical-prefix check.'
    $last = $changedRows[-1]; $originalLast = $originalRows[-1]
    Require ((Max-Difference $last.wind_vector $originalLast.wind_vector) -gt 0.5) 'Scheduled wind change did not affect actual later wind vectors.'
    Require ([double] $last.temperature_k - [double] $originalLast.temperature_k -gt 2.9) 'Scheduled temperature change did not affect the actual later atmospheric state.'
    Require ((Max-Difference $last.velocity_vector $originalLast.velocity_vector) -gt 1e-3) 'Scheduled conditions did not affect the actual later solved rocket motion.'
    $proof.causal_environment = [ordered]@{ checked_prefix_samples = $shared; last_checked_prefix_time_s = $lastSharedTime; maximum_prefix_error = $maximumPrefixError; event_time_s = 0.8; later_velocity_difference_m_s = (Max-Difference $last.velocity_vector $originalLast.velocity_vector) }

    $structural = $changed.result.dynamic_structural_analysis
    if ([version]$ExpectedVersion -ge [version]'0.3.3') {
        $supportedModels = @($structural.components | Where-Object { $_.supported })
        Require ($supportedModels.Count -gt 0) 'Exact modal verification has no supported fin model.'
        foreach ($model in $supportedModels) {
            Require ($model.time_integrator -eq 'exact_foh' -and $model.retained_modes -eq $model.free_dofs) 'Installed default did not retain the complete exact modal basis.'
            Require ($null -eq $model.maximum_internal_step_s) 'Exact modal integration incorrectly declares a Newmark timestep.'
        }
        $studyStart = Api '/api/jobs' 'POST' @{ kind = 'sweep'; conditions = $conditions; configuration_id = $project.active_configuration_id; options = @{ parameter = 'wind_speed'; start = 0.1; stop = 0.2; count = 2; flight = $true } }
        $study = Wait-JobResult $studyStart.id
        Require ($study.result.sample_counts.statistics_eligible -eq 0 -and $study.result.sample_counts.excluded -eq 2) 'Installed partial launch study polluted completed-flight statistics.'
        Require (@($study.result.statistics.PSObject.Properties).Count -eq 0) 'Partial launch study returned completed-flight aggregate metrics.'
        foreach ($sample in @($study.result.rows)) {
            Require (!$sample.complete -and !$sample.statistics_eligible -and $null -ne $sample.observed_apogee_m -and $null -eq $sample.apogee_m) 'Partial launch study lost observed-value labeling.'
        }
        $proof.study_eligibility = $study.result.sample_counts
        $proof.fin_time_integrator = 'exact_foh'
    }
    Require ($null -ne $structural -and $structural.summary.status -eq 'completed' -and $structural.summary.complete -eq $true -and $structural.summary.substeps -gt 0) 'Installed dynamic fin FEM did not perform and finish its actual internal integration.'
    Require ($structural.summary.supported_components -gt 0 -and $structural.summary.rows_with_available_results -gt 0 -and $structural.summary.unavailable_rows -gt 0) 'Dynamic fin result does not expose actual supported and unavailable flight coverage.'
    Require ($structural.summary.max_stress_pa -gt 0 -and $structural.summary.max_deflection_m -gt 0 -and $changed.result.summary.max_dynamic_fin_stress_pa -gt 0) 'Installed dynamic fin FEM returned no actual nonzero structural response.'
    $available = 0; $unavailable = 0
    foreach ($row in $changedRows) {
        Require ($null -ne $row.PSObject.Properties['dynamic_stress'] -and $null -ne $row.PSObject.Properties['dynamic_structural_components']) 'Actual flight timestamp is missing its aligned dynamic structural state.'
        if ($null -eq $row.dynamic_stress) { $unavailable++; continue }
        Assert-FiniteField @($row.dynamic_stress) 'dynamic_stress'
        $available++
        foreach ($component in @($row.dynamic_structural_components)) {
            if (!$component.supported) { continue }
            Require ($component.translational_base_inertia_included -eq $true) 'Actual dynamic fin result omitted its recorded translational inertial forcing.'
            foreach ($fin in @($component.fins)) {
                foreach ($field in @('span_m', 'nodal_displacement_m', 'nodal_bending_stress_pa', 'root_reaction_force_n', 'root_reaction_moment_nm', 'base_inertial_force_n')) { Assert-FiniteField @($fin.$field) $field }
            }
        }
    }
    Require ($available -eq $structural.summary.rows_with_available_results -and $unavailable -eq $structural.summary.unavailable_rows) 'Dynamic fin FEM coverage counts disagree with actual nullable flight states.'
    $proof.dynamic_fin_fem = [ordered]@{ substeps = $structural.summary.substeps; max_stress_pa = $structural.summary.max_stress_pa; max_deflection_m = $structural.summary.max_deflection_m; available_rows = $available; unavailable_rows = $unavailable; coverage = $structural.summary.coverage; isotropic_surrogate_explicitly_acknowledged = $true }

    $options = @{ mode = 'transient'; physics_model = 'laminar'; transient_source = 'launch'; flight_job_id = $changed.id; flight_start_s = 1.0; flight_end_s = 1.0001; backend = 'cpu'; grid_resolution = 12; transverse_resolution = 12; max_cells = 50000; sample_limit = 30; surface_limit = 30; snapshot_count = 4 }
    $cfdStart = Api '/api/jobs' 'POST' @{ kind = 'cfd'; conditions = $changedConditions; configuration_id = $project.active_configuration_id; options = $options }
    $cfd = Wait-JobResult $cfdStart.id
    $result = $cfd.result; $frames = @($result.transient.frames)
    Require ($result.summary.physics_model -eq 'laminar' -and $result.summary.status -eq 'transient_complete' -and $cfd.progress_basis -eq 'physical_time') 'Installed laminar CFD did not finish an actual physical-time solve.'
    Require ([Math]::Abs([double] $result.summary.physical_time_s - 0.0001) -lt 1e-12 -and $frames.Count -ge 2 -and $frames.Count -le 4) 'Installed laminar CFD returned incomplete actual frame/time evidence.'
    Require ($result.inputs.flight_source.job_id -eq $changed.id -and $result.inputs.flight_source.inputs.project_sha256 -eq $changed.result.inputs.project_sha256) 'Laminar CFD did not use the selected actual changed flight and rocket geometry.'
    Require ($result.inputs.flight_source.resolved_attitude -eq $true) 'Laminar launch boundary does not identify the actual integrated 6DOF attitude.'
    Require ($result.summary.viscous_force_validated -is [bool] -and !$result.summary.viscous_force_validated -and !$result.summary.viscous_force_steady -and !$result.summary.converged) 'Experimental transient laminar CFD incorrectly claims validated or steady forces.'
    $maximumClosureError = 0.0; $maximumShear = 0.0
    foreach ($frame in $frames) {
        foreach ($field in @('sample_velocity_m_s', 'sample_pressure_pa', 'flow_velocity_m_s', 'surface_viscous_traction_pa', 'surface_shear_traction_pa', 'surface_shear_stress_pa', 'surface_total_traction_pa', 'surface_wall_fluid_temperature_k', 'viscous_force_n', 'total_force_n')) { Assert-FiniteField $frame.$field $field }
        for ($axis = 0; $axis -lt 3; $axis++) {
            $closureError = [Math]::Abs([double] $frame.total_force_n[$axis] - [double] $frame.force_n[$axis] - [double] $frame.viscous_force_n[$axis])
            $maximumClosureError = [Math]::Max($maximumClosureError, $closureError)
        }
        foreach ($shear in @($frame.surface_shear_stress_pa)) { $maximumShear = [Math]::Max($maximumShear, [double] $shear) }
    }
    Require ($maximumClosureError -lt 1e-8 -and $maximumShear -gt 0) 'Actual laminar pressure-plus-viscous force closure or no-slip shear check failed.'
    $proof.laminar_cfd = [ordered]@{ job_id = $cfd.id; backend = $result.backend; frame_count = $frames.Count; physical_time_s = $result.summary.physical_time_s; resolved_launch_attitude = $true; maximum_total_force_closure_error_n = $maximumClosureError; maximum_sampled_wall_shear_pa = $maximumShear; validated_viscous_force = $false }
    $proof.status = 'ok'
    Write-Output "Installed $ExpectedVersion advanced physics passed: actual 6DOF/Dryden, causal environment prefix, dynamic fin FEM and $($frames.Count) laminar transient fields. No physical GPU or turbulent-flow validation claim."
} catch {
    $proof.error = $_.Exception.Message
    throw
} finally {
    if ($null -ne $process) {
        if (!$process.HasExited) { $process.Kill($true); $process.WaitForExit(10000) | Out-Null }
        $process.Dispose()
    }
    $proof.completed_at_utc = [DateTime]::UtcNow.ToString('o')
    $proof | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $output -Encoding utf8
}
