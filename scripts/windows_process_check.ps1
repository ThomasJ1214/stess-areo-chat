# Bound unattended installer/native checks; a frozen exception must not leave CI
# waiting for a dialog or orphaned mesher/browser process until its job deadline.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)] [string] $FilePath,
    [string[]] $ProcessArguments = @(),
    [ValidateRange(1, 7200)] [int] $TimeoutSeconds = 360
)
$ErrorActionPreference = 'Stop'
if ($ProcessArguments.Count -gt 0) {
    $process = Start-Process -FilePath $FilePath -ArgumentList $ProcessArguments -PassThru
} else {
    $process = Start-Process -FilePath $FilePath -PassThru
}
if (!$process.WaitForExit($TimeoutSeconds * 1000)) {
    $process.Kill($true)
    $process.WaitForExit()
    throw "Process exceeded ${TimeoutSeconds}s and its process tree was stopped: $FilePath"
}
$process.Refresh()
if ($process.ExitCode -ne 0) {
    throw "Process failed with exit code $($process.ExitCode): $FilePath"
}
