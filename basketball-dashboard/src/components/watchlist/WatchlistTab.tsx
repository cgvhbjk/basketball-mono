"use client";

import { useState, useMemo } from "react";
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

interface WatchlistTabProps {
  data: PlayerStatsRow[];
  seasons: number[];
  starred: Set<string>;
  annotations: Record<string, WatchlistEntry>;
  statusOptions: string[];
  setNotes: (id: string, notes: string) => void;
  setStatus: (id: string, status: string | null) => void;
  addStatusOption: (label: string) => void;
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
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value);

  if (editing) {
    return (
      <textarea
        autoFocus
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={() => {
          onChange(playerId, draft);
          setEditing(false);
        }}
        className="w-full text-xs p-1 border border-blue-300 rounded resize-none min-w-[140px]"
        rows={3}
      />
    );
  }

  const preview = value.split("\n")[0];
  return (
    <button
      onClick={() => { setDraft(value); setEditing(true); }}
      className="text-left text-xs w-full min-w-[100px] max-w-[200px] truncate"
      title={value || undefined}
    >
      {preview || <span className="text-gray-300 italic">Add note…</span>}
    </button>
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
  starred,
  annotations,
  statusOptions,
  setNotes,
  setStatus,
  addStatusOption,
}: WatchlistTabProps) {
  const [sorting, setSorting] = useState<SortingState>([]);
  const [globalFilter, setGlobalFilter] = useState("");
  const [selectedSeason, setSelectedSeason] = useState("");
  const [selectedCircuit, setSelectedCircuit] = useState("");
  const [selectedDivision, setSelectedDivision] = useState("");
  const [per40, setPer40] = useState(false);

  const starredData = useMemo(
    () => data.filter((r) => starred.has(r.player_id)),
    [data, starred]
  );

  const filteredData = useMemo(() => {
    let rows = starredData;
    if (selectedSeason) rows = rows.filter((r) => r.season === Number(selectedSeason));
    if (selectedCircuit) rows = rows.filter((r) => r.teams?.circuits?.name === selectedCircuit);
    if (selectedDivision) rows = rows.filter((r) => r.age_division === selectedDivision);
    return rows;
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
    const [starCol, ...statCols] = baseColumns;
    return [
      starCol,
      {
        id: "status",
        header: "Status",
        accessorFn: (row) => annotations[row.player_id]?.status ?? null,
        cell: ({ row }) => (
          <StatusCell
            playerId={row.original.player_id}
            value={annotations[row.original.player_id]?.status ?? null}
            options={statusOptions}
            onSetStatus={setStatus}
            onAddOption={addStatusOption}
          />
        ),
        sortingFn: "basic",
      },
      {
        id: "notes",
        header: "Notes",
        cell: ({ row }) => (
          <NotesCell
            playerId={row.original.player_id}
            value={annotations[row.original.player_id]?.notes ?? ""}
            onChange={setNotes}
          />
        ),
        enableSorting: false,
      },
      ...statCols,
    ];
  }, [baseColumns, statusOptions, annotations, setNotes, setStatus, addStatusOption]);

  const table = useReactTable({
    data: filteredData,
    columns,
    state: { sorting, globalFilter },
    onSortingChange: setSorting,
    onGlobalFilterChange: setGlobalFilter,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    globalFilterFn: "includesString",
  });

  if (starred.size === 0) {
    return (
      <div className="flex flex-col h-full items-center justify-center text-gray-400 gap-2">
        <span className="text-4xl">☆</span>
        <p className="text-sm">No starred players yet.</p>
        <p className="text-xs">Click ☆ in the Players tab to add someone to your watchlist.</p>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
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

      {/* Table */}
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
    </div>
  );
}
