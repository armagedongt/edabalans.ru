param(
    [string]$VaultRoot = 'D:\Codex\work\edabalans-materials',
    [string]$InstallRoot = 'D:\Codex\tools\edabalans-editorial'
)
$ErrorActionPreference = 'Stop'
$pythonPath = (Get-Command python).Source
$toolsRoot = Join-Path $InstallRoot 'tools'
[IO.Directory]::CreateDirectory($toolsRoot) | Out-Null
[IO.Directory]::CreateDirectory($VaultRoot) | Out-Null
foreach ($name in @('editorial_vault.py', 'editorial_vault_desktop.py', 'publish_course_material.py', 'editorial_bot_adapter.py', 'editorial_git_adapter.py', 'editorial_email_adapter.py', 'editorial_catalog_adapter.py', 'editorial_graph_adapter.py', 'editorial_pricing_adapter.py', 'connect_editorial_github.py')) {
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot $name) -Destination (Join-Path $toolsRoot $name)
}
$utf8 = New-Object System.Text.UTF8Encoding($false)
[IO.File]::WriteAllText((Join-Path $toolsRoot '__init__.py'), '', $utf8)
$repoRoot = Split-Path -Parent $PSScriptRoot
$rulesText = [IO.File]::ReadAllText((Join-Path $repoRoot 'docs/knowledge-base/EDITORIAL_VAULT.md'))
$homepageRulesPath = (Join-Path $repoRoot 'docs/knowledge-base/PUBLIC_SITE.md').Replace('\', '/')
$recipeRulesPath = (Join-Path $repoRoot 'content/masterclass/recipes/README.md').Replace('\', '/')
$operationsRulesPath = (Join-Path $repoRoot 'docs/OPERATIONS.md').Replace('\', '/')
$pricingRulesPath = (Join-Path $repoRoot 'docs/knowledge-base/PRICING_CATALOG.md').Replace('\', '/')
$rulesText = $rulesText.Replace('(PUBLIC_SITE.md)', '(<'+$homepageRulesPath+'>)').Replace('(../../content/masterclass/recipes/README.md)', '(<'+$recipeRulesPath+'>)').Replace('(PRICING_CATALOG.md)', '(<'+$pricingRulesPath+'>)').Replace('(../OPERATIONS.md#однократное-подключение-git-редактора)', '(<'+$operationsRulesPath+'#однократное-подключение-git-редактора>)')
[IO.File]::WriteAllText((Join-Path $VaultRoot 'Правила публикации.md'), $rulesText, $utf8)
$quickGuide = @'
# Как пользоваться

1. Открой эту папку в Obsidian как хранилище.
2. В «Каталог.md» выбери материал и отредактируй его. Сохрани файл.
3. Открой ярлык «Опубликовать материалы» на рабочем столе.
4. Выбери нужные изменения и нажми «Опубликовать выбранные».

Codex редактирует эти же файлы: достаточно назвать материал. Голосовая команда
«Опубликуй» запускает тот же публикатор. Остальные черновики не отправляются.
Обновление с сервера сохраняет твои правки; конфликт поможет объединить Codex.
Материалы со статусом «Публикация через Codex» требуют своего специального маршрута.
Новые картинки и изменение структуры курса пока выполняются через Codex.

Технические подробности и границы — [Правила публикации](<Правила публикации.md>).
'@
[IO.File]::WriteAllText((Join-Path $VaultRoot 'Как пользоваться.md'), $quickGuide, $utf8)
$instructions = @'
# Материалы сайта — одна рабочая папка

Эти файлы — редакционные оригиналы рабочих правок. Редактировать их здесь,
не копировать в Git/worktree. Публикация: единый tools.editorial_vault из
D:\Codex\tools\edabalans-editorial. Сначала Каталог.md и .publisher/state.json.
Правила и действующие границы — Правила публикации.md. Сервер хранит принятые
редакции; обновление не заменяет локальный черновик. Сохранять stable IDs.
Авторские правки выполнять через проектный Писарь. По команде публикации
отправлять только выбранные IDs, проверять каждый результат. Git/recipe
исключения выполняются через действующий маршрут Codex, не обычный PUT.
'@
[IO.File]::WriteAllText((Join-Path $VaultRoot 'AGENTS.md'), $instructions, $utf8)
& $pythonPath (Join-Path $PSScriptRoot 'install_editorial_example.py') $VaultRoot
if ($LASTEXITCODE -ne 0) { throw 'Не удалось установить пример Markdown' }
$desktop = [Environment]::GetFolderPath('Desktop')
$shell = New-Object -ComObject WScript.Shell
$publisher = $shell.CreateShortcut((Join-Path $desktop 'Опубликовать материалы.lnk'))
$pythonwPath = Join-Path (Split-Path -Parent $pythonPath) 'pythonw.exe'
if (-not (Test-Path -LiteralPath $pythonwPath)) { $pythonwPath = $pythonPath }
$publisher.TargetPath = $pythonwPath
$publisher.Arguments = '-m tools.editorial_vault_desktop --root "' + $VaultRoot + '"'
$publisher.WorkingDirectory = $InstallRoot
$publisher.Description = 'Выбрать и опубликовать изменённые материалы'
$publisher.Save()
$folder = $shell.CreateShortcut((Join-Path $desktop 'Материалы сайта.lnk'))
$folder.TargetPath = $VaultRoot
$folder.Description = 'Одна папка для Obsidian и Codex'
$folder.Save()
Write-Output "Клиент установлен: $InstallRoot"
Write-Output "Материалы: $VaultRoot"
