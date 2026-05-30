"use client";

import { useState, useEffect, useCallback } from "react";

const STORAGE_KEY = "basketball_scout_name";

export function useScoutName() {
  const [scoutName, setScoutNameState] = useState<string>("");
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (raw && typeof raw === "string") setScoutNameState(raw);
    } catch {}
    setHydrated(true);
  }, []);

  const setScoutName = useCallback((name: string) => {
    const trimmed = name.trim();
    setScoutNameState(trimmed);
    try {
      if (trimmed) localStorage.setItem(STORAGE_KEY, trimmed);
      else localStorage.removeItem(STORAGE_KEY);
    } catch {}
  }, []);

  return { scoutName, setScoutName, hydrated };
}
