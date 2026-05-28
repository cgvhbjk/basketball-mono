"use client";

import { Table } from "@tanstack/react-table";
import { Search, Download } from "lucide-react";
import type { PlayerStatsRow } from "@/types/database";

interface ToolbarProps {
  table: Table<PlayerStatsRow>;
  circuits: string[];
  seasons: number[];
  selectedCircuit: string;
  selectedSeason: string;
  selectedDivision: string;
  onCircuitChange: (v: string) => void;
  onSeasonChange: (v: string) => void;
  onDivisionChange: (v: string) => void;
  per40: boolean;
  onPer40Change: (v: boolean) => void;
}

function fmtHeight(inches: number | null): string {
  if (!inches) return "";
  return `${Math.floor(inches / 12)}'${inches % 12}"`;
}

function p40csv(val: number | null, mpg: number | null, per40: boolean, decimals = 1): string {
  if (val === null || val === undefined) return "";
  if (!per40 || !mpg) return val.toFixed(decimals);
  return ((val / mpg) * 40).toFixed(decimals);
}

function exportCSV(table: Table<PlayerStatsRow>, per40: boolean) {
  const rows = table.getFilteredRowModel().rows;

  const headers = [
    "Player", "Circuit", "Team", "Grad", "Height",
    "GP",
    per40 ? "PTS/40" : "PPG",
    per40 ? "REB/40" : "RPG",
    per40 ? "AST/40" : "APG",
    per40 ? "STL/40" : "SPG",
    per40 ? "BLK/40" : "BPG",
    per40 ? "FGA/40" : "FGA",
    per40 ? "TO/40"  : "TO",
    per40 ? "FTA/40" : "FTA",
    "MIN", "FG%", "3P%", "EFF",
  ];

  const csvRows = rows.map((row) => {
    const d = row.original;
    const mpg = d.mpg ?? null;

    const eff = d.ppg !== null
      ? ((d.ppg ?? 0) + (d.rpg ?? 0) + (d.apg ?? 0) + (d.spg ?? 0) + (d.bpg ?? 0) - (d.tpg ?? 0))
      : null;

    return [
      `${d.players?.last_name ?? ""}, ${d.players?.first_name ?? ""}`,
      d.teams?.circuits?.name ?? "",
      d.teams?.name ?? "",
      d.players?.grad_year ?? "",
      fmtHeight(d.players?.height_inches ?? null),
      d.games_played ?? "",
      p40csv(d.ppg, mpg, per40),
      p40csv(d.rpg, mpg, per40),
      p40csv(d.apg, mpg, per40),
      p40csv(d.spg, mpg, per40),
      p40csv(d.bpg, mpg, per40),
      p40csv(d.fga, mpg, per40),
      p40csv(d.tpg, mpg, per40),
      p40csv(d.fta, mpg, per40),
      d.mpg?.toFixed(1) ?? "",
      d.fg_pct != null ? `${(d.fg_pct * 100).toFixed(1)}%` : "",
      d.three_pt_pct != null ? `${(d.three_pt_pct * 100).toFixed(1)}%` : "",
      eff != null ? (per40 && mpg ? ((eff / mpg) * 40).toFixed(1) : eff.toFixed(1)) : "",
    ].map((v) => `"${String(v).replace(/"/g, '""')}"`).join(",");
  });

  const csv = [headers.map((h) => `"${h}"`).join(","), ...csvRows].join("\n");
  const blob = new Blob([csv], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "basketball-players.csv";
  a.click();
  URL.revokeObjectURL(url);
}

export function Toolbar({
  table,
  circuits,
  seasons,
  selectedCircuit,
  selectedSeason,
  selectedDivision,
  onCircuitChange,
  onSeasonChange,
  onDivisionChange,
  per40,
  onPer40Change,
}: ToolbarProps) {
  return (
    <div className="flex flex-wrap items-center gap-2 pb-2">
      {/* Global search */}
      <div className="relative">
        <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-gray-400" />
        <input
          type="text"
          placeholder="Search player, team, school…"
          value={(table.getState().globalFilter as string) ?? ""}
          onChange={(e) => table.setGlobalFilter(e.target.value)}
          className="pl-7 pr-3 py-1 text-xs border border-gray-300 rounded focus:outline-none focus:ring-1 focus:ring-blue-400 w-56"
        />
      </div>

      {/* Season filter */}
      <select
        value={selectedSeason}
        onChange={(e) => onSeasonChange(e.target.value)}
        className="text-xs border border-gray-300 rounded px-2 py-1 focus:outline-none focus:ring-1 focus:ring-blue-400"
      >
        <option value="">All seasons</option>
        {seasons.map((s) => (
          <option key={s} value={String(s)}>{s}</option>
        ))}
      </select>

      {/* Age division filter */}
      <select
        value={selectedDivision}
        onChange={(e) => onDivisionChange(e.target.value)}
        className="text-xs border border-gray-300 rounded px-2 py-1 focus:outline-none focus:ring-1 focus:ring-blue-400"
      >
        <option value="">All divisions</option>
        <option value="17U">17U</option>
        <option value="16U">16U</option>
        <option value="15U">15U</option>
      </select>

      {/* Circuit filter */}
      <select
        value={selectedCircuit}
        onChange={(e) => onCircuitChange(e.target.value)}
        className="text-xs border border-gray-300 rounded px-2 py-1 focus:outline-none focus:ring-1 focus:ring-blue-400"
      >
        <option value="">All circuits</option>
        {circuits.map((c) => (
          <option key={c} value={c}>{c}</option>
        ))}
      </select>

      <span className="ml-auto text-xs text-gray-400">
        {table.getFilteredRowModel().rows.length} players
      </span>

      {/* Per 40 toggle */}
      <button
        onClick={() => onPer40Change(!per40)}
        className={`text-xs border rounded px-2 py-1 transition-colors ${
          per40
            ? "bg-blue-600 text-white border-blue-600"
            : "border-gray-300 text-gray-600 hover:bg-gray-50"
        }`}
        title="Toggle per-40-minute rate stats"
      >
        Per 40
      </button>

      <button
        onClick={() => exportCSV(table, per40)}
        className="flex items-center gap-1 text-xs border border-gray-300 rounded px-2 py-1 hover:bg-gray-50 text-gray-600"
        title="Export current view as CSV"
      >
        <Download className="h-3.5 w-3.5" />
        Export CSV
      </button>
    </div>
  );
}
