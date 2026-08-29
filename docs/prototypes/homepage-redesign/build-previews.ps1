param(
    [string]$SourceHtml = 'D:\сайт\Мастер-класс по изменению питания.html',
    [string]$OutputDirectory = (Join-Path $PSScriptRoot 'dist')
)

$ErrorActionPreference = 'Stop'

$sourcePath = [IO.Path]::GetFullPath($SourceHtml)
if (-not [IO.File]::Exists($sourcePath)) {
    throw "Source HTML was not found: $sourcePath"
}

[IO.Directory]::CreateDirectory($OutputDirectory) | Out-Null

$source = [IO.File]::ReadAllText($sourcePath)
$sourceAssetPrefix = './Мастер-класс по изменению питания_files/'
$source = $source.Replace($sourceAssetPrefix, '/source-assets/')
$source = [regex]::Replace(
    $source,
    '<script[^>]+src="/source-assets/tilda-forms-payments-1\.0\.min\.js[^\"]*"[^>]*></script>',
    '',
    [Text.RegularExpressions.RegexOptions]::IgnoreCase
)
$analyticsPattern = 'mc\.yandex\.ru|ym\(97331502|top-fwz1\.mail\.ru|_tmr|VK-RTRG|tildastat|tilda-stat-1\.0|topmailru-code|tmr-code|/tag\.js|/openapi\.js'
$source = [regex]::Replace(
    $source,
    '<script\b[^>]*>[\s\S]*?</script>',
    {
        param($match)
        if ($match.Value -match $analyticsPattern) { return '' }
        return $match.Value
    },
    [Text.RegularExpressions.RegexOptions]::IgnoreCase
)
$source = [regex]::Replace(
    $source,
    '<noscript\b[^>]*>[\s\S]*?</noscript>',
    {
        param($match)
        if ($match.Value -match $analyticsPattern) { return '' }
        return $match.Value
    },
    [Text.RegularExpressions.RegexOptions]::IgnoreCase
)

$commonCss = [IO.File]::ReadAllText((Join-Path $PSScriptRoot 'common.css'))
$previewJs = [IO.File]::ReadAllText((Join-Path $PSScriptRoot 'preview.js'))

foreach ($variant in @('a', 'b')) {
    $variantCss = [IO.File]::ReadAllText((Join-Path $PSScriptRoot "version-$variant.css"))
    $html = $source.Replace(
        '</head>',
        "<style data-redesign-common>$commonCss</style><style data-redesign-variant>$variantCss</style></head>"
    )

    if ($html -match '<body[^>]*class="') {
        $html = [regex]::Replace(
            $html,
            '(<body[^>]*class=")([^"]*)',
            "`$1`$2 eb-version-$variant",
            1
        )
    } else {
        $replacement = '<body$1 class="eb-version-{0}">' -f $variant
        $html = [regex]::Replace($html, '<body([^>]*)>', $replacement, 1)
    }

    $html = $html.Replace('</body>', "<script data-redesign-preview>$previewJs</script></body>")
    $target = Join-Path $OutputDirectory "version-$variant.html"
    [IO.File]::WriteAllText($target, $html, [Text.UTF8Encoding]::new($false))
    Write-Output $target
}
