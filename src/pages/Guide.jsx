import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { BookOpen, Map, Code, ArrowRight, Download } from "lucide-react";
import { Button } from "@/components/ui/button";

const pythonScript = `#!/usr/bin/env python3
"""
Land Parcel Fraud Detection Script
Ehime Mbano Verification System
Usage: python fraud_detect.py parcels.json
"""
import json, sys, math

def haversine(lat1, lon1, lat2, lon2):
    R = 6371000
    p = math.pi / 180
    a = (math.sin((lat2-lat1)*p/2)**2 +
         math.cos(lat1*p) * math.cos(lat2*p) *
         math.sin((lon2-lon1)*p/2)**2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

def detect_fraud(parcels, threshold=5):
    flags = []
    for i, a in enumerate(parcels):
        for j, b in enumerate(parcels):
            if i >= j: continue
            if not all([a.get('latitude'), a.get('longitude'),
                        b.get('latitude'), b.get('longitude')]):
                continue
            dist = haversine(a['latitude'], a['longitude'],
                           b['latitude'], b['longitude'])
            if dist < 0.5:
                flags.append({
                    'parcel_a': a.get('id', i),
                    'parcel_b': b.get('id', j),
                    'reason': 'Duplicate coordinates',
                    'distance_m': round(dist, 2)
                })
            elif dist < threshold:
                flags.append({
                    'parcel_a': a.get('id', i),
                    'parcel_b': b.get('id', j),
                    'reason': 'Suspicious proximity',
                    'distance_m': round(dist, 2)
                })
            if (a.get('owner_name','').lower().strip() ==
                b.get('owner_name','').lower().strip() and dist < 50):
                flags.append({
                    'parcel_a': a.get('id', i),
                    'parcel_b': b.get('id', j),
                    'reason': 'Possible duplicate owner',
                    'distance_m': round(dist, 2)
                })
    return flags

if __name__ == '__main__':
    file = sys.argv[1] if len(sys.argv) > 1 else 'parcels.json'
    with open(file) as f:
        parcels = json.load(f)
    results = detect_fraud(parcels)
    print(f"\\n=== Fraud Detection Results ===")
    print(f"Parcels scanned: {len(parcels)}")
    print(f"Issues found: {len(results)}\\n")
    for r in results:
        print(f"  [{r['reason']}] Parcel {r['parcel_a']} <-> {r['parcel_b']} ({r['distance_m']}m)")
    if not results:
        print("  No issues detected.")
    with open('fraud_report.json', 'w') as f:
        json.dump(results, f, indent=2)
    print(f"\\nReport saved to fraud_report.json")
`;

function downloadScript() {
  const blob = new Blob([pythonScript], { type: "text/plain" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "fraud_detect.py";
  a.click();
  URL.revokeObjectURL(url);
}

const sampleOutput = `=== Fraud Detection Results ===
Parcels scanned: 6
Issues found: 3

  [Duplicate coordinates] Parcel P001 <-> P004 (0.12m)
  [Suspicious proximity] Parcel P002 <-> P005 (3.45m)
  [Possible duplicate owner] Parcel P001 <-> P004 (0.12m)

Report saved to fraud_report.json`;

export default function Guide() {
  return (
    <div className="p-4 pt-6 space-y-4">
      <div className="flex items-center gap-2 mb-2">
        <div className="w-10 h-10 rounded-xl bg-primary flex items-center justify-center">
          <BookOpen className="w-5 h-5 text-primary-foreground" />
        </div>
        <div>
          <h1 className="text-lg font-bold text-foreground leading-tight">Integration Guide</h1>
          <p className="text-xs text-muted-foreground">QGIS + Python workflow</p>
        </div>
      </div>

      {/* Workflow Overview */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm flex items-center gap-2">
            <ArrowRight className="w-4 h-4 text-primary" />
            Workflow
          </CardTitle>
        </CardHeader>
        <CardContent className="pb-4">
          <div className="flex items-center gap-2 flex-wrap text-xs">
            <Badge variant="outline" className="bg-primary/10">1. Capture</Badge>
            <ArrowRight className="w-3 h-3 text-muted-foreground" />
            <Badge variant="outline" className="bg-accent/10">2. Export CSV/JSON</Badge>
            <ArrowRight className="w-3 h-3 text-muted-foreground" />
            <Badge variant="outline" className="bg-primary/10">3. QGIS Visualize</Badge>
            <ArrowRight className="w-3 h-3 text-muted-foreground" />
            <Badge variant="outline" className="bg-destructive/10">4. Fraud Detect</Badge>
            <ArrowRight className="w-3 h-3 text-muted-foreground" />
            <Badge variant="outline" className="bg-primary/10">5. Verify</Badge>
          </div>
        </CardContent>
      </Card>

      {/* QGIS Guide */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm flex items-center gap-2">
            <Map className="w-4 h-4 text-primary" />
            QGIS Step-by-Step
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 text-sm">
          <div className="space-y-2">
            <div className="flex gap-2">
              <Badge className="bg-primary text-primary-foreground w-6 h-6 rounded-full flex items-center justify-center text-xs flex-shrink-0">1</Badge>
              <div>
                <p className="font-medium">Import Data</p>
                <p className="text-xs text-muted-foreground">
                  Export CSV from Dashboard → QGIS → Layer → Add Delimited Text Layer → Select CSV → Set X=longitude, Y=latitude → CRS: EPSG:4326
                </p>
              </div>
            </div>

            <div className="flex gap-2">
              <Badge className="bg-primary text-primary-foreground w-6 h-6 rounded-full flex items-center justify-center text-xs flex-shrink-0">2</Badge>
              <div>
                <p className="font-medium">Add Basemap</p>
                <p className="text-xs text-muted-foreground">
                  Install QuickMapServices plugin → Web → QuickMapServices → OSM Standard
                </p>
              </div>
            </div>

            <div className="flex gap-2">
              <Badge className="bg-primary text-primary-foreground w-6 h-6 rounded-full flex items-center justify-center text-xs flex-shrink-0">3</Badge>
              <div>
                <p className="font-medium">Visualize Parcels</p>
                <p className="text-xs text-muted-foreground">
                  Right-click layer → Properties → Symbology → Categorized → Column: status → Classify → Apply distinct colors for pending/verified/rejected
                </p>
              </div>
            </div>

            <div className="flex gap-2">
              <Badge className="bg-primary text-primary-foreground w-6 h-6 rounded-full flex items-center justify-center text-xs flex-shrink-0">4</Badge>
              <div>
                <p className="font-medium">Find Overlaps</p>
                <p className="text-xs text-muted-foreground">
                  Vector → Geoprocessing → Buffer (5m radius) → Vector → Geoprocessing → Intersection → Review overlapping areas
                </p>
              </div>
            </div>

            <div className="flex gap-2">
              <Badge className="bg-primary text-primary-foreground w-6 h-6 rounded-full flex items-center justify-center text-xs flex-shrink-0">5</Badge>
              <div>
                <p className="font-medium">Label Parcels</p>
                <p className="text-xs text-muted-foreground">
                  Layer Properties → Labels → Single Labels → Field: owner_name → Apply
                </p>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Python Script */}
      <Card>
        <CardHeader className="pb-2">
          <div className="flex items-center justify-between">
            <CardTitle className="text-sm flex items-center gap-2">
              <Code className="w-4 h-4 text-primary" />
              Python Fraud Detection
            </CardTitle>
            <Button size="sm" variant="outline" className="gap-1.5 h-7 text-xs" onClick={downloadScript}>
              <Download className="w-3 h-3" />
              Download .py
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          <div className="bg-foreground/5 rounded-lg p-3 overflow-x-auto">
            <pre className="text-xs text-foreground/80 whitespace-pre font-mono leading-relaxed">
              {pythonScript}
            </pre>
          </div>
          <p className="text-xs text-muted-foreground mt-2">
            <strong>Usage:</strong> Export JSON from Dashboard → Run: <code className="bg-muted px-1 py-0.5 rounded text-[10px]">python fraud_detect.py parcels.json</code>
          </p>
        </CardContent>
      </Card>

      {/* Sample Output */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">Example Output</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="bg-foreground/5 rounded-lg p-3">
            <pre className="text-xs text-foreground/80 whitespace-pre font-mono leading-relaxed">
              {sampleOutput}
            </pre>
          </div>
        </CardContent>
      </Card>

      <div className="h-8" />
    </div>
  );
}