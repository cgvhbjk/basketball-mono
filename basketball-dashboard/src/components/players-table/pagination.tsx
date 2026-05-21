"use client";

import { Table } from "@tanstack/react-table";
import { ChevronLeft, ChevronRight } from "lucide-react";
import type { PlayerStatsRow } from "@/types/database";

export function Pagination({ table }: { table: Table<PlayerStatsRow> }) {
  return (
    <div className="flex items-center justify-between pt-2 text-xs text-gray-600">
      <div className="flex items-center gap-1">
        <span>Rows per page:</span>
        <select
          value={table.getState().pagination.pageSize}
          onChange={(e) => table.setPageSize(Number(e.target.value))}
          className="border border-gray-300 rounded px-1 py-0.5"
        >
          {[25, 50, 100, 200].map((n) => (
            <option key={n} value={n}>{n}</option>
          ))}
        </select>
      </div>

      <div className="flex items-center gap-2">
        <span>
          Page {table.getState().pagination.pageIndex + 1} of {table.getPageCount()}
        </span>
        <button
          onClick={() => table.previousPage()}
          disabled={!table.getCanPreviousPage()}
          className="p-0.5 rounded disabled:opacity-30 hover:bg-gray-100"
        >
          <ChevronLeft className="h-3.5 w-3.5" />
        </button>
        <button
          onClick={() => table.nextPage()}
          disabled={!table.getCanNextPage()}
          className="p-0.5 rounded disabled:opacity-30 hover:bg-gray-100"
        >
          <ChevronRight className="h-3.5 w-3.5" />
        </button>
      </div>
    </div>
  );
}
