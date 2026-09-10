// Minimal, dependency-free syntax highlighter for code slides.
// Single-pass tokeniser: patterns are tried in order, so comments and strings
// always win over keywords that appear inside them.
const esc = (s) =>
  s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

const KW = {
  js: "const|let|var|function|return|if|else|for|while|do|await|async|try|catch|finally|throw|new|class|extends|import|from|export|default|typeof|instanceof|delete|switch|case|break|continue|null|undefined|true|false|this|of|in",
  ts: "const|let|var|function|return|if|else|for|while|do|await|async|try|catch|finally|throw|new|class|extends|implements|interface|type|enum|import|from|export|default|typeof|instanceof|switch|case|break|continue|null|undefined|true|false|this|of|in|public|private|readonly",
  py: "def|return|if|elif|else|for|while|try|except|finally|raise|with|as|import|from|class|lambda|yield|async|await|pass|break|continue|and|or|not|is|in|None|True|False|global|nonlocal|assert",
  php: "function|return|if|elseif|else|foreach|for|while|try|catch|finally|throw|new|class|extends|implements|use|namespace|public|private|protected|static|const|echo|null|true|false|array|match|fn",
  sql: "SELECT|INSERT|UPDATE|DELETE|FROM|WHERE|JOIN|LEFT|RIGHT|INNER|OUTER|ON|GROUP|ORDER|BY|HAVING|LIMIT|OFFSET|VALUES|SET|INTO|CREATE|TABLE|INDEX|ALTER|DROP|BEGIN|COMMIT|ROLLBACK|AND|OR|NOT|NULL|AS|DISTINCT|UNION|WITH|RETURNING|CONFLICT|DO|NOTHING|UNIQUE|PRIMARY|KEY|FOR|SHARE",
  bash: "if|then|else|fi|for|in|do|done|while|case|esac|function|return|export|local|echo|exit|set|trap",
  go: "func|return|if|else|for|range|switch|case|default|break|continue|go|defer|select|chan|var|const|type|struct|interface|import|package|nil|true|false|map|make|new",
  json: "true|false|null",
};

const COMMENT = {
  js: /\/\/[^\n]*|\/\*[\s\S]*?\*\//,
  ts: /\/\/[^\n]*|\/\*[\s\S]*?\*\//,
  go: /\/\/[^\n]*|\/\*[\s\S]*?\*\//,
  php: /\/\/[^\n]*|#[^\n]*|\/\*[\s\S]*?\*\//,
  py: /#[^\n]*/,
  bash: /#[^\n]*/,
  sql: /--[^\n]*|\/\*[\s\S]*?\*\//,
  json: /(?!)/,
};

const STRING =
  /"""[\s\S]*?"""|'''[\s\S]*?'''|`(?:\\.|[^`\\])*`|"(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*'/;

export function highlight(code, lang = "js") {
  const key = KW[lang] ? lang : "js";
  const rules = [
    ["com", COMMENT[key] || COMMENT.js],
    ["str", STRING],
    ["num", /\b0x[\da-fA-F]+\b|\b\d[\d_]*(?:\.\d+)?(?:e[+-]?\d+)?\b/],
    ["kw", new RegExp(`\\b(?:${KW[key]})\\b`, key === "sql" ? "i" : "")],
    ["fn", /\b[A-Za-z_$][\w$]*(?=\s*\()/],
    ["prop", /(?<=\.)[A-Za-z_$][\w$]*\b/],
    ["op", /[=+\-*/%<>!&|^~?:]+/],
    ["punc", /[{}[\]();,.]/],
  ];
  const master = new RegExp(rules.map(([, r]) => `(${r.source})`).join("|"), "g");

  let out = "";
  let last = 0;
  for (let m; (m = master.exec(code)); ) {
    if (m.index > last) out += esc(code.slice(last, m.index));
    const gi = m.slice(1).findIndex((g) => g !== undefined);
    out += `<span class="t-${rules[gi][0]}">${esc(m[0])}</span>`;
    last = m.index + m[0].length;
    if (m[0].length === 0) master.lastIndex++; // guard against zero-width matches
  }
  out += esc(code.slice(last));
  return out;
}

export const TOKEN_CSS = ({ mono }) => `
  .code { font-family: "${mono}", ui-monospace, monospace; }
  .t-com  { color: #7d8ba6; font-style: italic; }
  .t-str  { color: #2f9e6e; }
  .t-num  { color: #c2762b; }
  .t-kw   { color: #7c4dd6; font-weight: 700; }
  .t-fn   { color: #2563eb; }
  .t-prop { color: #1d6fd0; }
  .t-op   { color: #5b6478; }
  .t-punc { color: #8a93a6; }
`;
