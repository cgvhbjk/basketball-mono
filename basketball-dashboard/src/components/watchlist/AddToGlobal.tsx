"use client";

import { useState, useMemo, useEffect, useRef } from "react";
import { Plus } from "lucide-react";
import type { PlayerStatsRow } from "@/types/database";

interface Props {
  data: PlayerStatsRow[];
  starred: Set<string>;
  onAdd: (playerId: string) => void;
}

interface PlayerOption {
  id: string;
  name: string;
  team: string;
}

export function AddToGlobal({ data, starred, onAdd }: Props) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const ref = useRef<HTMLDivElement>(null);

  // Distinct players (across seasons / teams in the row dataset).
  const options = useMemo<PlayerOption[]>(() => {
    const seen = new Map<string, PlayerOption>();
    for (const r of data) {
      if (!r.player_id || seen.has(r.player_id)) continue;
      const first = r.players?.first_name ?? "";
      const last = r.players?.last_name ?? "";
      seen.set(r.player_id, {
        id: r.player_id,
        name: `${last}, ${first}`.replace(/^, /, ""),
        team: r.teams?.name ?? "",
      });
    }
    return Array.from(seen.values());
  }, [data]);

  const matches = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return [] as PlayerOption[];
    const out: PlayerOption[] = [];
    for (const o of options) {
      if (out.length >= 8) break;
      if (
        o.name.toLowerCase().includes(q) ||
        o.team.toLowerCase().includes(q)
      ) {
        out.push(o);
      }
    }
    return out;
  }, [options, query]);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-1 text-xs border border-gray-300 rounded px-2 py-1 text-gray-600 hover:bg-gray-50"
      >
        <Plus className="h-3.5 w-3.5" />
        Add to global
      </button>
      {open && (
        <div className="absolute left-0 mt-1 z-20 w-80 bg-white border border-gray-300 rounded shadow-lg p-2">
          <input
            autoFocus
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search player or team…"
            className="w-full text-xs border border-gray-300 rounded px-2 py-1 focus:outline-none focus:ring-1 focus:ring-blue-400"
          />
          {query.trim() && (
            <ul className="mt-1 max-h-64 overflow-auto">
              {matches.length === 0 ? (
                <li className="px-2 py-1 text-xs text-gray-400">No matches.</li>
              ) : (
                matches.map((m) => {
                  const already = starred.has(m.id);
                  return (
                    <li key={m.id}>
                      <button
                        disabled={already}
                        onClick={() => {
                          onAdd(m.id);
                          setQuery("");
                        }}
                        className={`w-full text-left flex items-center justify-between px-2 py-1 text-xs rounded ${
                          already
                            ? "text-gray-400 cursor-not-allowed"
                            : "text-gray-700 hover:bg-blue-50"
                        }`}
                      >
                        <span className="truncate">
                          <span className="font-medium">{m.name}</span>{" "}
                          <span className="text-gray-400">{m.team}</span>
                        </span>
                        <span className="text-xs">{already ? "★" : "+"}</span>
                      </button>
                    </li>
                  );
                })
              )}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
