import { memo } from "react";
import { Streamdown, type StreamdownTranslations } from "streamdown";
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
      {...props}
    />
  ),
  (prevProps, nextProps) => prevProps.children === nextProps.children
);
Markdown.displayName = "Markdown";

export default Markdown;
