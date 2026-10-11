# PowerShell 5.1 entry, runnable without an existing Python installation.
param([string]$Target, [switch]$Activate, [switch]$NoActivate)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0
if ($Activate -and $NoActivate) { throw 'Choose either -Activate or -NoActivate, not both' }
if ($PSVersionTable.PSVersion -lt [version]'5.1') { throw 'PowerShell 5.1 required' }
$os = Get-CimInstance Win32_OperatingSystem
$arch = (Get-CimInstance Win32_Processor | Select-Object -First 1).Architecture
if ($arch -ne 9 -or $os.ProductType -ne 1 -or [int]$os.BuildNumber -lt 17763 -or
    [int]$os.BuildNumber -ge 22000) { throw 'Windows 10 x64 build 17763+ required (19045 recommended)' }
$bundle = $PSScriptRoot
if (-not (Test-Path -LiteralPath (Join-Path $bundle 'manifest.json'))) {
    $bundle = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
}
if (-not $Target) {
    $defaultTarget = Join-Path $env:LOCALAPPDATA 'Chiheng\legal'
    $answer = Read-Host ('New installation directory (Enter for ' + $defaultTarget + ')')
    $Target = if ($answer) { $answer } else { $defaultTarget }
}
$Target = [IO.Path]::GetFullPath($Target)
if (Test-Path -LiteralPath $Target) { throw ('Target exists; nothing overwritten: ' + $Target) }
$enableTasks = [bool]$Activate
if (-not $Activate -and -not $NoActivate) {
    Write-Host 'Autostart will start local search when the current user signs in.'
    Write-Host 'It will also run the existing update scheduler every 5 minutes.'
    Write-Host 'No Windows password is stored. Enabling is recommended; choose N to install without autostart.'
    do { $choice = Read-Host 'Enable these tasks? [Y/n]' }
    while ($choice -notmatch '^(?i:y|yes|n|no)?$')
    $enableTasks = ($choice -eq '' -or $choice -match '^(?i:y|yes)$')
}

function Assert-Plain($path) {
    $item = Get-Item -LiteralPath $path -Force
    if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw ('Reparse path refused: ' + $path) }
    return $item
}
function Assert-Name([string]$name) {
    if ($name -match '[\\:<>"|?*\x00-\x1f]' -or $name -match '(^|/)($|\.{1,2}(/|$))') { throw 'Unsafe bundle path' }
    foreach ($part in $name.Split('/')) {
        if ($part -match '[. ]$' -or $part -match '^(?i:CON|PRN|AUX|NUL|CONIN\$|CONOUT\$|COM[1-9\u00b9\u00b2\u00b3]|LPT[1-9\u00b9\u00b2\u00b3])(\.|$)') { throw 'Unsafe Windows name' }
    }
}
$ancestor = [IO.DirectoryInfo]$bundle
while ($null -ne $ancestor) { $null = Assert-Plain $ancestor.FullName; $ancestor = $ancestor.Parent }
$manifestPath = Join-Path $bundle 'manifest.json'
$manifestItem = Assert-Plain $manifestPath
if ($manifestItem.Length -gt 16777216) { throw 'Manifest too large' }
$manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($manifest.schema_version -ne 1) { throw 'Unsupported bundle manifest' }
$declared = @{}
$prefixes = @{}
foreach ($entry in $manifest.files.PSObject.Properties) {
    $name = $entry.Name
    Assert-Name $name
    $prefix = ''
    foreach ($part in $name.Split('/')) {
        $prefix = if ($prefix) { $prefix + '/' + $part } else { $part }
        $key = $prefix.Normalize([Text.NormalizationForm]::FormC).ToLowerInvariant()
        if ($prefixes.ContainsKey($key) -and $prefixes[$key] -cne $prefix) { throw 'Case/Unicode collision' }
        $prefixes[$key] = $prefix
    }
    if ($declared.ContainsKey($name)) { throw 'Duplicate payload path' }
    $declared[$name] = $entry.Value
}
# Enumerate one level at a time so reparse directories are rejected before descent.
$queue = New-Object 'System.Collections.Generic.Queue[string]'
$queue.Enqueue($bundle)
$seen = @{}
while ($queue.Count -gt 0) {
    $directory = $queue.Dequeue()
    foreach ($item in Get-ChildItem -LiteralPath $directory -Force) {
        $null = Assert-Plain $item.FullName
        $name = $item.FullName.Substring($bundle.Length + 1).Replace('\','/')
        if ($item.PSIsContainer) {
            if (-not $prefixes.ContainsKey($name.Normalize([Text.NormalizationForm]::FormC).ToLowerInvariant())) { throw 'Undeclared directory' }
            $queue.Enqueue($item.FullName)
        } elseif ($name -ne 'manifest.json') {
            if (-not $declared.ContainsKey($name)) { throw ('Undeclared file: ' + $name) }
            $expected = $declared[$name]
            if ($item.Length -ne $expected.size -or $expected.sha256 -notmatch '^[0-9a-f]{64}$' -or
                (Get-FileHash -LiteralPath $item.FullName -Algorithm SHA256).Hash.ToLowerInvariant() -cne $expected.sha256) { throw ('Hash/size mismatch: ' + $name) }
            $seen[$name] = $true
        }
    }
}
if ($seen.Count -ne $declared.Count) { throw 'Declared payload missing' }
$archive = Join-Path $bundle 'runtime\python-3.13.16-amd64.zip'
$pythonHash = 'bbf675bb5e763c1efbb09a3a461b259d81598a63c30c4b0d7ea11b9f063df159'
if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant() -cne $pythonHash) { throw 'Official Python hash mismatch' }
Write-Host 'Bundle integrity checked. Publisher identity depends on your separate outer ZIP SHA-256 check.'
$temporary = Join-Path ([IO.Path]::GetTempPath()) ('chiheng-bootstrap-' + [guid]::NewGuid().ToString('N'))
if (Test-Path -LiteralPath $temporary) { throw 'Temporary directory unexpectedly exists' }
$null = New-Item -ItemType Directory -Path $temporary
try {
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [IO.Compression.ZipFile]::ExtractToDirectory($archive, $temporary)
    $python = Join-Path $temporary 'python.exe'
    $env:PYTHONUTF8 = '1'
    $env:PYTHONIOENCODING = 'utf-8'
    $env:PYTHONDONTWRITEBYTECODE = '1'
    $env:PYTHONNOUSERSITE = '1'
    Remove-Item Env:PYTHONHOME -ErrorAction SilentlyContinue
    Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
    $installer = Join-Path $bundle 'source\scripts\install_windows.py'
    if (-not $declared.ContainsKey('source/scripts/install_windows.py')) { throw 'Installer not declared' }
    $arguments = @('-E','-s','-X','utf8','-B', $installer, '--bundle', $bundle, '--target', $Target)
    if ($enableTasks) { $arguments += '--activate' }
    & $python @arguments
    $installerExit = $LASTEXITCODE
    if ($installerExit -ne 0) { throw ('Installation failed with exit code ' + $installerExit + '; target retained for review') }
} finally {
    # Only this newly created GUID directory is removed; never the installation.
    $null = Assert-Plain $temporary
    Get-ChildItem -LiteralPath $temporary -Recurse -Force | ForEach-Object { $null = Assert-Plain $_.FullName }
    Remove-Item -LiteralPath $temporary -Recurse -Force
}
