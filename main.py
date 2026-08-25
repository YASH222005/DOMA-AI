import re
from collections import Counter
from typing import Set
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse
from pypdf import PdfReader

app = FastAPI(title="AI Resume Keyword Matcher")

STOPWORDS: Set[str] = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "has", "he",
    "in", "is", "it", "its", "of", "on", "that", "the", "to", "was", "were", "will",
    "with", "you", "your", "this", "or", "have", "be", "with", "must", "can", "our"
}

def clean_and_tokenize(text: str) -> list[str]:
    text = text.lower()
    words = re.findall(r'\b[a-z0-9+#.-]+\b', text)
    return [w.strip('.#,') for w in words if w not in STOPWORDS and len(w) > 1]

def extract_keywords_from_jd(text: str, top_n: int = 25) -> list[str]:
    tokens = clean_and_tokenize(text)
    freq = Counter(tokens)
    return [word for word, count in freq.most_common(top_n)]

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
    except Exception as e:
        raise HTTPException(status_code=400, detail="Could not extract text from PDF.")

    if not resume_text.strip():
        raise HTTPException(status_code=400, detail="Uploaded PDF contains no extractable text.")

    jd_keywords = set(extract_keywords_from_jd(job_description))
    resume_tokens = set(clean_and_tokenize(resume_text))
    
    matched = sorted(list(jd_keywords.intersection(resume_tokens)))
    missing = sorted(list(jd_keywords - resume_tokens))
    
    match_score = round((len(matched) / len(jd_keywords)) * 100) if jd_keywords else 0

    return {
        "score": match_score,
        "matched": matched,
        "missing": missing,
        "total_keywords": len(jd_keywords)
    }

@app.get("/", response_class=HTMLResponse)
async def serve_ui():
    return """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>AI Resume Keyword Matcher</title>
        <script src="https://cdn.tailwindcss.com"></script>
    </head>
    <body class="bg-gray-900 text-gray-100 min-h-screen flex flex-col items-center py-10 px-4 font-sans">
        <div class="max-w-4xl w-full space-y-8">
            <header class="text-center">
                <h1 class="text-4xl font-extrabold text-blue-400">ATS Resume Matcher</h1>
                <p class="text-gray-400 mt-2">Instantly analyze your resume against any target job description.</p>
            </header>

            <form id="matcherForm" class="bg-gray-800 p-6 rounded-xl shadow-lg border border-gray-700 space-y-6">
                <div>
                    <label class="block text-sm font-semibold text-gray-300 mb-2">Job Description</label>
                    <textarea id="jd" required rows="5" placeholder="Paste target job description..." 
                        class="w-full bg-gray-900 border border-gray-700 rounded-lg p-3 text-sm text-gray-100 focus:ring-2 focus:ring-blue-500 outline-none"></textarea>
                </div>

                <div>
                    <label class="block text-sm font-semibold text-gray-300 mb-2">Upload Resume (PDF)</label>
                    <input type="file" id="resume" accept=".pdf" required
                        class="w-full bg-gray-900 border border-gray-700 rounded-lg p-3 text-sm text-gray-400 file:mr-4 file:py-2 file:px-4 file:rounded-md file:border-0 file:bg-blue-600 file:text-white hover:file:bg-blue-500 cursor-pointer">
                </div>

                <button type="submit" id="submitBtn" 
                    class="w-full bg-blue-600 hover:bg-blue-500 text-white font-bold py-3 px-6 rounded-lg transition duration-200 shadow-md">
                    Scan Resume
                </button>
            </form>

            <div id="results" class="hidden bg-gray-800 p-6 rounded-xl border border-gray-700 space-y-6">
                <div class="flex items-center justify-between border-b border-gray-700 pb-4">
                    <div>
                        <h2 class="text-2xl font-bold text-gray-200">ATS Match Score</h2>
                        <p class="text-sm text-gray-400">Coverage based on key job criteria</p>
                    </div>
                    <span id="scoreBadge" class="text-4xl font-black px-4 py-2 rounded-lg bg-gray-900">0%</span>
                </div>

                <div>
                    <h3 class="text-lg font-semibold text-green-400 mb-2">🟢 Matched Keywords</h3>
                    <div id="matchedList" class="flex flex-wrap gap-2"></div>
                </div>

                <div>
                    <h3 class="text-lg font-semibold text-red-400 mb-2">🔴 Missing Keywords</h3>
                    <div id="missingList" class="flex flex-wrap gap-2"></div>
                </div>

                <div class="mt-6 pt-4 border-t border-gray-700 flex justify-between items-center bg-gray-900 p-4 rounded-lg">
                    <div>
                        <h4 class="font-bold text-yellow-400">Unlock AI Bullet Rewriter Pro</h4>
                        <p class="text-xs text-gray-400">Automatically integrate missing keywords into your resume bullets.</p>
                    </div>
                    <button onclick="alert('Monetization paywall placeholder ($5 Stripe Pass)')" 
                        class="bg-yellow-500 hover:bg-yellow-400 text-black font-bold text-xs py-2 px-4 rounded-md">
                        Upgrade $5
                    </button>
                </div>
            </div>
        </div>

        <script>
            document.getElementById('matcherForm').addEventListener('submit', async (e) => {
                e.preventDefault();
                const btn = document.getElementById('submitBtn');
                btn.disabled = true;
                btn.innerText = "Analyzing Resume...";

                const formData = new FormData();
                formData.append('resume_file', document.getElementById('resume').files[0]);
                formData.append('job_description', document.getElementById('jd').value);

                try {
                    const res = await fetch('/api/scan', { method: 'POST', body: formData });
                    const data = await res.json();
                    
                    if (!res.ok) throw new Error(data.detail || 'Scan failed');

                    document.getElementById('results').classList.remove('hidden');
                    
                    const scoreEl = document.getElementById('scoreBadge');
                    scoreEl.innerText = data.score + '%';
                    scoreEl.className = `text-4xl font-black px-4 py-2 rounded-lg ${data.score >= 70 ? 'text-green-400 bg-green-950' : 'text-yellow-400 bg-yellow-950'}`;

                    document.getElementById('matchedList').innerHTML = data.matched.map(w => 
                        `<span class="bg-green-900 text-green-200 text-xs px-2.5 py-1 rounded-full border border-green-700">${w}</span>`
                    ).join('');

                    document.getElementById('missingList').innerHTML = data.missing.map(w => 
                        `<span class="bg-red-900 text-red-200 text-xs px-2.5 py-1 rounded-full border border-red-700">${w}</span>`
                    ).join('');

                } catch (err) {
                    alert(err.message);
                } finally {
                    btn.disabled = false;
                    btn.innerText = "Scan Resume";
                }
            });
        </script>
    </body>
    </html>
    """