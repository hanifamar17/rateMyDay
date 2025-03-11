const puppeteer = require("puppeteer");

async function generateScreenshot(entry_id) {
    const browser = await puppeteer.launch();
    const page = await browser.newPage();

    const url = `http://127.0.0.1:5000/journal_image/${entry_id}`;
    await page.goto(url, { waitUntil: "networkidle0" }); // ✅ Menunggu halaman selesai termuat

    await page.waitForTimeout(1000); // Opsional: Beri waktu tambahan jika perlu

    const screenshot = await page.screenshot({ encoding: "base64", fullPage: true });

    await browser.close();
    return screenshot;
}
