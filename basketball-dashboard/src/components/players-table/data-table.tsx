"use client";

import { useState, useMemo } from "react";
import { useRouter, usePathname, useSearchParams } from "next/navigation";
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
  seasons: number[];
  initialDivision: string;
}

export function DataTable({ data, seasons, initialDivision }: DataTableProps) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const [sorting, setSorting] = useState<SortingState>([{ id: "ppg", desc: true }]);
  const [globalFilter, setGlobalFilter] = useState("");
  const [columnFilters, setColumnFilters] = useState<ColumnFiltersState>([]);
  const [selectedCircuit, setSelectedCircuit] = useState("");
  const [selectedSeason, setSelectedSeason] = useState("");

  // Division is URL-driven: changes trigger a server re-fetch with filtered payload.
  const selectedDivision = searchParams.get("division") ?? initialDivision;

  const handleDivisionChange = (v: string) => {
    const params = new URLSearchParams(searchParams.toString());
    if (v) {
      params.set("division", v);
    } else {
      params.delete("division");
    }
    const qs = params.toString();
    router.push(qs ? `${pathname}?${qs}` : pathname);
  };

  // Circuit and season filters remain client-side for instant response.
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

  // Circuits are derived from the season-filtered subset so the dropdown
  // only shows circuits that actually have data in the selected season.
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
        circuits={availableCircuits}
        seasons={seasons}
        selectedCircuit={selectedCircuit}
        selectedSeason={selectedSeason}
        selectedDivision={selectedDivision}
        onCircuitChange={setSelectedCircuit}
        onSeasonChange={setSelectedSeason}
        onDivisionChange={handleDivisionChange}
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
