"use client";

import { useState, useEffect, useCallback, useMemo, useRef } from "react";
import { createClient } from "@/lib/supabase/client";
import type { GlobalWatchlistRow } from "@/types/database";

// The project's `Database` type isn't a complete supabase-js shape, so typed
// calls on tables it doesn't list collapse to `never`. Drop to `any` for the
// supabase reference — runtime behavior is unchanged.
type AnyClient = any;

export interface GlobalWatchlistEntry {
  notes: string;
  status: string | null;
  starredAt: string;
  scoutName: string;
}

interface State {
  entries: Record<string, GlobalWatchlistEntry>;
  statusOptions: string[];
  loading: boolean;
  error: string | null;
}

const INITIAL: State = {
  entries: {},
  statusOptions: ["In Progress"],
  loading: true,
  error: null,
};

function rowToEntry(r: GlobalWatchlistRow): GlobalWatchlistEntry {
  return {
    notes: r.notes,
    status: r.status,
    starredAt: r.starred_at,
    scoutName: r.scout_name,
  };
}

export function useGlobalWatchlist(scoutName: string) {
  const [state, setState] = useState<State>(INITIAL);
  // The supabase client is stable for the lifetime of the component, so we
  // memoize once. Recomputing it on every render would re-open WS connections.
  const supabase = useMemo(() => createClient() as AnyClient, []);
  // Keep latest scoutName accessible in the realtime callback without forcing
  // a re-subscribe each time the name changes.
  const scoutNameRef = useRef(scoutName);
  useEffect(() => {
    scoutNameRef.current = scoutName;
  }, [scoutName]);

  const refresh = useCallback(async () => {
    const [entriesRes, optsRes] = await Promise.all([
      supabase.from("global_watchlist").select("*").order("starred_at", { ascending: false }),
      supabase.from("global_watchlist_status_options").select("label"),
    ]);
    if (entriesRes.error || optsRes.error) {
      const err = entriesRes.error ?? optsRes.error;
      console.error("[global_watchlist] refresh", err);
      setState((s) => ({
        ...s,
        loading: false,
        error: err?.message ?? "Unknown error",
      }));
      return;
    }
    const entries: Record<string, GlobalWatchlistEntry> = {};
    for (const r of (entriesRes.data ?? []) as GlobalWatchlistRow[]) {
      // Last write per player_id wins — order is starred_at desc so this puts
      // the newest entry on top. For multi-scout views we'd key by composite.
      if (!entries[r.player_id]) entries[r.player_id] = rowToEntry(r);
    }
    const opts = (optsRes.data ?? []) as { label: string }[];
    setState({
      entries,
      statusOptions:
        opts.length > 0
          ? opts.map((o) => o.label)
          : ["In Progress"],
      loading: false,
      error: null,
    });
  }, [supabase]);

  useEffect(() => {
    refresh();
    const channel = supabase
      .channel("global_watchlist_changes")
      .on(
        "postgres_changes",
        { event: "*", schema: "public", table: "global_watchlist" },
        () => refresh()
      )
      .on(
        "postgres_changes",
        { event: "*", schema: "public", table: "global_watchlist_status_options" },
        () => refresh()
      )
      .subscribe();
    return () => {
      supabase.removeChannel(channel);
    };
  }, [supabase, refresh]);

  const starred = useMemo(() => new Set(Object.keys(state.entries)), [state.entries]);

  const toggleStar = useCallback(
    async (playerId: string) => {
      const name = scoutNameRef.current;
      if (!name) return;
      const existing = state.entries[playerId];
      if (existing) {
        // Delete by composite (player_id, scout_name) — only remove this scout's
        // row even if other scouts also starred the same player.
        const { error } = await supabase
          .from("global_watchlist")
          .delete()
          .eq("player_id", playerId)
          .eq("scout_name", name);
        if (error) {
          console.error("[global_watchlist]", error);
          setState((s) => ({ ...s, error: error.message }));
          return;
        }
      } else {
        const { error } = await supabase
          .from("global_watchlist")
          .insert({ player_id: playerId, scout_name: name, notes: "", status: null });
        if (error) {
          console.error("[global_watchlist]", error);
          setState((s) => ({ ...s, error: error.message }));
          return;
        }
      }
      refresh();
    },
    [state.entries, supabase, refresh]
  );

  const setNotes = useCallback(
    async (playerId: string, notes: string) => {
      const name = scoutNameRef.current;
      if (!name) return;
      const { error } = await supabase
        .from("global_watchlist")
        .update({ notes })
        .eq("player_id", playerId)
        .eq("scout_name", name);
      if (error) {
        console.error("[global_watchlist]", error);
        setState((s) => ({ ...s, error: error.message }));
      } else refresh();
    },
    [supabase, refresh]
  );

  const setStatus = useCallback(
    async (playerId: string, status: string | null) => {
      const name = scoutNameRef.current;
      if (!name) return;
      const { error } = await supabase
        .from("global_watchlist")
        .update({ status })
        .eq("player_id", playerId)
        .eq("scout_name", name);
      if (error) {
        console.error("[global_watchlist]", error);
        setState((s) => ({ ...s, error: error.message }));
      } else refresh();
    },
    [supabase, refresh]
  );

  const addStatusOption = useCallback(
    async (label: string) => {
      const { error } = await supabase
        .from("global_watchlist_status_options")
        .insert({ label });
      // Duplicate label is fine — table PK will reject silently.
      if (error && !error.message.includes("duplicate")) {
        setState((s) => ({ ...s, error: error.message }));
        return;
      }
      refresh();
    },
    [supabase, refresh]
  );

  const removeStatusOption = useCallback(
    async (label: string) => {
      const { error } = await supabase
        .from("global_watchlist_status_options")
        .delete()
        .eq("label", label);
      if (error) {
        console.error("[global_watchlist]", error);
        setState((s) => ({ ...s, error: error.message }));
      } else refresh();
    },
    [supabase, refresh]
  );

  // Bulk-promote a list of player entries into the current scout's global list.
  // Players already present (same player_id + scout_name) are silently skipped
  // via the UNIQUE constraint. Caller can pass `notes` to carry across local
  // notes when promoting a player from local → global.
  const pushMany = useCallback(
    async (
      entries: Array<{ id: string; notes?: string }>
    ): Promise<{ added: number; skipped: number }> => {
      const name = scoutNameRef.current;
      if (!name || entries.length === 0) return { added: 0, skipped: entries.length };
      const rows = entries.map((e) => ({
        player_id: e.id,
        scout_name: name,
        notes: e.notes ?? "",
        status: null,
      }));
      // PostgREST returns clean errors only when the unique constraint is named
      // exactly right; trying a plain insert and tolerating individual
      // duplicate-row errors turns out to be more diagnostic-friendly than
      // bulk upsert. Walk one-by-one so we can keep going past duplicates.
      let added = 0;
      let skipped = 0;
      let lastError: unknown = null;
      for (const r of rows) {
        let resp: { error: unknown } = { error: null };
        try {
          resp = await supabase.from("global_watchlist").insert(r);
        } catch (thrown) {
          resp = { error: thrown };
        }
        const error = resp.error as
          | (Error & { code?: string; details?: string; hint?: string })
          | null;
        if (!error) {
          added++;
          continue;
        }
        const code = (error as { code?: string }).code ?? "";
        const message = error.message ?? "";
        if (code === "23505" || /duplicate/i.test(message)) {
          skipped++;
          continue;
        }
        lastError = error;
        // Errors from supabase-js / fetch can have non-enumerable props,
        // so reach for them by name instead of relying on enumeration.
        const ownProps = Object.getOwnPropertyNames(error);
        const ownDump: Record<string, unknown> = {};
        for (const k of ownProps) ownDump[k] = (error as unknown as Record<string, unknown>)[k];
        console.error("[global_watchlist] pushMany insert failed", {
          row: r,
          name: (error as { name?: string }).name,
          ctor: error?.constructor?.name,
          message,
          code,
          details: (error as { details?: string }).details,
          hint: (error as { hint?: string }).hint,
          status: (error as { status?: number }).status,
          ownProps,
          ownDump,
          raw: error,
        });
      }
      if (lastError) {
        const e = lastError as { message?: string; code?: string };
        const msg = e.message || e.code || "Unknown error (see console)";
        setState((s) => ({ ...s, error: `Push: ${msg}` }));
      }
      refresh();
      return { added, skipped };
    },
    [supabase, refresh]
  );

  return {
    starred,
    annotations: state.entries,
    statusOptions: state.statusOptions,
    loading: state.loading,
    error: state.error,
    toggleStar,
    setNotes,
    setStatus,
    addStatusOption,
    removeStatusOption,
    pushMany,
  };
}
