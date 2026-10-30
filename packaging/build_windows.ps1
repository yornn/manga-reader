# Builds the portable Windows folder, checks it with --self-test and zips it.
$ErrorActionPreference = "Stop"

python -m pip install -e ".[dev]"
python -m PyInstaller packaging/mangareader.spec --noconfirm
if ($LASTEXITCODE -ne 0) { exit 1 }

$version = python -c "import mangareader; print(mangareader.__version__)"
$data = Join-Path ([IO.Path]::GetTempPath()) "mangareader-selftest"
if (Test-Path $data) { Remove-Item -Recurse -Force $data }
$env:MANGAREADER_DATA = $data
$proc = Start-Process -FilePath "dist\MangaReader\MangaReader.exe" -ArgumentList "--self-test" -Wait -PassThru
Remove-Item Env:MANGAREADER_DATA
Get-Content (Join-Path $data "logs\selftest.log")
if ($proc.ExitCode -ne 0) {
    Write-Error "Self-test failed with exit code $($proc.ExitCode)"
    exit 1
}
if (Test-Path "dist\MangaReader\data") { Remove-Item -Recurse -Force "dist\MangaReader\data" }

Compress-Archive -Path "dist\MangaReader" -DestinationPath "MangaReader-$version-win64.zip" -Force
Write-Output "Built MangaReader-$version-win64.zip"
