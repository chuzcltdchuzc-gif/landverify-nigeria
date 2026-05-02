// Haversine distance in meters
function haversine(lat1, lon1, lat2, lon2) {
  const R = 6371000;
  const toRad = (d) => (d * Math.PI) / 180;
  const dLat = toRad(lat2 - lat1);
  const dLon = toRad(lon2 - lon1);
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLon / 2) ** 2;
  return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

function normalizeName(name) {
  return (name || "").toLowerCase().trim().replace(/\s+/g, " ");
}

export function detectFraud(parcels, proximityThreshold = 5) {
  const results = parcels.map((p) => ({
    ...p,
    detectedFlags: [],
    relatedIds: [],
  }));

  for (let i = 0; i < results.length; i++) {
    for (let j = i + 1; j < results.length; j++) {
      const a = results[i];
      const b = results[j];

      if (a.latitude == null || b.latitude == null) continue;

      const dist = haversine(a.latitude, a.longitude, b.latitude, b.longitude);

      // Exact duplicate coordinates
      if (dist < 0.5) {
        if (!a.detectedFlags.includes("Duplicate coordinates")) {
          a.detectedFlags.push("Duplicate coordinates");
          a.relatedIds.push(b.id);
        }
        if (!b.detectedFlags.includes("Duplicate coordinates")) {
          b.detectedFlags.push("Duplicate coordinates");
          b.relatedIds.push(a.id);
        }
      }
      // Proximity conflict
      else if (dist < proximityThreshold) {
        if (!a.detectedFlags.includes("Suspicious proximity")) {
          a.detectedFlags.push("Suspicious proximity");
          a.relatedIds.push(b.id);
        }
        if (!b.detectedFlags.includes("Suspicious proximity")) {
          b.detectedFlags.push("Suspicious proximity");
          b.relatedIds.push(a.id);
        }
      }

      // Duplicate owner + close location
      if (
        normalizeName(a.owner_name) === normalizeName(b.owner_name) &&
        dist < 50
      ) {
        if (!a.detectedFlags.includes("Possible duplicate owner")) {
          a.detectedFlags.push("Possible duplicate owner");
          a.relatedIds.push(b.id);
        }
        if (!b.detectedFlags.includes("Possible duplicate owner")) {
          b.detectedFlags.push("Possible duplicate owner");
          b.relatedIds.push(a.id);
        }
      }
    }
  }

  return results;
}

export function computeConfidence(parcel) {
  let score = 50;
  if (parcel.photos?.length > 0) score += 15;
  if (parcel.photos?.length > 1) score += 5;
  if (parcel.description?.length > 20) score += 10;
  if (parcel.latitude && parcel.longitude) score += 10;
  
  const flagPenalty = (parcel.detectedFlags?.length || parcel.flags?.length || 0) * 20;
  score -= flagPenalty;

  return Math.max(0, Math.min(100, score));
}