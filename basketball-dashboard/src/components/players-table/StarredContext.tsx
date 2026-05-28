"use client";

import { createContext, useContext } from "react";

interface StarredCtx {
  starred: Set<string>;
  toggleStar: (id: string) => void;
}

// Cells read this via useStarred() so the column definitions themselves don't
// have to close over `starred` — toggling a star then only re-renders the star
// cell whose context value changed, not the whole columns array (which would
// otherwise reset TanStack's internal state on every toggle).
export const StarredContext = createContext<StarredCtx>({
  starred: new Set(),
  toggleStar: () => {},
});

export const useStarred = () => useContext(StarredContext);
