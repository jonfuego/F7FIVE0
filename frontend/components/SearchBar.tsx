// Client-side filter input for library pages, restyled for the Marquee
// look. Archivo, squared border, focus ring. Used by the four
// browse pages to narrow an already-loaded list locally.

"use client";

type Props = {
  value: string;
  onChange: (next: string) => void;
  placeholder?: string;
};

export function SearchBar({ value, onChange, placeholder }: Props) {
  return (
    <div
      style={{
        position: "relative",
        width: "100%",
        maxWidth: 320,
        display: "flex",
        alignItems: "center",
      }}
    >
      <input
        type="search"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder ?? "Filter…"}
        spellCheck={false}
        autoComplete="off"
        style={{
          width: "100%",
          padding: "9px 36px 9px 16px",
          background: "var(--surface-3)",
          border: "1px solid var(--line)",
          borderRadius: 999,
          fontFamily: "var(--mono)",
          fontSize: 12,
          letterSpacing: "0.06em",
          color: "var(--ink)",
          outline: "none",
        }}
      />
      {value ? (
        <button
          type="button"
          onClick={() => onChange("")}
          aria-label="Clear filter"
          style={{
            position: "absolute",
            right: 12,
            top: "50%",
            transform: "translateY(-50%)",
            padding: 4,
            fontFamily: "var(--mono)",
            fontSize: 10,
            letterSpacing: "0.18em",
            textTransform: "uppercase",
            color: "var(--ink-3)",
          }}
        >
          Clear
        </button>
      ) : null}
    </div>
  );
}

// Substring match, case-insensitive. Used by all library pages.
export function matches(query: string, haystack: string): boolean {
  const q = query.trim().toLowerCase();
  if (!q) return true;
  return haystack.toLowerCase().includes(q);
}
