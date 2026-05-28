"use client";

import { useState, useEffect, useCallback, useMemo } from "react";

export interface WatchlistEntry {
  notes: string;
  status: string | null;
  starredAt: string;
}

interface StoredWatchlist {
  entries: Record<string, WatchlistEntry>;
  statusOptions: string[];
}

const STORAGE_KEY = "basketball_watchlist";

const DEFAULT: StoredWatchlist = {
  entries: {},
  statusOptions: ["In Progress"],
};

export function useWatchlist() {
  const [stored, setStored] = useState<StoredWatchlist>(DEFAULT);
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (raw) {
        const parsed = JSON.parse(raw);
        // Defensive: localStorage may hold an older schema (or a manual edit).
        // Coerce missing/wrong-shape fields back to the defaults so downstream
        // `Object.keys(stored.entries)` never sees undefined.
        if (parsed && typeof parsed === "object") {
          setStored({
            entries:
              parsed.entries && typeof parsed.entries === "object"
                ? parsed.entries
                : DEFAULT.entries,
            statusOptions: Array.isArray(parsed.statusOptions)
              ? parsed.statusOptions
              : DEFAULT.statusOptions,
          });
        }
      }
    } catch {}
    setHydrated(true);
  }, []);

  useEffect(() => {
    if (!hydrated) return;
    localStorage.setItem(STORAGE_KEY, JSON.stringify(stored));
  }, [stored, hydrated]);

  const starred = useMemo(() => new Set(Object.keys(stored.entries)), [stored.entries]);

  const toggleStar = useCallback((playerId: string) => {
    setStored((prev) => {
      const entries = { ...prev.entries };
      if (entries[playerId]) {
        delete entries[playerId];
      } else {
        entries[playerId] = { notes: "", status: null, starredAt: new Date().toISOString() };
      }
      return { ...prev, entries };
    });
  }, []);

  const setNotes = useCallback((playerId: string, notes: string) => {
    setStored((prev) => {
      // If the player was unstarred mid-edit (e.g. starred elsewhere, then the
      // onBlur fires here), spreading `undefined` would create a partial entry
      // {notes} without starredAt and re-star the player on the next render —
      // since the `starred` Set is derived from Object.keys(entries).
      const existing = prev.entries[playerId];
      if (!existing) return prev;
      return {
        ...prev,
        entries: { ...prev.entries, [playerId]: { ...existing, notes } },
      };
    });
  }, []);

  const setStatus = useCallback((playerId: string, status: string | null) => {
    setStored((prev) => {
      const existing = prev.entries[playerId];
      if (!existing) return prev;
      return {
        ...prev,
        entries: { ...prev.entries, [playerId]: { ...existing, status } },
      };
    });
  }, []);

  const addStatusOption = useCallback((label: string) => {
    setStored((prev) => {
      if (prev.statusOptions.includes(label)) return prev;
      return { ...prev, statusOptions: [...prev.statusOptions, label] };
    });
  }, []);

  const removeStatusOption = useCallback((label: string) => {
    setStored((prev) => ({
      ...prev,
      statusOptions: prev.statusOptions.filter((o) => o !== label),
    }));
  }, []);

  return {
    starred,
    annotations: stored.entries,
    statusOptions: stored.statusOptions,
    toggleStar,
    setNotes,
    setStatus,
    addStatusOption,
    removeStatusOption,
  };
}
