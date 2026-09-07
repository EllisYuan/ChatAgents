import { create } from "zustand";

type UiState = {
  inspectorOpen: boolean;
  toggleInspector: () => void;
};

export const useUiStore = create<UiState>((set) => ({
  inspectorOpen: true,
  toggleInspector: () => set((state) => ({ inspectorOpen: !state.inspectorOpen })),
}));
