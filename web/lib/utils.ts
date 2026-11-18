import { clsx, type ClassValue } from "clsx";
import { createElement, type ReactElement } from "react";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/** "2026-11-19 13:05 UTC": the user's time zone, named (copy.md "Voice"). */
export function absoluteTime(d: Date): string {
  const p = Object.fromEntries(
    new Intl.DateTimeFormat("en-US", { year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23", timeZoneName: "short" })
      .formatToParts(d)
      .map((x) => [x.type, x.value]),
  );
  return `${p.year}-${p.month}-${p.day} ${p.hour}:${p.minute} ${p.timeZoneName}`;
}

const UNITS: [Intl.RelativeTimeFormatUnit, number][] = [["year", 31536e6], ["month", 2592e6], ["day", 864e5], ["hour", 36e5], ["minute", 6e4]];

/** "5 minutes ago" or "in 10 days" (under a minute: "now"). */
export function relativeTime(d: Date, now = Date.now()): string {
  const ms = d.getTime() - now;
  const rtf = new Intl.RelativeTimeFormat("en", { numeric: "auto" });
  for (const [unit, size] of UNITS) if (Math.abs(ms) >= size) return rtf.format(Math.trunc(ms / size), unit);
  return "now";
}

/** A time from the API: relative, with the absolute time and zone on hover and in the accessible
 * name; `absolute` shows the absolute form in the text (audit evidence). */
export function when(s: string | null | undefined, { absolute = false } = {}): ReactElement | string {
  if (!s) return "Never";
  const d = new Date(s.replace(" ", "T"));
  if (Number.isNaN(d.getTime())) return s;
  const abs = absoluteTime(d);
  const shown = absolute ? abs : relativeTime(d);
  return createElement(
    "time",
    { dateTime: d.toISOString(), title: abs },
    createElement("span", { "aria-hidden": true }, shown),
    createElement("span", { className: "sr-only" }, absolute ? abs : `${shown}, ${abs}`),
  );
}
