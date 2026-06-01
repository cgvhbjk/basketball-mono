"use client";

import { useState, useEffect, useCallback } from "react";
import type { ColumnOrderState, OnChangeFn } from "@tanstack/react-table";

// Persists the user's column order in localStorage. `allIds` is the full set
// of column ids in their natural (definition) order — used both as the initial
// value and to reconcile a saved order against the current columns so that
// newly-shipped columns still appear (appended) and removed columns drop out.
export function useColumnOrder(storageKey: string, allIds: string[]) {
  const [order, setOrderState] = useState<ColumnOrderState>(allIds);
  const [hydrated, setHydrated] = useState(false);

  const reconcile = useCallback(
    (saved: string[]): ColumnOrderState => {
      const known = new Set(allIds);
      // Keep saved ids that still exist (preserving the user's arrangement),
      // then append any current columns the saved order didn't know about.
      const kept = saved.filter((id) => known.has(id));
      const missing = allIds.filter((id) => !kept.includes(id));
      return [...kept, ...missing];
    },
    [allIds]
  );

  useEffect(() => {
    try {
      const raw = localStorage.getItem(storageKey);
      if (raw) {
        const parsed = JSON.parse(raw);
        if (Array.isArray(parsed) && parsed.every((v) => typeof v === "string")) {
          setOrderState(reconcile(parsed));
        }
      }
    } catch {}
    setHydrated(true);
    // Only reconcile from storage once on mount; subsequent column-set changes
    // are rare and would otherwise clobber an in-flight drag.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [storageKey]);

  useEffect(() => {
    if (!hydrated) return;
    localStorage.setItem(storageKey, JSON.stringify(order));
  }, [order, hydrated, storageKey]);

  // TanStack passes either the next state or an updater fn — handle both.
  const setOrder: OnChangeFn<ColumnOrderState> = useCallback((updater) => {
    setOrderState((prev) =>
      typeof updater === "function" ? updater(prev) : updater
    );
  }, []);

  return { order, setOrder };
}
