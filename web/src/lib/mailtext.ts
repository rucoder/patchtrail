// SPDX-License-Identifier: Apache-2.0
// Line classes for mail bodies, following src/patchtrail/data/neomuttrc.
const DG = /^(diff --git |index |new file mode|deleted file mode|old mode|new mode|similarity index|rename from|rename to)/;
const TR = /^(Signed-off-by|Reviewed-by|Acked-by|Tested-by|Reported-by|Co-developed-by|Suggested-by|Reported-and-tested-by):/;
const TF = /^(Fixes|Cc|Link|Closes|BugLink):/;

export function classify(line: string): string | null {
  if (DG.test(line)) return "dg";
  if (/^(---|\+\+\+) /.test(line)) return "df";
  if (/^@@ .* @@/.test(line)) return "dh";
  if (/^\+([^+]|$)/.test(line)) return "da";
  if (/^-[^-]/.test(line)) return "dd";
  if (/^> ?> ?>/.test(line)) return "q3";
  if (/^> ?>/.test(line)) return "q2";
  if (line.startsWith(">")) return "q1";
  if (TR.test(line)) return "tr";
  if (TF.test(line)) return "tf";
  return null;
}

export type Row = { line: string; cls: string | null };
export type Fold = { fold: number; at: number };

const isDiffLine = (l: string) => {
  const c = classify(l);
  return (c !== null && c.startsWith("d")) || l.startsWith(" ") || l.startsWith("\\ ");
};

/** Keep the first `max` lines of each diff block, then one fold marker for the rest. */
export function foldDiffs(lines: string[], max = 60): (Row | Fold)[] {
  const out: (Row | Fold)[] = [];
  let i = 0;
  while (i < lines.length) {
    if (!lines[i].startsWith("diff --git ")) {
      out.push({ line: lines[i], cls: classify(lines[i]) });
      i++;
      continue;
    }
    let end = i + 1;
    for (; end < lines.length; end++) {
      if (isDiffLine(lines[end])) continue;
      if (lines[end] === "") { // a blank line stays in the block if the diff goes on after it
        let k = end;
        while (k < lines.length && lines[k] === "") k++;
        if (k < lines.length && isDiffLine(lines[k])) { end = k - 1; continue; }
      }
      break;
    }
    const n = end - i;
    const keep = n > max ? max : n;
    for (let j = i; j < i + keep; j++) out.push({ line: lines[j], cls: classify(lines[j]) });
    if (n > max) out.push({ fold: n - max, at: i + max });
    i = end;
  }
  return out;
}
