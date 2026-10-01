// Full-bleed backdrop for the detail page hero. The parent div renders
// .detail .backdrop (color-tinted gradient + scrim); this component
// drops a real keyart image into that slot when one exists.

type Props = {
  src: string | null;
  alt?: string;
};

export function Backdrop({ src, alt = "" }: Props) {
  if (!src) return null;
  return (
    <img
      src={src}
      alt={alt}
      aria-hidden={!alt}
      className="keyart-img"
      loading="eager"
      decoding="async"
    />
  );
}
