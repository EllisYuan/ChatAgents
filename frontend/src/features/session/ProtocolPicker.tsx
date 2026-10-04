import type { components } from "../../generated/api";
import { SettingsSelect } from "./SettingsSelect";

type Protocol = components["schemas"]["ModelRefreshRequest"]["protocol"];

const PROTOCOLS: Protocol[] = ["openai_responses", "openai_chat_completions", "anthropic_messages"];

interface ProtocolPickerProps {
  value: Protocol;
  onChange: (value: Protocol) => void;
  disabled: boolean;
}

export function ProtocolPicker({ value, onChange, disabled }: ProtocolPickerProps) {
  return (
    <SettingsSelect
      id="protocol-picker"
      label="上游协议"
      value={value}
      options={PROTOCOLS.map((protocol) => ({ value: protocol, label: protocol }))}
      onChange={onChange}
      disabled={disabled}
    />
  );
}
