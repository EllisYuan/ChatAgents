import { create } from "zustand";

type UiState = {
  settingsOpen: boolean;
  openSettings: () => void;
  closeSettings: () => void;
  modelSettingsDisabled: boolean;
  setModelSettingsDisabled: (disabled: boolean) => void;
};

export const useUiStore = create<UiState>((set) => ({
  settingsOpen: false,
  openSettings: () => set({ settingsOpen: true }),
  closeSettings: () => set({ settingsOpen: false }),
  modelSettingsDisabled: false,
  setModelSettingsDisabled: (modelSettingsDisabled) => set({ modelSettingsDisabled }),
}));
