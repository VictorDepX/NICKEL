<#
.SYNOPSIS
  Mede tokens/s de prompt e de geração do llama-server em execução, e a RAM livre antes e depois.
.DESCRIPTION
  Rode start-llama.ps1 numa janela e este script em outra. Faz duas requisições: prompt curto e prompt longo.
  Use os números para ajustar -NCpuMoe e -Ctx (veja docs/deploy/local-windows-llamacpp.md).
#>
param(
    [int]$Port = 8080,
    [string]$Model = "gemma-4-26b-a4b",
    [int]$LongPromptWords = 1500,
    [int]$GenerateTokens = 128
)
$ErrorActionPreference = "Stop"
$url = "http://127.0.0.1:$Port"

function Get-FreeGB { [math]::Round((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory / 1MB, 1) }

try { Invoke-RestMethod -Uri "$url/health" -TimeoutSec 5 | Out-Null }
catch { throw "llama-server não respondeu em $url. Rode start-llama.ps1 e espere carregar." }

function Invoke-Case([string]$label, [string]$prompt) {
    $body = @{
        model = $Model
        messages = @(@{ role = "user"; content = $prompt })
        max_tokens = $GenerateTokens
        temperature = 0.3
        chat_template_kwargs = @{ enable_thinking = $false }
    } | ConvertTo-Json -Depth 6
    $watch = [Diagnostics.Stopwatch]::StartNew()
    $response = Invoke-RestMethod -Uri "$url/v1/chat/completions" -Method Post -Body $body -ContentType "application/json; charset=utf-8" -TimeoutSec 900
    $watch.Stop()
    $usage = $response.usage
    Write-Host ("[{0}] {1:N1}s total | prompt {2} tok | gerou {3} tok" -f $label, $watch.Elapsed.TotalSeconds, $usage.prompt_tokens, $usage.completion_tokens)
    if ($response.timings) {
        Write-Host ("      prefill {0:N1} tok/s | geração {1:N1} tok/s" -f $response.timings.prompt_per_second, $response.timings.predicted_per_second)
    } else {
        Write-Host "      (o servidor não devolveu 'timings'; calcule: geração ≈ tokens gerados / tempo total, sem o prefill)"
    }
}

Write-Host "RAM livre antes: $(Get-FreeGB) GB"
Invoke-Case "curto" "Explique em três frases o que é um lembrete recorrente."
$filler = ("O investigador examinou o porão da casa com cuidado. " * [math]::Ceiling($LongPromptWords / 8))
Invoke-Case "longo" ($filler + "`nResuma o trecho acima em duas frases.")
Write-Host "RAM livre depois: $(Get-FreeGB) GB"
Write-Host "Se a RAM livre ficar abaixo de ~2 GB ou a geração cair muito, use uma quantização menor ou -Ctx menor."
