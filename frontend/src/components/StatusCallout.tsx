type StatusTone = "info" | "warning" | "error";

const TONE_CLASS: Record<StatusTone, string> = {
  info: "border-sky-200 bg-sky-50 text-sky-900",
  warning: "border-amber-200 bg-amber-50 text-amber-900",
  error: "border-red-200 bg-red-50 text-red-800",
};

type StatusCalloutProps = {
  title: string;
  message: string;
  tone?: StatusTone;
};

export function StatusCallout({ title, message, tone = "info" }: StatusCalloutProps) {
  return (
    <div className={`rounded-2xl border p-4 text-sm ${TONE_CLASS[tone]}`}>
      <p className="font-semibold">{title}</p>
      <p className="mt-1">{message}</p>
    </div>
  );
}
