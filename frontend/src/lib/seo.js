/**
 * Dynamic SEO and Metadata Manager for CampusLens.
 *
 * Updates document.title, meta[name="description"], and robots noindex
 * directives in response to SPA hash route changes.
 */

const ROUTE_META = {
  '#/': {
    title: 'CampusLens · Student Portal | IIT Kanpur',
    description: 'Track campus issues, submit maintenance requests, and help make IIT Kanpur better.',
    noindex: false,
  },
  '#/home': {
    title: 'CampusLens · Student Portal | IIT Kanpur',
    description: 'Track campus issues, submit maintenance requests, and help make IIT Kanpur better.',
    noindex: false,
  },
  '#/submit': {
    title: 'Submit a Report · CampusLens | IIT Kanpur',
    description: 'Report campus infrastructure issues, broken equipment, or safety hazards with photos for fast resolution.',
    noindex: false,
  },
  '#/mine': {
    title: 'My Complaints · CampusLens | IIT Kanpur',
    description: 'Track your submitted campus reports, view AI evaluations, and monitor resolution status in real time.',
    noindex: true, // Private student data
  },
  '#/community': {
    title: 'Public Community Feed · CampusLens | IIT Kanpur',
    description: 'View campus-wide sanitized maintenance reports and resolution status across IIT Kanpur.',
    noindex: false,
  },
  '#/profile': {
    title: 'Profile & Preferences · CampusLens | IIT Kanpur',
    description: 'Manage your CampusLens account preferences, notifications, and profile details.',
    noindex: true, // Private user settings
  },
  '#/dashboard': {
    title: 'Operations Command Dashboard · CampusLens | IIT Kanpur',
    description: 'Campus operations, facility analytics, and maintenance triage management.',
    noindex: true, // Admin only
  },
  '#/triage': {
    title: 'Issue Triage Workspace · CampusLens | IIT Kanpur',
    description: 'Campus maintenance ticket triage and priority confirmation.',
    noindex: true, // Admin only
  },
  '#/signin': {
    title: 'Sign In · CampusLens | IIT Kanpur',
    description: 'Sign in to CampusLens using your IIT Kanpur campus credentials.',
    noindex: false,
  },
  '#/signup': {
    title: 'Create Account · CampusLens | IIT Kanpur',
    description: 'Register for a CampusLens account with your IIT Kanpur email address.',
    noindex: false,
  },
};

export function updatePageMetadata(currentPath = '#/') {
  // Check for complaint detail subpath
  let meta;
  if (currentPath.startsWith('#/complaint/')) {
    const complaintId = decodeURIComponent(currentPath.slice('#/complaint/'.length));
    meta = {
      title: `Complaint #${complaintId.slice(0, 8).toUpperCase()} · CampusLens | IIT Kanpur`,
      description: 'Review complaint details, status updates, and AI priority analysis.',
      noindex: true,
    };
  } else {
    meta = ROUTE_META[currentPath] || {
      title: 'Page Not Found (404) · CampusLens | IIT Kanpur',
      description: 'The requested campus page could not be found.',
      noindex: true,
    };
  }

  // Update document title
  document.title = meta.title;

  // Update meta description
  let descTag = document.querySelector('meta[name="description"]');
  if (!descTag) {
    descTag = document.createElement('meta');
    descTag.setAttribute('name', 'description');
    document.head.appendChild(descTag);
  }
  descTag.setAttribute('content', meta.description);

  // Update robots tag (protect private/admin views from search engines)
  let robotsTag = document.querySelector('meta[name="robots"]');
  if (!robotsTag) {
    robotsTag = document.createElement('meta');
    robotsTag.setAttribute('name', 'robots');
    document.head.appendChild(robotsTag);
  }
  robotsTag.setAttribute('content', meta.noindex ? 'noindex, nofollow' : 'index, follow');
}
