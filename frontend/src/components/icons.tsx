import type { SVGProps } from "react";

/* Small inline icons (decorative: the action's text is its accessible name). One stroke style and size so they align. */

function Icon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg
      viewBox="0 0 20 20"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.75}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      {...props}
      className={`size-4 shrink-0 ${props.className ?? ""}`}
    />
  );
}

export const ArrowLeftIcon = (props: SVGProps<SVGSVGElement>) => (
  <Icon {...props}>
    <path d="M16 10H4m0 0 5-5m-5 5 5 5" />
  </Icon>
);

export const DownloadIcon = (props: SVGProps<SVGSVGElement>) => (
  <Icon {...props}>
    <path d="M10 3v10m0 0 4-4m-4 4-4-4M4 16h12" />
  </Icon>
);

export const UploadIcon = (props: SVGProps<SVGSVGElement>) => (
  <Icon {...props}>
    <path d="M10 13V3m0 0L6 7m4-4 4 4M4 16h12" />
  </Icon>
);

export const DocumentIcon = (props: SVGProps<SVGSVGElement>) => (
  <Icon {...props}>
    <path d="M6 2.5h5.5L15 6v11.5H6zM11 2.5V6h4M8.5 10h4M8.5 13h4" />
  </Icon>
);
