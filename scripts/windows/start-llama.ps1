<#
.SYNOPSIS
  Sobe o llama-server (llama.cpp, Vulkan) com o Qwen3.6-35B-A3B para o NICKEL.
.DESCRIPTION
  O modelo é MoE: os pesos dos experts ficam na RAM e só atenção/camadas fixas ocupam a VRAM.
  -NCpuMoe -1 (padrão) manda TODOS os experts para a RAM (--cpu-moe): é o ponto de partida seguro para 8 GB.
  Se sobrar VRAM, reduza o valor (ex.: -NCpuMoe 30) para trazer camadas de volta à GPU e acelerar;
  se faltar VRAM ou RAM, aumente o contexto menos ou troque a quantização.
.EXAMPLE
  .\start-llama.ps1
  .\start-llama.ps1 -NCpuMoe 30 -Ctx 8192 -Vision
#>
param(
    [string]$LlamaDir = "$env:LOCALAPPDATA\llama.cpp",
    [string]$Model = "$env:USERPROFILE\models\Qwen_Qwen3.6-35B-A3B-IQ4_XS.gguf",
    [string]$Mmproj = "$env:USERPROFILE\models\mmproj-Qwen_Qwen3.6-35B-A3B-f16.gguf",
    [switch]$Vision,
    [int]$Ctx = 16384,
    [int]$Port = 8080,
    [string]$Alias = "qwen3.6-35b-a3b",
    [int]$NCpuMoe = -1,
    [int]$Threads = 0,
    [switch]$KvQuant,
    [switch]$NoMmap
)
$ErrorActionPreference = "Stop"

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
if ($NoMmap) { $serverArgs += "--no-mmap" }
if ($Vision) {
    if (-not (Test-Path $Mmproj)) { throw "mmproj não encontrado: $Mmproj. Rode get-model.ps1 -WithVision." }
    $serverArgs += @("--mmproj", $Mmproj)
}

Write-Host "llama-server: $($server.FullName)"
Write-Host ("Argumentos: " + ($serverArgs -join " "))
Write-Host "Aguarde 'server is listening'. O NICKEL usa http://127.0.0.1:$Port/v1 (LLM_PROVIDER=llamacpp)."
& $server.FullName @serverArgs
