import { useState, type FormEvent } from "react";
import { createERPLocation, type ERPLocationUpsert } from "@/lib/api";

const NODE_TYPES: ERPLocationUpsert["type"][] = [
  "supplier",
  "warehouse",
  "distribution_center",
  "port",
];
const NODE_TYPE_LABEL: Record<ERPLocationUpsert["type"], string> = {
  supplier: "SUPPLIER",
  warehouse: "WAREHOUSE",
  distribution_center: "DIST CENTER",
  port: "PORT",
};

const INPUT_CLS =
  "font-mono text-[10px] bg-stone-900 border border-stone-700 text-stone-200 " +
  "px-2 py-1 w-full focus:outline-none focus:border-lime-600 placeholder-stone-600";

function TacField({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label className="flex flex-col gap-0.5">
      <span className="tac-label">{label}</span>
      {children}
    </label>
  );
}

export default function AddNodePanel({ onSuccess }: { onSuccess: () => void }) {
  const [open, setOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [feedback, setFeedback] = useState<{ ok: boolean; msg: string } | null>(
    null,
  );

  // form state
  const [name, setName] = useState("");
  const [type, setType] = useState<ERPLocationUpsert["type"]>("supplier");
  const [lat, setLat] = useState("");
  const [lon, setLon] = useState("");
  const [inv, setInv] = useState("");
  const [leadTime, setLeadTime] = useState("");

  const reset = () => {
    setName("");
    setLat("");
    setLon("");
    setInv("");
    setLeadTime("");
    setType("supplier");
    setFeedback(null);
  };

  const handleToggle = () => {
    setOpen((o) => !o);
    if (open) reset();
  };

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    setFeedback(null);
    try {
      const payload: ERPLocationUpsert = {
        name: name.trim(),
        type,
        lat: parseFloat(lat),
        lon: parseFloat(lon),
        ...(inv ? { inventory_value_usd: parseFloat(inv) } : {}),
        ...(leadTime ? { avg_lead_time_hours: parseFloat(leadTime) } : {}),
      };
      const res = await createERPLocation(payload);
      setFeedback({
        ok: true,
        msg: `${res.status.toUpperCase()} · ${res.location_id}`,
      });
      onSuccess();
      setTimeout(() => {
        reset();
        setOpen(false);
      }, 2200);
    } catch {
      setFeedback({ ok: false, msg: "ERR: SUBMISSION FAILED" });
    }
    setSubmitting(false);
  };

  return (
    <div className="border-b border-stone-800">
      {/* Toggle */}
      <button
        onClick={handleToggle}
        className="w-full flex items-center gap-2 px-3 py-2 hover:bg-stone-800 transition-colors duration-75"
      >
        <span
          className="font-mono text-[9px] text-lime-400"
          style={{ lineHeight: 1 }}
        >
          {open ? "✕" : "⊕"}
        </span>
        <span className="tac-label">{open ? "CANCEL" : "ADD ERP NODE"}</span>
      </button>

      {/* Form */}
      {open && (
        <form
          onSubmit={handleSubmit}
          className="px-3 py-2 bg-stone-950 flex flex-col gap-2"
        >
          <TacField label="NAME *">
            <input
              required
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="APEX GRAIN CO."
              className={INPUT_CLS}
              style={{ borderRadius: "1px" }}
            />
          </TacField>

          <TacField label="TYPE">
            <select
              value={type}
              onChange={(e) =>
                setType(e.target.value as ERPLocationUpsert["type"])
              }
              className={INPUT_CLS}
              style={{ borderRadius: "1px" }}
            >
              {NODE_TYPES.map((t) => (
                <option key={t} value={t}>
                  {NODE_TYPE_LABEL[t]}
                </option>
              ))}
            </select>
          </TacField>

          {/* Lat / Lon side by side */}
          <div className="flex gap-1.5">
            <TacField label="LAT *">
              <input
                required
                type="number"
                step="any"
                min={-90}
                max={90}
                value={lat}
                onChange={(e) => setLat(e.target.value)}
                placeholder="38.90"
                className={INPUT_CLS}
                style={{ borderRadius: "1px" }}
              />
            </TacField>
            <TacField label="LON *">
              <input
                required
                type="number"
                step="any"
                min={-180}
                max={180}
                value={lon}
                onChange={(e) => setLon(e.target.value)}
                placeholder="-77.03"
                className={INPUT_CLS}
                style={{ borderRadius: "1px" }}
              />
            </TacField>
          </div>

          {/* Optional fields */}
          <div className="flex gap-1.5">
            <TacField label="INV $">
              <input
                type="number"
                step="any"
                min={0}
                value={inv}
                onChange={(e) => setInv(e.target.value)}
                placeholder="optional"
                className={INPUT_CLS}
                style={{ borderRadius: "1px" }}
              />
            </TacField>
            <TacField label="LEAD HRS">
              <input
                type="number"
                step="any"
                min={0}
                value={leadTime}
                onChange={(e) => setLeadTime(e.target.value)}
                placeholder="24"
                className={INPUT_CLS}
                style={{ borderRadius: "1px" }}
              />
            </TacField>
          </div>

          {/* Feedback line */}
          {feedback && (
            <span
              className={`font-mono text-[9px] uppercase tracking-widest truncate ${
                feedback.ok ? "text-lime-400" : "text-red-500"
              }`}
            >
              {feedback.msg}
            </span>
          )}

          <button type="submit" disabled={submitting} className="tac-btn-lime">
            {submitting ? "▶ REGISTERING..." : "↑ REGISTER NODE"}
          </button>
        </form>
      )}
    </div>
  );
}
