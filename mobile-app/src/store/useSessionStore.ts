import { create } from 'zustand';
import type { Direction, ExifReadyData, VisionReadyData } from '../api/types';

interface SessionState {
  photoPath: string | null;
  device: string | null;
  exif: ExifReadyData | null;
  vision: VisionReadyData | null;
  directions: Direction[];
  sessionId: string | null;
  // 拍摄阶段进行中
  isAnalyzing: boolean;
  progressText: string;

  setPhoto: (path: string) => void;
  setExif: (d: ExifReadyData) => void;
  setVision: (d: VisionReadyData) => void;
  setDirections: (dirs: Direction[], sessionId: string) => void;
  setProgressText: (text: string) => void;
  setAnalyzing: (b: boolean) => void;
  reset: () => void;
}

const initial = {
  photoPath: null,
  device: null,
  exif: null,
  vision: null,
  directions: [],
  sessionId: null,
  isAnalyzing: false,
  progressText: '',
};

export const useSessionStore = create<SessionState>(set => ({
  ...initial,
  setPhoto: photoPath => set({ photoPath }),
  setExif: exif => set({ exif, device: exif.device_name ?? null }),
  setVision: vision => set({ vision }),
  setDirections: (directions, sessionId) =>
    set({ directions, sessionId, isAnalyzing: false }),
  setProgressText: progressText => set({ progressText }),
  setAnalyzing: isAnalyzing => set({ isAnalyzing }),
  reset: () => set(initial),
}));
