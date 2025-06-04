import express from 'express';

const app = express();
const PORT = 8080;

const args = process.argv.slice(2);
// The only argument controls to which depth level the links to next level are generated
const DEPTH_LEVEL = parseInt(args[0]) || 10;

// Function to generate HTML response
function generateHtmlResponse(path) {
    let links = '';
    if (path.length !== DEPTH_LEVEL) {
        // Generate links based on the level
        links = Array.from({ length: 10 }, (_, i) => `<a href="${path}${i}">${path}${i}</a>`).join('\n');
    }

    return `
<html>
    <head>
        <title>${path}</title>
    </head>
    <body>
        ${links}
    </body>
</html>`;
}

// Route handler
app.get(/(.*)/, (req, res) => {
    const path = req.path;
    const htmlContent = generateHtmlResponse(path);
    res.status(200).send(htmlContent);
});

// Start the server
app.listen(PORT, () => {
    console.log(`Server is running on http://localhost:${PORT}`);
});
