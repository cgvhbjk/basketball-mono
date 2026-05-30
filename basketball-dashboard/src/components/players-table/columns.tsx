"use client";

import { ColumnDef, SortingFn } from "@tanstack/react-table";
import { ArrowUpDown, ArrowUp, ArrowDown } from "lucide-react";
import type { PlayerStatsRow } from "@/types/database";
import { useStarred } from "./StarredContext";

function StarCell({ playerId }: { playerId: string }) {
  const { starred, toggleStar } = useStarred();
  const isStarred = starred.has(playerId);
  return (
    <button
      onClick={() => toggleStar(playerId)}
      className={`text-sm leading-none transition-colors ${
        isStarred ? "text-yellow-400 hover:text-yellow-500" : "text-gray-300 hover:text-yellow-300"
      }`}
      title={isStarred ? "Remove from watchlist" : "Add to watchlist"}
    >
      {isStarred ? "★" : "☆"}
    </button>
  );
}

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

function p40(val: number | null, mpg: number | null, per40 = false, decimals = 1): string {
  if (val === null || val === undefined) return "—";
  // In per-40 mode without mpg we can't actually compute the rate — showing the
  // raw value under a "PTS/40" header would mislead. Render an em-dash instead.
  if (per40 && !mpg) return "—";
  if (!per40) return fmtStat(val, decimals);
  return ((val / mpg!) * 40).toFixed(decimals);
}

// Sort comparator. We rely on each per40-sorted column having `sortUndefined: 'last'`
// AND an accessor that converts null → undefined, so missing data is pushed to
// the bottom by TanStack BEFORE this fn runs — and that placement is independent
// of asc/desc, which a hand-rolled sentinel (e.g. -Infinity) could not achieve.
function makePer40SortFn(per40: boolean): SortingFn<PlayerStatsRow> {
  return (rowA, rowB, columnId) => {
    const aRaw = rowA.getValue(columnId) as number | undefined;
    const bRaw = rowB.getValue(columnId) as number | undefined;
    if (aRaw === undefined || bRaw === undefined) return 0; // intercepted upstream
    const toVal = (v: number, mpg: number | null | undefined): number => {
      if (!per40 || !mpg) return v;
      return (v / mpg) * 40;
    };
    const a = toVal(aRaw, rowA.original.mpg);
    const b = toVal(bRaw, rowB.original.mpg);
    if (a === b) return 0;
    return a - b;
  };
}

// Coerce null → undefined so TanStack's sortUndefined treats them as missing.
function num(v: number | null | undefined): number | undefined {
  return v ?? undefined;
}

export function createColumns(per40: boolean): ColumnDef<PlayerStatsRow>[] {
  const per40Sort = makePer40SortFn(per40);
  return [
    {
      id: "star",
      header: "",
      accessorFn: (row) => row.player_id,
      cell: ({ row }) => <StarCell playerId={row.original.player_id} />,
      enableSorting: false,
      enableGlobalFilter: false,
      enableHiding: false,
    },
    {
      id: "player_name",
      accessorFn: (row) => `${row.players?.last_name}, ${row.players?.first_name}`,
      header: ({ column }) => <SortHeader column={column} label="Player" />,
      cell: ({ getValue }) => (
        <span className="font-medium whitespace-nowrap">{getValue() as string}</span>
      ),
      enableGlobalFilter: true,
      meta: { label: "Player" },
    },
    {
      id: "national_rank",
      accessorFn: (row) => row.players?.national_rank,
      header: ({ column }) => <SortHeader column={column} label="Nat#" />,
      cell: ({ getValue }) => {
        const v = getValue() as number | null;
        return v ? <span className="text-blue-600 font-medium">#{v}</span> : "—";
      },
      sortingFn: "basic",
      meta: { label: "National rank" },
    },
    {
      id: "state_rank",
      accessorFn: (row) => row.players?.state_rank,
      header: ({ column }) => <SortHeader column={column} label="St#" />,
      cell: ({ getValue }) => {
        const v = getValue() as number | null;
        return v ? <span className="text-blue-500">#{v}</span> : "—";
      },
      sortingFn: "basic",
      meta: { label: "State rank" },
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
      meta: { label: "Stars" },
    },
    {
      id: "position",
      accessorFn: (row) => row.players?.position ?? "—",
      header: "Pos",
      cell: ({ getValue }) => (
        <span className="text-gray-500 font-mono text-xs">{getValue() as string}</span>
      ),
      meta: { label: "Position" },
    },
    {
      id: "circuit",
      accessorFn: (row) => row.teams?.circuits?.name ?? "—",
      header: ({ column }) => <SortHeader column={column} label="Circuit" />,
      cell: ({ getValue }) => (
        <span className="text-gray-600 whitespace-nowrap">{getValue() as string}</span>
      ),
      enableGlobalFilter: true,
      meta: { label: "Circuit" },
    },
    {
      id: "team",
      accessorFn: (row) => row.teams?.name ?? "—",
      header: ({ column }) => <SortHeader column={column} label="Team" />,
      cell: ({ getValue }) => (
        <span className="whitespace-nowrap">{getValue() as string}</span>
      ),
      enableGlobalFilter: true,
      meta: { label: "Team" },
    },
    {
      id: "grad_year",
      accessorFn: (row) => row.players?.grad_year,
      header: ({ column }) => <SortHeader column={column} label="Grad" />,
      cell: ({ getValue }) => getValue() ?? "—",
      meta: { label: "Grad year" },
    },
    {
      id: "height",
      accessorFn: (row) => row.players?.height_inches,
      header: ({ column }) => <SortHeader column={column} label="Ht" />,
      cell: ({ getValue }) => fmtHeight(getValue() as number | null),
      sortingFn: "basic",
      meta: { label: "Height" },
    },
    {
      id: "games_played",
      accessorFn: (row) => num(row.games_played),
      header: ({ column }) => <SortHeader column={column} label="GP" />,
      cell: ({ getValue }) => (getValue() as number | undefined) ?? "—",
      sortUndefined: "last",
      meta: { label: "Games played" },
    },
    {
      id: "ppg",
      accessorFn: (row) => num(row.ppg),
      header: ({ column }) => <SortHeader column={column} label={per40 ? "PTS/40" : "PPG"} />,
      cell: ({ row }) => p40(row.original.ppg, row.original.mpg, per40),
      sortDescFirst: true,
      sortingFn: per40Sort,
      sortUndefined: "last",
      meta: { label: "PPG" },
    },
    {
      id: "rpg",
      accessorFn: (row) => num(row.rpg),
      header: ({ column }) => <SortHeader column={column} label={per40 ? "REB/40" : "RPG"} />,
      cell: ({ row }) => p40(row.original.rpg, row.original.mpg, per40),
      sortDescFirst: true,
      sortingFn: per40Sort,
      sortUndefined: "last",
      meta: { label: "RPG" },
    },
    {
      id: "apg",
      accessorFn: (row) => num(row.apg),
      header: ({ column }) => <SortHeader column={column} label={per40 ? "AST/40" : "APG"} />,
      cell: ({ row }) => p40(row.original.apg, row.original.mpg, per40),
      sortDescFirst: true,
      sortingFn: per40Sort,
      sortUndefined: "last",
      meta: { label: "APG" },
    },
    {
      id: "spg",
      accessorFn: (row) => num(row.spg),
      header: ({ column }) => <SortHeader column={column} label={per40 ? "STL/40" : "SPG"} />,
      cell: ({ row }) => p40(row.original.spg, row.original.mpg, per40),
      sortDescFirst: true,
      sortingFn: per40Sort,
      sortUndefined: "last",
      meta: { label: "SPG" },
    },
    {
      id: "bpg",
      accessorFn: (row) => num(row.bpg),
      header: ({ column }) => <SortHeader column={column} label={per40 ? "BLK/40" : "BPG"} />,
      cell: ({ row }) => p40(row.original.bpg, row.original.mpg, per40),
      sortDescFirst: true,
      sortingFn: per40Sort,
      sortUndefined: "last",
      meta: { label: "BPG" },
    },
    {
      id: "fga",
      accessorFn: (row) => num(row.fga),
      header: ({ column }) => <SortHeader column={column} label={per40 ? "FGA/40" : "FGA"} />,
      cell: ({ row }) => p40(row.original.fga, row.original.mpg, per40),
      sortDescFirst: true,
      sortingFn: per40Sort,
      sortUndefined: "last",
      meta: { label: "FGA" },
    },
    {
      id: "tpg",
      accessorFn: (row) => num(row.tpg),
      header: ({ column }) => <SortHeader column={column} label={per40 ? "TO/40" : "TO"} />,
      cell: ({ row }) => p40(row.original.tpg, row.original.mpg, per40),
      sortDescFirst: false,
      sortingFn: per40Sort,
      sortUndefined: "last",
      meta: { label: "Turnovers" },
    },
    {
      id: "fta",
      accessorFn: (row) => num(row.fta),
      header: ({ column }) => <SortHeader column={column} label={per40 ? "FTA/40" : "FTA"} />,
      cell: ({ row }) => p40(row.original.fta, row.original.mpg, per40),
      sortDescFirst: true,
      sortingFn: per40Sort,
      sortUndefined: "last",
      meta: { label: "FTA" },
    },
    {
      id: "mpg",
      accessorFn: (row) => num(row.mpg),
      header: ({ column }) => <SortHeader column={column} label="MIN" />,
      cell: ({ getValue }) => fmtStat((getValue() as number | undefined) ?? null),
      sortDescFirst: true,
      sortUndefined: "last",
      meta: { label: "Minutes" },
    },
    {
      id: "fg_pct",
      accessorFn: (row) => num(row.fg_pct),
      header: ({ column }) => <SortHeader column={column} label="FG%" />,
      cell: ({ getValue }) => fmtPct((getValue() as number | undefined) ?? null),
      sortDescFirst: true,
      sortUndefined: "last",
      meta: { label: "FG%" },
    },
    {
      id: "three_pt_pct",
      accessorFn: (row) => num(row.three_pt_pct),
      header: ({ column }) => <SortHeader column={column} label="3P%" />,
      cell: ({ getValue }) => fmtPct((getValue() as number | undefined) ?? null),
      sortDescFirst: true,
      sortUndefined: "last",
      meta: { label: "3P%" },
    },
    {
      id: "eff",
      accessorFn: (row) => {
        if (row.ppg === null) return undefined;
        // No scraper populates `oreb` today, so omit it from the formula rather
        // than silently treating null as zero and pretending oreb is in the mix.
        return (
          (row.ppg ?? 0) +
          (row.rpg ?? 0) +
          (row.apg ?? 0) +
          (row.spg ?? 0) +
          (row.bpg ?? 0) -
          (row.tpg ?? 0)
        );
      },
      header: ({ column }) => <SortHeader column={column} label="EFF" />,
      cell: ({ row, getValue }) => {
        const v = getValue() as number | undefined;
        if (v === undefined) return "—";
        if (!per40) return fmtStat(v);
        const mpg = row.original.mpg;
        if (!mpg) return "—";
        return ((v / mpg) * 40).toFixed(1);
      },
      sortDescFirst: true,
      sortingFn: per40Sort,
      sortUndefined: "last",
      meta: { label: "Efficiency" },
    },
  ];
}
