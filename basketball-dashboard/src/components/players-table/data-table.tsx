"use client";

import { useState, useMemo } from "react";
import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  getFilteredRowModel,
  getPaginationRowModel,
  flexRender,
  SortingState,
  ColumnFiltersState,
} from "@tanstack/react-table";
import type { PlayerStatsRow } from "@/types/database";
import { columns } from "./columns";
import { Toolbar } from "./toolbar";
import { Pagination } from "./pagination";

interface DataTableProps {
  data: PlayerStatsRow[];
  circuits: string[];
  seasons: number[];
}

export function DataTable({ data, circuits, seasons }: DataTableProps) {
  const [sorting, setSorting] = useState<SortingState>([{ id: "ppg", desc: true }]);
  const [globalFilter, setGlobalFilter] = useState("");
  const [columnFilters, setColumnFilters] = useState<ColumnFiltersState>([]);
  const [selectedCircuit, setSelectedCircuit] = useState("");
  const [selectedSeason, setSelectedSeason] = useState("");

  // Client-side circuit + season filter (server already filtered, but these
  // allow instant switching without a server round-trip on small datasets)
  const filteredData = useMemo(() => {
    let rows = data;
    if (selectedCircuit) {
      rows = rows.filter((r) => r.teams?.circuits?.name === selectedCircuit);
    }
    if (selectedSeason) {
      rows = rows.filter((r) => r.season === Number(selectedSeason));
    }
    return rows;
  }, [data, selectedCircuit, selectedSeason]);

  const table = useReactTable({
    data: filteredData,
    columns,
    state: { sorting, globalFilter, columnFilters },
    onSortingChange: setSorting,
    onGlobalFilterChange: setGlobalFilter,
    onColumnFiltersChange: setColumnFilters,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    initialState: { pagination: { pageSize: 50 } },
    globalFilterFn: "includesString",
  });

  return (
    <div className="flex flex-col h-full">
      <Toolbar
        table={table}
        circuits={circuits}
        seasons={seasons}
        selectedCircuit={selectedCircuit}
        selectedSeason={selectedSeason}
        onCircuitChange={setSelectedCircuit}
        onSeasonChange={setSelectedSeason}
      />

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
                <td colSpan={columns.length} className="text-center py-8 text-gray-400">
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
