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
});
