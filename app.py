from flask import Flask, render_template, request, jsonify, session, url_for, redirect
from vosk import Model, KaldiRecognizer
import json
import wave
import os
import difflib
import uuid
import random
import shutil
import math

app = Flask(__name__)
app.secret_key = "super-secret-key-change-this"

# =====================================================
# LOAD SENTENCES ONLY ONCE
# =====================================================
DATASET_PATH = "sentences.json"
with open(DATASET_PATH, "r", encoding="utf-8") as f:
    DATASET = json.load(f)

READ_SENTENCES = DATASET.get("read_speak_sentences", [])
LISTEN_SENTENCES = DATASET.get("listen_speak_sentences", [])

# =====================================================
# LOAD VOSK MODEL ONLY ONCE (⚡ SUPER SPEED)
# =====================================================
print("🔥 Loading Vosk Model once...")
MODEL_PATH = "vosk-model-small-en-us-0.15"
VOSK_MODEL = Model(MODEL_PATH)
print("✅ Model loaded!")

# =====================================================
# JARO SIMILARITY (PRONUNCIATION)
# =====================================================
def jaro_similarity(s1, s2):
    if s1 == s2:
        return 1.0

    len1, len2 = len(s1), len(s2)
    max_dist = math.floor(max(len1, len2) / 2) - 1

    match1 = [False] * len1
    match2 = [False] * len2

    matches = 0
    transpositions = 0

    for i in range(len1):
        start = max(0, i - max_dist)
        end = min(i + max_dist + 1, len2)
        for j in range(start, end):
            if not match2[j] and s1[i] == s2[j]:
                match1[i] = match2[j] = True
                matches += 1
                break

    if matches == 0:
        return 0.0

    k = 0
    for i in range(len1):
        if match1[i]:
            while not match2[k]:
                k += 1
            if s1[i] != s2[k]:
                transpositions += 1
            k += 1

    transpositions /= 2

    return (
        (matches / len1)
        + (matches / len2)
        + ((matches - transpositions) / matches)
    ) / 3

# =====================================================
# FAST AUDIO CONVERSION + SPEECH-TO-TEXT
# =====================================================
def convert_audio_to_text(webm_path):
    wav_path = webm_path.replace(".webm", ".wav")
    cmd = f'ffmpeg -y -i "{webm_path}" -ac 1 -ar 16000 "{wav_path}" -loglevel quiet'
    os.system(cmd)

    with wave.open(wav_path, "rb") as wf:
        rate = wf.getframerate()
        frames = wf.getnframes()
        duration = frames / rate

        rec = KaldiRecognizer(VOSK_MODEL, rate)
        while True:
            data = wf.readframes(4000)
            if not data:
                break
            rec.AcceptWaveform(data)

        spoken = json.loads(rec.FinalResult()).get("text", "").strip()

    return spoken, duration

# =====================================================
# SCORING FUNCTIONS
# =====================================================
def score_pronunciation(reference, spoken):
    ref_words = reference.lower().split()
    spoken_words = spoken.lower().split()
    if not spoken_words:
        return 0.0

    sims = []
    for i, ref_word in enumerate(ref_words):
        sims.append(jaro_similarity(ref_word, spoken_words[i]) if i < len(spoken_words) else 0)

    return round((sum(sims) / len(sims)) * 100, 2)

def score_fluency(reference, duration):
    word_count = len(reference.split())
    expected = word_count * 0.55
    if duration <= 0:
        return 0.0
    ratio = expected / duration
    return round(max(0, min(100, ratio * 100)), 2)

def score_grammar(reference, spoken):
    ref_words = reference.lower().split()
    spoken_words = spoken.lower().split()
    if not spoken_words:
        return 0.0
    correct = sum(1 for w in ref_words if w in spoken_words)
    return round((correct / len(ref_words)) * 100, 2)

def score_accuracy(reference, spoken):
    if not spoken.strip():
        return 0.0
    return round(difflib.SequenceMatcher(None, reference.lower(), spoken.lower()).ratio() * 100, 2)

def calculate_final_scores(reference, spoken, duration):
    pron = score_pronunciation(reference, spoken)
    flu = score_fluency(reference, duration)
    gram = score_grammar(reference, spoken)
    acc = score_accuracy(reference, spoken)

    final = (pron * 0.30) + (flu * 0.25) + (gram * 0.25) + (acc * 0.20)

    return {
        "pronunciation": pron,
        "fluency": flu,
        "grammar": gram,
        "accuracy": acc,
        "final": round(final, 2)
    }

# =====================================================
# TEST START
# =====================================================
def start_test(mode, qcount):
    src = READ_SENTENCES if mode == "read" else LISTEN_SENTENCES
    qcount = max(3, min(20, int(qcount)))
    questions = random.sample(src, qcount)

    session_id = uuid.uuid4().hex
    user_folder = os.path.join("uploads", f"user_{session_id}")
    os.makedirs(user_folder, exist_ok=True)

    session.update({
        "mode": mode,
        "questions": questions,
        "current_index": 0,
        "details": [],
        "user_folder": user_folder
    })

    return questions[0], qcount

# =====================================================
# ROUTES
# =====================================================
@app.route("/")
def home():
    return render_template("index.html")

@app.route("/choose-questions/<mode>")
def choose_questions(mode):
    return render_template("choose_questions.html", mode=mode)

@app.route("/start-test", methods=["POST"])
def start_test_route():
    mode = request.form.get("mode")
    count = int(request.form.get("question_count", 20))
    first_q, total = start_test(mode, count)
    template = "read_speak.html" if mode == "read" else "listen_speak.html"
    return render_template(template, sentence=first_q, current_index=1, total_questions=total)

# =====================================================
# EVALUATION
# =====================================================
@app.route("/evaluate", methods=["POST"])
def evaluate():
    questions = session["questions"]
    idx = session["current_index"]
    total = len(questions)
    user_folder = session["user_folder"]

    audio = request.files["audio"]
    webm_path = os.path.join(user_folder, f"{uuid.uuid4().hex}.webm")
    audio.save(webm_path)

    reference = questions[idx]
    spoken, duration = convert_audio_to_text(webm_path)

    try:
        os.remove(webm_path)
        os.remove(webm_path.replace(".webm", ".wav"))
    except:
        pass

    scores = calculate_final_scores(reference, spoken, duration)
    session["details"].append({"question": reference, "spoken": spoken, **scores})

    idx += 1
    session["current_index"] = idx

    if idx >= total:
        session["overall"] = round(sum(d["final"] for d in session["details"]) / total, 2)
        try:
            shutil.rmtree(user_folder)
        except:
            pass
        return jsonify({"done": True, "redirect_url": url_for("results")})

    return jsonify({
        "done": False,
        "current": idx + 1,
        "total": total,
        "next_sentence": questions[idx]
    })

# =====================================================
# RESULTS
# =====================================================
@app.route("/results")
def results():
    if "overall" not in session:
        return redirect(url_for("home"))

    return render_template(
        "result.html",
        mode=session.get("mode"),
        overall=session.get("overall"),
        details=session.get("details")
    )

@app.route("/retry")
def retry():
    folder = session.get("user_folder")
    if folder:
        try:
            shutil.rmtree(folder)
        except:
            pass

    session.clear()
    return redirect(url_for("home"))

if __name__ == "__main__":
    app.run(debug=True)
