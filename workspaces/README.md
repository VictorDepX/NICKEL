# Workspaces

Cada arquivo `.md` aqui é um workspace: um perfil de trabalho (o equivalente local de um Projeto do Claude) sobre o **mesmo modelo**. O nome do arquivo vira o identificador (`rpg-coc.md` → `/rpg-coc`).

Troque de workspace pelo WhatsApp, pela voz ou pela UI:

| Comando | Efeito |
|---|---|
| `/ws` | Lista os workspaces e mostra o ativo |
| `/rpg` | Ativa o workspace `rpg` (por id ou apelido) |
| `/rpg texto…` | Ativa e já envia a mensagem |
| `/ws rpg texto…` | Igual ao anterior |

O workspace fica ativo até você trocar. Cada um tem a própria conversa; a memória de preferências (`memory_*`) é global.

## Formato

```markdown
---
name: RPG CoC
description: Guardião de Chamado de Cthulhu 7e
aliases: [rpg, coc]
keywords: [investigador, sanidade, guardião]   # só vale com WORKSPACE_AUTO_ROUTE=true
tools: [notes_*]        # padrões fnmatch; omitido = todas as ferramentas; [] = nenhuma
backend: local          # local | cloud (RunPod, via LLM_CLOUD_*)
think: false            # raciocínio do modelo (mais lento, mais cuidadoso)
temperature: 0.8
max_tokens: 1500
history: 24             # mensagens de histórico enviadas ao modelo
notes_dir: 06 Pensamentos/RPG CoC   # pasta (dentro do vault) usada por notes_capture e notes_search
---
Instruções do workspace, em Markdown. Entram no system prompt, depois da persona base.
```

Todos os campos do frontmatter são opcionais. Edições nos arquivos valem na mensagem seguinte, sem reiniciar.

## Dica: editar pelo Obsidian

Aponte `WORKSPACES_DIR` para uma pasta dentro do vault (por exemplo `WORKSPACES_DIR=C:\Users\Pichau\Documents\Editora\NICKEL\Workspaces`). Assim você edita as instruções no Obsidian, e o Syncthing leva as mudanças para onde o NICKEL rodar.

## Os arquivos deste diretório são modelos

Substitua o corpo de cada um pelas instruções reais dos seus Projetos.
