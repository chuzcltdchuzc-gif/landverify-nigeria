import { MapContainer, TileLayer, CircleMarker, Popup } from "react-leaflet";
import "leaflet/dist/leaflet.css";
import { Badge } from "@/components/ui/badge";

const statusColor = {
  pending: "#f97316",
  verified: "#16a34a",
  rejected: "#dc2626",
  under_review: "#0ea5e9",
};

export default function ParcelMap({ parcels }) {
  const mapped = parcels.filter((p) => p.latitude && p.longitude);

  const center =
    mapped.length > 0
      ? [
          mapped.reduce((s, p) => s + p.latitude, 0) / mapped.length,
          mapped.reduce((s, p) => s + p.longitude, 0) / mapped.length,
        ]
      : [5.68, 7.33]; // Ehime Mbano default

  return (
    <div className="rounded-xl overflow-hidden border border-border" style={{ height: 340 }}>
      <MapContainer
        center={center}
        zoom={mapped.length > 0 ? 14 : 10}
        style={{ height: "100%", width: "100%" }}
        scrollWheelZoom={false}
      >
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OSM</a>'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        {mapped.map((p) => (
          <CircleMarker
            key={p.id}
            center={[p.latitude, p.longitude]}
            radius={8}
            pathOptions={{
              color: statusColor[p.status] || "#6b7280",
              fillColor: statusColor[p.status] || "#6b7280",
              fillOpacity: 0.85,
              weight: 2,
            }}
          >
            <Popup>
              <div className="text-xs space-y-0.5 min-w-[140px]">
                <p className="font-semibold text-sm">{p.owner_name}</p>
                <p className="text-gray-500">{p.phone}</p>
                <p className="text-gray-500">
                  {p.latitude.toFixed(5)}, {p.longitude.toFixed(5)}
                </p>
                <span
                  className="inline-block mt-1 px-2 py-0.5 rounded-full text-white text-[10px] font-medium"
                  style={{ background: statusColor[p.status] || "#6b7280" }}
                >
                  {p.status}
                </span>
                {p.flags?.length > 0 && (
                  <p className="text-red-500 font-medium">⚠ {p.flags[0]}</p>
                )}
              </div>
            </Popup>
          </CircleMarker>
        ))}
      </MapContainer>

      {/* Legend */}
      <div className="flex flex-wrap gap-3 px-3 py-2 bg-card border-t border-border text-[10px] text-muted-foreground">
        {Object.entries(statusColor).map(([s, c]) => (
          <span key={s} className="flex items-center gap-1">
            <span className="w-2.5 h-2.5 rounded-full inline-block" style={{ background: c }} />
            {s.replace("_", " ")}
          </span>
        ))}
      </div>
    </div>
  );
}