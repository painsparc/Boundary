# Run this in your target directory on the X: drive
$baseDir = Get-Location

# 1. Define the minimal folder structure
$folders = @(
    "data\input",
    "data\output",
    "logs",
    "src"
)

# 2. Create the folders
foreach ($folder in $folders) {
    $targetPath = Join-Path $baseDir $folder
    New-Item -Path $targetPath -ItemType Directory -Force | Out-Null
    Write-Host "Created folder: $targetPath" -ForegroundColor Green
}

# 3. Create the 2 minimal Python files in the src directory
$srcDir = Join-Path $baseDir "src"
New-Item -Path (Join-Path $srcDir "config.py") -ItemType File -Force | Out-Null
New-Item -Path (Join-Path $srcDir "main.py") -ItemType File -Force | Out-Null
Write-Host "Created config.py and main.py in the src folder." -ForegroundColor Green

Write-Host "Workspace scaffolded successfully. Ready to code." -ForegroundColor Cyan