// Reusable SVG Brand Assets and Icons for CampusLens & IIT Kanpur

export function IITKLogo({ className = "w-8 h-8" }) {
  return (
    <svg className={className} viewBox="0 0 100 100" fill="none" xmlns="http://www.w3.org/2000/svg">
      <circle cx="50" cy="50" r="46" stroke="currentColor" strokeWidth="3" />
      <circle cx="50" cy="50" r="40" stroke="currentColor" strokeWidth="1.5" strokeDasharray="3 3" />
      {/* Central Flame / Torch & Gears symbolic of IIT Kanpur emblem */}
      <path d="M50 20 L53 32 L64 35 L55 42 L58 53 L50 46 L42 53 L45 42 L36 35 L47 32 Z" fill="currentColor" opacity="0.9" />
      <circle cx="50" cy="62" r="14" stroke="currentColor" strokeWidth="2.5" />
      <path d="M50 52 L50 72 M40 62 L60 62" stroke="currentColor" strokeWidth="2" />
      <path d="M30 76 Q50 86 70 76" stroke="currentColor" strokeWidth="2.5" fill="none" />
      <text x="50" y="88" textAnchor="middle" fontSize="6.5" fontWeight="bold" fill="currentColor" letterSpacing="0.8">IIT KANPUR</text>
    </svg>
  );
}

export function GoogleLogo({ className = "w-5 h-5" }) {
  return (
    <svg className={className} viewBox="0 0 24 24">
      <path
        fill="#4285F4"
        d="M23.745 12.27c0-.7-.06-1.4-.19-2.07H12v4.51h6.6c-.29 1.52-1.14 2.82-2.4 3.68v3.05h3.88c2.27-2.09 3.665-5.17 3.665-9.17z"
      />
      <path
        fill="#34A853"
        d="M12 24c3.24 0 5.95-1.08 7.93-2.91l-3.88-3.05c-1.08.72-2.45 1.16-4.05 1.16-3.12 0-5.77-2.1-6.72-4.93H1.25v3.15C3.26 21.36 7.34 24 12 24z"
      />
      <path
        fill="#FBBC05"
        d="M5.28 14.27c-.25-.72-.38-1.49-.38-2.27s.13-1.55.38-2.27V6.58H1.25C.45 8.18 0 10.03 0 12s.45 3.82 1.25 5.42l4.03-3.15z"
      />
      <path
        fill="#EA4335"
        d="M12 4.75c1.77 0 3.35.61 4.6 1.8l3.42-3.42C17.95 1.19 15.24 0 12 0 7.34 0 3.26 2.64 1.25 6.58l4.03 3.15c.95-2.83 3.6-4.98 6.72-4.98z"
      />
    </svg>
  );
}

export function RobotAvatar({ className = "w-16 h-16" }) {
  return (
    <div className={`relative flex items-center justify-center rounded-2xl bg-gradient-to-tr from-indigo-500 to-purple-400 p-3 shadow-lg shadow-indigo-500/25 ${className}`}>
      <svg viewBox="0 0 48 48" fill="none" className="w-full h-full text-white" xmlns="http://www.w3.org/2000/svg">
        {/* Antenna */}
        <circle cx="24" cy="8" r="3" fill="currentColor" />
        <path d="M24 11 L24 16" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" />
        {/* Head */}
        <rect x="10" y="16" width="28" height="22" rx="9" fill="currentColor" />
        {/* Face screen */}
        <rect x="14" y="20" width="20" height="14" rx="5" fill="#1e1b4b" />
        {/* Glowing Eyes */}
        <circle cx="19" cy="26" r="2.5" fill="#38bdf8" />
        <circle cx="29" cy="26" r="2.5" fill="#38bdf8" />
        {/* Smile */}
        <path d="M22 30 Q24 32 26 30" stroke="#38bdf8" strokeWidth="1.5" strokeLinecap="round" />
        {/* Ears */}
        <rect x="7" y="23" width="3" height="8" rx="1.5" fill="currentColor" opacity="0.8" />
        <rect x="38" y="23" width="3" height="8" rx="1.5" fill="currentColor" opacity="0.8" />
      </svg>
    </div>
  );
}

export function CampusLensIcon({ className = "w-9 h-9" }) {
  return (
    <div className={`relative flex items-center justify-center rounded-xl bg-gradient-to-tr from-purple-600 via-indigo-600 to-blue-500 shadow-md shadow-indigo-500/30 ${className}`}>
      <svg viewBox="0 0 24 24" fill="none" className="w-5 h-5 text-white" xmlns="http://www.w3.org/2000/svg">
        <path d="M4 8V6a2 2 0 0 1 2-2h2" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"/>
        <path d="M4 16v2a2 2 0 0 0 2 2h2" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"/>
        <path d="M16 4h2a2 2 0 0 1 2 2v2" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"/>
        <path d="M16 20h2a2 2 0 0 0 2-2v-2" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"/>
        <circle cx="12" cy="12" r="3.5" stroke="currentColor" strokeWidth="2.5"/>
      </svg>
    </div>
  );
}
