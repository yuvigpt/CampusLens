import { useState } from 'react';
import { X, MapPin, Sparkles, Shield, AlertTriangle, Cpu, CheckCircle } from 'lucide-react';
import { RobotAvatar } from './BrandIcons.jsx';

/**
 * Interactive Campus Map Modal showing IIT Kanpur campus landmarks & active issue pins.
 */
export function CampusMapModal({ isOpen, onClose }) {
  const [selectedPin, setSelectedPin] = useState(null);

  if (!isOpen) return null;

  const PINS = [
    { id: 1, x: '35%', y: '42%', title: 'Water leakage in Ganga Hostel', area: 'Ganga Hostel', status: 'In Progress', type: 'Plumbing' },
    { id: 2, x: '52%', y: '28%', title: 'Broken fan regulator', area: 'Hall 12, Block A', status: 'Resolved', type: 'Electrical' },
    { id: 3, x: '68%', y: '58%', title: 'Lighting fault in corridor', area: 'Academic Area (Library)', status: 'Under Review', type: 'Electrical' },
    { id: 4, x: '24%', y: '70%', title: 'Slow Wi-Fi hotspot', area: 'Hall 4 Common Room', status: 'Reported', type: 'IT/Network' },
    { id: 5, x: '78%', y: '35%', title: 'Mess water cooler maintenance', area: 'Hall 3 Dining', status: 'In Progress', type: 'Sanitation' },
  ];

  return (
    <div 
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/60 backdrop-blur-sm animate-fade-in"
      role="dialog"
      aria-modal="true"
      aria-labelledby="map-modal-title"
      onClick={onClose}
    >
      <div 
        className="bg-white rounded-2xl max-w-4xl w-full shadow-2xl border border-slate-200 overflow-hidden flex flex-col max-h-[90vh]"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Modal Header */}
        <div className="p-5 border-b border-slate-200 flex items-center justify-between bg-slate-50">
          <div className="flex items-center gap-2.5">
            <div className="p-2 rounded-xl bg-blue-50 text-blue-600">
              <MapPin className="w-5 h-5" />
            </div>
            <div>
              <h3 id="map-modal-title" className="text-lg font-bold text-slate-900">IIT Kanpur Campus Issue Map</h3>
              <p className="text-xs text-slate-500">Live geographic distribution of reported complaints</p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close map"
            className="p-2 rounded-lg text-slate-400 hover:text-slate-700 hover:bg-slate-200/60 transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Modal Body / Map Canvas */}
        <div className="relative p-6 flex-1 flex flex-col overflow-hidden bg-slate-100">
          {/* Simulated stylized Campus Map Grid */}
          <div className="relative w-full h-[400px] rounded-xl overflow-hidden border border-slate-300 bg-[#e2e8f0] shadow-inner select-none">
            {/* Map terrain textures & roads */}
            <div className="absolute inset-0 opacity-40 bg-[radial-gradient(#94a3b8_1px,transparent_1px)] [background-size:16px_16px]" />
            <div className="absolute top-1/2 left-0 right-0 h-10 bg-slate-300/80 -rotate-3" />
            <div className="absolute top-0 bottom-0 left-1/3 w-8 bg-slate-300/80 rotate-6" />
            <div className="absolute top-0 bottom-0 right-1/4 w-8 bg-slate-300/80 -rotate-12" />

            {/* Campus Zones / Blocks */}
            <div className="absolute top-6 left-12 p-3 bg-white/70 rounded-lg border border-slate-300 text-xs font-semibold text-slate-700 shadow-sm">
              Hostel Zone (Halls 1-14)
            </div>
            <div className="absolute top-16 right-16 p-3 bg-white/70 rounded-lg border border-slate-300 text-xs font-semibold text-slate-700 shadow-sm">
              Academic Area & PK Kelkar Library
            </div>
            <div className="absolute bottom-8 left-1/2 -translate-x-1/2 p-3 bg-white/70 rounded-lg border border-slate-300 text-xs font-semibold text-slate-700 shadow-sm">
              Airstrip & Outreach Center
            </div>

            {/* Pins */}
            {PINS.map((pin) => (
              <button
                key={pin.id}
                type="button"
                onClick={() => setSelectedPin(pin)}
                style={{ top: pin.y, left: pin.x }}
                className="absolute -translate-x-1/2 -translate-y-1/2 group cursor-pointer focus:outline-none"
              >
                <span className="relative flex h-7 w-7 items-center justify-center">
                  <span className={`animate-ping absolute inline-flex h-full w-full rounded-full opacity-75 ${
                    pin.status === 'Resolved' ? 'bg-emerald-400' : 'bg-rose-400'
                  }`} />
                  <span className={`relative inline-flex rounded-full h-6 w-6 items-center justify-center text-white shadow-md ${
                    pin.status === 'Resolved' ? 'bg-emerald-600' : 'bg-rose-600'
                  }`}>
                    <MapPin className="w-3.5 h-3.5" />
                  </span>
                </span>
                <span className="absolute top-full left-1/2 -translate-x-1/2 mt-1 hidden group-hover:block whitespace-nowrap bg-slate-900 text-white text-[11px] px-2 py-0.5 rounded shadow-lg pointer-events-none z-30">
                  {pin.area}
                </span>
              </button>
            ))}

            {/* Selected Pin Info Card */}
            {selectedPin && (
              <div className="absolute bottom-4 right-4 max-w-xs bg-white rounded-xl p-4 shadow-xl border border-slate-200 z-40 animate-scale-in">
                <div className="flex items-start justify-between gap-2 mb-2">
                  <span className="text-xs font-bold uppercase tracking-wider text-indigo-600">{selectedPin.type}</span>
                  <button type="button" onClick={() => setSelectedPin(null)} className="text-slate-400 hover:text-slate-600">
                    <X className="w-3.5 h-3.5" />
                  </button>
                </div>
                <h4 className="text-sm font-bold text-slate-900 mb-1">{selectedPin.title}</h4>
                <p className="text-xs text-slate-500 mb-2 flex items-center gap-1">
                  <MapPin className="w-3 h-3 text-slate-400" />
                  {selectedPin.area}
                </p>
                <div className="flex items-center justify-between text-xs pt-2 border-t border-slate-100">
                  <span className="font-semibold text-slate-700">Status:</span>
                  <span className={`px-2 py-0.5 rounded-full font-bold text-[10px] ${
                    selectedPin.status === 'Resolved' ? 'bg-emerald-100 text-emerald-800' : 'bg-amber-100 text-amber-800'
                  }`}>
                    {selectedPin.status}
                  </span>
                </div>
              </div>
            )}
          </div>

          <div className="mt-4 flex flex-wrap items-center justify-between text-xs text-slate-500 gap-2">
            <div className="flex items-center gap-4">
              <span className="flex items-center gap-1.5"><span className="w-3 h-3 rounded-full bg-rose-600 inline-block"/> Active Issues</span>
              <span className="flex items-center gap-1.5"><span className="w-3 h-3 rounded-full bg-emerald-600 inline-block"/> Resolved Issues</span>
            </div>
            <p>Click on any pin to view location and status</p>
          </div>
        </div>
      </div>
    </div>
  );
}

/**
 * Interactive AI Analysis Preview Modal demonstrating computer vision classification.
 */
export function AIAnalysisModal({ isOpen, onClose }) {
  if (!isOpen) return null;

  return (
    <div 
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/60 backdrop-blur-sm animate-fade-in"
      role="dialog"
      aria-modal="true"
      aria-labelledby="ai-modal-title"
      onClick={onClose}
    >
      <div 
        className="bg-white rounded-2xl max-w-2xl w-full shadow-2xl border border-slate-200 overflow-hidden flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="p-5 border-b border-slate-200 flex items-center justify-between bg-gradient-to-r from-indigo-50 to-purple-50">
          <div className="flex items-center gap-3">
            <RobotAvatar className="w-10 h-10" />
            <div>
              <h3 id="ai-modal-title" className="text-lg font-bold text-slate-900 flex items-center gap-1.5">
                CampusLens AI Vision Pipeline
                <Sparkles className="w-4 h-4 text-purple-600" />
              </h3>
              <p className="text-xs text-slate-500">Autonomous issue triaging & safety classification</p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close AI preview"
            className="p-2 rounded-lg text-slate-400 hover:text-slate-700 hover:bg-slate-200/60 transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Content */}
        <div className="p-6 space-y-5">
          <p className="text-sm text-slate-700 leading-relaxed">
            When you attach a photo to a report, our multi-modal AI model automatically inspects the image to assist campus engineers:
          </p>

          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <div className="p-4 rounded-xl border border-indigo-100 bg-indigo-50/50 flex flex-col gap-1.5">
              <Cpu className="w-5 h-5 text-indigo-600 mb-1" />
              <h4 className="text-xs font-bold uppercase tracking-wider text-indigo-900">1. Category</h4>
              <p className="text-xs text-slate-600">Identifies whether it is Electrical, Plumbing, IT, Civil, or Sanitation.</p>
            </div>
            <div className="p-4 rounded-xl border border-amber-100 bg-amber-50/50 flex flex-col gap-1.5">
              <AlertTriangle className="w-5 h-5 text-amber-600 mb-1" />
              <h4 className="text-xs font-bold uppercase tracking-wider text-amber-900">2. Hazard Check</h4>
              <p className="text-xs text-slate-600">Scans for open wires, fire hazards, or water intrusion risks immediately.</p>
            </div>
            <div className="p-4 rounded-xl border border-emerald-100 bg-emerald-50/50 flex flex-col gap-1.5">
              <Shield className="w-5 h-5 text-emerald-600 mb-1" />
              <h4 className="text-xs font-bold uppercase tracking-wider text-emerald-900">3. Priority Band</h4>
              <p className="text-xs text-slate-600">Recommends Urgency & Impact levels for administrator confirmation.</p>
            </div>
          </div>

          <div className="p-4 rounded-xl bg-slate-50 border border-slate-200 text-xs text-slate-600 space-y-1">
            <p className="font-semibold text-slate-900">🔒 Privacy First Guarantee:</p>
            <p>Faces and personal belongings are never stored in public summaries. Only sanitized descriptions are published to the community feed.</p>
          </div>

          <div className="flex justify-end pt-2">
            <button
              type="button"
              onClick={onClose}
              className="px-5 py-2.5 rounded-xl font-semibold text-white bg-indigo-600 hover:bg-indigo-700 shadow-sm transition-colors text-sm"
            >
              Got it, thanks!
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
