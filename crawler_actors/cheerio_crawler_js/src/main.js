// Apify SDK - toolkit for building Apify Actors (Read more at https://docs.apify.com/sdk/js/)
import {Actor as Apify, Actor } from 'apify';
// Crawlee - web scraping and browser automation library (Read more at https://crawlee.dev)
import { CheerioCrawler, Dataset } from 'crawlee';
// this is ESM project, and as such, it requires you to specify extensions in your relative imports
// read more about this here: https://nodejs.org/docs/latest-v18.x/api/esm.html#mandatory-file-extensions
// import { router } from './routes.js';

// The init() call configures the Actor for its environment. It's recommended to start every Actor with an init()
await Actor.init();

const {
    startUrls = ['https://apify.com'],
    exclude = [],
    proxyConfiguration = null,
    maxRequestsPerCrawl = 100,
} = await Actor.getInput() ?? {};

const proxyConfigurationObj = proxyConfiguration ? await Actor.createProxyConfiguration(proxyConfiguration) : await Actor.createProxyConfiguration();

const crawler = new CheerioCrawler({
    maxRequestsPerCrawl,
    proxyConfiguration: proxyConfigurationObj,
    async requestHandler({ enqueueLinks, request, $, log }) {
        log.info(`Processing ${request.url} ...`);

        await enqueueLinks({ exclude });

        // Extract title from the page.
        const title = $?.('title').text();

        // Save url and title to Dataset - a table-like storage.
        await Dataset.pushData({ url: request.loadedUrl, title: title || null });
    },
    additionalMimeTypes: ['image/webp', 'image/jpeg', 'image/png'],
});

await crawler.run(startUrls);

// Gracefully exit the Actor process. It's recommended to quit all Actors with an exit()
await Actor.exit();
