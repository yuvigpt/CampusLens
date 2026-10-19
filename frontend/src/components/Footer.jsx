import { Mail, Phone, ShieldCheck, Heart, ExternalLink, MapPin } from 'lucide-react';
import { CampusLensIcon } from './BrandIcons.jsx';

/**
 * Universal accessible footer for CampusLens.
 */
export default function Footer({ onOpenMap }) {
  const currentYear = new Date().getFullYear();

  return (
    <footer className="mt-auto border-t border-slate-200/90 bg-white/70 backdrop-blur-sm text-slate-600 text-xs select-none">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 sm:py-10">
        <div className="grid grid-cols-1 md:grid-cols-12 gap-8 items-start">
          {/* Col 1: Branding & Description (5/12) */}
          <div className="md:col-span-5 flex flex-col gap-3">
            <a href="#/" className="flex items-center gap-2.5 group w-fit">
              <CampusLensIcon className="w-7 h-7" />
              <div className="flex flex-col">
                <span className="font-extrabold text-sm text-slate-900 tracking-tight group-hover:text-indigo-600 transition-colors">
                  CampusLens
                </span>
                <span className="text-[10px] text-indigo-600 font-semibold tracking-wide">
                  IIT Kanpur Official Portal
                </span>
              </div>
            </a>
            <p className="text-slate-500 text-xs leading-relaxed max-w-sm">
              An intelligent, transparent campus infrastructure and facility redressal system.
              Empowering students and campus operations to resolve issues faster together.
            </p>
            <div className="flex items-center gap-2 text-[11px] text-slate-500 mt-1">
              <ShieldCheck className="w-4 h-4 text-emerald-600 shrink-0" />
              <span>Sanitized reports · Student privacy guaranteed</span>
            </div>
          </div>

          {/* Col 2: Navigation Links (3/12) */}
          <div className="md:col-span-3 flex flex-col gap-2.5">
            <span className="text-[11px] font-bold uppercase tracking-wider text-slate-900">
              Quick Navigation
            </span>
            <ul className="space-y-1.5">
              <li>
                <a href="#/" className="hover:text-indigo-600 transition-colors">Student Home</a>
              </li>
              <li>
                <a href="#/submit" className="hover:text-indigo-600 transition-colors">Submit a Report</a>
              </li>
              <li>
                <a href="#/mine" className="hover:text-indigo-600 transition-colors">My Complaints</a>
              </li>
              <li>
                <a href="#/community" className="hover:text-indigo-600 transition-colors">Public Community Feed</a>
              </li>
              <li>
                <a href="#/profile" className="hover:text-indigo-600 transition-colors">Profile &amp; Preferences</a>
              </li>
            </ul>
          </div>

          {/* Col 3: Campus Support & Emergency Contacts (4/12) */}
          <div className="md:col-span-4 flex flex-col gap-2.5">
            <span className="text-[11px] font-bold uppercase tracking-wider text-slate-900">
              Campus Help &amp; Emergency
            </span>
            <div className="space-y-2 text-xs">
              <div className="flex items-center gap-2">
                <Mail className="w-3.5 h-3.5 text-indigo-500 shrink-0" />
                <span>Support:</span>
                <a
                  href="mailto:campuslens-support@iitk.ac.in"
                  className="font-medium text-slate-800 hover:text-indigo-600 hover:underline transition-colors truncate"
                >
                  campuslens-support@iitk.ac.in
                </a>
              </div>
              <div className="flex items-center gap-2">
                <Phone className="w-3.5 h-3.5 text-emerald-600 shrink-0" />
                <span>Security Control:</span>
                <a
                  href="tel:+915122597200"
                  className="font-medium text-slate-800 hover:text-indigo-600 hover:underline transition-colors"
                >
                  +91 512 259 7200
                </a>
              </div>
              <div className="flex items-start gap-2 text-slate-500 text-[11px] pt-1">
                <MapPin className="w-3.5 h-3.5 text-slate-400 shrink-0 mt-0.5" />
                <span>Estate Office &amp; IWD, Indian Institute of Technology Kanpur, UP 208016</span>
              </div>
            </div>
          </div>
        </div>

        {/* Bottom Bar: Copyright & Seals */}
        <div className="mt-8 pt-6 border-t border-slate-200 flex flex-col sm:flex-row items-center justify-between gap-4 text-[11px] text-slate-500">
          <div className="flex items-center gap-2">
            <img src="/iitk-logo.svg" alt="IIT Kanpur Emblem" className="w-4 h-4 object-contain" />
            <span>
              &copy; {currentYear} CampusLens · Indian Institute of Technology Kanpur. All rights reserved.
            </span>
          </div>

          <div className="flex items-center gap-4 text-[11px]">
            <a href="https://www.iitk.ac.in" target="_blank" rel="noopener noreferrer" className="hover:text-slate-800 transition-colors inline-flex items-center gap-1">
              <span>IITK Main Site</span>
              <ExternalLink className="w-3 h-3 text-slate-400" />
            </a>
            <span>&bull;</span>
            <span className="text-slate-400">v2.0 Production Ready</span>
          </div>
        </div>
      </div>
    </footer>
  );
}
