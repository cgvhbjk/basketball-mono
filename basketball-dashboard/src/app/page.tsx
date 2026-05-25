import { DataTable } from "@/components/players-table/data-table";
import { getPlayersWithStats, getAvailableSeasons } from "@/lib/queries/players";

export const revalidate = 3600;

export default async function HomePage() {
  const [data, seasons] = await Promise.all([
    getPlayersWithStats({ season: 2026 }),
    getAvailableSeasons(),
  ]);

  return (
    <main className="flex flex-col h-screen p-4 gap-3">
      <header className="flex items-baseline gap-3">
        <h1 className="text-base font-bold tracking-tight">Basketball Scout Dashboard</h1>
        <span className="text-xs text-gray-400">AAU circuits · 2026</span>
      </header>

      <div className="flex-1 min-h-0">
        <DataTable data={data} seasons={seasons} />
      </div>
    </main>
  );
}
