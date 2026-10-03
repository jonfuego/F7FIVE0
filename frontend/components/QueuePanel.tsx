// Right-side drawer surfaced by the MiniPlayer. Lists the queue,
// highlights the current row, and exposes jump-to / remove / clear plus
// Shuffle and Repeat (off → all → one) controls. Rows are
// drag-to-reorder via @dnd-kit/sortable; native HTML5 drag does not
// fire on touch devices, so the pointer-event-driven kit is required
// for mobile.

"use client";

import {
  DndContext,
  KeyboardSensor,
  PointerSensor,
  closestCenter,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import {
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import Link from "next/link";
import { useEffect, useRef, useState, type CSSProperties } from "react";
import { GripVertical, X } from "lucide-react";
import { Icon } from "@/components/Icon";
import { apiGet } from "@/lib/client-api";
import {
  useQueue,
  type QueueItem,
  type RepeatMode,
} from "@/lib/queue";

type Props = {
  open: boolean;
  onClose: () => void;
};

export function QueuePanel({ open, onClose }: Props) {
  const {
    items,
    currentIndex,
    repeat,
    shuffle,
    skipTo,
    removeAt,
    reorder,
    clear,
    setRepeat,
    setShuffle,
  } = useQueue();

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );

  if (!open) return null;

  const cycleRepeat = () => {
    const order: RepeatMode[] = ["off", "all", "one"];
    const i = order.indexOf(repeat);
    setRepeat(order[(i + 1) % order.length]);
  };
  const repeatLabel =
    repeat === "off" ? "Off" : repeat === "all" ? "All" : "One";

  const handleRemove = (e: React.MouseEvent, index: number) => {
    e.stopPropagation();
    removeAt(index);
  };

  const onDragEnd = (event: DragEndEvent) => {
    const { active, over } = event;
    if (!over || active.id === over.id) return;
    const from = items.findIndex((_, i) => rowKey(items[i], i) === active.id);
    const to = items.findIndex((_, i) => rowKey(items[i], i) === over.id);
    if (from === -1 || to === -1) return;
    // The reducer is the single source of truth for currentIndex
    // adjustment; we forward from/to and let it fix the index so the
    // currently playing track stays correct after the move.
    reorder(from, to);
  };

  const ids = items.map((item, i) => rowKey(item, i));

  return (
    <div className="fixed inset-0 z-50">
      <div
        className="absolute inset-0 bg-black/50"
        aria-hidden="true"
        onClick={onClose}
      />
      <aside
        role="dialog"
        aria-label="Queue"
        className="absolute right-0 top-0 flex h-full w-full max-w-md flex-col border-l border-neutral-800 bg-neutral-950 shadow-2xl"
      >
        <header className="flex items-center justify-between gap-2 border-b border-neutral-800 px-4 py-3">
          <h2 className="text-sm font-semibold text-neutral-100">Queue</h2>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setShuffle(!shuffle)}
              aria-pressed={shuffle}
              className={`rounded-md border px-2.5 py-1 text-xs transition ${
                shuffle
                  ? "border-hive bg-hive-tint text-hive-text"
                  : "border-neutral-800 text-neutral-300 hover:border-neutral-600 hover:text-white"
              }`}
            >
              Shuffle: {shuffle ? "On" : "Off"}
            </button>
            <button
              type="button"
              onClick={cycleRepeat}
              aria-pressed={repeat !== "off"}
              className={`rounded-md border px-2.5 py-1 text-xs transition ${
                repeat !== "off"
                  ? "border-hive bg-hive-tint text-hive-text"
                  : "border-neutral-800 text-neutral-300 hover:border-neutral-600 hover:text-white"
              }`}
            >
              Repeat: {repeatLabel}
            </button>
            <button
              type="button"
              onClick={clear}
              className="rounded-md border border-neutral-800 px-2.5 py-1 text-xs text-neutral-300 transition hover:border-neutral-600 hover:text-white"
            >
              Clear
            </button>
            <button
              type="button"
              onClick={onClose}
              aria-label="Close queue"
              className="rounded-md border border-neutral-800 px-2.5 py-1 text-xs text-neutral-300 transition hover:border-neutral-600 hover:text-white"
            >
              Close
            </button>
          </div>
        </header>

        <div className="flex-1 overflow-y-auto">
          {items.length === 0 ? (
            <div className="px-4 py-6 text-sm text-neutral-500">
              Queue is empty.
            </div>
          ) : (
            <DndContext
              sensors={sensors}
              collisionDetection={closestCenter}
              onDragEnd={onDragEnd}
            >
              <SortableContext items={ids} strategy={verticalListSortingStrategy}>
                <ul className="divide-y divide-neutral-900">
                  {items.map((item, i) => (
                    <SortableRow
                      key={ids[i]}
                      id={ids[i]}
                      item={item}
                      index={i}
                      active={i === currentIndex}
                      onJump={() => skipTo(i)}
                      onRemove={(e) => handleRemove(e, i)}
                    />
                  ))}
                </ul>
              </SortableContext>
            </DndContext>
          )}
        </div>
      </aside>
    </div>
  );
}

function rowKey(item: QueueItem, index: number): string {
  return `${item.media_file_id}-${index}`;
}

type SortableRowProps = {
  id: string;
  item: QueueItem;
  index: number;
  active: boolean;
  onJump: () => void;
  onRemove: (e: React.MouseEvent) => void;
};

function SortableRow({ id, item, active, onJump, onRemove }: SortableRowProps) {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id });
  const { playNext, playNextBlock, addToQueue } = useQueue();
  const [menuOpen, setMenuOpen] = useState(false);
  const menuWrapRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!menuOpen) return;
    function onDocClick(e: MouseEvent) {
      if (!menuWrapRef.current) return;
      if (!menuWrapRef.current.contains(e.target as Node)) {
        setMenuOpen(false);
      }
    }
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, [menuOpen]);

  const style: CSSProperties = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.7 : 1,
  };
  const artistHref = item.artist_id ? `/music/artists/${item.artist_id}` : null;
  const albumHref = item.album_id ? `/music/${item.album_id}` : null;

  function onRowKeyDown(e: React.KeyboardEvent<HTMLDivElement>) {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      onJump();
    }
  }

  function toggleMenu(e: React.MouseEvent) {
    e.stopPropagation();
    setMenuOpen((v) => !v);
  }

  function onPlayNext(e: React.MouseEvent) {
    e.stopPropagation();
    setMenuOpen(false);
    playNext(item);
  }

  function onAddToQueue(e: React.MouseEvent) {
    e.stopPropagation();
    setMenuOpen(false);
    addToQueue([item]);
  }

  async function onPlayAlbumNext(e: React.MouseEvent) {
    e.stopPropagation();
    setMenuOpen(false);
    if (!item.album_id) return;
    try {
      const album = await apiGet<{
        tracks: Array<{
          id: string;
          title: string;
          duration_sec: number | null;
          media_files: Array<{ id: string }>;
        }>;
        id: string;
        title: string;
        artist_id: string;
        artist_name: string | null;
        cover_path: string | null;
      }>(`/api/library/albums/${item.album_id}`);
      const block: QueueItem[] = [];
      for (const t of album.tracks) {
        const file = t.media_files[0];
        if (!file) continue;
        block.push({
          media_file_id: file.id,
          title: t.title,
          artist_name: album.artist_name,
          album_title: album.title,
          cover_path: album.cover_path,
          duration_sec: t.duration_sec,
          track_id: t.id,
          artist_id: album.artist_id,
          album_id: album.id,
        });
      }
      if (block.length > 0) playNextBlock(block);
    } catch {
      // best-effort
    }
  }

  async function onArtistRadioNext(e: React.MouseEvent) {
    e.stopPropagation();
    setMenuOpen(false);
    if (!item.artist_id) return;
    try {
      const data = await apiGet<{ items: QueueItem[] }>(
        `/api/library/auto-playlist/artist-radio/${item.artist_id}`,
      );
      if (Array.isArray(data.items) && data.items.length > 0) {
        playNextBlock(data.items);
      }
    } catch {
      // best-effort
    }
  }

  return (
    <li ref={setNodeRef} style={style}>
      <div
        className={`flex items-center gap-2 px-2 py-2.5 ${
          active ? "bg-hive-tint" : "hover:bg-neutral-900/60"
        }`}
      >
        <button
          type="button"
          aria-label="Drag to reorder"
          {...attributes}
          {...listeners}
          className="cursor-grab touch-none px-1 py-1 text-neutral-500 hover:text-neutral-200"
        >
          <GripIcon />
        </button>
        <div
          role="button"
          tabIndex={0}
          onClick={onJump}
          onKeyDown={onRowKeyDown}
          aria-label={`Play ${item.title}`}
          className="flex min-w-0 flex-1 cursor-pointer items-center gap-3 text-left"
        >
          {item.cover_path ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={item.cover_path}
              alt=""
              className="h-10 w-10 shrink-0 rounded object-cover"
            />
          ) : (
            <div
              aria-hidden="true"
              className="h-10 w-10 shrink-0 rounded bg-neutral-900"
            />
          )}
          <div className="min-w-0 flex-1">
            <div
              className={`truncate text-sm ${
                active ? "text-hive-text" : "text-neutral-100"
              }`}
            >
              {item.title}
            </div>
            <div className="truncate text-xs text-neutral-500">
              {artistHref ? (
                <Link
                  href={artistHref}
                  onClick={(e) => e.stopPropagation()}
                  className="text-neutral-400 hover:text-hive-text hover:underline"
                >
                  {item.artist_name ?? "Unknown artist"}
                </Link>
              ) : (
                <span>{item.artist_name ?? "Unknown artist"}</span>
              )}
              {item.album_title ? (
                <>
                  {" · "}
                  {albumHref ? (
                    <Link
                      href={albumHref}
                      onClick={(e) => e.stopPropagation()}
                      className="text-neutral-400 hover:text-hive-text hover:underline"
                    >
                      {item.album_title}
                    </Link>
                  ) : (
                    <span>{item.album_title}</span>
                  )}
                </>
              ) : null}
            </div>
          </div>
        </div>
        <div ref={menuWrapRef} className="relative flex-shrink-0">
          <button
            type="button"
            onClick={toggleMenu}
            aria-label="Track actions"
            aria-haspopup="menu"
            aria-expanded={menuOpen}
            className="rounded-md px-2 py-1 font-sans text-base leading-none text-neutral-400 transition hover:bg-neutral-900 hover:text-neutral-100"
          >
            ⋮
          </button>
          {menuOpen ? (
            <div
              role="menu"
              onClick={(e) => e.stopPropagation()}
              className="absolute right-0 top-full z-10 mt-1 min-w-[180px] rounded-md border border-neutral-800 bg-neutral-950 text-sm text-neutral-100 shadow-lg"
            >
              <button
                type="button"
                role="menuitem"
                onClick={onPlayNext}
                className="block w-full px-3 py-2 text-left hover:bg-neutral-900"
              >
                Play next
              </button>
              <button
                type="button"
                role="menuitem"
                onClick={onPlayAlbumNext}
                disabled={!item.album_id}
                className="block w-full px-3 py-2 text-left hover:bg-neutral-900 disabled:cursor-not-allowed disabled:opacity-40"
              >
                Play album next
              </button>
              <button
                type="button"
                role="menuitem"
                onClick={onArtistRadioNext}
                disabled={!item.artist_id}
                className="block w-full px-3 py-2 text-left hover:bg-neutral-900 disabled:cursor-not-allowed disabled:opacity-40"
              >
                Artist radio next
              </button>
              <button
                type="button"
                role="menuitem"
                onClick={onAddToQueue}
                className="block w-full px-3 py-2 text-left hover:bg-neutral-900"
              >
                Add to queue
              </button>
            </div>
          ) : null}
        </div>
        <button
          type="button"
          onClick={onRemove}
          aria-label={`Remove ${item.title}`}
          className="rounded-md p-1 text-neutral-500 transition hover:bg-neutral-900 hover:text-red-400"
        >
          <CloseIcon />
        </button>
      </div>
    </li>
  );
}

function CloseIcon() {
  return <Icon icon={X} size={16} />;
}

function GripIcon() {
  return <Icon icon={GripVertical} size={14} />;
}
