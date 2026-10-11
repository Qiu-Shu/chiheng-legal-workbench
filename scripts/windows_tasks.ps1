# Native Task Scheduler API. No passwords, elevation, SYSTEM, or overwrite.
param(
    [Parameter(Mandatory=$true)][ValidateSet('Activate','Disable','Remove')][string]$Mode,
    [Parameter(Mandatory=$true)][string]$Manifest
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0
if ($PSVersionTable.PSVersion -lt [version]'5.1') { throw 'PowerShell 5.1 required' }
$request = Get-Content -LiteralPath $Manifest -Raw -Encoding UTF8 | ConvertFrom-Json
$target = [IO.Path]::GetFullPath($request.target).TrimEnd('\')
$expectedManifest = Join-Path $target 'verification\install\tasks.json'
if ([IO.Path]::GetFullPath($Manifest) -cne $expectedManifest) { throw 'Unexpected manifest path' }
$state = Get-Content -LiteralPath (Join-Path $target 'verification\install\state.json') -Raw -Encoding UTF8 | ConvertFrom-Json
if ($state.status -ne 'complete' -or $state.target -cne $request.target -or
    $state.install_id -cne $request.install_id) { throw 'Installation identity mismatch' }
$sid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
if ($sid -in @('S-1-5-18','S-1-5-19','S-1-5-20')) { throw 'Interactive user required' }
$service = New-Object -ComObject 'Schedule.Service'
$service.Connect()
$folder = $service.GetFolder('\')
$marker = 'Chiheng installation ' + $request.install_id + ' at ' + $target

function Find-Task([string]$name) {
    try { return $folder.GetTask($name) }
    catch {
        $failure = $_.Exception
        while ($null -ne $failure.InnerException) { $failure = $failure.InnerException }
        if (($failure.HResult -band 0xFFFF) -eq 2) { return $null }
        throw
    }
}

function Assert-Owned($task, $spec) {
    $definition = $task.Definition
    if ($definition.RegistrationInfo.Description -cne $marker -or
        $definition.Principal.UserId -ne $sid -or
        $definition.Principal.LogonType -ne 3 -or $definition.Principal.RunLevel -ne 0 -or
        $definition.Actions.Count -ne 1) { throw ('Foreign task refused: ' + $spec.name) }
    $action = $definition.Actions.Item(1)
    if ($action.Type -ne 0 -or $action.Path -cne $spec.execute -or
        $action.Arguments -cne $spec.arguments -or
        $action.WorkingDirectory -cne $target) { throw ('Changed task action refused: ' + $spec.name) }
}

if (@($request.tasks).Count -ne 2) { throw 'Exactly MCP and update tasks required' }
$kinds = @()
foreach ($spec in $request.tasks) {
    if ($spec.name -notmatch '^Chiheng-[0-9a-f]{16}-(mcp|update)$' -or
        $spec.kind -notin @('mcp','update') -or $spec.name -notlike ('*-' + $spec.kind) -or
        $spec.execute -cne (Join-Path $target '.venv\Scripts\python.exe') -or
        $spec.working_directory -cne $target) { throw 'Invalid task specification' }
    $kinds += $spec.kind
}
if (($kinds | Sort-Object -Unique).Count -ne 2) { throw 'Duplicate task kind' }

if ($Mode -ne 'Activate') {
    # Validate every action before changing any. Missing or foreign task fails closed.
    foreach ($spec in $request.tasks) {
        $task = Find-Task $spec.name
        if ($null -eq $task) { throw ('Task missing: ' + $spec.name) }
        Assert-Owned $task $spec
    }
    foreach ($spec in $request.tasks) {
        $task = Find-Task $spec.name
        Assert-Owned $task $spec
        $task.Enabled = $false
        $task.Stop(0)
        if ($Mode -eq 'Remove') {
            Assert-Owned (Find-Task $spec.name) $spec
            $folder.DeleteTask($spec.name, 0)
        }
    }
    @{ disabled=$true; removed=($Mode -eq 'Remove'); data_deleted=$false } | ConvertTo-Json -Compress
    exit 0
}

$existing = @()
foreach ($spec in $request.tasks) {
    $task = Find-Task $spec.name
    if ($null -ne $task) { $existing += $spec }
}
if ($existing.Count -ne 0 -and $existing.Count -ne 2) { throw 'Partial task installation; no task changed' }
foreach ($spec in $existing) {
    $task = Find-Task $spec.name
    Assert-Owned $task $spec
    if ($task.Enabled) { throw ('Task already enabled; no task changed: ' + $spec.name) }
}
$listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, 18063)
try { $listener.Start() } finally { $listener.Stop() }
if ($existing.Count -eq 2) {
    $enabled = @()
    try {
        foreach ($spec in $existing) {
            $task = Find-Task $spec.name
            Assert-Owned $task $spec
            if ($task.Enabled) { throw ('Task state changed before resume: ' + $spec.name) }
            # Record before the COM setter so an ambiguous setter failure is also undone.
            $enabled += $spec
            $task.Enabled = $true
        }
        foreach ($spec in $enabled) {
            $task = Find-Task $spec.name
            Assert-Owned $task $spec
            if ($spec.kind -eq 'mcp') { $null = $task.Run($null) }
        }
        @{ activated=$true; activation_mode='resumed'; tasks=@($enabled | ForEach-Object { $_.name });
           http_ready_verified=$false; login_restart_verified=$false } | ConvertTo-Json -Compress
        exit 0
    } catch {
        $cause = $_
        for ($index = $enabled.Count - 1; $index -ge 0; $index--) {
            $spec = $enabled[$index]
            try {
                $task = Find-Task $spec.name
                Assert-Owned $task $spec
                $task.Enabled = $false
                $task.Stop(0)
            } catch { [Console]::Error.WriteLine('Resume rollback refused or failed: ' + $_.Exception.Message) }
        }
        throw $cause
    }
}
$created = @()
try {
    foreach ($spec in $request.tasks) {
        $definition = $service.NewTask(0)
        $definition.RegistrationInfo.Description = $marker
        $definition.Principal.UserId = $sid
        $definition.Principal.LogonType = 3 # InteractiveToken, no password storage.
        $definition.Principal.RunLevel = 0 # Limited/LUA, never Highest.
        $definition.Settings.Enabled = $true
        $definition.Settings.StartWhenAvailable = $true
        $definition.Settings.MultipleInstances = 2 # IgnoreNew.
        $definition.Settings.DisallowStartIfOnBatteries = $false
        $definition.Settings.StopIfGoingOnBatteries = $false
        $definition.Settings.ExecutionTimeLimit = if ($spec.kind -eq 'mcp') { 'PT0S' } else { 'PT1H' }
        $definition.Settings.RestartCount = 3
        $definition.Settings.RestartInterval = 'PT1M'
        $logon = $definition.Triggers.Create(9)
        $logon.UserId = $sid
        $logon.Enabled = $true
        if ($spec.kind -eq 'update') {
            $timer = $definition.Triggers.Create(1)
            $timer.StartBoundary = (Get-Date).AddMinutes(5).ToString('yyyy-MM-ddTHH:mm:ss')
            $timer.Repetition.Interval = 'PT5M'
            $timer.Enabled = $true
        }
        $action = $definition.Actions.Create(0)
        $action.Path = $spec.execute
        $action.Arguments = $spec.arguments
        $action.WorkingDirectory = $target
        # TASK_CREATE=2 is atomic create-only, never TASK_CREATE_OR_UPDATE=6.
        $null = $folder.RegisterTaskDefinition($spec.name, $definition, 2, $sid, $null, 3, $null)
        $created += $spec
    }
    foreach ($spec in $created) {
        $task = Find-Task $spec.name
        Assert-Owned $task $spec
        if ($spec.kind -eq 'mcp') { $null = $task.Run($null) }
    }
    @{ activated=$true; activation_mode='created'; tasks=@($created | ForEach-Object { $_.name });
       http_ready_verified=$false; login_restart_verified=$false } | ConvertTo-Json -Compress
} catch {
    $cause = $_
    foreach ($spec in $created) {
        try {
            $task = Find-Task $spec.name
            Assert-Owned $task $spec
            $task.Enabled = $false
            $task.Stop(0)
            Assert-Owned (Find-Task $spec.name) $spec
            $folder.DeleteTask($spec.name, 0)
        } catch { [Console]::Error.WriteLine('Rollback refused or failed: ' + $_.Exception.Message) }
    }
    throw $cause
}
