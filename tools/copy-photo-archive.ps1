[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$SourceRoot,

    [Parameter(Mandatory)]
    [string]$DestinationRoot,

    [Parameter(Mandatory)]
    [string]$LogPath
)

$ErrorActionPreference = 'Stop'

if (-not (Test-Path -LiteralPath $SourceRoot -PathType Container)) {
    throw "Source directory does not exist: $SourceRoot"
}

$sourceFullPath = [System.IO.Path]::GetFullPath((Resolve-Path -LiteralPath $SourceRoot).Path)
$destinationFullPath = [System.IO.Path]::GetFullPath($DestinationRoot)
$sourcePrefix = $sourceFullPath
if (-not $sourcePrefix.EndsWith([System.IO.Path]::DirectorySeparatorChar)) {
    $sourcePrefix += [System.IO.Path]::DirectorySeparatorChar
}

if ($destinationFullPath.Equals($sourceFullPath, [System.StringComparison]::OrdinalIgnoreCase) -or
    $destinationFullPath.StartsWith($sourcePrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw 'Destination directory must be outside the source directory.'
}

New-Item -ItemType Directory -Path $DestinationRoot -Force | Out-Null
$logDirectory = Split-Path -Path $LogPath -Parent
if ($logDirectory) {
    New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
}

$copied = 0
$skipped = 0
$conflicts = 0

try {
    $sourceFiles = Get-ChildItem -LiteralPath $SourceRoot -File -Recurse -Force
} catch {
    "$(Get-Date -Format s) fatal :: cannot enumerate source :: $($_.Exception.Message)" |
        Add-Content -LiteralPath $LogPath -Encoding utf8
    throw
}

$sourceFiles | ForEach-Object {
    $relativePath = $_.FullName.Substring($SourceRoot.Length).TrimStart('\')
    $destinationPath = Join-Path $DestinationRoot $relativePath
    $destinationFile = Get-Item -LiteralPath $destinationPath -ErrorAction SilentlyContinue

    if ($destinationFile) {
        $sourceHash = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash
        $destinationHash = (Get-FileHash -LiteralPath $destinationFile.FullName -Algorithm SHA256).Hash
        if ($sourceHash -eq $destinationHash) {
            $skipped++
        } else {
            "$(Get-Date -Format s) conflict=$relativePath :: destination file differs from source" |
                Add-Content -LiteralPath $LogPath -Encoding utf8
            $conflicts++
        }
        return
    }

    try {
        New-Item -ItemType Directory -Path (Split-Path -Path $destinationPath -Parent) -Force | Out-Null
        Copy-Item -LiteralPath $_.FullName -Destination $destinationPath
        $copied++
    } catch {
        "$(Get-Date -Format s) error=$relativePath :: $($_.Exception.Message)" |
            Add-Content -LiteralPath $LogPath -Encoding utf8
    }
}

"$(Get-Date -Format s) complete copied=$copied skipped=$skipped conflicts=$conflicts" |
    Add-Content -LiteralPath $LogPath -Encoding utf8
