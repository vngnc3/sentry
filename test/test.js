// Syntehtic rendering test
// Spits out fake render frames at a slightly randomized interval, much like a real rendering process.

// Set total render frames
// Set estimated render time per frame
// Set deviation time per frame

// Read the file config.json next to this test file
// Use the values to generate frames

const fs = require('fs');
const path = require('path');
const { PNG } = require('pngjs');

// Helper to pad frame numbers
function padFrameNumber(num, size = 4) {
    let s = num + "";
    while (s.length < size) s = "0" + s;
    return s;
}

// Read config.json
const configPath = path.join(__dirname, 'config.json');
const config = JSON.parse(fs.readFileSync(configPath, 'utf8'));

const totalFrames = config.total_frames;
const estTimePerFrame = config.estimated_render_time_per_frame; // in ms
const pctDeviation = config.pct_deviation_time_per_frame; // in percent

// Output directory
const outputDir = path.join(__dirname, 'renderOutput');
if (!fs.existsSync(outputDir)) {
    fs.mkdirSync(outputDir, { recursive: true });
}

// Function to generate a black 32x32 PNG buffer
function generateBlackPNG() {
    const png = new PNG({ width: 32, height: 32 });
    // All pixels are already zeroed (black, alpha=0), but let's set alpha to 255
    for (let y = 0; y < 32; y++) {
        for (let x = 0; x < 32; x++) {
            const idx = (32 * y + x) << 2;
            png.data[idx + 0] = 0;   // R
            png.data[idx + 1] = 0;   // G
            png.data[idx + 2] = 0;   // B
            png.data[idx + 3] = 255; // A
        }
    }
    return PNG.sync.write(png);
}

// Function to get randomized render time (returns milliseconds)
function getRandomizedRenderTime() {
    const deviation = estTimePerFrame * (pctDeviation / 100);
    const min = estTimePerFrame - deviation;
    const max = estTimePerFrame + deviation;
    // Convert seconds to milliseconds for setTimeout
    return (Math.random() * (max - min) + min) * 1000;
}

// Async function to render all frames, ensuring each frame is fully rendered and waits before starting the next
async function renderFrames() {
    console.log(`Starting render of ${totalFrames} frames...`);
    console.log(`Estimated time per frame: ${estTimePerFrame}s ± ${pctDeviation}%`);
    
    for (let i = 1; i <= totalFrames; i++) {
        const frameNum = padFrameNumber(i);
        const filename = `testRender_${frameNum}.png`;
        const filePath = path.join(outputDir, filename);

        console.log(`Rendering frame ${frameNum}...`);

        // Generate PNG buffer
        const pngBuffer = generateBlackPNG();

        // Write PNG to disk asynchronously and wait for it to finish
        await fs.promises.writeFile(filePath, pngBuffer);

        console.log(`✓ Frame ${frameNum} rendered and saved as ${filename}`);

        // Wait for randomized time before starting the next frame, even after the last frame
        const waitTime = getRandomizedRenderTime();
        console.log(`Waiting ${waitTime/1000}s before next frame...`);
        await new Promise(res => setTimeout(res, waitTime));
    }
    console.log('🎬 All frames rendered successfully!');
}

// Run the render process if this file is executed directly
if (require.main === module) {
    renderFrames().catch(console.error);
}
