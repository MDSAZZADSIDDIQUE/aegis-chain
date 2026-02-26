"use client";

import { useState, useEffect, useMemo, useRef } from "react";
import { PlayIcon, PauseIcon } from "@heroicons/react/24/solid";

interface TimeSliderProps {
  onTimeChange: (offsetHours: number) => void;
  maxHours?: number;
}

export default function TimeSlider({ onTimeChange, maxHours = 72 }: TimeSliderProps) {
  const [offset, setOffset] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);

  // Hardcode the distinct hour intervals our backend calculates for simplicity
  // We include 0 for current "real-time" state
  const timeStops = useMemo(
    () => [0, 12, 24, 48, 72].filter(h => h <= maxHours),
    [maxHours]
  );

  // BUG-007: Use a ref for the callback to prevent deps instability
  const onTimeChangeRef = useRef(onTimeChange);
  onTimeChangeRef.current = onTimeChange;

  useEffect(() => {
    let interval: NodeJS.Timeout;
    if (isPlaying) {
      interval = setInterval(() => {
        setOffset((prev) => {
          const currentIndex = timeStops.indexOf(prev);
          const nextIndex = (currentIndex + 1) % timeStops.length;
          return timeStops[nextIndex];
        });
      }, 1500); // Step every 1.5 seconds
    }
    return () => clearInterval(interval);
  }, [isPlaying, timeStops]);

  useEffect(() => {
    onTimeChangeRef.current(offset);
  }, [offset]);

  const togglePlayback = () => setIsPlaying(!isPlaying);

  return (
    <div className="absolute bottom-10 left-1/2 -translate-x-1/2 z-[40] w-full max-w-lg">
      <div className="bg-slate-900/95 border border-slate-700/50 backdrop-blur-md px-6 py-4 rounded-xl shadow-2xl flex flex-col gap-4">
        
        {/* Header / Play Controls */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <button
              onClick={togglePlayback}
              className="p-2 bg-slate-800 hover:bg-slate-700 text-teal-400 rounded-full transition-colors border border-slate-700/50"
              title={isPlaying ? "Pause Simulation" : "Play Simulation"}
            >
              {isPlaying ? (
                <PauseIcon className="w-5 h-5" />
              ) : (
                <PlayIcon className="w-5 h-5" />
              )}
            </button>
            <div>
              <h3 className="text-slate-200 text-sm font-semibold tracking-wide flex items-center gap-2">
                Temporal Threat Simulation
                <span className="bg-teal-500/10 text-teal-400 px-2 py-0.5 rounded text-[10px] uppercase font-bold tracking-wider border border-teal-500/20">
                  Predictive
                </span>
              </h3>
              <p className="text-slate-500 text-xs mt-0.5">
                {offset === 0 ? "Current Live Conditions" : `T + ${offset} Hours Simulated Projection`}
              </p>
            </div>
          </div>
          <div className="text-3xl font-bold bg-gradient-to-br from-slate-100 to-slate-400 bg-clip-text text-transparent font-mono">
            {offset === 0 ? "LIVE" : `+${offset}h`}
          </div>
        </div>

        {/* Range Slider */}
        <div className="w-full relative py-2">
          {/* Track background */}
          <div className="absolute top-1/2 left-0 right-0 h-1.5 -translate-y-1/2 bg-slate-800 rounded-full overflow-hidden">
             <div 
                className="h-full bg-gradient-to-r from-teal-500 to-emerald-400 transition-all duration-300 ease-out"
                style={{ width: `${(timeStops.indexOf(offset) / Math.max(timeStops.length - 1, 1)) * 100}%` }}
             ></div>
          </div>
          
          <input
            type="range"
            min={0}
            max={timeStops.length - 1}
            step={1}
            value={timeStops.indexOf(offset)}
            onChange={(e) => setOffset(timeStops[parseInt(e.target.value)])}
            className="w-full absolute top-1/2 -translate-y-1/2 appearance-none bg-transparent outline-none cursor-pointer z-10"
            style={{
               WebkitAppearance: "none",
            }}
          />
          
          <style dangerouslySetInnerHTML={{ __html: `
            input[type='range']::-webkit-slider-thumb {
              -webkit-appearance: none;
              height: 20px;
              width: 20px;
              border-radius: 50%;
              background: #f8fafc;
              border: 3px solid #14b8a6;
              box-shadow: 0 0 10px rgba(20, 184, 166, 0.5);
              cursor: pointer;
              transition: transform 0.1s;
            }
            input[type='range']::-webkit-slider-thumb:hover {
              transform: scale(1.15);
            }
            input[type='range']::-moz-range-thumb {
              height: 20px;
              width: 20px;
              border-radius: 50%;
              background: #f8fafc;
              border: 3px solid #14b8a6;
              box-shadow: 0 0 10px rgba(20, 184, 166, 0.5);
              cursor: pointer;
              transition: transform 0.1s;
            }
          `}} />

          {/* Time markers */}
          <div className="absolute top-full left-0 right-0 mt-3 flex justify-between pointer-events-none px-[10px]">
            {timeStops.map((stop, idx) => (
              <div 
                key={stop} 
                className={`flex flex-col items-center transition-colors duration-300 ${offset >= stop ? "text-teal-400" : "text-slate-600"}`}
                style={{
                  position: "absolute",
                  left: `${(idx / Math.max(timeStops.length - 1, 1)) * 100}%`,
                  transform: "translateX(-50%)",
                }}
              >
                <div className={`w-1 h-2 mb-1 rounded-sm ${offset >= stop ? "bg-teal-400" : "bg-slate-700"}`}></div>
                <span className="text-[10px] font-bold font-mono tracking-wider">
                  {stop === 0 ? "NOW" : `+${stop}H`}
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
