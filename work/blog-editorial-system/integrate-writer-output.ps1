$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$writerRoot = Join-Path $repoRoot "work\blog-copywriter-output-v2"
$contentRoot = Join-Path $repoRoot "content\blog"
$articleRoot = Join-Path $contentRoot "articles"
$mediaRoot = Join-Path $contentRoot "media"
$manifestPath = Join-Path $contentRoot "manifest.json"

$sources = @(
    @{ Id = "13277231"; File = "13277231-skolko-vremeni-nuzhno-na-pohudenie.md"; Title = "Сколько времени нужно на похудение?"; Excerpt = "Ответ на вопрос о сроках либо поставит жирный крест на вашем похудении, либо заложит крепкий фундамент для изменений в жизни."; Alt = "Таблица для примерного расчёта сроков похудения при разном дефиците калорий" },
    @{ Id = "11401696"; File = "11401696-pohudenie-nachinaetsya-ne-s-pohudeniya.md"; Title = "Похудение начинается не с похудения"; Excerpt = "Надо сбросить 2, 5 или 25 килограммов? Неважно. Если это не получается легко и играючи, нужно менять подход."; Alt = "Схема привычного плана похудения: мотивация, диета, неизвестный этап и успех" },
    @{ Id = "11927800"; File = "11927800-pochemu-yapontsy-hudye-a-ty-net.md"; Title = "Почему японцы худые, а ты нет?"; Excerpt = "Когда заходит разговор о стройности японцев, первым делом вспоминают генетику. Удобное объяснение: им просто повезло, а нам — нет."; Alt = "Иллюстрация к сравнению пищевых привычек в Японии и России" },
    @{ Id = "11269472"; File = "11269472-temperatura-vody-dlya-priema-vnutr.md"; Title = "Температура воды для приёма внутрь"; Excerpt = "Это вообще-то важно. Короткая история и издевательски простой совет для сохранения здоровья."; Alt = "Два способа пить горячий напиток: торопясь и после остывания" },
    @{ Id = "12237133"; File = "12237133-samyy-zdorovyy-chelovek-na-planete.md"; Title = "Самый здоровый человек на планете"; Excerpt = "На фотографии — Брайан Джонсон. В 47 лет предприниматель называл себя самым здоровым человеком на планете и тратил огромные деньги на проект Blueprint: анализы, режим, оборудование и попытку замедлить старение."; Alt = "Брайан Джонсон и его проект Blueprint" },
    @{ Id = "11875492"; File = "11875492-nepriyatnaya-pravda-pro-med.md"; Title = "Неприятная правда про мёд"; Excerpt = "Стоит сказать, что мёд — в первую очередь сладость, как тут же начинаются возражения: «Зато в нём микроэлементы!» и «При умеренном употреблении от него только польза»."; Alt = "Спор о пользе мёда и умеренном употреблении" }
)

$manifest = Get-Content $manifestPath -Raw | ConvertFrom-Json

foreach ($source in $sources) {
    $raw = Get-Content (Join-Path $writerRoot $source.File) -Raw
    $body = [regex]::Replace($raw, "(?s)\A---\r?\n.*?\r?\n---\r?\n+", "")
    $imageMatches = [regex]::Matches($body, '!\[[^\]]*\]\((https://cs[^)]+)\)')
    $urls = @($imageMatches | ForEach-Object { $_.Groups[1].Value } | Select-Object -Unique)
    $articleMediaDir = Join-Path $mediaRoot $source.Id
    New-Item -ItemType Directory -Path $articleMediaDir -Force | Out-Null

    $mediaFiles = @()
    for ($index = 0; $index -lt $urls.Count; $index++) {
        $url = $urls[$index]
        $extension = [IO.Path]::GetExtension(([Uri]$url).AbsolutePath).ToLowerInvariant()
        if ($extension -notin @(".jpg", ".jpeg", ".png", ".webp", ".gif")) {
            throw "Unsupported blog image extension: $url"
        }
        $relativeFile = "{0}/{1:d2}{2}" -f $source.Id, ($index + 1), $extension
        $destination = Join-Path $mediaRoot $relativeFile
        Invoke-WebRequest -Uri $url -OutFile $destination -UseBasicParsing
        if ((Get-Item $destination).Length -eq 0) {
            throw "Downloaded empty blog image: $url"
        }
        $body = $body.Replace($url, "/blog/media/$relativeFile")
        $mediaFiles += $relativeFile
    }

    $entry = $manifest.articles | Where-Object { $_.source_id -eq $source.Id }
    if ($null -eq $entry) {
        throw "Manifest entry not found: $($source.Id)"
    }
    $entry.title = $source.Title
    $entry.excerpt = $source.Excerpt
    $entry.hero.file = $mediaFiles[0]
    $entry.hero.alt = $source.Alt
    $entry.hero.provenance = $urls[0]
    $entry.media = @($mediaFiles | Select-Object -Skip 1)

    # The first source image becomes the page hero and must not be duplicated in the body.
    $escapedHero = [regex]::Escape("/blog/media/$($mediaFiles[0])")
    $body = [regex]::Replace($body, "(?m)^!\[[^\]]*\]\($escapedHero\)\r?\n?", "", 1)

    $ctaBlock = "`n`nblog_cta(`n$($entry.cta)`n)`n"
    $sourcesHeading = "`n### Источники к проверяемым утверждениям"
    if ($body.Contains($sourcesHeading)) {
        $body = $body.Replace($sourcesHeading, "$ctaBlock$sourcesHeading")
    } else {
        $body = $body.TrimEnd() + $ctaBlock
    }
    [IO.File]::WriteAllText((Join-Path $articleRoot "$($source.Id).md"), $body.Trim() + "`n", [Text.UTF8Encoding]::new($false))
}

$json = $manifest | ConvertTo-Json -Depth 8
[IO.File]::WriteAllText($manifestPath, $json + "`n", [Text.UTF8Encoding]::new($false))
