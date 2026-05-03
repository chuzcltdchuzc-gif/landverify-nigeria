import { useState, useEffect, useCallback } from "react";

const QUEUE_KEY = "parcel_offline_queue";

export function useOfflineQueue() {
  const [isOnline, setIsOnline] = useState(navigator.onLine);
  const [queue, setQueue] = useState(() => {
    try {
      return JSON.parse(localStorage.getItem(QUEUE_KEY) || "[]");
    } catch {
      return [];
    }
  });

  useEffect(() => {
    const on = () => setIsOnline(true);
    const off = () => setIsOnline(false);
    window.addEventListener("online", on);
    window.addEventListener("offline", off);
    return () => {
      window.removeEventListener("online", on);
      window.removeEventListener("offline", off);
    };
  }, []);

  const saveToQueue = useCallback((data) => {
    const entry = { ...data, _queued_at: new Date().toISOString(), _id: crypto.randomUUID() };
    setQueue((prev) => {
      const next = [...prev, entry];
      localStorage.setItem(QUEUE_KEY, JSON.stringify(next));
      return next;
    });
    return entry;
  }, []);

  const removeFromQueue = useCallback((id) => {
    setQueue((prev) => {
      const next = prev.filter((e) => e._id !== id);
      localStorage.setItem(QUEUE_KEY, JSON.stringify(next));
      return next;
    });
  }, []);

  const clearQueue = useCallback(() => {
    localStorage.removeItem(QUEUE_KEY);
    setQueue([]);
  }, []);

  return { isOnline, queue, saveToQueue, removeFromQueue, clearQueue };
}