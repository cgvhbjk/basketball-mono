"use client";

import { useEffect, useRef, useState } from "react";
import { Table } from "@tanstack/react-table";
import { Columns3 } from "lucide-react";

interface Props<T> {
  table: Table<T>;
}

export function ColumnVisibilityMenu<T>({ table }: Props<T>) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);

  const hideable = table.getAllLeafColumns().filter((c) => c.getCanHide());
  const hiddenCount = hideable.filter((c) => !c.getIsVisible()).length;

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen((o) => !o)}
        className={`flex items-center gap-1 text-xs border rounded px-2 py-1 transition-colors ${
          hiddenCount > 0
            ? "bg-blue-600 text-white border-blue-600"
            : "border-gray-300 text-gray-600 hover:bg-gray-50"
        }`}
        title="Show or hide columns"
      >
        <Columns3 className="h-3.5 w-3.5" />
        Columns{hiddenCount > 0 ? ` (${hiddenCount} hidden)` : ""}
      </button>

      {open && (
        <div className="absolute right-0 mt-1 z-20 w-56 bg-white border border-gray-300 rounded shadow-lg py-1 max-h-80 overflow-auto">
          {hideable.map((col) => {
            const label =
              (col.columnDef.meta as { label?: string } | undefined)?.label ??
              col.id;
            return (
              <label
                key={col.id}
                className="flex items-center gap-2 px-3 py-1 text-xs text-gray-700 hover:bg-gray-50 cursor-pointer"
              >
                <input
                  type="checkbox"
                  checked={col.getIsVisible()}
                  onChange={col.getToggleVisibilityHandler()}
                  className="h-3 w-3"
                />
                {label}
              </label>
            );
          })}
          <div className="border-t border-gray-200 mt-1 pt-1 px-3">
            <button
              onClick={() => table.resetColumnVisibility()}
              className="text-xs text-blue-600 hover:text-blue-700"
            >
              Show all
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
