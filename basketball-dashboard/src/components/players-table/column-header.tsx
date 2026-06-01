"use client";

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Column } from "@tanstack/react-table";
import { ArrowUpDown, ArrowUp, ArrowDown, Filter } from "lucide-react";
import type { PlayerStatsRow } from "@/types/database";

type FilterType = "range" | "category";
interface FilterMeta {
  filterType?: FilterType;
  // When true, the column's stored value is a 0–1 fraction but the filter
  // inputs/hints are shown as a 0–100 percentage (FG%, 3P%).
  percent?: boolean;
}

const POPOVER_WIDTH = 224;

interface Props {
  column: Column<PlayerStatsRow, unknown>;
  label: string;
}

export function ColumnHeader({ column, label }: Props) {
  const sorted = column.getIsSorted();
  const meta = column.columnDef.meta as FilterMeta | undefined;
  const filterType = meta?.filterType;
  const isFiltered = column.getIsFiltered();

  const [open, setOpen] = useState(false);
  const btnRef = useRef<HTMLButtonElement>(null);
  const popRef = useRef<HTMLDivElement>(null);
  const [coords, setCoords] = useState({ top: 0, left: 0 });

  // Anchor the (portaled, fixed) popover under the funnel button, clamped to
  // the viewport so right-edge columns don't open off-screen.
  useLayoutEffect(() => {
    if (!open || !btnRef.current) return;
    const r = btnRef.current.getBoundingClientRect();
    const left = Math.min(r.left, window.innerWidth - POPOVER_WIDTH - 8);
    setCoords({ top: r.bottom + 4, left: Math.max(8, left) });
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      const t = e.target as Node;
      if (popRef.current?.contains(t) || btnRef.current?.contains(t)) return;
      setOpen(false);
    };
    // The table scrolls inside its own container, so reposition would drift —
    // simplest correct behavior is to close on scroll/resize.
    const close = () => setOpen(false);
    document.addEventListener("mousedown", onDown);
    window.addEventListener("scroll", close, true);
    window.addEventListener("resize", close);
    return () => {
      document.removeEventListener("mousedown", onDown);
      window.removeEventListener("scroll", close, true);
      window.removeEventListener("resize", close);
    };
  }, [open]);

  return (
    <div className="flex items-center gap-1">
      <button
        className="flex items-center gap-1 font-semibold hover:text-black"
        onClick={() => column.toggleSorting(sorted === "asc")}
      >
        {label}
        {sorted === "asc" ? (
          <ArrowUp className="h-3 w-3" />
        ) : sorted === "desc" ? (
          <ArrowDown className="h-3 w-3" />
        ) : (
          <ArrowUpDown className="h-3 w-3 opacity-40" />
        )}
      </button>

      {filterType && (
        <button
          ref={btnRef}
          onClick={() => setOpen((o) => !o)}
          className={`rounded p-0.5 transition-colors ${
            isFiltered ? "text-blue-600" : "text-gray-300 hover:text-gray-600"
          }`}
          title="Filter this column"
        >
          <Filter className={`h-3 w-3 ${isFiltered ? "fill-blue-600" : ""}`} />
        </button>
      )}

      {open &&
        filterType &&
        typeof document !== "undefined" &&
        createPortal(
          <div
            ref={popRef}
            style={{ position: "fixed", top: coords.top, left: coords.left, width: POPOVER_WIDTH }}
            className="z-50 bg-white border border-gray-300 rounded shadow-lg p-2 text-xs font-normal text-gray-700"
          >
            {filterType === "range" ? (
              <RangeFilter column={column} percent={meta?.percent} />
            ) : (
              <CategoryFilter column={column} />
            )}
          </div>,
          document.body
        )}
    </div>
  );
}

function round(n: number): number {
  return Math.round(n * 10) / 10;
}

function RangeFilter({
  column,
  percent,
}: {
  column: Column<PlayerStatsRow, unknown>;
  percent?: boolean;
}) {
  const stored = (column.getFilterValue() as [number | undefined, number | undefined]) ?? [
    undefined,
    undefined,
  ];
  // Local string state lets the user type freely (decimals, partials) without
  // the value getting reparsed mid-edit.
  const [lo, setLo] = useState(stored[0] === undefined ? "" : String(stored[0]));
  const [hi, setHi] = useState(stored[1] === undefined ? "" : String(stored[1]));

  const facet = column.getFacetedMinMaxValues();
  const scale = percent ? 100 : 1;
  const minHint = facet?.[0] !== undefined ? round(facet[0] * scale) : undefined;
  const maxHint = facet?.[1] !== undefined ? round(facet[1] * scale) : undefined;

  const apply = (loStr: string, hiStr: string) => {
    const toNum = (s: string) => {
      if (s.trim() === "") return undefined;
      const n = Number(s);
      return Number.isNaN(n) ? undefined : n;
    };
    const min = toNum(loStr);
    const max = toNum(hiStr);
    if (min === undefined && max === undefined) column.setFilterValue(undefined);
    else column.setFilterValue([min, max]);
  };

  const clear = () => {
    setLo("");
    setHi("");
    column.setFilterValue(undefined);
  };

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-1">
        <input
          type="number"
          inputMode="decimal"
          value={lo}
          onChange={(e) => {
            setLo(e.target.value);
            apply(e.target.value, hi);
          }}
          placeholder={minHint !== undefined ? `≥ ${minHint}` : "min"}
          className="w-full border border-gray-300 rounded px-1.5 py-1 focus:outline-none focus:ring-1 focus:ring-blue-400"
        />
        <span className="text-gray-400">–</span>
        <input
          type="number"
          inputMode="decimal"
          value={hi}
          onChange={(e) => {
            setHi(e.target.value);
            apply(lo, e.target.value);
          }}
          placeholder={maxHint !== undefined ? `≤ ${maxHint}` : "max"}
          className="w-full border border-gray-300 rounded px-1.5 py-1 focus:outline-none focus:ring-1 focus:ring-blue-400"
        />
      </div>
      <button onClick={clear} className="self-start text-blue-600 hover:text-blue-700">
        Clear
      </button>
    </div>
  );
}

// Position values sort into basketball order; everything else (teams) falls
// back to alphabetical, with the "no data" em-dash pushed last.
const CATEGORY_ORDER = ["PG", "SG", "SF", "PF", "C", "G", "F"];
function compareCategory(a: string, b: string): number {
  if (a === "—") return 1;
  if (b === "—") return -1;
  const ia = CATEGORY_ORDER.indexOf(a);
  const ib = CATEGORY_ORDER.indexOf(b);
  if (ia !== -1 || ib !== -1) return (ia === -1 ? 99 : ia) - (ib === -1 ? 99 : ib);
  return a.localeCompare(b);
}

function CategoryFilter({ column }: { column: Column<PlayerStatsRow, unknown> }) {
  const selected = (column.getFilterValue() as string[]) ?? [];
  const values = Array.from(column.getFacetedUniqueValues().entries())
    .map(([value, count]) => ({ value: String(value), count }))
    .sort((a, b) => compareCategory(a.value, b.value));

  const toggle = (value: string) => {
    const next = selected.includes(value)
      ? selected.filter((v) => v !== value)
      : [...selected, value];
    column.setFilterValue(next.length ? next : undefined);
  };

  return (
    <div className="flex flex-col gap-1">
      <div className="max-h-56 overflow-auto flex flex-col gap-0.5">
        {values.map(({ value, count }) => (
          <label
            key={value}
            className="flex items-center gap-2 px-1 py-0.5 hover:bg-gray-50 cursor-pointer rounded"
          >
            <input
              type="checkbox"
              checked={selected.includes(value)}
              onChange={() => toggle(value)}
              className="h-3 w-3"
            />
            <span className="flex-1 truncate">{value}</span>
            <span className="text-gray-400">{count}</span>
          </label>
        ))}
      </div>
      {selected.length > 0 && (
        <button
          onClick={() => column.setFilterValue(undefined)}
          className="self-start text-blue-600 hover:text-blue-700 border-t border-gray-200 pt-1 mt-0.5 w-full text-left"
        >
          Clear
        </button>
      )}
    </div>
  );
}
