import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import {
  Badge,
  Button,
  Dialog,
  Drawer,
  EmptyState,
  Skeleton,
  Toast,
} from "./index";

function DialogHarness() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button onClick={() => setOpen(true)}>打开对话框</Button>
      <Dialog open={open} title="确认操作" onClose={() => setOpen(false)}>
        对话框内容
      </Dialog>
    </>
  );
}

function DrawerHarness() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button onClick={() => setOpen(true)}>打开抽屉</Button>
      <Drawer open={open} title="任务筛选" onClose={() => setOpen(false)}>
        抽屉内容
      </Drawer>
    </>
  );
}

function DialogWithFooterHarness() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button onClick={() => setOpen(true)}>打开对话框</Button>
      <Dialog
        open={open}
        title="确认操作"
        onClose={() => setOpen(false)}
        footer={<Button onClick={() => setOpen(false)}>确认</Button>}
      >
        对话框内容
      </Dialog>
    </>
  );
}

function DrawerWithFooterHarness() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button onClick={() => setOpen(true)}>打开抽屉</Button>
      <Drawer
        open={open}
        title="任务筛选"
        onClose={() => setOpen(false)}
        footer={<Button onClick={() => setOpen(false)}>应用</Button>}
      >
        抽屉内容
      </Drawer>
    </>
  );
}

describe("WEB-02 UI 基础组件", () => {
  it("Button 渲染并响应点击", async () => {
    const user = userEvent.setup();
    const onClick = vi.fn();
    render(<Button onClick={onClick}>开始分析</Button>);
    await user.click(screen.getByRole("button", { name: "开始分析" }));
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("Badge 渲染文案与圆点", () => {
    const { container } = render(
      <Badge tone="success" dot>
        已完成
      </Badge>,
    );
    expect(screen.getByText("已完成")).toBeInTheDocument();
    expect(container.querySelector('[aria-hidden="true"]')).not.toBeNull();
  });

  it("Skeleton 只作为装饰，不进入无障碍树", () => {
    const { container } = render(<Skeleton width={120} height={16} />);
    const node = container.firstElementChild;
    expect(node).toHaveAttribute("aria-hidden", "true");
    expect(node).toHaveStyle({ width: "120px", height: "16px" });
  });

  it("EmptyState 渲染标题、说明与操作", () => {
    render(
      <EmptyState
        title="还没有分析任务"
        description="从工作台发起一次分析。"
        action={<Button>去工作台</Button>}
      />,
    );
    expect(screen.getByRole("heading", { name: "还没有分析任务" })).toBeVisible();
    expect(screen.getByText("从工作台发起一次分析。")).toBeVisible();
    expect(screen.getByRole("button", { name: "去工作台" })).toBeVisible();
  });

  it("Toast 渲染并可手动关闭", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(
      <Toast
        open
        title="已保存"
        description="筛选条件已更新。"
        durationMs={0}
        onClose={onClose}
      />,
    );
    expect(screen.getByRole("status")).toHaveTextContent("已保存");
    await user.click(screen.getByRole("button", { name: "关闭提示" }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("Dialog 打开后焦点进入容器，Esc 关闭并还原焦点", async () => {
    const user = userEvent.setup();
    render(<DialogHarness />);
    const opener = screen.getByRole("button", { name: "打开对话框" });
    opener.focus();

    await user.click(opener);
    const dialog = screen.getByRole("dialog", { name: "确认操作" });
    expect(dialog.contains(document.activeElement)).toBe(true);

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.activeElement).toBe(opener);
  });

  it("Drawer 打开后焦点进入容器，Esc 关闭并还原焦点", async () => {
    const user = userEvent.setup();
    render(<DrawerHarness />);
    const opener = screen.getByRole("button", { name: "打开抽屉" });
    opener.focus();

    await user.click(opener);
    const drawer = screen.getByRole("dialog", { name: "任务筛选" });
    expect(drawer.contains(document.activeElement)).toBe(true);

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.activeElement).toBe(opener);
  });

  it("Drawer 锁住 body 与 data-scroll-lock 容器并恢复原值", async () => {    const user = userEvent.setup();
    const scroller = document.createElement("div");
    scroller.setAttribute("data-scroll-lock", "");
    scroller.style.overflow = "auto";
    document.body.appendChild(scroller);
    const previousBody = document.body.style.overflow;
    render(<DrawerHarness />);

    await user.click(screen.getByRole("button", { name: "打开抽屉" }));
    expect(document.body.style.overflow).toBe("hidden");
    expect(scroller.style.overflow).toBe("hidden");

    await user.keyboard("{Escape}");
    expect(document.body.style.overflow).toBe(previousBody);
    expect(scroller.style.overflow).toBe("auto");
    scroller.remove();
  });

  it("KB-06 Dialog 的 Tab 正向与反向都在容器内循环，Escape 归还原焦点", async () => {
    const user = userEvent.setup();
    render(<DialogWithFooterHarness />);
    const opener = screen.getByRole("button", { name: "打开对话框" });
    opener.focus();

    await user.click(opener);
    const close = screen.getByRole("button", { name: "关闭对话框" });
    const confirm = screen.getByRole("button", { name: "确认" });
    expect(close).toHaveFocus();

    await user.tab();
    expect(confirm).toHaveFocus();
    await user.tab();
    expect(close).toHaveFocus();
    await user.tab({ shift: true });
    expect(confirm).toHaveFocus();
    await user.tab({ shift: true });
    expect(close).toHaveFocus();

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(opener).toHaveFocus();
  });

  it("KB-07 Drawer 的 Tab 循环、Escape 与滚动锁恢复", async () => {
    const user = userEvent.setup();
    const scroller = document.createElement("div");
    scroller.setAttribute("data-scroll-lock", "");
    scroller.style.overflow = "auto";
    document.body.appendChild(scroller);
    const previousBody = document.body.style.overflow;
    render(<DrawerWithFooterHarness />);
    const opener = screen.getByRole("button", { name: "打开抽屉" });
    opener.focus();

    await user.click(opener);
    const close = screen.getByRole("button", { name: "关闭抽屉" });
    const apply = screen.getByRole("button", { name: "应用" });
    expect(close).toHaveFocus();

    await user.tab();
    expect(apply).toHaveFocus();
    await user.tab();
    expect(close).toHaveFocus();
    await user.tab({ shift: true });
    expect(apply).toHaveFocus();

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(opener).toHaveFocus();
    expect(document.body.style.overflow).toBe(previousBody);
    expect(scroller.style.overflow).toBe("auto");
    scroller.remove();
  });
});
