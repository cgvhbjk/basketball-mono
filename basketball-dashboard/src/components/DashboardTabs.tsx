"use client";

import { useState } from "react";
import type { PlayerStatsRow } from "@/types/database";
import { DataTable } from "@/components/players-table/data-table";
import { WatchlistTab } from "@/components/watchlist/WatchlistTab";
import { useWatchlist } from "@/hooks/useWatchlist";

interface DashboardTabsProps {
  data: PlayerStatsRow[];
  seasons: number[];
}

type ActiveTab = "players" | "watchlist";

export function DashboardTabs({ data, seasons }: DashboardTabsProps) {
  const [activeTab, setActiveTab] = useState<ActiveTab>("players");
  const watchlist = useWatchlist();

  return (
    <div className="flex flex-col h-full">
      <div className="flex gap-0 border-b border-gray-200 mb-2 shrink-0">
        <TabButton
          label="Players"
          active={activeTab === "players"}
          onClick={() => setActiveTab("players")}
        />
        <TabButton
          label={watchlist.starred.size > 0 ? `Watchlist (${watchlist.starred.size})` : "Watchlist"}
          active={activeTab === "watchlist"}
          onClick={() => setActiveTab("watchlist")}
        />
      </div>

      <div className="flex-1 min-h-0">
        {activeTab === "players" ? (
          <DataTable
            data={data}
            seasons={seasons}
            starred={watchlist.starred}
            onToggleStar={watchlist.toggleStar}
          />
        ) : (
          <WatchlistTab
            data={data}
            seasons={seasons}
            starred={watchlist.starred}
            annotations={watchlist.annotations}
            statusOptions={watchlist.statusOptions}
            toggleStar={watchlist.toggleStar}
            setNotes={watchlist.setNotes}
            setStatus={watchlist.setStatus}
            addStatusOption={watchlist.addStatusOption}
          />
        )}
      </div>
    </div>
  );
}

function TabButton({
  label,
  active,
  onClick,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={`px-3 py-1.5 text-xs font-medium border-b-2 transition-colors ${
        active
          ? "border-blue-600 text-blue-600"
          : "border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300"
      }`}
    >
      {label}
    </button>
  );
}
