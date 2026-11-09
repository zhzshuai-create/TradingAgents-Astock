import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ReportMarkdown } from "./ReportMarkdown";

function renderMarkdown(markdown: string): HTMLElement {
  return render(<ReportMarkdown>{markdown}</ReportMarkdown>).container;
}

describe("ReportMarkdown", () => {
  it("renders bold markers that CommonMark leaves literal next to CJK punctuation", () => {
    const container = renderMarkdown(
      [
        "属于**“挤压（squeeze）”形态**。",
        "",
        "处于**「首板放量后第二波：接力资金减弱、主力减仓」**的博弈状态。",
        "",
        '这在A股游资语言里叫**"放量滞涨"**——是典型的**接力资金撤退、获利盘兑现**信号。',
      ].join("\n"),
    );

    expect(container.textContent).not.toContain("**");
    const strongs = container.querySelectorAll("strong");
    expect(strongs).toHaveLength(4);
    expect(strongs[0].textContent).toBe("“挤压（squeeze）”形态");
    expect(strongs[1].textContent).toBe(
      "「首板放量后第二波：接力资金减弱、主力减仓」",
    );
    expect(strongs[2].textContent).toBe('"放量滞涨"');
    expect(strongs[3].textContent).toBe("接力资金撤退、获利盘兑现");
  });

  it("repairs bold inside desktop table cells", () => {
    const container = renderMarkdown(
      "| 项目 | 结论 |\n| --- | --- |\n| 量价 | 属于**“量价背离”**。 |",
    );

    expect(container.textContent).not.toContain("**");
    expect(container.querySelector("table")).not.toBeNull();
    expect(container.querySelector("td strong")?.textContent).toBe(
      "“量价背离”",
    );
  });

  it("leaves well-formed emphasis and inline code untouched", () => {
    const container = renderMarkdown("这是**正常加粗**，而 `**x**` 保持原样。");

    const strongs = container.querySelectorAll("strong");
    expect(strongs).toHaveLength(1);
    expect(strongs[0].textContent).toBe("正常加粗");
    expect(container.querySelector("code")?.textContent).toBe("**x**");
  });

  it("keeps unmatched delimiters literal", () => {
    const container = renderMarkdown("单位 ** 表示乘法。");

    expect(container.querySelectorAll("strong")).toHaveLength(0);
    expect(container.textContent).toContain("**");
  });
});
