import { render, screen } from "@testing-library/react";
import { lazy, Suspense, type ReactElement } from "react";
import { MemoryRouter, type RouteObject } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { PAGE_CHUNKS, routes } from "./routes";
import { AppShell } from "./shell/AppShell";
import { PageFallback } from "./shell/PageFallback";

const LAZY = Symbol.for("react.lazy");
const PAGES = routes[0].children as RouteObject[];

function route(path: string): RouteObject {
  const found = PAGES.find((child) => child.path === path);
  if (found === undefined) {
    throw new Error(`missing route ${path}`);
  }
  return found;
}

describe("DS-07 路由懒加载", () => {
  it("每个页面都是 React.lazy 组件", () => {
    for (const chunk of Object.values(PAGE_CHUNKS)) {
      expect((chunk as unknown as { $$typeof: symbol }).$$typeof).toBe(LAZY);
    }
  });

  it("AppShell 留在入口块，页面挂在 Suspense 下", () => {
    expect(routes[0].element).toBeTruthy();
    expect((routes[0].element as ReactElement).type).toBe(AppShell);

    for (const path of ["market", "stocks/:ticker", "workbench", "reports/:reportId"]) {
      const element = route(path).element;
      expect(element).toBeTruthy();
      expect((element as ReactElement).type).toBe(Suspense);
    }
  });

  it("进入 /market 才挂载该页块", async () => {
    render(<MemoryRouter>{route("market").element}</MemoryRouter>);

    expect(await screen.findByTestId("page-market")).toBeInTheDocument();
  });

  it("块未就绪时显示页面骨架而不是空白", () => {
    const NeverResolves = lazy(
      () => new Promise<{ default: () => null }>(() => undefined),
    );
    render(
      <Suspense fallback={<PageFallback />}>
        <NeverResolves />
      </Suspense>,
    );

    const fallback = screen.getByTestId("route-fallback");
    expect(fallback).toHaveAttribute("aria-busy", "true");
  });
});
