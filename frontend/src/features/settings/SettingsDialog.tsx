import { useEffect, useRef } from "react";

import { useUiStore } from "../../stores/ui-store";
import { AdvancedOptions } from "../session/AdvancedOptions";
import { CloseIcon } from "../session/icons";

export function SettingsDialog() {
  const dialog = useRef<HTMLDialogElement>(null);
  const open = useUiStore((state) => state.settingsOpen);
  const close = useUiStore((state) => state.closeSettings);
  const disabled = useUiStore((state) => state.modelSettingsDisabled);

  useEffect(() => {
    const element = dialog.current;
    if (!element) return;
    if (open && !element.open) element.showModal();
    if (!open && element.open) element.close();
  }, [open]);

  return (
    <dialog ref={dialog} className="settings-dialog" aria-labelledby="settings-title" onCancel={close} onClose={close}>
      <div className="settings-header">
        <h2 id="settings-title">设置</h2>
        <button className="icon-button" type="button" onClick={close} title="关闭设置" aria-label="关闭设置" autoFocus>
          <CloseIcon size={18} />
        </button>
      </div>
      <div className="settings-content">
        <h3>模型与连接</h3>
        <p className="settings-description">配置端点、认证方式和模型。修改应用于后续发送，不影响已开始的运行。</p>
        {disabled && <p className="settings-notice" role="status">正在生成回答，完成或停止后可修改配置。</p>}
        {open && <AdvancedOptions disabled={disabled} />}
      </div>
      <div className="settings-footer">
        <span>关闭设置即可返回当前会话。</span>
        <button type="button" className="settings-done" onClick={close}>完成</button>
      </div>
    </dialog>
  );
}
