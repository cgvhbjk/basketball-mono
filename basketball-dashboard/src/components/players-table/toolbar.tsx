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
  onCircuitChange: (v: string) => void;
  onSeasonChange: (v: string) => void;
}

function exportCSV(table: Table<PlayerStatsRow>) {
  const rows = table.getFilteredRowModel().rows;

  const headers = ["Player", "Circuit", "Team", "Grad", "Height", "High School", "GP", "PPG", "RPG", "APG", "FG%", "3P%", "EFF"];

  function fmtHeight(inches: number | null): string {
    if (!inches) return "";
    return `${Math.floor(inches / 12)}'${inches % 12}"`;
  }

  function fmtEff(row: PlayerStatsRow): string {
    if (row.ppg === null) return "";
    const v = (row.ppg ?? 0) + (row.rpg ?? 0) + (row.apg ?? 0) + (row.spg ?? 0) + (row.bpg ?? 0);
    return v.toFixed(1);
  }

  const csvRows = rows.map((row) => {
    const d = row.original;
    return [
      `${d.players?.last_name ?? ""}, ${d.players?.first_name ?? ""}`,
      d.teams?.circuits?.name ?? "",
      d.teams?.name ?? "",
      d.players?.grad_year ?? "",
      fmtHeight(d.players?.height_inches ?? null),
      d.players?.high_school ?? "",
      d.games_played ?? "",
      d.ppg?.toFixed(1) ?? "",
      d.rpg?.toFixed(1) ?? "",
      d.apg?.toFixed(1) ?? "",
      d.fg_pct != null ? `${(d.fg_pct * 100).toFixed(1)}%` : "",
      d.three_pt_pct != null ? `${(d.three_pt_pct * 100).toFixed(1)}%` : "",
      fmtEff(d),
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
  onCircuitChange,
  onSeasonChange,
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
        onChange={(e) => {
          const val = e.target.value;
          table.getColumn("age_division")?.setFilterValue(val || undefined);
        }}
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

      <button
        onClick={() => exportCSV(table)}
        className="flex items-center gap-1 text-xs border border-gray-300 rounded px-2 py-1 hover:bg-gray-50 text-gray-600"
        title="Export current view as CSV"
      >
        <Download className="h-3.5 w-3.5" />
        Export CSV
      </button>
    </div>
  );
}
