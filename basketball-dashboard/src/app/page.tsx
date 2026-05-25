import { Suspense } from "react";
import { DataTable } from "@/components/players-table/data-table";
import { getPlayersWithStats, getAvailableSeasons } from "@/lib/queries/players";

export default async function HomePage({
  searchParams,
}: {
  searchParams: Promise<{ division?: string }>;
}) {
  const { division = "" } = await searchParams;

  const [data, seasons] = await Promise.all([
    getPlayersWithStats({ season: 2026, ageDivision: division || undefined }),
    getAvailableSeasons(),
  ]);

  return (
    <main className="flex flex-col h-screen p-4 gap-3">
      <header className="flex items-baseline gap-3">
        <h1 className="text-base font-bold tracking-tight">Basketball Scout Dashboard</h1>
        <span className="text-xs text-gray-400">AAU circuits · 2026</span>
      </header>

      <div className="flex-1 min-h-0">
        <Suspense fallback={null}>
          <DataTable data={data} seasons={seasons} initialDivision={division} />
        </Suspense>
      </div>
    </main>
  );
}
