<#
.SYNOPSIS
  Baixa o Gemma 4 26B-A4B (instruct) em GGUF (repositório bartowski) e, opcionalmente, o arquivo de visão (mmproj).
.DESCRIPTION
  IQ4_XS (~13,2 GB) é o padrão para 20 GB de RAM. Q4_K_M (~15,9 GB) deixa pouca RAM com o VoiceStudio aberto.
  O download pode ser retomado: rode o comando de novo se a conexão cair.
#>
param(
    [string]$Dest = "D:\models",
    [ValidateSet("IQ4_XS", "IQ4_NL", "Q4_K_S", "Q4_K_M", "IQ3_XXS", "IQ3_M")]
    [string]$Quant = "IQ4_XS",
    [switch]$WithVision
)
$ErrorActionPreference = "Stop"
$repo = "https://huggingface.co/bartowski/google_gemma-4-26B-A4B-it-GGUF/resolve/main"
New-Item -ItemType Directory -Force -Path $Dest | Out-Null

$files = @("google_gemma-4-26B-A4B-it-$Quant.gguf")
if ($WithVision) { $files += "mmproj-google_gemma-4-26B-A4B-it-f16.gguf" }

foreach ($name in $files) {
    $target = Join-Path $Dest $name
    Write-Host "Baixando $name ..."
    # curl.exe acompanha o Windows 10/11 e retoma downloads (-C -)
    & curl.exe -L -C - --fail -o $target "$repo/$name"
    if ($LASTEXITCODE -ne 0) { throw "Falha ao baixar $name (código $LASTEXITCODE)." }
    Write-Host ("  {0}: {1:N1} GB" -f $name, ((Get-Item $target).Length / 1GB)) -ForegroundColor Green
}
Write-Host "Modelo em $Dest. Próximo passo: scripts\windows\start-llama.ps1"
