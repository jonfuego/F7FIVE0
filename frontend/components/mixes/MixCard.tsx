// One playbill on the /mixes record-store wall. Two flavors:
//
//   - Non-parameterized: "Play" CTA hits the endpoint and hands the
//     items to playAlbum. A secondary "+ Queue" appends without
//     replacing the queue.
//
//   - Parameterized: tapping Play flips the body into a small inline
//     picker (year, artist UUID, genre slug). State lives in useState,
//     no URL sync.
//
// `kind` is wired to the playbill's data-kind attribute so per-kind CSS
// in globals.css can give each tile a distinct typographic treatment via
// display-cap variations only.

"use client";

import { useCallback, useState } from "react";
import { apiGet, ApiError } from "@/lib/client-api";
import { useQueue, type QueueItem } from "@/lib/queue";
import { hasMixArt, type MixArtMap } from "@/lib/mix-art";
import { MixPicture } from "@/components/mixes/MixPicture";

type MixResponse = {
  kind: string;
  params?: Record<string, unknown>;
  items: QueueItem[];
};

export type MixCardProps = {
  kind: string;
  tag: string;
  title: string;
  description: string;
  buildUrl: (input?: PickerInput) => string | null;
  picker?: PickerSpec;
  index: number;
  /** Picker values used last time for this mix (saved view), and where to
   * save them after a successful play or add. */
  savedValues?: PickerInput;
  onSaveValues?: (values: PickerInput) => void;
  /** Picture overrides by mix key, whether the viewer is an admin (edit
   * control), and a refresh after an edit. Only the four home mixes have a
   * picture; the rest keep the typographic art. */
  mixArt?: MixArtMap;
  isAdmin?: boolean;
  onArtChanged?: () => void;
};

type PickerInput = Record<string, string>;

type PickerSpec = {
  fields: PickerField[];
};

type PickerField =
  | { kind: "text"; name: string; label: string; placeholder?: string }
  | { kind: "number"; name: string; label: string; placeholder?: string; min?: number; max?: number };

export function MixCard({
  kind,
  tag,
  title,
  description,
  buildUrl,
  picker,
  index,
  savedValues,
  onSaveValues,
  mixArt,
  isAdmin,
  onArtChanged,
}: MixCardProps) {
  const { playAlbum, addToQueue } = useQueue();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [pickerValues, setPickerValues] = useState<PickerInput>({});
  // Opening the picker starts from the values used last time (a saved view).
  const openPicker = useCallback(() => {
    setPickerValues((cur) => (Object.keys(cur).length === 0 && savedValues ? { ...savedValues } : cur));
    setPickerOpen(true);
  }, [savedValues]);

  const fetchItems = useCallback(
    async (input?: PickerInput): Promise<QueueItem[] | null> => {
      const url = buildUrl(input);
      if (!url) {
        setError("Fill in the field above first.");
        return null;
      }
      setBusy(true);
      setError(null);
      try {
        const data = await apiGet<MixResponse>(url);
        if (!Array.isArray(data?.items) || data.items.length === 0) {
          setError("Nothing to play for that selection.");
          return null;
        }
        return data.items;
      } catch (err) {
        setError(
          err instanceof ApiError
            ? `Failed (${err.status}).`
            : err instanceof Error
              ? err.message
              : "Failed",
        );
        return null;
      } finally {
        setBusy(false);
      }
    },
    [buildUrl],
  );

  const onPlay = useCallback(async () => {
    if (picker && !pickerOpen) {
      openPicker();
      return;
    }
    const items = await fetchItems(picker ? pickerValues : undefined);
    if (items) {
      if (picker) onSaveValues?.(pickerValues);
      playAlbum(items, { shuffle: false });
      setPickerOpen(false);
    }
  }, [fetchItems, picker, pickerOpen, pickerValues, playAlbum, openPicker, onSaveValues]);

  const onAdd = useCallback(async () => {
    if (picker && !pickerOpen) {
      openPicker();
      return;
    }
    const items = await fetchItems(picker ? pickerValues : undefined);
    if (items) {
      if (picker) onSaveValues?.(pickerValues);
      addToQueue(items);
      setPickerOpen(false);
    }
  }, [addToQueue, fetchItems, picker, pickerOpen, pickerValues, openPicker, onSaveValues]);

  return (
    <div className="playbill" data-kind={kind} role="group" aria-label={title}>
      <div className="pb-art">
        {hasMixArt(kind) ? (
          <MixPicture
            mixKey={kind}
            title={title}
            overrides={mixArt ?? {}}
            isAdmin={Boolean(isAdmin)}
            onChanged={onArtChanged ?? (() => {})}
          />
        ) : (
          <>
            <div className="big-num">{String(index).padStart(2, "0")}</div>
            <div className="num-stamp">{tag}</div>
          </>
        )}
      </div>
      <div className="pb-body">
        <div className="pb-tag">{tag}</div>
        <h3>{title}</h3>
        <p className="pb-sub">{description}</p>

        {picker && pickerOpen ? (
          <PickerInputs
            spec={picker}
            values={pickerValues}
            onChange={setPickerValues}
          />
        ) : null}

        <div
          style={{
            display: "flex",
            gap: 10,
            flexWrap: "wrap",
            alignItems: "center",
          }}
        >
          <button
            type="button"
            onClick={onPlay}
            disabled={busy}
            className="btn play"
            style={{ padding: "10px 18px", fontSize: 13 }}
          >
            <span className="tri" />
            {busy ? "..." : picker && !pickerOpen ? "Choose" : "Play"}
          </button>
          <button
            type="button"
            onClick={onAdd}
            disabled={busy}
            className="btn ghost"
            style={{ padding: "10px 16px", fontSize: 12 }}
          >
            + Queue
          </button>
          {picker && pickerOpen ? (
            <button
              type="button"
              onClick={() => {
                setPickerOpen(false);
                setError(null);
              }}
              style={{
                fontFamily: "var(--mono)",
                fontSize: 11,
                letterSpacing: "0.16em",
                textTransform: "uppercase",
                color: "var(--ink-3)",
                padding: "10px 6px",
              }}
            >
              Cancel
            </button>
          ) : null}
        </div>

        {error ? (
          <div
            style={{
              fontFamily: "var(--mono)",
              fontSize: 11,
              color: "var(--danger)",
              letterSpacing: "0.06em",
            }}
          >
            {error}
          </div>
        ) : null}

        <div className="pb-foot">
          <span>Auto-playlist</span>
        </div>
      </div>
    </div>
  );
}

function PickerInputs({
  spec,
  values,
  onChange,
}: {
  spec: PickerSpec;
  values: PickerInput;
  onChange: (next: PickerInput) => void;
}) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      {spec.fields.map((f) => (
        <label
          key={f.name}
          style={{ display: "flex", flexDirection: "column", gap: 4 }}
        >
          <span
            style={{
              fontFamily: "var(--mono)",
              fontSize: 10,
              letterSpacing: "0.18em",
              textTransform: "uppercase",
              color: "var(--ink-3)",
            }}
          >
            {f.label}
          </span>
          <input
            type={f.kind === "number" ? "number" : "text"}
            value={values[f.name] ?? ""}
            onChange={(e) =>
              onChange({ ...values, [f.name]: e.currentTarget.value })
            }
            placeholder={"placeholder" in f ? f.placeholder : undefined}
            min={f.kind === "number" ? f.min : undefined}
            max={f.kind === "number" ? f.max : undefined}
            style={{
              padding: "8px 12px",
              background: "var(--surface-1)",
              border: "1px solid var(--line)",
              borderRadius: 3,
              color: "var(--ink)",
              fontFamily: "var(--mono)",
              fontSize: 12,
              outline: "none",
            }}
          />
        </label>
      ))}
    </div>
  );
}
