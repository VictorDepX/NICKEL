import test from "node:test";
import assert from "node:assert/strict";
import { renderMarkdown } from "../../nickel/ui/static/markdown.js";

test("negrito, itálico e código inline", () => {
  assert.equal(renderMarkdown("**Oi** *tudo* `x_y`"), "<p><strong>Oi</strong> <em>tudo</em> <code>x_y</code></p>");
});

test("lista com marcador * e negrito dentro", () => {
  assert.equal(
    renderMarkdown("Plano:\n*   **Frontend:** UI\n*   Backend"),
    "<p>Plano:</p><ul><li><strong>Frontend:</strong> UI</li><li>Backend</li></ul>",
  );
});

test("lista numerada, título e bloco de código", () => {
  assert.equal(
    renderMarkdown("## Fases\n1. A\n2. B\n```py\nprint('<b>')\n```"),
    '<p class="md-h">Fases</p><ol><li value="1">A</li><li value="2">B</li></ol><pre><code>print(&#39;&lt;b&gt;&#39;)</code></pre>',
  );
});

test("escapa HTML e preserva link com sublinhado", () => {
  assert.equal(
    renderMarkdown("<script>x</script> veja https://a.b/c_d_e."),
    '<p>&lt;script&gt;x&lt;/script&gt; veja <a href="https://a.b/c_d_e" target="_blank" rel="noopener">https://a.b/c_d_e</a>.</p>',
  );
});

test("parágrafos separados por linha em branco; quebra simples vira <br>", () => {
  assert.equal(renderMarkdown("a\nb\n\nc"), "<p>a<br>b</p><p>c</p>");
});
