"use client";

import { useState, useEffect, useCallback } from "react";
import type { VisibilityState, OnChangeFn } from "@tanstack/react-table";

// Columns we currently have no live data for — start them hidden so the
// table doesn't show a wall of em-dashes. Users can re-enable from the
// column-visibility menu; their choice persists in localStorage.
export const HIDDEN_BY_DEFAULT: VisibilityState = {
  grad_year: false,
  height: false,
  national_rank: false,
  state_rank: false,
  star_rating: false,
};

export function useColumnVisibility(
  storageKey: string,
  defaults: VisibilityState = {}
) {
  const [visibility, setVisibilityState] = useState<VisibilityState>(defaults);
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    try {
      const raw = localStorage.getItem(storageKey);
      if (raw) {
        const parsed = JSON.parse(raw);
        if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
          // Merge so newly-added defaults (e.g. a new column shipped hidden)
          // apply to users who already have a saved visibility map without
          // an entry for the new id.
          setVisibilityState({ ...defaults, ...(parsed as VisibilityState) });
        }
      }
    } catch {}
    setHydrated(true);
  }, [storageKey]);

  useEffect(() => {
    if (!hydrated) return;
    localStorage.setItem(storageKey, JSON.stringify(visibility));
  }, [visibility, hydrated, storageKey]);

  // TanStack passes either the next state or an updater fn — handle both so
  // table.resetColumnVisibility() and per-column toggles both work.
  const setVisibility: OnChangeFn<VisibilityState> = useCallback((updater) => {
    setVisibilityState((prev) =>
      typeof updater === "function" ? updater(prev) : updater
    );
  }, []);

  return { visibility, setVisibility };
}
