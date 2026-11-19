<#
.SYNOPSIS
  Baixa o llama.cpp (build Vulkan para Windows x64) da última release e extrai em -Dest.
.NOTES
  O nome do asset é procurado por padrão (bin-win-vulkan-x64.zip). Se a release mudar o nome,
  o script lista os assets do Windows para você escolher o certo e baixar à mão.
#>
param(
    [string]$Dest = "$env:LOCALAPPDATA\llama.cpp"
)
$ErrorActionPreference = "Stop"

Write-Host "Consultando a última release do llama.cpp..."
$release = Invoke-RestMethod -Uri "https://api.github.com/repos/ggml-org/llama.cpp/releases/latest" -Headers @{ "User-Agent" = "nickel" }
$asset = $release.assets | Where-Object { $_.name -match "bin-win-vulkan-x64\.zip$" } | Select-Object -First 1
if (-not $asset) {
    Write-Host "Não achei o build Vulkan x64. Assets do Windows nesta release ($($release.tag_name)):" -ForegroundColor Yellow
    $release.assets | Where-Object { $_.name -match "win" } | ForEach-Object { Write-Host "  $($_.name)" }
    throw "Baixe o zip Vulkan manualmente e extraia em $Dest."
}

New-Item -ItemType Directory -Force -Path $Dest | Out-Null
$zip = Join-Path $env:TEMP $asset.name
Write-Host "Baixando $($asset.name) ($([math]::Round($asset.size / 1MB)) MB)..."
Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $zip
Expand-Archive -Path $zip -DestinationPath $Dest -Force
Remove-Item $zip

$server = Get-ChildItem -Path $Dest -Recurse -Filter "llama-server.exe" | Select-Object -First 1
if (-not $server) { throw "llama-server.exe não encontrado em $Dest." }
Write-Host "Pronto: $($server.FullName)" -ForegroundColor Green
Write-Host "Use -LlamaDir '$($server.DirectoryName)' em start-llama.ps1 se ele não for achado sozinho."
