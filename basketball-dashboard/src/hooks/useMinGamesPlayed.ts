"use client";

import { useState, useEffect, useCallback } from "react";

export function useMinGamesPlayed(storageKey: string) {
  const [minGP, setMinGPState] = useState(0);
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    try {
      const raw = localStorage.getItem(storageKey);
      if (raw !== null) {
        const parsed = Number(raw);
        if (Number.isFinite(parsed) && parsed >= 0) {
          setMinGPState(parsed);
        }
      }
    } catch {}
    setHydrated(true);
  }, [storageKey]);

  useEffect(() => {
    if (!hydrated) return;
    localStorage.setItem(storageKey, String(minGP));
  }, [minGP, hydrated, storageKey]);

  const setMinGP = useCallback((v: number) => setMinGPState(v), []);

  return { minGP, setMinGP };
}
