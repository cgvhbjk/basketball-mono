"use client";

import { ColumnDef } from "@tanstack/react-table";
import { ArrowUpDown, ArrowUp, ArrowDown } from "lucide-react";
import type { PlayerStatsRow } from "@/types/database";

function SortHeader({ column, label }: { column: any; label: string }) {
  const sorted = column.getIsSorted();
  return (
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
  );
}

function fmtHeight(inches: number | null): string {
  if (!inches) return "—";
  return `${Math.floor(inches / 12)}'${inches % 12}"`;
}

function fmtPct(val: number | null): string {
  if (val === null || val === undefined) return "—";
  return `${(val * 100).toFixed(1)}%`;
}

function fmtStat(val: number | null, decimals = 1): string {
  if (val === null || val === undefined) return "—";
  return val.toFixed(decimals);
}

function fmtStars(rating: number | null): string {
  if (rating === null || rating === undefined) return "—";
  return "★".repeat(rating) + "☆".repeat(5 - rating);
}

export const columns: ColumnDef<PlayerStatsRow>[] = [
  {
    id: "player_name",
    accessorFn: (row) => `${row.players?.last_name}, ${row.players?.first_name}`,
    header: ({ column }) => <SortHeader column={column} label="Player" />,
    cell: ({ getValue }) => (
      <span className="font-medium whitespace-nowrap">{getValue() as string}</span>
    ),
    enableGlobalFilter: true,
  },
  {
    id: "national_rank",
    accessorFn: (row) => row.players?.national_rank,
    header: ({ column }) => <SortHeader column={column} label="Rank" />,
    cell: ({ getValue }) => {
      const v = getValue() as number | null;
      return v ? <span className="text-blue-600 font-medium">#{v}</span> : "—";
    },
    sortingFn: "basic",
  },
  {
    id: "star_rating",
    accessorFn: (row) => row.players?.star_rating,
    header: ({ column }) => <SortHeader column={column} label="Stars" />,
    cell: ({ getValue }) => (
      <span className="text-yellow-500 tracking-tight text-xs">
        {fmtStars(getValue() as number | null)}
      </span>
    ),
    sortingFn: "basic",
    sortDescFirst: true,
  },
  {
    id: "position",
    accessorFn: (row) => row.players?.position ?? "—",
    header: "Pos",
    cell: ({ getValue }) => (
      <span className="text-gray-500 font-mono text-xs">{getValue() as string}</span>
    ),
  },
  {
    id: "circuit",
    accessorFn: (row) => row.teams?.circuits?.name ?? "—",
    header: ({ column }) => <SortHeader column={column} label="Circuit" />,
    cell: ({ getValue }) => (
      <span className="text-gray-600 whitespace-nowrap">{getValue() as string}</span>
    ),
    enableGlobalFilter: true,
  },
  {
    id: "team",
    accessorFn: (row) => row.teams?.name ?? "—",
    header: ({ column }) => <SortHeader column={column} label="Team" />,
    cell: ({ getValue }) => (
      <span className="whitespace-nowrap">{getValue() as string}</span>
    ),
    enableGlobalFilter: true,
  },
  {
    id: "grad_year",
    accessorFn: (row) => row.players?.grad_year,
    header: ({ column }) => <SortHeader column={column} label="Grad" />,
    cell: ({ getValue }) => getValue() ?? "—",
  },
  {
    id: "height",
    accessorFn: (row) => row.players?.height_inches,
    header: ({ column }) => <SortHeader column={column} label="Ht" />,
    cell: ({ getValue }) => fmtHeight(getValue() as number | null),
    sortingFn: "basic",
  },
  {
    id: "high_school",
    accessorFn: (row) => row.players?.high_school ?? "—",
    header: "HS",
    enableGlobalFilter: true,
    cell: ({ getValue }) => (
      <span className="text-gray-600">{getValue() as string}</span>
    ),
  },
  {
    accessorKey: "games_played",
    header: ({ column }) => <SortHeader column={column} label="GP" />,
    cell: ({ getValue }) => getValue() ?? "—",
  },
  {
    accessorKey: "ppg",
    header: ({ column }) => <SortHeader column={column} label="PPG" />,
    cell: ({ getValue }) => fmtStat(getValue() as number | null),
    sortDescFirst: true,
  },
  {
    accessorKey: "rpg",
    header: ({ column }) => <SortHeader column={column} label="RPG" />,
    cell: ({ getValue }) => fmtStat(getValue() as number | null),
    sortDescFirst: true,
  },
  {
    accessorKey: "apg",
    header: ({ column }) => <SortHeader column={column} label="APG" />,
    cell: ({ getValue }) => fmtStat(getValue() as number | null),
    sortDescFirst: true,
  },
  {
    accessorKey: "spg",
    header: ({ column }) => <SortHeader column={column} label="SPG" />,
    cell: ({ getValue }) => fmtStat(getValue() as number | null),
    sortDescFirst: true,
  },
  {
    accessorKey: "bpg",
    header: ({ column }) => <SortHeader column={column} label="BPG" />,
    cell: ({ getValue }) => fmtStat(getValue() as number | null),
    sortDescFirst: true,
  },
  {
    accessorKey: "fg_pct",
    header: ({ column }) => <SortHeader column={column} label="FG%" />,
    cell: ({ getValue }) => fmtPct(getValue() as number | null),
    sortDescFirst: true,
  },
  {
    accessorKey: "three_pt_pct",
    header: ({ column }) => <SortHeader column={column} label="3P%" />,
    cell: ({ getValue }) => fmtPct(getValue() as number | null),
    sortDescFirst: true,
  },
  {
    id: "eff",
    accessorFn: (row) => {
      if (row.ppg === null) return null;
      return (
        (row.ppg ?? 0) +
        (row.rpg ?? 0) +
        (row.apg ?? 0) +
        (row.spg ?? 0) +
        (row.bpg ?? 0)
      );
    },
    header: ({ column }) => <SortHeader column={column} label="EFF" />,
    cell: ({ getValue }) => fmtStat(getValue() as number | null),
    sortDescFirst: true,
    sortingFn: "basic",
  },
];
