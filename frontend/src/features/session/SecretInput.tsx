import { useState } from "react";

interface SecretInputProps {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  disabled?: boolean;
}

/**
 * 带可视开关的密钥输入框（issue #70）。
 *
 * 默认遮蔽，点「显示」临时明文——中转站的 key 常常是手抄的长串，看不见就
 * 只能靠重输来排错。这不违背 ADR-0029「界面从不提及密钥」：那条规则约束的
 * 是**展示位**（不显示密钥来源、不在跨度与失败态里露出密钥），而这里是它
 * 明确保留的**输入位**，显示的是用户此刻自己敲进去的值。
 *
 * 切换只改 `type`，不把值搬进别处：state 里始终只有一份明文，遮蔽是浏览器
 * 的渲染行为。离开高级选项面板即回到遮蔽态（组件卸载，`revealed` 不留存）。
 */
export function SecretInput({ value, onChange, placeholder, disabled }: SecretInputProps) {
  const [revealed, setRevealed] = useState(false);

  return (
    <div className="secret-input">
      <input
        className="advanced-input secret-input-field"
        type={revealed ? "text" : "password"}
        placeholder={placeholder}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        autoComplete="off"
        spellCheck={false}
        disabled={disabled}
      />
      <button
        type="button"
        className="secret-input-toggle"
        onClick={() => setRevealed((open) => !open)}
        disabled={disabled}
        aria-pressed={revealed}
        aria-label={revealed ? "隐藏密钥" : "显示密钥"}
      >
        {revealed ? "隐藏" : "显示"}
      </button>
    </div>
  );
}
