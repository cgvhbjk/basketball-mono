"use client";

import { useState } from "react";

interface Props {
  initialValue?: string;
  onSubmit: (name: string) => void;
  onCancel?: () => void;
}

export function ScoutNamePrompt({ initialValue = "", onSubmit, onCancel }: Props) {
  const [name, setName] = useState(initialValue);

  const submit = () => {
    if (name.trim()) onSubmit(name.trim());
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30">
      <div className="bg-white rounded shadow-lg p-5 w-80 flex flex-col gap-3">
        <h2 className="text-sm font-semibold">Who's scouting?</h2>
        <p className="text-xs text-gray-600">
          Your name tags entries you add to the global watchlist so other scouts
          can see who starred each player. Stored locally; change it any time.
        </p>
        <input
          autoFocus
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") submit();
            if (e.key === "Escape" && onCancel) onCancel();
          }}
          placeholder="e.g. Ben"
          className="border border-gray-300 rounded px-2 py-1 text-sm focus:outline-none focus:ring-1 focus:ring-blue-400"
        />
        <div className="flex justify-end gap-2">
          {onCancel && (
            <button
              onClick={onCancel}
              className="text-xs border border-gray-300 rounded px-3 py-1 text-gray-600 hover:bg-gray-50"
            >
              Cancel
            </button>
          )}
          <button
            onClick={submit}
            disabled={!name.trim()}
            className="text-xs bg-blue-600 text-white rounded px-3 py-1 hover:bg-blue-700 disabled:opacity-50"
          >
            Save
          </button>
        </div>
      </div>
    </div>
  );
}
