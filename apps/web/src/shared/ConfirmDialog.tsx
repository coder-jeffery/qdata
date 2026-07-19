type Props = {
  open: boolean;
  title: string;
  body: string;
  confirmLabel?: string;
  cancelLabel?: string;
  danger?: boolean;
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
};

export function ConfirmDialog({
  open,
  title,
  body,
  confirmLabel = "确认",
  cancelLabel = "取消",
  danger,
  busy,
  onConfirm,
  onCancel,
}: Props) {
  if (!open) return null;
  return (
    <div className="modal-overlay" role="dialog" aria-modal="true" onClick={onCancel}>
      <div className="panel modal-card" onClick={(e) => e.stopPropagation()}>
        <h3 style={{ color: "var(--text)", fontSize: 16, letterSpacing: "-0.02em", marginBottom: 8 }}>
          {title}
        </h3>
        <p className="muted" style={{ lineHeight: 1.6, marginBottom: 18 }}>
          {body}
        </p>
        <div className="btn-row" style={{ justifyContent: "flex-end" }}>
          <button type="button" className="btn ghost" disabled={busy} onClick={onCancel}>
            {cancelLabel}
          </button>
          <button
            type="button"
            className={`btn primary ${danger ? "danger" : ""}`}
            disabled={busy}
            onClick={onConfirm}
          >
            {busy ? "处理中…" : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
