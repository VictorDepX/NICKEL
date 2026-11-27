// Compartilhado entre Início e Conversa (fora da rota, para a Conversa carregar sob demanda).

export const MESSAGES_KEY = ["messages"] as const;

// "Pensar" tem três estados, como na interface antiga: true/false depois que o usuário mexe;
// null enquanto não mexe, e aí o servidor decide (workspace ativo ou LLM_THINK).
const THINK_KEY = "nickel.think";

export function readThink(): boolean | null {
  try {
    const stored = localStorage.getItem(THINK_KEY);
    return stored === "1" ? true : stored === "0" ? false : null;
  } catch {
    return null;
  }
}

export function writeThink(value: boolean) {
  try {
    localStorage.setItem(THINK_KEY, value ? "1" : "0");
  } catch {
    /* sem armazenamento: vale só nesta sessão */
  }
}
