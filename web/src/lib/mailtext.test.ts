// SPDX-License-Identifier: Apache-2.0
import { describe, expect, it } from "vitest";
import { classify, foldDiffs, type Fold, type Row } from "./mailtext";

describe("classify", () => {
  const table: [string, string | null][] = [
    ["diff --git a/x b/x", "dg"], ["index 1..2 100644", "dg"], ["new file mode 100644", "dg"],
    ["deleted file mode 100644", "dg"], ["old mode 100644", "dg"], ["new mode 100755", "dg"],
    ["similarity index 90%", "dg"], ["rename from a", "dg"], ["rename to b", "dg"],
    ["--- a/x", "df"], ["+++ b/x", "df"], ["+++ /dev/null", "df"],
    ["@@ -1,2 +1,3 @@ fn()", "dh"],
    ["+added", "da"], ["+", "da"], ["++x", null],
    ["-removed", "dd"], ["--x", null], ["-- ", null],
    ["> one", "q1"], [">one", "q1"], ["> > two", "q2"], [">>two", "q2"],
    ["> > > three", "q3"], [">>>>x", "q3"], ["> +quoted diff", "q1"],
    ["Signed-off-by: A <a@b>", "tr"], ["Reviewed-by: A", "tr"], ["Acked-by: A", "tr"],
    ["Tested-by: A", "tr"], ["Reported-by: A", "tr"], ["Co-developed-by: A", "tr"],
    ["Suggested-by: A", "tr"], ["Reported-and-tested-by: A", "tr"],
    ["Fixes: abc", "tf"], ["Cc: a@b", "tf"], ["Link: http://x", "tf"], ["Closes: x", "tf"], ["BugLink: x", "tf"],
    ["plain text", null], ["", null], [" context", null],
  ];
  it.each(table)("%j -> %s", (line, cls) => expect(classify(line)).toBe(cls));
  it("+++ is df, not da; --- is df, not dd", () => {
    expect(classify("+++ b/f")).toBe("df");
    expect(classify("--- a/f")).toBe("df");
  });
});

describe("foldDiffs", () => {
  const diff = (n: number) => ["diff --git a/x b/x", ...Array.from({ length: n - 1 }, (_, i) => `+l${i}`)];
  it("leaves a block of exactly max lines alone", () => {
    const r = foldDiffs(diff(60));
    expect(r).toHaveLength(60);
    expect(r.some((x) => "fold" in x)).toBe(false);
  });
  it("folds the rest of a block of max+1 lines", () => {
    const r = foldDiffs(diff(61));
    expect(r).toHaveLength(61);
    expect(r[60]).toEqual({ fold: 1, at: 60 });
  });
  it("keeps text before and after, ends the block at non-diff text", () => {
    const lines = ["intro", ...diff(100), "-- ", "2.39", "tail"];
    const r = foldDiffs(lines, 60);
    expect(r[0]).toEqual({ line: "intro", cls: null });
    expect(r[61]).toEqual({ fold: 40, at: 61 });
    expect((r[62] as Row).line).toBe("-- ");
    expect(r).toHaveLength(61 + 1 + 3);
  });
  it("keeps blank and context lines inside a block, and folds two blocks separately", () => {
    const lines = [...diff(3), "", " ctx", "+x", "text", ...diff(70)];
    const r = foldDiffs(lines, 60);
    expect(r.slice(0, 6).every((x) => "line" in x)).toBe(true);
    expect((r[6] as Row).line).toBe("text");
    expect(r.filter((x): x is Fold => "fold" in x)).toEqual([{ fold: 10, at: lines.length - 10 }]);
  });
  it("does not fold plain text, however long", () => {
    expect(foldDiffs(Array.from({ length: 200 }, () => "hi"))).toHaveLength(200);
  });
});
