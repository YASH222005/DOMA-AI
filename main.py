import re
from collections import Counter
from typing import Set
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse
from pypdf import PdfReader

app = FastAPI(title="DOMA AI")

# --- PAYMENT LINK CONFIGURATION ---
# Replace these with your actual Razorpay / Stripe payment links when ready
PAYMENT_LINK_9 = "https://rzp.io/l/your-9-quick-pass"
PAYMENT_LINK_49 = "https://rzp.io/l/your-49-monthly"
PAYMENT_LINK_499 = "https://rzp.io/l/your-499-annual"
PAYMENT_LINK_999 = "https://rzp.io/l/your-999-lifetime"

STOPWORDS: Set[str] = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "has", "he",
    "in", "is", "it", "its", "of", "on", "that", "the", "to", "was", "were", "will",
    "with", "you", "your", "this", "or", "have", "be", "with", "must", "can", "our",
    "required", "seeking", "looking", "ability", "work", "responsibilities"
}

def clean_and_tokenize(text: str) -> list[str]:
    text = text.lower()
    words = re.findall(r'\b[a-z0-9+#.-]+\b', text)
    return [w.strip('.#,') for w in words if w not in STOPWORDS and len(w) > 1]

def extract_keywords_from_jd(text: str, top_n: int = 25) -> list[str]:
    tokens = clean_and_tokenize(text)
    freq = Counter(tokens)
    return [word for word, count in freq.most_common(top_n)]

def generate_optimized_bullets(missing_keywords: list[str]) -> list[str]:
    bullets = []
    actions = ["Spearheaded", "Architected", "Optimized", "Engineered", "Implemented", "Leveraged"]
    
    for i, kw in enumerate(missing_keywords[:5]):
        action = actions[i % len(actions)]
        bullets.append(f"{action} high-impact workflows by integrating {kw.upper()} into core systems to boost efficiency.")
    return bullets

@app.post("/api/scan")
async def scan_resume(
    resume_file: UploadFile = File(...),
    job_description: str = Form(...)
):
    if not resume_file.filename.endswith('.pdf'):
        raise HTTPException(status_code=400, detail="Please upload a valid PDF file.")
    
    try:
        reader = PdfReader(resume_file.file)
        resume_text = ""
        for page in reader.pages:
            resume_text += page.extract_text() or ""
    except Exception:
        raise HTTPException(status_code=400, detail="Could not read text from PDF file.")

    if not resume_text.strip():
        raise HTTPException(status_code=400, detail="Uploaded PDF file is empty or scanned as an image.")

    jd_keywords = set(extract_keywords_from_jd(job_description))
    resume_tokens = set(clean_and_tokenize(resume_text))
    
    matched = sorted(list(jd_keywords.intersection(resume_tokens)))
    missing = sorted(list(jd_keywords - resume_tokens))
    match_score = round((len(matched) / len(jd_keywords)) * 100) if jd_keywords else 0
    
    suggested_bullets = generate_optimized_bullets(missing)

    return {
        "score": match_score,
        "matched": matched,
        "missing": missing,
        "suggested_bullets": suggested_bullets,
        "pay_9_url": PAYMENT_LINK_9,
        "pay_49_url": PAYMENT_LINK_49,
        "pay_499_url": PAYMENT_LINK_499,
        "pay_999_url": PAYMENT_LINK_999
    }

@app.get("/", response_class=HTMLResponse)
async def serve_ui():
    return """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>DOMA AI - ATS Resume Optimization</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <style>
            .glass-panel {
                background: rgba(15, 23, 42, 0.75);
                backdrop-filter: blur(16px);
                border: 1px solid rgba(186, 230, 253, 0.2);
                box-shadow: 0 8px 32px 0 rgba(0, 191, 255, 0.15);
            }
            .ice-glow {
                box-shadow: 0 0 25px rgba(56, 189, 248, 0.3);
            }
            .crystal-text {
                background: linear-gradient(135deg, #ffffff 0%, #a5f3fc 50%, #38bdf8 100%);
                -webkit-background-clip: text;
                -webkit-text-fill-color: transparent;
            }
        </style>
    </head>
    <body class="bg-slate-950 text-slate-100 min-h-screen font-sans flex flex-col items-center py-10 px-4 relative overflow-x-hidden">
        
        <div class="absolute top-0 left-1/2 -translate-x-1/2 w-[600px] h-[600px] bg-cyan-500/10 rounded-full blur-[140px] pointer-events-none"></div>

        <div class="max-w-4xl w-full space-y-8 relative z-10">
            <header class="flex flex-col items-center text-center space-y-3 relative">
                <button onclick="toggleSettings()" class="absolute right-0 top-0 bg-slate-900/80 hover:bg-slate-800 border border-cyan-500/30 text-cyan-300 text-xs px-3.5 py-2 rounded-xl flex items-center gap-1.5 transition">
                    ⚙️ Settings
                </button>
                <div class="inline-flex items-center gap-2 bg-cyan-950/60 text-cyan-300 text-xs px-4 py-1.5 rounded-full border border-cyan-500/30 ice-glow">
                    ❄️ DOMA AI Engine v2.0
                </div>
                <h1 class="text-6xl font-black tracking-tight crystal-text">DOMA AI</h1>
                <p class="text-cyan-200/70 text-sm max-w-md">Precision ATS Resume Matcher & AI Bullet Point Optimizer.</p>
            </header>

            <form id="matcherForm" class="glass-panel p-8 rounded-3xl space-y-6">
                <div>
                    <label class="block text-sm font-semibold text-cyan-200 mb-2">Target Job Description</label>
                    <textarea id="jd" required rows="5" placeholder="Paste target job requirements here..." 
                        class="w-full bg-slate-950/80 border border-slate-800 rounded-2xl p-4 text-sm text-slate-100 focus:border-cyan-400 outline-none transition"></textarea>
                </div>

                <div>
                    <label class="block text-sm font-semibold text-cyan-200 mb-2">Upload Resume (PDF)</label>
                    <input type="file" id="resume" accept=".pdf" required
                        class="w-full bg-slate-950/80 border border-slate-800 rounded-2xl p-3 text-sm text-slate-400 file:mr-4 file:py-2 px-4 file:rounded-xl file:border-0 file:bg-cyan-600 file:text-white file:font-semibold hover:file:bg-cyan-500 cursor-pointer">
                </div>

                <button type="submit" id="submitBtn" 
                    class="w-full bg-gradient-to-r from-cyan-600 to-blue-600 hover:from-cyan-500 hover:to-blue-500 text-white font-bold py-4 px-6 rounded-2xl transition shadow-lg ice-glow flex items-center justify-center gap-2">
                    <span>❄️ Analyze & Rewrite Resume</span>
                </button>
            </form>

            <div id="results" class="hidden space-y-6">
                <div class="glass-panel p-8 rounded-3xl space-y-6">
                    <div class="flex items-center justify-between border-b border-slate-800 pb-6">
                        <div>
                            <h2 class="text-2xl font-bold text-slate-100">ATS Match Breakdown</h2>
                            <p class="text-xs text-cyan-300/70 mt-1">Calculated term frequency match ratio</p>
                        </div>
                        <span id="scoreBadge" class="text-4xl font-black px-6 py-2.5 rounded-2xl bg-slate-950 border border-slate-800">0%</span>
                    </div>

                    <div>
                        <h3 class="text-sm font-semibold text-emerald-400 mb-3 flex items-center gap-2">🟢 Matched Keywords</h3>
                        <div id="matchedList" class="flex flex-wrap gap-2"></div>
                    </div>

                    <div>
                        <h3 class="text-sm font-semibold text-rose-400 mb-3 flex items-center gap-2">🔴 Missing Key Terms</h3>
                        <div id="missingList" class="flex flex-wrap gap-2"></div>
                    </div>
                </div>

                <div class="glass-panel p-8 rounded-3xl space-y-4">
                    <h3 class="text-xl font-bold text-white flex items-center gap-2">💎 AI Bullet Rewrites</h3>
                    <p class="text-xs text-slate-400">Copy these optimized bullet points directly into your resume section:</p>
                    <div id="bulletList" class="space-y-3 pt-2"></div>
                </div>

                <!-- Pricing Section -->
                <div class="grid md:grid-cols-2 gap-4">
                    <div class="glass-panel p-6 rounded-3xl border border-cyan-500/30 flex flex-col justify-between space-y-4">
                        <div>
                            <span class="text-xs font-bold text-cyan-400 bg-cyan-950/80 px-3 py-1 rounded-full border border-cyan-800">QUICK FIX</span>
                            <h4 class="font-black text-2xl text-white mt-2">$9 Quick Pass</h4>
                            <p class="text-xs text-slate-300 mt-1">10 full ATS scans + instant AI bullet rewrites with 1-click copy.</p>
                        </div>
                        <button onclick="openPay('9')" class="w-full bg-slate-900 hover:bg-slate-800 text-cyan-300 font-bold py-3 rounded-2xl border border-cyan-500/30 transition">
                            Buy Quick Pass ($9)
                        </button>
                    </div>

                    <div class="glass-panel p-6 rounded-3xl border border-cyan-500/30 flex flex-col justify-between space-y-4">
                        <div>
                            <span class="text-xs font-bold text-blue-400 bg-blue-950/80 px-3 py-1 rounded-full border border-blue-800">DOMA PRO</span>
                            <h4 class="font-black text-2xl text-white mt-2">$49 / month</h4>
                            <p class="text-xs text-slate-300 mt-1">DOMA Pro Unlimited scans & bullet point rewrites.</p>
                        </div>
                        <button onclick="openPay('49')" class="w-full bg-slate-900 hover:bg-slate-800 text-cyan-300 font-bold py-3 rounded-2xl border border-cyan-500/30 transition">
                            Subscribe ($49 / mo)
                        </button>
                    </div>

                    <div class="glass-panel p-6 rounded-3xl border border-cyan-500/30 flex flex-col justify-between space-y-4">
                        <div>
                            <span class="text-xs font-bold text-emerald-400 bg-emerald-950/80 px-3 py-1 rounded-full border border-emerald-800">DOMA PRO+</span>
                            <h4 class="font-black text-2xl text-white mt-2">$499 / year</h4>
                            <p class="text-xs text-slate-300 mt-1">DOMA Pro+ Unlimited annual access (save over 15%).</p>
                        </div>
                        <button onclick="openPay('499')" class="w-full bg-slate-900 hover:bg-slate-800 text-cyan-300 font-bold py-3 rounded-2xl border border-cyan-500/30 transition">
                            Subscribe ($499 / yr)
                        </button>
                    </div>

                    <div class="bg-gradient-to-br from-cyan-950/80 to-blue-950/80 p-6 rounded-3xl border border-cyan-400/50 flex flex-col justify-between space-y-4 ice-glow">
                        <div>
                            <span class="text-xs font-bold text-slate-950 bg-cyan-400 px-3 py-1 rounded-full">DOMA ULTIMATE</span>
                            <h4 class="font-black text-2xl text-white mt-2">$999 Lifetime</h4>
                            <p class="text-xs text-cyan-100/80 mt-1">DOMA Ultimate unlimited scans & features forever.</p>
                        </div>
                        <button onclick="openPay('999')" class="w-full bg-cyan-400 hover:bg-cyan-300 text-slate-950 font-black py-3 rounded-2xl transition shadow-lg">
                            Get Ultimate ($999)
                        </button>
                    </div>
                </div>
            </div>
        </div>

        <div id="settingsModal" class="fixed inset-0 bg-slate-950/80 backdrop-blur-md hidden items-center justify-center p-4 z-50">
            <div class="glass-panel max-w-md w-full p-6 rounded-3xl space-y-6">
                <div class="flex justify-between items-center border-b border-slate-800 pb-4">
                    <h3 class="text-lg font-bold text-cyan-300">⚙️ System & Settings</h3>
                    <button onclick="toggleSettings()" class="text-slate-400 hover:text-white">✕</button>
                </div>
                <div class="space-y-4 text-sm text-slate-300">
                    <div class="flex justify-between items-center">
                        <span>Parser Mode</span>
                        <span class="text-xs bg-cyan-950 text-cyan-300 px-2.5 py-1 rounded-lg border border-cyan-800">Strict ATS Match</span>
                    </div>
                    <div class="flex justify-between items-center">
                        <span>API Status</span>
                        <span class="text-xs bg-emerald-950 text-emerald-300 px-2.5 py-1 rounded-lg border border-emerald-800">Online 🟢</span>
                    </div>
                </div>
                <button onclick="toggleSettings()" class="w-full bg-slate-800 hover:bg-slate-700 text-white font-semibold py-2.5 rounded-xl text-xs border border-slate-700">Close</button>
            </div>
        </div>

        <script>
            let urls = {};

            function toggleSettings() {
                const modal = document.getElementById('settingsModal');
                modal.classList.toggle('hidden');
                modal.classList.toggle('flex');
            }

            document.getElementById('matcherForm').addEventListener('submit', async (e) => {
                e.preventDefault();
                const btn = document.getElementById('submitBtn');
                btn.disabled = true;
                btn.innerHTML = "<span>❄️ Analyzing & Rewriting...</span>";

                const formData = new FormData();
                formData.append('resume_file', document.getElementById('resume').files[0]);
                formData.append('job_description', document.getElementById('jd').value);

                try {
                    const res = await fetch('/api/scan', { method: 'POST', body: formData });
                    const data = await res.json();
                    
                    if (!res.ok) throw new Error(data.detail || 'Scan failed');

                    urls['9'] = data.pay_9_url;
                    urls['49'] = data.pay_49_url;
                    urls['499'] = data.pay_499_url;
                    urls['999'] = data.pay_999_url;

                    document.getElementById('results').classList.remove('hidden');
                    
                    const scoreEl = document.getElementById('scoreBadge');
                    scoreEl.innerText = data.score + '%';
                    scoreEl.className = `text-4xl font-black px-6 py-2.5 rounded-2xl border ${data.score >= 70 ? 'text-emerald-400 bg-emerald-950/40 border-emerald-800' : 'text-amber-400 bg-amber-950/40 border-amber-800'}`;

                    document.getElementById('matchedList').innerHTML = data.matched.map(w => 
                        `<span class="bg-emerald-950/50 text-emerald-300 text-xs font-medium px-3 py-1 rounded-xl border border-emerald-800/50">${w}</span>`
                    ).join('');

                    document.getElementById('missingList').innerHTML = data.missing.map(w => 
                        `<span class="bg-rose-950/50 text-rose-300 text-xs font-medium px-3 py-1 rounded-xl border border-rose-800/50">${w}</span>`
                    ).join('');

                    document.getElementById('bulletList').innerHTML = data.suggested_bullets.map(b => 
                        `<div class="bg-slate-950/90 p-4 rounded-2xl border border-slate-800 text-sm text-slate-200 flex items-start justify-between gap-4">
                            <span>• ${b}</span>
                            <button onclick="navigator.clipboard.writeText('${b.replace(/'/g, "\\'")}')" class="text-xs bg-slate-900 hover:bg-slate-800 text-cyan-300 px-3 py-1 rounded-lg border border-cyan-800/50 transition">Copy</button>
                        </div>`
                    ).join('');

                } catch (err) {
                    alert(err.message);
                } finally {
                    btn.disabled = false;
                    btn.innerHTML = "<span>❄️ Analyze & Rewrite Resume</span>";
                }
            });

            function openPay(plan) {
                const url = urls[plan];
                if(url && !url.includes('your-')) {
                    window.open(url, '_blank');
                } else {
                    alert("Please replace the payment link placeholders inside main.py with your real Razorpay links.");
                }
            }
        </script>
    </body>
    </html>
    """