// UI cases of page 12, Help (B7), at the mockup's widths (design/mockups/12-help/shot-{1280,390}-full.png).
const HTTP_ERROR_LINE = /^Failed to load resource: the server responded with a status of 503/;

export const cases = [
  {
    name: "help-india",
    path: "/india/help",
    mockup: "12-help",
    widths: [1280, 390],
    waitFor: ".fam",
    expectText: ["How to read the cockpit", "294 still to go", "HDFC Bank: 2 of 15 at N+1", "₹1,00,000 by default", "Model + news", "the reference"],
    expectSelector: ["#paper", "#glossary", ".chk li.no", ".chk li.na", ".toc a[href='#news']"],
  },
  { name: "help-us", path: "/us/help", market: "us", mockup: "12-help", widths: [1280], waitFor: ".fam", expectText: ["How to read the cockpit", "$"] },
  {
    name: "help-data-down",
    path: "/india/help",
    apiStatus: 503,
    allowConsole: [HTTP_ERROR_LINE],
    widths: [1280],
    waitFor: '[role="alert"]',
    expectText: ["How to read the cockpit", "Data service unavailable", "not available right now", "Glossary"],
  },
];
