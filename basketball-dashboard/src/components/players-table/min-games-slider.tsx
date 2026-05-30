"use client";

interface Props {
  value: number;
  onChange: (v: number) => void;
  max: number;
}

export function MinGamesSlider({ value, onChange, max }: Props) {
  // Clamp the displayed value down if the data's max shrinks below it
  // (e.g. switching to a season with fewer games per player).
  const safeValue = Math.min(value, max);
  return (
    <div className="flex items-center gap-1 text-xs text-gray-600">
      <span className="whitespace-nowrap">GP ≥ {safeValue}</span>
      <input
        type="range"
        min={0}
        max={max}
        step={1}
        value={safeValue}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-24 accent-blue-600"
        title={`Hide players with fewer than ${safeValue} games`}
      />
    </div>
  );
}
