/**
 * This template is a production ready boilerplate for developing with `PlaywrightCrawler`.
 * Use this to bootstrap your projects using the most up-to-date code.
 * If you're looking for examples or want to learn more, see README.
 */

// For more information, see https://docs.apify.com/sdk/js
import { Actor } from 'apify';
// For more information, see https://crawlee.dev
import { PlaywrightCrawler, Dataset, createPlaywrightRouter } from 'crawlee';
// this is ESM project, and as such, it requires you to specify extensions in your relative imports
// read more about this here: https://nodejs.org/docs/latest-v18.x/api/esm.html#mandatory-file-extensions

// Initialize the Apify SDK
await Actor.init();

const {
    startUrls = ['https://apify.com'],
    exclude = [],
    proxyConfiguration = null,
    maxRequestsPerCrawl = 100,
} = await Actor.getInput() ?? {};

const proxyConfigurationObj = proxyConfiguration ? await Actor.createProxyConfiguration(proxyConfiguration) : await Actor.createProxyConfiguration();

export const router = createPlaywrightRouter();

router.addDefaultHandler(async ({ request, enqueueLinks, page, log }) => {
    log.info(`Processing ${request.url} ...`);

    await enqueueLinks({ exclude });

    // Extract title from the page.
    const title = await page.title();

    // Save url and title to Dataset - a table-like storage.
    await Dataset.pushData({ url: request.loadedUrl, title });
});

const crawler = new PlaywrightCrawler({
    maxRequestsPerCrawl,
    proxyConfiguration: proxyConfigurationObj,
    requestHandler: router,
    launchContext: {
        launchOptions: {
            args: [
                '--disable-gpu', // Mitigates the "crashing GPU process" issue in Docker containers
            ],
        },
    },
});

await crawler.run(startUrls);

// Exit successfully
await Actor.exit();
