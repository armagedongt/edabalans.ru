param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('approach', 'program', 'recipes', 'consultation', 'calories', 'training', 'faq')]
    [string]$Slug,
    [string]$HostAlias = 'edabalans-prod'
)

$ErrorActionPreference = 'Stop'
$utf8WithoutBom = New-Object System.Text.UTF8Encoding($false)
$OutputEncoding = $utf8WithoutBom
[Console]::OutputEncoding = $utf8WithoutBom
$repositoryRoot = Split-Path -Parent $PSScriptRoot
$contentPath = Join-Path $repositoryRoot "content/public-site/homepage/$Slug.md"
if (-not (Test-Path -LiteralPath $contentPath)) {
    throw "Не найден Markdown-документ: $contentPath"
}

$markdown = Get-Content -LiteralPath $contentPath -Raw -Encoding UTF8
$versionMatch = [regex]::Match($markdown, '^<!-- public-site-version: ([0-9]+) -->')
if (-not $versionMatch.Success) {
    throw "В начале $contentPath нет служебной строки public-site-version"
}
$expectedVersion = [int]$versionMatch.Groups[1].Value
$publishedVersion = $markdown |
    ssh $HostAlias "cd /opt/edabalans && docker compose exec -T backend python -m app.public_site_content_cli $Slug --expected-version $expectedVersion"
if ($LASTEXITCODE -ne 0) {
    throw "Публикация документа $Slug отклонена. Сначала получите актуальную редакцию и объедините изменения"
}
$publishedVersion = [int]($publishedVersion | Select-Object -Last 1)
$updatedMarkdown = [regex]::Replace(
    $markdown,
    '^<!-- public-site-version: [0-9]+ -->',
    "<!-- public-site-version: $publishedVersion -->",
    1
)
[IO.File]::WriteAllText($contentPath, $updatedMarkdown, $utf8WithoutBom)
Write-Output "Опубликована редакция $publishedVersion документа $Slug"
