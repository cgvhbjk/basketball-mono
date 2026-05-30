"use client";

import { useState, useMemo, useEffect } from "react";
import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  getFilteredRowModel,
  flexRender,
  SortingState,
  ColumnDef,
} from "@tanstack/react-table";
import { Search } from "lucide-react";
import type { PlayerStatsRow } from "@/types/database";
import type { WatchlistEntry } from "@/hooks/useWatchlist";
import { createColumns } from "@/components/players-table/columns";
import { ColumnVisibilityMenu } from "@/components/players-table/column-visibility-menu";
import { MinGamesSlider } from "@/components/players-table/min-games-slider";
import { StarredContext } from "@/components/players-table/StarredContext";
import { useColumnVisibility, HIDDEN_BY_DEFAULT } from "@/hooks/useColumnVisibility";
import { useMinGamesPlayed } from "@/hooks/useMinGamesPlayed";
import type { useScoutName } from "@/hooks/useScoutName";
import type { useGlobalWatchlist } from "@/hooks/useGlobalWatchlist";
import { ScoutNamePrompt } from "./ScoutNamePrompt";
import { AddToGlobal } from "./AddToGlobal";
import { PushToGlobal } from "./PushToGlobal";

type Mode = "local" | "global";
const MODE_STORAGE_KEY = "basketball_watchlist_mode";

interface WatchlistTabProps {
  data: PlayerStatsRow[];
  seasons: number[];
  starred: Set<string>;
  annotations: Record<string, WatchlistEntry>;
  statusOptions: string[];
  setNotes: (id: string, notes: string) => void;
  setStatus: (id: string, status: string | null) => void;
  addStatusOption: (label: string) => void;
  toggleStar: (id: string) => void;
  scout: ReturnType<typeof useScoutName>;
  global: ReturnType<typeof useGlobalWatchlist>;
}

function NotesCell({
  playerId,
  value,
  onChange,
}: {
  playerId: string;
  value: string;
  onChange: (id: string, notes: string) => void;
}) {
  // Notes are stored as newline-separated entries. Each line is one bubble.
  const notes = value ? value.split("\n").filter((n) => n.trim().length > 0) : [];
  const [draft, setDraft] = useState("");

  const submit = () => {
    const trimmed = draft.trim();
    setDraft("");
    if (!trimmed) return;
    onChange(playerId, [...notes, trimmed].join("\n"));
  };

  const removeAt = (idx: number) => {
    onChange(playerId, notes.filter((_, i) => i !== idx).join("\n"));
  };

  return (
    <div className="flex flex-col gap-1 min-w-[160px] max-w-[260px]">
      {notes.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {notes.map((n, i) => (
            <span
              key={i}
              className="inline-flex items-start gap-1 bg-blue-50 border border-blue-200 rounded px-1.5 py-0.5 text-xs text-blue-800 max-w-full"
              title={n}
            >
              <span className="break-words whitespace-pre-wrap">{n}</span>
              <button
                type="button"
                onClick={() => removeAt(i)}
                className="-mr-0.5 text-blue-400 hover:text-blue-700 leading-none"
                aria-label="Remove note"
              >
                ×
              </button>
            </span>
          ))}
        </div>
      )}
      <input
        type="text"
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            submit();
          }
        }}
        onBlur={submit}
        placeholder={notes.length ? "+ Add…" : "Add note…"}
        className="w-full text-xs px-1.5 py-0.5 border border-gray-200 rounded focus:outline-none focus:border-blue-300"
      />
    </div>
  );
}

function StatusCell({
  playerId,
  value,
  options,
  onSetStatus,
  onAddOption,
}: {
  playerId: string;
  value: string | null;
  options: string[];
  onSetStatus: (id: string, status: string | null) => void;
  onAddOption: (label: string) => void;
}) {
  const [addingNew, setAddingNew] = useState(false);
  const [newLabel, setNewLabel] = useState("");

  if (addingNew) {
    return (
      <input
        autoFocus
        value={newLabel}
        onChange={(e) => setNewLabel(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && newLabel.trim()) {
            onAddOption(newLabel.trim());
            onSetStatus(playerId, newLabel.trim());
            setAddingNew(false);
            setNewLabel("");
          }
          if (e.key === "Escape") {
            setAddingNew(false);
            setNewLabel("");
          }
        }}
        onBlur={() => {
          setAddingNew(false);
          setNewLabel("");
        }}
        placeholder="New label…"
        className="text-xs border border-blue-300 rounded px-1 py-0.5 w-28 focus:outline-none"
      />
    );
  }

  return (
    <select
      value={value ?? ""}
      onChange={(e) => {
        if (e.target.value === "__add__") {
          setAddingNew(true);
        } else {
          onSetStatus(playerId, e.target.value || null);
        }
      }}
      className="text-xs border border-gray-200 rounded px-1 py-0.5 focus:outline-none focus:border-blue-300"
    >
      <option value="">—</option>
      {options.map((o) => (
        <option key={o} value={o}>{o}</option>
      ))}
      <option value="__add__">+ Add option…</option>
    </select>
  );
}

export function WatchlistTab({
  data,
  seasons,
  starred: localStarred,
  annotations: localAnnotations,
  statusOptions: localStatusOptions,
  setNotes: localSetNotes,
  setStatus: localSetStatus,
  addStatusOption: localAddStatusOption,
  toggleStar: localToggleStar,
  scout,
  global,
}: WatchlistTabProps) {
  const [sorting, setSorting] = useState<SortingState>([]);
  const [globalFilter, setGlobalFilter] = useState("");
  const [selectedSeason, setSelectedSeason] = useState("");
  const [selectedCircuit, setSelectedCircuit] = useState("");
  const [selectedDivision, setSelectedDivision] = useState("");
  const [per40, setPer40] = useState(false);
  const [mode, setMode] = useState<Mode>("local");
  const [showScoutPrompt, setShowScoutPrompt] = useState(false);
  const [rowSelection, setRowSelection] = useState<Record<string, boolean>>({});
  // Bumped to v2 when we changed the default-hidden set — see data-table.tsx
  const { visibility, setVisibility } = useColumnVisibility(
    "basketball_columns_watchlist_v2",
    HIDDEN_BY_DEFAULT
  );
  const { minGP, setMinGP } = useMinGamesPlayed("basketball_min_gp_watchlist");
  const { scoutName, setScoutName, hydrated: scoutHydrated } = scout;

  // Hydrate the persisted mode after first paint to avoid an SSR/CSR mismatch.
  useEffect(() => {
    try {
      const raw = localStorage.getItem(MODE_STORAGE_KEY);
      if (raw === "local" || raw === "global") setMode(raw);
    } catch {}
  }, []);
  useEffect(() => {
    try {
      localStorage.setItem(MODE_STORAGE_KEY, mode);
    } catch {}
  }, [mode]);

  const active = mode === "global"
    ? {
        starred: global.starred,
        annotations: global.annotations,
        statusOptions: global.statusOptions,
        setNotes: global.setNotes,
        setStatus: global.setStatus,
        addStatusOption: global.addStatusOption,
        toggleStar: global.toggleStar,
      }
    : {
        starred: localStarred,
        annotations: localAnnotations as Record<string, WatchlistEntry | { notes: string; status: string | null; starredAt: string }>,
        statusOptions: localStatusOptions,
        setNotes: localSetNotes,
        setStatus: localSetStatus,
        addStatusOption: localAddStatusOption,
        toggleStar: localToggleStar,
      };

  // Switching into global mode without a scout name prompts for one.
  useEffect(() => {
    if (mode === "global" && scoutHydrated && !scoutName) setShowScoutPrompt(true);
  }, [mode, scoutHydrated, scoutName]);

  // Clear bulk selection whenever the active list changes — selections from
  // local mode don't carry over to global, and vice versa.
  useEffect(() => {
    setRowSelection({});
  }, [mode]);

  const starredData = useMemo(
    () => data.filter((r) => active.starred.has(r.player_id)),
    [data, active.starred]
  );

  const filteredData = useMemo(() => {
    let rows = starredData;
    if (selectedSeason) rows = rows.filter((r) => r.season === Number(selectedSeason));
    if (selectedCircuit) rows = rows.filter((r) => r.teams?.circuits?.name === selectedCircuit);
    if (selectedDivision) rows = rows.filter((r) => r.age_division === selectedDivision);
    if (per40) rows = rows.filter((r) => r.mpg);
    if (minGP > 0) rows = rows.filter((r) => (r.games_played ?? 0) >= minGP);
    return rows;
  }, [starredData, selectedSeason, selectedCircuit, selectedDivision, per40, minGP]);

  const gpMax = useMemo(() => {
    let rows = starredData;
    if (selectedSeason) rows = rows.filter((r) => r.season === Number(selectedSeason));
    if (selectedCircuit) rows = rows.filter((r) => r.teams?.circuits?.name === selectedCircuit);
    if (selectedDivision) rows = rows.filter((r) => r.age_division === selectedDivision);
    let max = 0;
    for (const r of rows) {
      const gp = r.games_played ?? 0;
      if (gp > max) max = gp;
    }
    return max;
  }, [starredData, selectedSeason, selectedCircuit, selectedDivision]);

  const availableCircuits = useMemo(() => {
    const src = selectedSeason
      ? starredData.filter((r) => r.season === Number(selectedSeason))
      : starredData;
    return [...new Set(src.map((r) => r.teams?.circuits?.name).filter((n): n is string => Boolean(n)))].sort();
  }, [starredData, selectedSeason]);

  // Star + toggle come from StarredContext now, so the base columns only need
  // to rebuild on the per40 flip — not on every star toggle.
  const baseColumns = useMemo(() => createColumns(per40), [per40]);

  const columns = useMemo<ColumnDef<PlayerStatsRow>[]>(() => {
    const statCols = baseColumns.slice(1);
    const selectCol: ColumnDef<PlayerStatsRow> = {
      id: "select",
      header: ({ table: t }) => (
        <input
          type="checkbox"
          checked={t.getIsAllRowsSelected()}
          ref={(el) => {
            if (el) el.indeterminate = t.getIsSomeRowsSelected();
          }}
          onChange={t.getToggleAllRowsSelectedHandler()}
          className="cursor-pointer"
          aria-label="Select all"
        />
      ),
      cell: ({ row }) => (
        <input
          type="checkbox"
          checked={row.getIsSelected()}
          onChange={row.getToggleSelectedHandler()}
          className="cursor-pointer"
          aria-label="Select row"
        />
      ),
      enableHiding: false,
      enableSorting: false,
      meta: { label: "Select" },
    };
    const scoutCol: ColumnDef<PlayerStatsRow> | null = mode === "global" ? {
      id: "scout",
      header: "Scout",
      accessorFn: (row) =>
        (active.annotations[row.player_id] as { scoutName?: string } | undefined)?.scoutName ?? "",
      cell: ({ getValue }) => (
        <span className="text-xs text-gray-600 whitespace-nowrap">{getValue() as string}</span>
      ),
      sortingFn: "basic",
      meta: { label: "Scout" },
    } : null;
    return [
      selectCol,
      ...(scoutCol ? [scoutCol] : []),
      {
        id: "status",
        header: "Status",
        accessorFn: (row) => active.annotations[row.player_id]?.status ?? null,
        cell: ({ row }) => (
          <StatusCell
            playerId={row.original.player_id}
            value={active.annotations[row.original.player_id]?.status ?? null}
            options={active.statusOptions}
            onSetStatus={active.setStatus}
            onAddOption={active.addStatusOption}
          />
        ),
        sortingFn: "basic",
        meta: { label: "Status" },
      },
      {
        id: "notes",
        header: "Notes",
        cell: ({ row }) => (
          <NotesCell
            playerId={row.original.player_id}
            value={active.annotations[row.original.player_id]?.notes ?? ""}
            onChange={active.setNotes}
          />
        ),
        enableSorting: false,
        meta: { label: "Notes" },
      },
      ...statCols,
    ];
  }, [baseColumns, active, mode]);

  const table = useReactTable({
    data: filteredData,
    columns,
    state: { sorting, globalFilter, columnVisibility: visibility, rowSelection },
    onSortingChange: setSorting,
    onGlobalFilterChange: setGlobalFilter,
    onColumnVisibilityChange: setVisibility,
    onRowSelectionChange: setRowSelection,
    enableRowSelection: true,
    getRowId: (row) => row.player_id,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    globalFilterFn: "includesString",
  });

  const modeToggle = (
    <div className="inline-flex rounded border border-gray-300 overflow-hidden">
      {(["local", "global"] as Mode[]).map((m) => (
        <button
          key={m}
          onClick={() => setMode(m)}
          className={`text-xs px-2 py-1 transition-colors ${
            mode === m
              ? "bg-blue-600 text-white"
              : "bg-white text-gray-600 hover:bg-gray-50"
          }`}
        >
          {m === "local" ? "Local" : "Global"}
        </button>
      ))}
    </div>
  );

  const scoutPill = mode === "global" ? (
    <button
      onClick={() => setShowScoutPrompt(true)}
      className="text-xs border border-gray-300 rounded px-2 py-1 text-gray-600 hover:bg-gray-50"
      title="Change scout name"
    >
      Scout: <span className="font-medium">{scoutName || "—"}</span>
    </button>
  ) : null;

  const [pushMessage, setPushMessage] = useState<string | null>(null);

  // Auto-clear status messages after a few seconds.
  useEffect(() => {
    if (!pushMessage) return;
    const t = setTimeout(() => setPushMessage(null), 4000);
    return () => clearTimeout(t);
  }, [pushMessage]);

  const pushButton =
    mode === "local" && localStarred.size > 0 ? (
      <PushToGlobal
        data={data}
        localStarred={localStarred}
        localAnnotations={localAnnotations}
        alreadyInGlobal={global.starred}
        scoutName={scoutName}
        onRequestScoutName={() => setShowScoutPrompt(true)}
        onConfirm={(entries) => global.pushMany(entries)}
        onMessage={setPushMessage}
      />
    ) : null;

  const selectedCount = Object.keys(rowSelection).length;
  const [bulkBusy, setBulkBusy] = useState(false);

  const handleBulkDelete = async () => {
    const ids = Object.keys(rowSelection);
    if (ids.length === 0) return;
    setBulkBusy(true);
    setRowSelection({});
    for (const id of ids) {
      await active.toggleStar(id);
    }
    setBulkBusy(false);
  };

  const bulkBar = selectedCount > 0 ? (
    <div className="flex items-center gap-2">
      <span className="text-xs text-gray-500">{selectedCount} selected</span>
      <button
        onClick={handleBulkDelete}
        disabled={bulkBusy}
        className="text-xs border border-red-300 text-red-600 rounded px-2 py-1 hover:bg-red-50 disabled:opacity-50"
      >
        {bulkBusy ? "Deleting…" : "Delete"}
      </button>
      <button
        onClick={() => setRowSelection({})}
        disabled={bulkBusy}
        className="text-xs text-gray-500 hover:underline disabled:opacity-50"
      >
        Clear
      </button>
    </div>
  ) : null;

  const tableBody = (
    <>
      <div className="flex-1 overflow-auto border border-gray-300 rounded">
        <table className="w-full border-collapse text-xs">
          <thead className="sticky top-0 z-10 bg-gray-50 border-b border-gray-300">
            {table.getHeaderGroups().map((hg) => (
              <tr key={hg.id}>
                {hg.headers.map((header) => (
                  <th
                    key={header.id}
                    className="px-2 py-1.5 text-left text-gray-600 font-semibold border-r border-gray-200 last:border-r-0 whitespace-nowrap select-none"
                  >
                    {header.isPlaceholder
                      ? null
                      : flexRender(header.column.columnDef.header, header.getContext())}
                  </th>
                ))}
              </tr>
            ))}
          </thead>
          <tbody>
            {table.getRowModel().rows.length === 0 ? (
              <tr>
                <td colSpan={table.getAllColumns().length} className="text-center py-8 text-gray-400">
                  No players match your filters.
                </td>
              </tr>
            ) : (
              table.getRowModel().rows.map((row, i) => (
                <tr key={row.id} className={i % 2 === 0 ? "bg-white" : "bg-gray-50/50"}>
                  {row.getVisibleCells().map((cell) => (
                    <td
                      key={cell.id}
                      className="px-2 py-1 border-r border-gray-200 last:border-r-0 border-b border-gray-100"
                    >
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </td>
                  ))}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </>
  );

  const emptyState = (
    <div className="flex flex-col h-full items-center justify-center text-gray-400 gap-2">
      <span className="text-4xl">☆</span>
      <p className="text-sm">
        {mode === "local"
          ? "No starred players yet."
          : scoutName
          ? "No global stars yet."
          : "Set a scout name to start a global watchlist."}
      </p>
      <p className="text-xs">
        {mode === "local"
          ? "Click ☆ in the Players tab to add someone to your watchlist."
          : "Use the search above to add players to the global list."}
      </p>
    </div>
  );

  const showEmpty = active.starred.size === 0;

  // In global mode, swap the StarredContext so the ☆ button in the star column
  // toggles the GLOBAL list. In local mode the parent's context already does this.
  const wrap = (node: React.ReactNode) =>
    mode === "global" ? (
      <StarredContext.Provider value={{ starred: global.starred, toggleStar: global.toggleStar }}>
        {node}
      </StarredContext.Provider>
    ) : (
      <>{node}</>
    );

  return wrap(
    <div className="flex flex-col h-full">
      {showScoutPrompt && (
        <ScoutNamePrompt
          initialValue={scoutName}
          onSubmit={(n) => {
            setScoutName(n);
            setShowScoutPrompt(false);
          }}
          onCancel={() => {
            setShowScoutPrompt(false);
            if (!scoutName) setMode("local");
          }}
        />
      )}

      {/* Mode + scout row */}
      <div className="flex items-center gap-2 pb-2">
        {modeToggle}
        {scoutPill}
        {pushButton}
        {mode === "global" && scoutName && (
          <AddToGlobal data={data} starred={global.starred} onAdd={global.toggleStar} />
        )}
        {bulkBar}
        {pushMessage && (
          <span className="text-xs text-gray-500">{pushMessage}</span>
        )}
        {global.error && (
          <span
            className="text-xs text-red-600 truncate max-w-md"
            title={global.error}
          >
            ⚠ {global.error}
          </span>
        )}
      </div>

      {/* Toolbar */}
      <div className="flex flex-wrap items-center gap-2 pb-2">
        <div className="relative">
          <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-gray-400" />
          <input
            type="text"
            placeholder="Search player, team, circuit…"
            value={(table.getState().globalFilter as string) ?? ""}
            onChange={(e) => table.setGlobalFilter(e.target.value)}
            className="pl-7 pr-3 py-1 text-xs border border-gray-300 rounded focus:outline-none focus:ring-1 focus:ring-blue-400 w-56"
          />
        </div>

        <select
          value={selectedSeason}
          onChange={(e) => { setSelectedSeason(e.target.value); setSelectedCircuit(""); }}
          className="text-xs border border-gray-300 rounded px-2 py-1 focus:outline-none focus:ring-1 focus:ring-blue-400"
        >
          <option value="">All seasons</option>
          {seasons.map((s) => <option key={s} value={String(s)}>{s}</option>)}
        </select>

        <select
          value={selectedDivision}
          onChange={(e) => setSelectedDivision(e.target.value)}
          className="text-xs border border-gray-300 rounded px-2 py-1 focus:outline-none focus:ring-1 focus:ring-blue-400"
        >
          <option value="">All divisions</option>
          <option value="17U">17U</option>
          <option value="16U">16U</option>
          <option value="15U">15U</option>
        </select>

        <select
          value={selectedCircuit}
          onChange={(e) => setSelectedCircuit(e.target.value)}
          className="text-xs border border-gray-300 rounded px-2 py-1 focus:outline-none focus:ring-1 focus:ring-blue-400"
        >
          <option value="">All circuits</option>
          {availableCircuits.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>

        <span className="ml-auto text-xs text-gray-400">
          {table.getFilteredRowModel().rows.length} players
        </span>

        <MinGamesSlider value={minGP} onChange={setMinGP} max={gpMax} />

        <ColumnVisibilityMenu table={table} />

        <button
          onClick={() => setPer40(!per40)}
          className={`text-xs border rounded px-2 py-1 transition-colors ${
            per40
              ? "bg-blue-600 text-white border-blue-600"
              : "border-gray-300 text-gray-600 hover:bg-gray-50"
          }`}
        >
          Per 40
        </button>
      </div>

      {showEmpty ? emptyState : tableBody}
    </div>
  );
}
