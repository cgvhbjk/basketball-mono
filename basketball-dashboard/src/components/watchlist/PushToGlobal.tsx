"use client";

import { useState, useMemo, useEffect, useRef } from "react";
import type { PlayerStatsRow } from "@/types/database";

interface Props {
  data: PlayerStatsRow[];
  localStarred: Set<string>;
  localAnnotations: Record<string, { notes: string } | undefined>;
  alreadyInGlobal: Set<string>;
  scoutName: string;
  onRequestScoutName: () => void;
  onConfirm: (
    entries: Array<{ id: string; notes?: string }>
  ) => Promise<{ added: number; skipped: number }>;
  onMessage: (msg: string | null) => void;
}

interface Row {
  id: string;
  name: string;
  team: string;
}

export function PushToGlobal({
  data,
  localStarred,
  localAnnotations,
  alreadyInGlobal,
  scoutName,
  onRequestScoutName,
  onConfirm,
  onMessage,
}: Props) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const ref = useRef<HTMLDivElement>(null);

  const candidates = useMemo<Row[]>(() => {
    const seen = new Map<string, Row>();
    for (const r of data) {
      if (!r.player_id || !localStarred.has(r.player_id) || seen.has(r.player_id)) continue;
      const first = r.players?.first_name ?? "";
      const last = r.players?.last_name ?? "";
      seen.set(r.player_id, {
        id: r.player_id,
        name: `${last}, ${first}`.replace(/^, /, ""),
        team: r.teams?.name ?? "",
      });
    }
    return Array.from(seen.values()).sort((a, b) => a.name.localeCompare(b.name));
  }, [data, localStarred]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return candidates;
    return candidates.filter(
      (c) => c.name.toLowerCase().includes(q) || c.team.toLowerCase().includes(q)
    );
  }, [candidates, query]);

  const openPicker = () => {
    if (!scoutName) {
      onRequestScoutName();
      return;
    }
    const def = new Set<string>();
    for (const c of candidates) if (!alreadyInGlobal.has(c.id)) def.add(c.id);
    setSelected(def);
    setQuery("");
    setOpen(true);
  };

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);

  const toggle = (id: string, checked: boolean) => {
    setSelected((s) => {
      const next = new Set(s);
      if (checked) next.add(id);
      else next.delete(id);
      return next;
    });
  };

  const selectAllVisible = () => {
    setSelected((s) => {
      const next = new Set(s);
      for (const r of filtered) next.add(r.id);
      return next;
    });
  };

  const clearAll = () => setSelected(new Set());

  const handlePush = async () => {
    setBusy(true);
    onMessage(null);
    const entries = Array.from(selected).map((id) => ({
      id,
      notes: localAnnotations[id]?.notes ?? "",
    }));
    const { added, skipped } = await onConfirm(entries);
    setBusy(false);
    setOpen(false);
    onMessage(
      skipped > 0
        ? `Pushed ${added}, ${skipped} already in global.`
        : `Pushed ${added} to global.`
    );
  };

  if (candidates.length === 0) return null;

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => (open ? setOpen(false) : openPicker())}
        disabled={busy}
        className="text-xs border border-gray-300 rounded px-2 py-1 text-gray-600 hover:bg-gray-50 disabled:opacity-50"
        title={scoutName ? `Push as ${scoutName}` : "Set scout name then push"}
      >
        {busy ? "Pushing…" : "Push to global"}
      </button>
      {open && (
        <div className="absolute left-0 mt-1 z-20 w-80 bg-white border border-gray-300 rounded shadow-lg">
          <div className="p-2 border-b border-gray-200 flex items-center gap-2">
            <input
              autoFocus
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Filter…"
              className="flex-1 text-xs border border-gray-300 rounded px-2 py-1 focus:outline-none focus:ring-1 focus:ring-blue-400"
            />
            <button
              type="button"
              onClick={selectAllVisible}
              className="text-xs text-blue-600 hover:underline"
            >
              All
            </button>
            <button
              type="button"
              onClick={clearAll}
              className="text-xs text-gray-500 hover:underline"
            >
              None
            </button>
          </div>
          <ul className="max-h-64 overflow-auto">
            {filtered.length === 0 ? (
              <li className="px-2 py-2 text-xs text-gray-400">No matches.</li>
            ) : (
              filtered.map((p) => {
                const checked = selected.has(p.id);
                const inGlobal = alreadyInGlobal.has(p.id);
                return (
                  <li key={p.id}>
                    <label className="flex items-center gap-2 px-2 py-1 text-xs hover:bg-blue-50 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={(e) => toggle(p.id, e.target.checked)}
                      />
                      <span className="flex-1 truncate">
                        <span className="font-medium">{p.name}</span>{" "}
                        <span className="text-gray-400">{p.team}</span>
                      </span>
                      {inGlobal && (
                        <span className="text-[10px] text-gray-400">in global</span>
                      )}
                    </label>
                  </li>
                );
              })
            )}
          </ul>
          <div className="p-2 border-t border-gray-200 flex items-center justify-between">
            <span className="text-xs text-gray-500">{selected.size} selected</span>
            <button
              type="button"
              onClick={handlePush}
              disabled={selected.size === 0 || busy}
              className="text-xs bg-blue-600 text-white rounded px-2 py-1 hover:bg-blue-700 disabled:opacity-50"
            >
              {busy ? "Pushing…" : "Push selected"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
