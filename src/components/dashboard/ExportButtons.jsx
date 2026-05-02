import { Button } from "@/components/ui/button";
import { Download } from "lucide-react";

function toCSV(parcels) {
  const headers = ["id", "owner_name", "phone", "latitude", "longitude", "description", "photos", "status", "confidence_score", "flags", "captured_at"];
  const rows = parcels.map((p) =>
    headers.map((h) => {
      const val = p[h];
      if (Array.isArray(val)) return `"${val.join("; ")}"`;
      if (typeof val === "string" && val.includes(",")) return `"${val}"`;
      return val ?? "";
    }).join(",")
  );
  return [headers.join(","), ...rows].join("\n");
}

function downloadFile(content, filename, mime) {
  const blob = new Blob([content], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

export default function ExportButtons({ parcels }) {
  return (
    <div className="flex gap-2">
      <Button
        variant="outline"
        size="sm"
        className="gap-1.5"
        onClick={() => downloadFile(toCSV(parcels), "parcels.csv", "text/csv")}
        disabled={parcels.length === 0}
      >
        <Download className="w-4 h-4" />
        CSV
      </Button>
      <Button
        variant="outline"
        size="sm"
        className="gap-1.5"
        onClick={() =>
          downloadFile(
            JSON.stringify(parcels, null, 2),
            "parcels.json",
            "application/json"
          )
        }
        disabled={parcels.length === 0}
      >
        <Download className="w-4 h-4" />
        JSON
      </Button>
    </div>
  );
}