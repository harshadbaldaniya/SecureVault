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

export const CloseIcon = (props: SVGProps<SVGSVGElement>) => (
  <Icon {...props}>
    <path d="m5 5 10 10M15 5 5 15" />
  </Icon>
);

export const ShieldIcon = (props: SVGProps<SVGSVGElement>) => (
  <Icon {...props}>
    <path d="M10 2.5 4 5v4.5c0 3.6 2.4 6.3 6 8 3.6-1.7 6-4.4 6-8V5l-6-2.5Z" />
    <path d="m7.5 10 1.8 1.8L12.8 8" />
  </Icon>
);

export const KeyIcon = (props: SVGProps<SVGSVGElement>) => (
  <Icon {...props}>
    <circle cx="7" cy="12" r="3.5" />
    <path d="m9.5 9.5 7-7m-2 2 2 2m-4-.5 1.5 1.5" />
  </Icon>
);

export const NoteIcon = (props: SVGProps<SVGSVGElement>) => (
  <Icon {...props}>
    <path d="M5 2.5h7l3 3v12H5v-15Z" />
    <path d="M8 9h4m-4 3h4" />
  </Icon>
);

export const ShareIcon = (props: SVGProps<SVGSVGElement>) => (
  <Icon {...props}>
    <circle cx="5" cy="10" r="2" />
    <circle cx="15" cy="5" r="2" />
    <circle cx="15" cy="15" r="2" />
    <path d="m6.8 9 6.4-3m-6.4 5 6.4 3" />
  </Icon>
);

export const ApprovalIcon = (props: SVGProps<SVGSVGElement>) => (
  <Icon {...props}>
    <rect x="3.5" y="3.5" width="13" height="13" rx="2" />
    <path d="m7 10 2.2 2.2L13.5 8" />
  </Icon>
);

export const UsersIcon = (props: SVGProps<SVGSVGElement>) => (
  <Icon {...props}>
    <circle cx="8" cy="7" r="3" />
    <path d="M2.5 16.5c.5-3 2.6-4.5 5.5-4.5s5 1.5 5.5 4.5M13 4.3a3 3 0 0 1 0 5.4m1.5 2.5c1.6.5 2.7 1.8 3 4.3" />
  </Icon>
);

export const DeviceIcon = (props: SVGProps<SVGSVGElement>) => (
  <Icon {...props}>
    <rect x="2.5" y="4" width="15" height="10" rx="1.5" />
    <path d="M7 17h6m-3-3v3" />
  </Icon>
);

export const MenuIcon = (props: SVGProps<SVGSVGElement>) => (
  <Icon {...props}>
    <path d="M3.5 6h13M3.5 10h13M3.5 14h13" />
  </Icon>
);
