<#
.SYNOPSIS
  Sobe o llama-server (llama.cpp, Vulkan) com o Gemma 4 26B-A4B para o NICKEL.
.DESCRIPTION
  O modelo é MoE: os pesos dos experts ficam na RAM e só atenção/camadas fixas ocupam a VRAM.
  -NCpuMoe 20 (padrão) mantém na RAM os experts das 20 primeiras camadas e leva o resto para a GPU.
  Medido numa RX 6600 8 GB + 20 GB RAM: ~19 tok/s de geração e ~126 tok/s de prefill, VRAM ~7,5 GB. Use -NCpuMoe -1 (--cpu-moe) se faltar VRAM.
  Sem mmap é o padrão (-Mmap liga). -NoMmap ainda é aceito, mas é obsoleto e não muda nada.
.EXAMPLE
  .\start-llama.ps1
  .\start-llama.ps1 -NCpuMoe 22 -Ctx 8192 -Vision
#>
param(
    [string]$LlamaDir = "$env:LOCALAPPDATA\llama.cpp",
    [string]$Model = "D:\models\google_gemma-4-26B-A4B-it-IQ4_XS.gguf",
    [string]$Mmproj = "D:\models\mmproj-google_gemma-4-26B-A4B-it-f16.gguf",
    [switch]$Vision,
    [int]$Ctx = 16384,
    [int]$Port = 8080,
    [string]$Alias = "gemma-4-26b-a4b",
    [int]$NCpuMoe = 20,
    [int]$Threads = 0,
    [switch]$KvQuant,
    [switch]$Mmap,
    [switch]$NoMmap  # obsoleto: sem mmap já é o padrão
)
$ErrorActionPreference = "Stop"
if ($NoMmap) { Write-Warning "-NoMmap está obsoleto e não muda nada: sem mmap já é o padrão (use -Mmap para ligar)." }

$server = Get-ChildItem -Path $LlamaDir -Recurse -Filter "llama-server.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $server) { throw "llama-server.exe não encontrado em $LlamaDir. Rode scripts\windows\get-llama.ps1 ou use -LlamaDir." }
if (-not (Test-Path $Model)) { throw "Modelo não encontrado: $Model. Rode scripts\windows\get-model.ps1." }

$serverArgs = @(
    "-m", $Model,
    "--alias", $Alias,
    "--host", "127.0.0.1",
    "--port", $Port,
    "-c", $Ctx,
    "-np", 1,                 # um slot só: o contexto inteiro vai para a conversa atual
    "-ngl", 99,
    "--flash-attn", "on",
    "--jinja"                 # necessário para chamada de ferramentas (tool calling)
)
if ($NCpuMoe -lt 0) { $serverArgs += "--cpu-moe" } else { $serverArgs += @("--n-cpu-moe", $NCpuMoe) }
if ($Threads -gt 0) { $serverArgs += @("-t", $Threads) }
if ($KvQuant) { $serverArgs += @("--cache-type-k", "q8_0", "--cache-type-v", "q8_0") }
# Sem mmap os experts ficam residentes na RAM; com mmap o Windows pagina do disco e o prefill despenca.
if (-not $Mmap) { $serverArgs += @("--load-mode", "none") }
if ($Vision) {
    if (-not (Test-Path $Mmproj)) { throw "mmproj não encontrado: $Mmproj. Rode get-model.ps1 -WithVision." }
    $serverArgs += @("--mmproj", $Mmproj)
}

Write-Host "llama-server: $($server.FullName)"
Write-Host ("Argumentos: " + ($serverArgs -join " "))
Write-Host "Aguarde 'server is listening'. O NICKEL usa http://127.0.0.1:$Port/v1 (LLM_PROVIDER=llamacpp)."
& $server.FullName @serverArgs
