const COMMON_TIMEZONES = [
  "Asia/Karachi",
  "Asia/Dubai",
  "Asia/Kolkata",
  "Asia/Dhaka",
  "Asia/Singapore",
  "Asia/Tokyo",
  "Europe/London",
  "Europe/Paris",
  "Europe/Berlin",
  "America/New_York",
  "America/Chicago",
  "America/Denver",
  "America/Los_Angeles",
  "Australia/Sydney",
  "UTC",
];

export default function DateTimeTimezonePicker({ date, time, timezone, onChange, error }) {
  const today = new Date().toISOString().split("T")[0];

  return (
    <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
      <div>
        <label className="label">Date</label>
        <input
          type="date"
          className="input"
          min={today}
          value={date}
          onChange={(e) => onChange({ date: e.target.value, time, timezone })}
        />
      </div>
      <div>
        <label className="label">Time</label>
        <input
          type="time"
          className="input"
          value={time}
          onChange={(e) => onChange({ date, time: e.target.value, timezone })}
        />
      </div>
      <div>
        <label className="label">Timezone</label>
        <select
          className="input"
          value={timezone}
          onChange={(e) => onChange({ date, time, timezone: e.target.value })}
        >
          {COMMON_TIMEZONES.map((tz) => (
            <option key={tz} value={tz}>
              {tz}
            </option>
          ))}
        </select>
      </div>
      {error && <p className="sm:col-span-3 text-xs text-red-600">{error}</p>}
    </div>
  );
}
