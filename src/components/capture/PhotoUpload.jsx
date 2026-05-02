import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Camera, X, Loader2, ImagePlus } from "lucide-react";
import { base44 } from "@/api/base44Client";

export default function PhotoUpload({ photos, onPhotosChange }) {
  const [uploading, setUploading] = useState(false);

  const handleUpload = async (e) => {
    const files = Array.from(e.target.files);
    if (files.length === 0) return;

    setUploading(true);
    const newPhotos = [...photos];

    for (const file of files) {
      const { file_url } = await base44.integrations.Core.UploadFile({ file });
      newPhotos.push(file_url);
    }

    onPhotosChange(newPhotos);
    setUploading(false);
    e.target.value = "";
  };

  const removePhoto = (index) => {
    onPhotosChange(photos.filter((_, i) => i !== index));
  };

  return (
    <div className="space-y-2">
      <label className="text-sm font-medium text-foreground">
        Photos <span className="text-destructive">*</span>
        <span className="text-muted-foreground text-xs ml-1">(min 1)</span>
      </label>

      {photos.length > 0 && (
        <div className="flex gap-2 flex-wrap">
          {photos.map((url, i) => (
            <div key={i} className="relative w-20 h-20 rounded-lg overflow-hidden border border-border">
              <img src={url} alt={`Photo ${i + 1}`} className="w-full h-full object-cover" />
              <button
                type="button"
                onClick={() => removePhoto(i)}
                className="absolute top-0.5 right-0.5 bg-destructive text-destructive-foreground rounded-full w-5 h-5 flex items-center justify-center"
              >
                <X className="w-3 h-3" />
              </button>
            </div>
          ))}
        </div>
      )}

      <label className="block">
        <input
          type="file"
          accept="image/*"
          capture="environment"
          multiple
          onChange={handleUpload}
          className="hidden"
          disabled={uploading}
        />
        <div className="flex items-center justify-center gap-2 h-14 rounded-lg border-2 border-dashed border-border bg-muted/50 text-muted-foreground cursor-pointer hover:border-primary hover:text-primary transition-colors text-base font-medium">
          {uploading ? (
            <>
              <Loader2 className="w-5 h-5 animate-spin" />
              Uploading...
            </>
          ) : (
            <>
              <Camera className="w-5 h-5" />
              Take Photo or Upload
            </>
          )}
        </div>
      </label>
    </div>
  );
}