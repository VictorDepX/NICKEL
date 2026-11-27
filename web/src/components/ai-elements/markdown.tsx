import { memo } from "react";
import type { ComponentProps } from "react";
import { Streamdown, defaultRehypePlugins, type StreamdownTranslations } from "streamdown";
import type { Pluggable } from "unified";
import { cn } from "@/lib/utils";

/** Rótulos dos controles do Streamdown (copiar código, tabelas, links) em português. */
export const STREAMDOWN_PT: Partial<StreamdownTranslations> = {
  close: "Fechar",
  copied: "Copiado",
  copyCode: "Copiar código",
  copyLink: "Copiar link",
  copyTable: "Copiar tabela",
  copyTableAsCsv: "Copiar como CSV",
  copyTableAsMarkdown: "Copiar como Markdown",
  copyTableAsTsv: "Copiar como TSV",
  downloadFile: "Baixar arquivo",
  downloadImage: "Baixar imagem",
  downloadTable: "Baixar tabela",
  downloadTableAsCsv: "Baixar como CSV",
  downloadTableAsMarkdown: "Baixar como Markdown",
  externalLinkWarning: "Este link abre fora do NICKEL.",
  imageNotAvailable: "Imagem indisponível",
  openExternalLink: "Abrir link externo",
  openLink: "Abrir link",
  exitFullscreen: "Sair da tela cheia",
  viewFullscreen: "Tela cheia",
};

/**
 * Imagens vindas da resposta do modelo não carregam: um `![x](https://…?d=segredo)` faria o navegador
 * buscar a URL (vazamento de dados). Só `data:` vira imagem; o resto vira um link "imagem: <url>".
 */
function SafeImage({ src, alt }: ComponentProps<"img">) {
  const url = typeof src === "string" ? src : "";
  if (url.startsWith("data:image/")) return <img src={url} alt={alt ?? ""} loading="lazy" />;
  if (!url) return <span>{alt ? `imagem: ${alt}` : "imagem"}</span>;
  return (
    <span>
      imagem:{" "}
      <a href={url} target="_blank" rel="noreferrer noopener">
        {alt || url}
      </a>
    </span>
  );
}

const COMPONENTS = { img: SafeImage };

/** Links bloqueados pelo harden viram só o texto (o padrão acrescentaria "[blocked]" em inglês). */
const REHYPE_PLUGINS: Pluggable[] = Object.entries(defaultRehypePlugins).map(([name, plugin]) => {
  if (name !== "harden" || !Array.isArray(plugin)) return plugin;
  return [plugin[0], { ...(plugin[1] as object), linkBlockPolicy: "text-only" }] as Pluggable;
});

export type MarkdownProps = Omit<React.ComponentProps<typeof Streamdown>, "children"> & { children: string };

export const Markdown = memo(
  ({ className, ...props }: MarkdownProps) => (
    <Streamdown
      className={cn(
        "size-full break-words [&>*:first-child]:mt-0 [&>*:last-child]:mb-0 [&_a]:text-ice [&_a]:underline-offset-2 [&_pre]:max-w-full [&_pre]:overflow-x-auto",
        className
      )}
      // Links vêm da própria resposta do NICKEL (local): abrem direto, sem o aviso do Streamdown.
      linkSafety={{ enabled: false }}
      translations={STREAMDOWN_PT}
      components={COMPONENTS}
      rehypePlugins={REHYPE_PLUGINS}
      {...props}
    />
  ),
  (prevProps, nextProps) => prevProps.children === nextProps.children
);
Markdown.displayName = "Markdown";

export default Markdown;
