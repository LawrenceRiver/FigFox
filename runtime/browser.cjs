// Project Playwright installation by default; explicit overrides remain supported.
const {chromium} = require(process.env.PLUS_PLAYWRIGHT_MODULE || 'playwright');
module.exports = {
  launch: () => chromium.launch({
    headless: true,
    ...(process.env.PLUS_CHROMIUM ? {executablePath: process.env.PLUS_CHROMIUM} : {})
  })
};
