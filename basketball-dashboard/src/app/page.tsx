import { DashboardTabs } from "@/components/DashboardTabs";
import { getPlayersWithStats } from "@/lib/queries/players";

export const revalidate = 3600;

export default async function HomePage() {
  const data = await getPlayersWithStats();
  // Derive the season list from the full dataset we already loaded — avoids a
  // second full-table scan and stays consistent with the rows actually shown.
  const seasons = [...new Set(data.map((r) => r.season))].sort((a, b) => b - a);

  return (
    <main className="flex flex-col h-screen p-4 gap-2">
      <header className="flex items-baseline gap-3 shrink-0">
        <h1 className="text-base font-bold tracking-tight">Basketball Scout Dashboard</h1>
        <span className="text-xs text-gray-400">AAU circuits</span>
      </header>

      <div className="flex-1 min-h-0">
        <DashboardTabs data={data} seasons={seasons} />
      </div>
    </main>
  );
}
