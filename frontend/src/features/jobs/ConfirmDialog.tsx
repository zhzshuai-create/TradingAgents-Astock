import { Button, Dialog } from "../../ui";

interface ConfirmDialogProps {
  open: boolean;
  busy: boolean;
  onClose: () => void;
  onConfirm: () => void;
}

export function ConfirmDialog({
  open,
  busy,
  onClose,
  onConfirm,
}: ConfirmDialogProps) {
  return (
    <Dialog
      open={open}
      title="确认取消任务？"
      fullscreenOnMobile
      onClose={busy ? () => undefined : onClose}
      footer={
        <>
          <Button
            data-autofocus
            data-testid="job-cancel-dismiss"
            disabled={busy}
            onClick={onClose}
          >
            不取消
          </Button>
          <Button
            variant="danger"
            data-testid="job-cancel-confirm"
            disabled={busy}
            onClick={onConfirm}
          >
            {busy ? "取消中…" : "确认取消"}
          </Button>
        </>
      }
    >
      <div data-testid="job-cancel-dialog">
        <p>取消后任务会停在当前阶段，已产生的模型费用不退，且不会生成完整报告。</p>
      </div>
    </Dialog>
  );
}
