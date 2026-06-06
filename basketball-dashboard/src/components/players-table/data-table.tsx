"use client";

import { useState, useMemo, useRef } from "react";
import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  getFilteredRowModel,
  getPaginationRowModel,
  getFacetedRowModel,
  getFacetedUniqueValues,
  getFacetedMinMaxValues,
  flexRender,
  SortingState,
  ColumnFiltersState,
} from "@tanstack/react-table";
import type { PlayerStatsRow } from "@/types/database";
import { createColumns } from "./columns";
import { Toolbar } from "./toolbar";
import { Pagination } from "./pagination";
import { useColumnVisibility, HIDDEN_BY_DEFAULT } from "@/hooks/useColumnVisibility";
import { useColumnOrder } from "@/hooks/useColumnOrder";
import { useMinGamesPlayed } from "@/hooks/useMinGamesPlayed";

interface DataTableProps {
  data: PlayerStatsRow[];
  seasons: number[];
}

// Move `fromId` to sit where `toId` currently is, preserving the rest.
function reorder(order: string[], fromId: string, toId: string): string[] {
  const from = order.indexOf(fromId);
  const to = order.indexOf(toId);
  if (from === -1 || to === -1 || from === to) return order;
  const next = [...order];
  next.splice(from, 1);
  next.splice(to, 0, fromId);
  return next;
}

export function DataTable({ data, seasons }: DataTableProps) {
  const [sorting, setSorting] = useState<SortingState>([{ id: "ppg", desc: true }]);
  const [globalFilter, setGlobalFilter] = useState("");
  const [columnFilters, setColumnFilters] = useState<ColumnFiltersState>([]);
  const [selectedCircuit, setSelectedCircuit] = useState("");
  const [selectedSeason, setSelectedSeason] = useState(seasons[0] ? String(seasons[0]) : "");
  const [selectedDivision, setSelectedDivision] = useState("");
  const [per40, setPer40] = useState(false);
  // Bumped to v2 when we changed the default-hidden set — old saved values
  // would otherwise override the new defaults for users who'd toggled.
  const { visibility, setVisibility } = useColumnVisibility(
    "basketball_columns_players_v2",
    HIDDEN_BY_DEFAULT
  );
  const { minGP, setMinGP } = useMinGamesPlayed("basketball_min_gp_players");

  const handleSeasonChange = (v: string) => {
    setSelectedSeason(v);
    setSelectedCircuit("");
  };

  const filteredData = useMemo(() => {
    let rows = data;
    if (selectedCircuit) {
      rows = rows.filter((r) => r.teams?.circuits?.name === selectedCircuit);
    }
    if (selectedSeason) {
      rows = rows.filter((r) => r.season === Number(selectedSeason));
    }
    if (selectedDivision) {
      rows = rows.filter((r) => r.age_division === selectedDivision);
    }
    // Max GP available in the current scope — mirrors the slider's upper bound
    // (computed before per40/minGP). Clamp the GP floor to it so a threshold
    // carried over from a higher-GP season can't silently hide every row while
    // the slider shows itself maxed out.
    const scopeMax = rows.reduce((m, r) => Math.max(m, r.games_played ?? 0), 0);
    // In per-40 mode, rows without mpg can't be rate-adjusted — the cells would
    // all em-dash. Hide them outright rather than show a row of "—".
    if (per40) {
      rows = rows.filter((r) => r.mpg);
    }
    const floor = Math.min(minGP, scopeMax);
    if (floor > 0) {
      rows = rows.filter((r) => (r.games_played ?? 0) >= floor);
    }
    return rows;
  }, [data, selectedCircuit, selectedSeason, selectedDivision, per40, minGP]);

  // Max games played in the current scope (season/circuit/division) — used as
  // the slider's upper bound. Computed BEFORE applying minGP so dragging the
  // slider doesn't collapse the max as players drop out.
  const gpMax = useMemo(() => {
    let rows = data;
    if (selectedCircuit) rows = rows.filter((r) => r.teams?.circuits?.name === selectedCircuit);
    if (selectedSeason) rows = rows.filter((r) => r.season === Number(selectedSeason));
    if (selectedDivision) rows = rows.filter((r) => r.age_division === selectedDivision);
    let max = 0;
    for (const r of rows) {
      const gp = r.games_played ?? 0;
      if (gp > max) max = gp;
    }
    return max;
  }, [data, selectedCircuit, selectedSeason, selectedDivision]);

  // Circuits derived from season-filtered rows so the dropdown only shows
  // circuits that have data in the selected season.
  const availableCircuits = useMemo(() => {
    const seasonRows = selectedSeason
      ? data.filter((r) => r.season === Number(selectedSeason))
      : data;
    return [
      ...new Set(
        seasonRows
          .map((r) => r.teams?.circuits?.name)
          .filter((n): n is string => Boolean(n))
      ),
    ].sort();
  }, [data, selectedSeason]);

  // `starred` is read from StarredContext inside the star cell, so the columns
  // array stays stable across star toggles — only the per40 toggle rebuilds it.
  const columns = useMemo(() => createColumns(per40), [per40]);

  // Column order (drag-to-reorder), persisted. Ids are stable across the per40
  // toggle, so the saved order survives it.
  const columnIds = useMemo(() => columns.map((c) => c.id as string), [columns]);
  const { order, setOrder } = useColumnOrder("basketball_columns_order_players", columnIds);

  // Tracks the in-flight header drag (source id) and the current drop target
  // for a light highlight. The star column is pinned and never participates.
  const dragColId = useRef<string | null>(null);
  const [dragOverId, setDragOverId] = useState<string | null>(null);

  const table = useReactTable({
    data: filteredData,
    columns,
    state: { sorting, globalFilter, columnFilters, columnVisibility: visibility, columnOrder: order },
    onSortingChange: setSorting,
    onGlobalFilterChange: setGlobalFilter,
    onColumnFiltersChange: setColumnFilters,
    onColumnVisibilityChange: setVisibility,
    onColumnOrderChange: setOrder,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    getFacetedRowModel: getFacetedRowModel(),
    getFacetedUniqueValues: getFacetedUniqueValues(),
    getFacetedMinMaxValues: getFacetedMinMaxValues(),
    initialState: { pagination: { pageSize: 50 } },
    globalFilterFn: "includesString",
  });

  return (
    <div className="flex flex-col h-full">
      <Toolbar
        table={table}
        circuits={availableCircuits}
        seasons={seasons}
        selectedCircuit={selectedCircuit}
        selectedSeason={selectedSeason}
        selectedDivision={selectedDivision}
        onCircuitChange={setSelectedCircuit}
        onSeasonChange={handleSeasonChange}
        onDivisionChange={setSelectedDivision}
        per40={per40}
        onPer40Change={setPer40}
        minGP={minGP}
        onMinGPChange={setMinGP}
        gpMax={gpMax}
      />

      <div className="flex-1 overflow-auto border border-gray-300 rounded">
        <table className="w-full border-collapse text-xs">
          <thead className="sticky top-0 z-10 bg-gray-50 border-b border-gray-300">
            {table.getHeaderGroups().map((hg) => (
              <tr key={hg.id}>
                {hg.headers.map((header) => {
                  const colId = header.column.id;
                  // The star column stays pinned first and is not reorderable.
                  const movable = colId !== "star";
                  return (
                    <th
                      key={header.id}
                      draggable={movable}
                      onDragStart={
                        movable
                          ? () => {
                              dragColId.current = colId;
                            }
                          : undefined
                      }
                      onDragEnter={() => {
                        if (movable && dragColId.current && dragColId.current !== colId) {
                          setDragOverId(colId);
                        }
                      }}
                      onDragOver={(e) => {
                        // Allow a drop only onto another movable column.
                        if (movable && dragColId.current) e.preventDefault();
                      }}
                      onDragLeave={() => setDragOverId((o) => (o === colId ? null : o))}
                      onDrop={(e) => {
                        e.preventDefault();
                        const from = dragColId.current;
                        dragColId.current = null;
                        setDragOverId(null);
                        if (from && movable && from !== colId) {
                          setOrder((prev) => reorder(prev, from, colId));
                        }
                      }}
                      onDragEnd={() => {
                        dragColId.current = null;
                        setDragOverId(null);
                      }}
                      className={`px-2 py-1.5 text-left text-gray-600 font-semibold border-r border-gray-200 last:border-r-0 whitespace-nowrap select-none ${
                        movable ? "cursor-move" : ""
                      } ${dragOverId === colId ? "bg-blue-100" : ""}`}
                    >
                      {header.isPlaceholder
                        ? null
                        : flexRender(header.column.columnDef.header, header.getContext())}
                    </th>
                  );
                })}
              </tr>
            ))}
          </thead>

          <tbody>
            {table.getRowModel().rows.length === 0 ? (
              <tr>
                <td colSpan={table.getAllColumns().length} className="text-center py-8 text-gray-400">
                  No players found.
                </td>
              </tr>
            ) : (
              table.getRowModel().rows.map((row, i) => (
                <tr
                  key={row.id}
                  className={i % 2 === 0 ? "bg-white" : "bg-gray-50/50"}
                >
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

      <Pagination table={table} />
    </div>
  );
}
