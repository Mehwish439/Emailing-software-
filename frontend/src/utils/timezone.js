/**
 * Converts a "wall clock" date + time as entered by the user in a given
 * IANA timezone into a correct UTC ISO-8601 string, suitable for sending to
 * the backend (which stores everything in UTC per USE_TZ=True).
 *
 * Native `Date` objects have no concept of "construct this instant as seen
 * from timezone X" — only the browser's *local* timezone or UTC. We work
 * around that using the Intl API: format a guessed UTC instant back into the
 * target timezone's wall-clock representation, then correct for the
 * difference between what we wanted and what we got. This approach needs no
 * external library (no date-fns-tz / luxon).
 */
export function localDateTimeInZoneToUTC(dateStr, timeStr, timeZone) {
  // dateStr: "YYYY-MM-DD", timeStr: "HH:MM"
  const [year, month, day] = dateStr.split("-").map(Number);
  const [hour, minute] = timeStr.split(":").map(Number);

  // Initial guess: treat the wall-clock values as if they were UTC.
  let guess = Date.UTC(year, month - 1, day, hour, minute, 0);

  for (let i = 0; i < 2; i++) {
    const asSeenInZone = getZonedParts(new Date(guess), timeZone);
    const diffMs =
      Date.UTC(asSeenInZone.year, asSeenInZone.month - 1, asSeenInZone.day, asSeenInZone.hour, asSeenInZone.minute) -
      Date.UTC(year, month - 1, day, hour, minute);
    guess -= diffMs;
  }

  return new Date(guess).toISOString();
}

function getZonedParts(date, timeZone) {
  const formatter = new Intl.DateTimeFormat("en-US", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
  const parts = formatter.formatToParts(date).reduce((acc, part) => {
    acc[part.type] = part.value;
    return acc;
  }, {});
  return {
    year: Number(parts.year),
    month: Number(parts.month),
    day: Number(parts.day),
    hour: Number(parts.hour === "24" ? "0" : parts.hour),
    minute: Number(parts.minute),
  };
}

export function formatInZone(isoString, timeZone) {
  if (!isoString) return "";
  return new Intl.DateTimeFormat("en-US", {
    timeZone,
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(isoString));
}
