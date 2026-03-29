/**
 * Graph Explorer Store — manages filter state and presets for the
 * graph explorer power-filtering system.
 *
 * Filter presets are persisted in localStorage so they survive page
 * refreshes. A set of built-in presets is always available and cannot
 * be deleted.
 */

import { create } from "zustand";
import type {
  GraphFilterState,
  FilterPreset,
  FilterRule,
} from "@/types/graphFilter";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const PRESETS_STORAGE_KEY = "netgraphy_filter_presets";
const DEBOUNCE_MS = 500;

// ---------------------------------------------------------------------------
// Built-in presets (always available, cannot be deleted)
// ---------------------------------------------------------------------------

const BUILTIN_PRESETS: FilterPreset[] = [
  {
    id: "builtin:cabled-interfaces",
    name: "Cabled Interfaces",
    description: "Interfaces that have at least one cable endpoint attached",
    filter: {
      enabled: true,
      rootGroup: {
        logic: "or",
        rules: [
          {
            kind: "relationship",
            node_type: "Interface",
            edge_type: "CABLE_ENDPOINT_A",
            direction: "any",
            presence: "has",
          },
          {
            kind: "relationship",
            node_type: "Interface",
            edge_type: "CABLE_ENDPOINT_B",
            direction: "any",
            presence: "has",
          },
        ],
      },
    },
  },
  {
    id: "builtin:active-devices",
    name: "Active Devices",
    description: "Devices with status set to active",
    filter: {
      enabled: true,
      rootGroup: {
        logic: "and",
        rules: [
          {
            kind: "attribute",
            node_type: "Device",
            field: "status",
            operator: "eq",
            value: "active",
          },
        ],
      },
    },
  },
  {
    id: "builtin:up-interfaces",
    name: "Up Interfaces",
    description: "Interfaces with operational status up",
    filter: {
      enabled: true,
      rootGroup: {
        logic: "and",
        rules: [
          {
            kind: "attribute",
            node_type: "Interface",
            field: "oper_status",
            operator: "eq",
            value: "up",
          },
        ],
      },
    },
  },
];

// ---------------------------------------------------------------------------
// localStorage helpers
// ---------------------------------------------------------------------------

function loadPresetsFromStorage(): FilterPreset[] {
  try {
    const raw = localStorage.getItem(PRESETS_STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed as FilterPreset[];
  } catch {
    return [];
  }
}

let saveTimeout: ReturnType<typeof setTimeout> | null = null;

function debounceSavePresets(presets: FilterPreset[]): void {
  if (saveTimeout) {
    clearTimeout(saveTimeout);
  }
  saveTimeout = setTimeout(() => {
    // Only persist user presets — builtins are always injected at runtime.
    const userPresets = presets.filter((p) => !p.id.startsWith("builtin:"));
    localStorage.setItem(PRESETS_STORAGE_KEY, JSON.stringify(userPresets));
  }, DEBOUNCE_MS);
}

// ---------------------------------------------------------------------------
// Default filter state
// ---------------------------------------------------------------------------

function defaultFilterState(): GraphFilterState {
  return {
    enabled: false,
    rootGroup: {
      logic: "and",
      rules: [],
    },
  };
}

// ---------------------------------------------------------------------------
// Store
// ---------------------------------------------------------------------------

interface GraphExplorerState {
  filter: GraphFilterState;
  filterPresets: FilterPreset[];

  // Filter mutations
  setFilter: (filter: GraphFilterState) => void;
  toggleFilterEnabled: () => void;
  addFilterRule: (rule: FilterRule) => void;
  removeFilterRule: (index: number) => void;
  updateFilterRule: (index: number, rule: FilterRule) => void;
  setFilterLogic: (logic: "and" | "or") => void;

  // Preset management
  saveFilterPreset: (name: string, description?: string) => void;
  loadFilterPreset: (id: string) => void;
  deleteFilterPreset: (id: string) => void;
}

export const useGraphExplorerStore = create<GraphExplorerState>((set, get) => ({
  filter: defaultFilterState(),
  filterPresets: [...BUILTIN_PRESETS, ...loadPresetsFromStorage()],

  // -- Filter mutations -----------------------------------------------------

  setFilter: (filter: GraphFilterState) => {
    set({ filter });
  },

  toggleFilterEnabled: () => {
    const current = get().filter;
    set({
      filter: { ...current, enabled: !current.enabled },
    });
  },

  addFilterRule: (rule: FilterRule) => {
    const current = get().filter;
    set({
      filter: {
        ...current,
        rootGroup: {
          ...current.rootGroup,
          rules: [...current.rootGroup.rules, rule],
        },
      },
    });
  },

  removeFilterRule: (index: number) => {
    const current = get().filter;
    const rules = current.rootGroup.rules.filter((_, i) => i !== index);
    set({
      filter: {
        ...current,
        rootGroup: { ...current.rootGroup, rules },
      },
    });
  },

  updateFilterRule: (index: number, rule: FilterRule) => {
    const current = get().filter;
    const rules = [...current.rootGroup.rules];
    if (index >= 0 && index < rules.length) {
      rules[index] = rule;
    }
    set({
      filter: {
        ...current,
        rootGroup: { ...current.rootGroup, rules },
      },
    });
  },

  setFilterLogic: (logic: "and" | "or") => {
    const current = get().filter;
    set({
      filter: {
        ...current,
        rootGroup: { ...current.rootGroup, logic },
      },
    });
  },

  // -- Preset management ----------------------------------------------------

  saveFilterPreset: (name: string, description?: string) => {
    const { filter, filterPresets } = get();
    const id = `user:${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    const preset: FilterPreset = {
      id,
      name,
      description,
      filter: structuredClone(filter),
    };
    const updated = [...filterPresets, preset];
    set({ filterPresets: updated });
    debounceSavePresets(updated);
  },

  loadFilterPreset: (id: string) => {
    const preset = get().filterPresets.find((p) => p.id === id);
    if (preset) {
      set({ filter: structuredClone(preset.filter) });
    }
  },

  deleteFilterPreset: (id: string) => {
    // Prevent deletion of built-in presets
    if (id.startsWith("builtin:")) return;

    const updated = get().filterPresets.filter((p) => p.id !== id);
    set({ filterPresets: updated });
    debounceSavePresets(updated);
  },
}));
