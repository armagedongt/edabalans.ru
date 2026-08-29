param(
    [int]$Port = 34567,
    [string]$SourceAssets = 'D:\сайт\Мастер-класс по изменению питания_files'
)

$ErrorActionPreference = 'Stop'

$dist = Join-Path $PSScriptRoot 'dist'
$assets = [IO.Path]::GetFullPath($SourceAssets)
$assetsPrefix = $assets.TrimEnd([IO.Path]::DirectorySeparatorChar, [IO.Path]::AltDirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar

if (-not [IO.Directory]::Exists($dist)) {
    & (Join-Path $PSScriptRoot 'build-previews.ps1')
}
if (-not [IO.Directory]::Exists($assets)) {
    throw "Source assets were not found: $assets"
}

$mime = @{
    '.css' = 'text/css; charset=utf-8'
    '.js' = 'text/javascript; charset=utf-8'
    '.html' = 'text/html; charset=utf-8'
    '.svg' = 'image/svg+xml'
    '.png' = 'image/png'
    '.jpg' = 'image/jpeg'
    '.jpeg' = 'image/jpeg'
    '.webp' = 'image/webp'
    '.woff' = 'font/woff'
    '.woff2' = 'font/woff2'
}

$listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, $Port)
$listener.Start()
Write-Output "Preview A: http://127.0.0.1:$Port/version-a"
Write-Output "Preview B: http://127.0.0.1:$Port/version-b"

try {
    while ($true) {
        $client = $listener.AcceptTcpClient()
        $stream = $client.GetStream()
        $reader = [IO.StreamReader]::new($stream, [Text.Encoding]::ASCII, $false, 1024, $true)
        $requestLine = $reader.ReadLine()
        while ($reader.ReadLine()) { }

        $rawTarget = ($requestLine -split ' ')[1]
        $route = [Uri]::UnescapeDataString(($rawTarget -split '\?')[0])
        $target = $null

        if ($route -like '/source-assets/tilda-forms-payments-1.0.min.js*') {
            $bytes = [Text.Encoding]::UTF8.GetBytes('/* Preview delegates checkout to the unchanged production Tilda order URL. */')
            $header = "HTTP/1.1 200 OK`r`nContent-Type: text/javascript; charset=utf-8`r`nContent-Length: $($bytes.Length)`r`nCache-Control: no-store`r`nConnection: close`r`n`r`n"
            $headerBytes = [Text.Encoding]::ASCII.GetBytes($header)
            $stream.Write($headerBytes, 0, $headerBytes.Length)
            $stream.Write($bytes, 0, $bytes.Length)
            $client.Close()
            continue
        }

        switch ($route) {
            '/version-a' { $target = Join-Path $dist 'version-a.html' }
            '/version-b' { $target = Join-Path $dist 'version-b.html' }
            default {
                if ($route.StartsWith('/source-assets/')) {
                    $relative = $route.Substring('/source-assets/'.Length)
                    $candidate = [IO.Path]::GetFullPath((Join-Path $assets $relative))
                    if ($candidate.StartsWith($assetsPrefix, [StringComparison]::OrdinalIgnoreCase)) {
                        $target = $candidate
                    }
                }
            }
        }

        if ($null -eq $target -or -not [IO.File]::Exists($target)) {
            $header = "HTTP/1.1 404 Not Found`r`nContent-Length: 0`r`nConnection: close`r`n`r`n"
            $headerBytes = [Text.Encoding]::ASCII.GetBytes($header)
            $stream.Write($headerBytes, 0, $headerBytes.Length)
            $client.Close()
            continue
        }

        $extension = [IO.Path]::GetExtension($target).ToLowerInvariant()
        $contentType = $mime[$extension] ?? 'application/octet-stream'
        $bytes = [IO.File]::ReadAllBytes($target)
        $header = "HTTP/1.1 200 OK`r`nContent-Type: $contentType`r`nContent-Length: $($bytes.Length)`r`nCache-Control: no-store`r`nConnection: close`r`n`r`n"
        $headerBytes = [Text.Encoding]::ASCII.GetBytes($header)
        $stream.Write($headerBytes, 0, $headerBytes.Length)
        $stream.Write($bytes, 0, $bytes.Length)
        $client.Close()
    }
} finally {
    $listener.Stop()
}
